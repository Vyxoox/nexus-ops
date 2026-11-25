import os
import re
import shutil
from collections import Counter
from datetime import datetime, date, timedelta, UTC
from threading import Lock
from time import perf_counter
from typing import Any
from urllib.parse import urlparse, urljoin

import pandas as pd
from dotenv import load_dotenv
from flask import Flask, render_template, request, redirect, url_for, flash, g, jsonify, current_app
from flask_login import login_required, current_user
from sqlalchemy import func, or_, text
from werkzeug.exceptions import HTTPException, RequestEntityTooLarge
from whoosh.index import open_dir, create_in
from whoosh.query import Every

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), '.env'))

from core.audit_policy import audit_event
from core.authz import superadmin_required
from core.config import Config
from core.extensions import db, login_manager, csrf, limiter
from core.logging_setup import setup_logging
from core.schema import schema
from models import Usuario, Funcionario, LogAuditoria
from routes.auditoria import auditoria_bp, _ips_bloqueados_atualmente
from routes.auth import auth_bp
from routes.busca import busca_bp
from routes.columns import columns_bp
from routes.criacao import criacao_bp
from routes.editfunc import editfunc_bp
from routes.funcionarios import funcionarios_bp
from routes.planilha import planilha_bp
from routes.reindexar import reindexar_bp
from routes.usuarios import usuario_bp
from routes.verfunc import verfunc_bp
from services.auditoria_services import registrar_evento_seguro
from services.busca_service import PERFIS_ACESSO_TOTAL, MAPA_PERFIL_DIRETORIA
from services.formatacao_service import formatar_rg, formatar_cpf
from services.indexacao_service import (
    reindexar_funcionario as _svc_reindexar_funcionario,
    reindexar_todos as _svc_reindexar_todos,
)
from services.normalizacao_service import normalizar_cpf, normalizar_rg, normalizar_maiusculo, normalizar_titulo

app = Flask(__name__)
app.config.from_object(Config)
APP_START_TIME = datetime.now(UTC)

# Logging com rotação por categoria (aplicação/segurança/auditoria/erros)
setup_logging(app)

db.init_app(app)
login_manager.init_app(app)
csrf.init_app(app)
limiter.init_app(app)

login_manager.login_view = 'auth.login'
login_manager.login_message = 'É necessário fazer login para acessar esta página.'
login_manager.login_message_category = 'error'


@login_manager.unauthorized_handler
def tratar_nao_autenticado():
    registrar_evento_seguro(
        'AUTH_ACESSO_NAO_AUTENTICADO',
        categoria='seguranca',
        status='falha',
        recurso='autenticacao',
        detalhes={
            'endpoint': request.endpoint or '',
            'rota_solicitada': request.path,
        },
    )
    flash(login_manager.login_message, login_manager.login_message_category)
    destino = request.full_path if request.query_string else request.path
    return redirect(url_for('auth.login', next=destino))


app.register_blueprint(auth_bp)
app.register_blueprint(funcionarios_bp)
app.register_blueprint(busca_bp)
app.register_blueprint(columns_bp)
app.register_blueprint(reindexar_bp)
app.register_blueprint(verfunc_bp)
app.register_blueprint(planilha_bp)
app.register_blueprint(criacao_bp)
app.register_blueprint(editfunc_bp)
app.register_blueprint(usuario_bp)
app.register_blueprint(auditoria_bp)

EMAIL_CORPORATIVO_PADRAO = os.getenv('EMAIL_CORPORATIVO_PADRAO', 'contato@nexuscorp.com.br')

# ============================================
# CONFIGURAÇÃO DO WHOOSH
# ============================================
CAMINHO_INDICE = os.getenv('WHOOSH_INDEX_DIR', 'indice_colaboradores')
if not os.path.exists(CAMINHO_INDICE):
    os.mkdir(CAMINHO_INDICE)
    ix = create_in(CAMINHO_INDICE, schema)
else:
    ix = open_dir(CAMINHO_INDICE)

app.config['WHOOSH_IX'] = ix

# ============================================
# FUNÇÕES AUXILIARES & MÉTRICAS
# ============================================
AUDITORIA_MAX_CHAVES = 30
AUDITORIA_MAX_ITENS_LISTA = 20
AUDITORIA_MAX_TEXTO = 160
AUDITORIA_EXTENSOES_IGNORADAS = (
    '.png', '.jpg', '.jpeg', '.gif', '.webp', '.svg', '.ico',
    '.css', '.js', '.map', '.woff', '.woff2', '.ttf', '.eot',
)
AUDITORIA_ROTAS_IGNORADAS = {'/healthz', '/readyz', '/metrics'}


def _env_int(nome: str, padrao: int) -> int:
    bruto = (os.getenv(nome, '') or '').strip()
    if not bruto:
        return padrao
    try:
        return int(bruto)
    except ValueError:
        return padrao


app.config['AUDIT_RETENCAO_DIAS_GERAL'] = _env_int('AUDIT_RETENCAO_DIAS_GERAL', 365)
app.config['AUDIT_RETENCAO_DIAS_SEGURANCA'] = _env_int('AUDIT_RETENCAO_DIAS_SEGURANCA', 1825)
app.config['AUDIT_RETENCAO_DIAS_ALERTA'] = _env_int('AUDIT_RETENCAO_DIAS_ALERTA', 3650)

_METRICAS_LOCK = Lock()
_METRICAS = Counter()
_LATENCIA_BUCKETS_MS = (50, 100, 250, 500, 1000, 2000, 5000)
_LATENCIA_HIST = Counter()


def _rotulo_rota_metricas() -> str:
    if request.endpoint:
        return request.endpoint
    return request.path or 'desconhecida'


def _registrar_metricas_requisicao(response, duracao_ms: float | None = None):
    rota = _rotulo_rota_metricas()
    status = str(response.status_code)
    metodo = request.method.upper()

    with _METRICAS_LOCK:
        _METRICAS['http_requests_total'] += 1
        _METRICAS[f'http_requests_by_method_total|{metodo}'] += 1
        _METRICAS[f'http_requests_by_status_total|{status}'] += 1
        _METRICAS[f'http_requests_by_route_total|{rota}'] += 1

        if response.status_code >= 500:
            _METRICAS['http_server_errors_total'] += 1
        elif response.status_code >= 400:
            _METRICAS['http_client_errors_total'] += 1

        if duracao_ms is not None:
            _METRICAS['http_request_duration_ms_sum'] += duracao_ms
            _METRICAS['http_request_duration_ms_count'] += 1
            limite_b = next((b for b in _LATENCIA_BUCKETS_MS if duracao_ms <= b), 'inf')
            _LATENCIA_HIST[f'http_request_duration_ms_bucket|{limite_b}'] += 1
            _LATENCIA_HIST['http_request_duration_ms_bucket|+Inf'] += 1

    return response


def _formatar_metricas_prometheus() -> str:
    with _METRICAS_LOCK:
        linhas = [
            '# HELP http_requests_total Total de requisicoes HTTP.',
            '# TYPE http_requests_total counter',
            f'http_requests_total {_METRICAS.get("http_requests_total", 0)}',
            '# HELP http_requests_by_method_total Total de requisicoes por metodo HTTP.',
            '# TYPE http_requests_by_method_total counter',
            '# HELP http_requests_by_status_total Total de requisicoes por status HTTP.',
            '# TYPE http_requests_by_status_total counter',
            '# HELP http_requests_by_route_total Total de requisicoes por rota.',
            '# TYPE http_requests_by_route_total counter',
            '# HELP http_server_errors_total Total de respostas 5xx.',
            '# TYPE http_server_errors_total counter',
            f'http_server_errors_total {_METRICAS.get("http_server_errors_total", 0)}',
            '# HELP http_client_errors_total Total de respostas 4xx.',
            '# TYPE http_client_errors_total counter',
            f'http_client_errors_total {_METRICAS.get("http_client_errors_total", 0)}',
            '# HELP http_request_duration_ms Latencia das requisicoes em milissegundos.',
            '# TYPE http_request_duration_ms histogram',
        ]

        for key, valor in sorted(_METRICAS.items()):
            if '|' in key:
                base, sufixo = key.split('|', 1)
                if base == 'http_requests_by_method_total':
                    linhas.append(f'{base}{{method="{sufixo}"}} {valor}')
                elif base == 'http_requests_by_status_total':
                    linhas.append(f'{base}{{status="{sufixo}"}} {valor}')
                elif base == 'http_requests_by_route_total':
                    linhas.append(f'{base}{{route="{sufixo}"}} {valor}')

        if _METRICAS.get('http_request_duration_ms_count', 0):
            linhas.append(f'http_request_duration_ms_sum {_METRICAS.get("http_request_duration_ms_sum", 0):.2f}')
            linhas.append(f'http_request_duration_ms_count {_METRICAS.get("http_request_duration_ms_count", 0)}')
            acumulado = 0
            for bucket in (*_LATENCIA_BUCKETS_MS, 'inf'):
                acumulado += _LATENCIA_HIST.get(f'http_request_duration_ms_bucket|{bucket}', 0)
                le = '+Inf' if bucket == 'inf' else bucket
                linhas.append(f'http_request_duration_ms_bucket{{le="{le}"}} {acumulado}')
        else:
            linhas.append('http_request_duration_ms_sum 0')
            linhas.append('http_request_duration_ms_count 0')
            for bucket in (*_LATENCIA_BUCKETS_MS, 'inf'):
                le = '+Inf' if bucket == 'inf' else bucket
                linhas.append(f'http_request_duration_ms_bucket{{le="{le}"}} 0')

    return '\n'.join(linhas) + '\n'


def _limitar_texto_auditoria(valor: Any, limite: int = AUDITORIA_MAX_TEXTO) -> str:
    return str(valor)[:limite]


def _normalizar_json_auditoria(valor: Any, profundidade: int = 0) -> Any:
    if profundidade >= 3:
        return '[profundidade_maxima]'

    if isinstance(valor, dict):
        itens = list(valor.items())
        saida: dict[str, Any] = {}
        for idx, (chave, conteudo) in enumerate(itens):
            if idx >= AUDITORIA_MAX_CHAVES:
                saida['__campos_excedentes__'] = len(itens) - AUDITORIA_MAX_CHAVES
                break
            saida[str(chave)] = _normalizar_json_auditoria(conteudo, profundidade + 1)
        return saida

    if isinstance(valor, (list, tuple)):
        itens = list(valor[:AUDITORIA_MAX_ITENS_LISTA])
        saida_lista = [_normalizar_json_auditoria(item, profundidade + 1) for item in itens]
        if len(valor) > AUDITORIA_MAX_ITENS_LISTA:
            saida_lista.append(f'... +{len(valor) - AUDITORIA_MAX_ITENS_LISTA} itens')
        return saida_lista

    if isinstance(valor, (str, int, float, bool)) or valor is None:
        return _limitar_texto_auditoria(valor) if isinstance(valor, str) else valor

    if hasattr(valor, 'isoformat'):
        return valor.isoformat()

    return _limitar_texto_auditoria(valor)


def _capturar_multidict_auditoria(multidict) -> dict[str, Any]:
    if not multidict:
        return {}

    chaves = sorted(multidict.keys())
    dados: dict[str, Any] = {}

    for idx, chave in enumerate(chaves):
        if idx >= AUDITORIA_MAX_CHAVES:
            dados['__campos_excedentes__'] = len(chaves) - AUDITORIA_MAX_CHAVES
            break

        valores = multidict.getlist(chave)
        if len(valores) <= 1:
            dados[chave] = _limitar_texto_auditoria(valores[0] if valores else '')
            continue

        itens = [_limitar_texto_auditoria(v) for v in valores[:AUDITORIA_MAX_ITENS_LISTA]]
        if len(valores) > AUDITORIA_MAX_ITENS_LISTA:
            itens.append(f'... +{len(valores) - AUDITORIA_MAX_ITENS_LISTA} itens')
        dados[chave] = itens

    return dados


def _acao_auditoria_requisicao() -> str:
    endpoint = (request.endpoint or 'endpoint_desconhecido').replace('.', '_')
    endpoint = re.sub(r'[^A-Za-z0-9_]+', '_', endpoint).upper()
    return f'HTTP_{request.method.upper()}_{endpoint}'


def _detalhes_requisicao_auditoria(status_code: int, duracao_ms: int | None) -> dict[str, Any]:
    detalhes: dict[str, Any] = {
        'endpoint': request.endpoint or '',
        'status_code': status_code,
        'duracao_ms': duracao_ms,
        'query_params': _capturar_multidict_auditoria(request.args),
    }

    if request.method.upper() in {'POST', 'PUT', 'PATCH', 'DELETE'}:
        if request.is_json:
            detalhes['payload_json'] = _normalizar_json_auditoria(request.get_json(silent=True))
        else:
            detalhes['form_data'] = _capturar_multidict_auditoria(request.form)

        arquivos = sorted(request.files.keys())
        if arquivos:
            detalhes['arquivos'] = arquivos[:AUDITORIA_MAX_ITENS_LISTA]

    return detalhes


def _deve_ignorar_auditoria_requisicao() -> bool:
    caminho = (request.path or '').lower()
    if request.endpoint == 'static' or caminho.startswith('/static/'):
        return True
    if caminho.endswith(AUDITORIA_EXTENSOES_IGNORADAS):
        return True
    if caminho in AUDITORIA_ROTAS_IGNORADAS:
        return True
    return False


def tratar_nao_se_aplica(valor: Any) -> str | None:
    if valor is None:
        return None
    s = str(valor).strip()
    if not s:
        return None
    if s.lower() in {'não se aplica', 'nao se aplica', 'n/a', 'na'}:
        return None
    return s


def normalizar_ramal(valor: Any) -> str:
    if valor is None:
        return ''
    return re.sub(r'\D', '', str(valor))[:10]


def normalizar_titulo_simples(valor: Any) -> str:
    """Texto: primeira letra de cada palavra em maiúsculo (sem preservar siglas)."""
    if valor is None:
        return ''

    s = str(valor).strip()
    if not s or s.lower() in ('none', 'nan', 'nat'):
        return ''

    palavras = re.split(r'\s+', s)
    saida = []
    for palavra in palavras:
        partes = re.split(r"([-/'])", palavra)
        nova = []
        for parte in partes:
            if parte in "-/'":
                nova.append(parte)
                continue
            if not parte:
                continue
            nova.append(parte.capitalize())
        saida.append(''.join(nova))

    return ' '.join(saida)


def limpar_valor_excel(val: Any) -> Any:
    if val is None:
        return ''
    if isinstance(val, str):
        val = val.strip()
        if val.lower() in ('none', 'nat', ''):
            return ''
    return val


def parse_date(date_str: Any) -> date | None:
    if date_str:
        try:
            return datetime.strptime(str(date_str), '%Y-%m-%d').date()
        except ValueError:
            return None
    return None


def parse_excel_date(valor: Any) -> date | None:
    if valor is None or pd.isna(valor):
        return None
    try:
        return pd.to_datetime(valor).date()
    except Exception:
        return None


def date_to_datetime(val: Any) -> datetime | None:
    if val is None:
        return None
    if isinstance(val, date):
        return datetime.combine(val, datetime.min.time())
    return val


def obter_unidade(form, prefixo='') -> str:
    unidade_direta = tratar_nao_se_aplica(form.get(f'{prefixo}unidade'))
    if unidade_direta:
        return normalizar_titulo(unidade_direta)
    return ''


def obter_email_corporativo(form, prefixo='') -> str:
    email = (form.get(f'{prefixo}email_corporativo') or '').strip()
    return email or EMAIL_CORPORATIVO_PADRAO


def obter_perfil_usuario(user) -> str:
    if not user or not getattr(user, 'is_authenticated', False):
        return ''
    perfil_raw = (user.perfil or user.login or '').strip()
    return perfil_raw.upper()


def is_safe_url(target):
    if not target:
        return False
    ref_url = urlparse(request.host_url)
    test_url = urlparse(urljoin(request.host_url, target))
    return test_url.scheme in ('http', 'https') and ref_url.netloc == test_url.netloc


@app.after_request
def adicionar_security_headers(response):
    response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
    response.headers['Content-Security-Policy'] = "default-src 'self' 'unsafe-inline'; img-src 'self' data:;"
    response.headers['X-Frame-Options'] = 'SAMEORIGIN'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    return response


@app.before_request
def iniciar_auditoria_requisicao():
    g.audit_inicio = datetime.now(UTC)
    if not hasattr(g, "audit_request_id"):
        g.audit_request_id = getattr(g, "audit_request_id", None) or os.urandom(16).hex()


@app.after_request
def auditar_requisicao(response):
    try:
        if _deve_ignorar_auditoria_requisicao():
            return response

        inicio = getattr(g, 'audit_inicio', None)
        duracao_ms = None
        if inicio:
            duracao_ms = int((datetime.now(UTC) - inicio).total_seconds() * 1000)

        status_http = int(response.status_code)
        status_evento = 'sucesso' if status_http < 400 else 'falha'
        categoria = 'acesso' if request.method.upper() in {'GET', 'HEAD', 'OPTIONS'} else 'operacao'

        registrar_evento_seguro(
            _acao_auditoria_requisicao(),
            categoria=categoria,
            status=status_evento,
            recurso=request.blueprint or 'app',
            recurso_id=request.endpoint or request.path,
            detalhes=_detalhes_requisicao_auditoria(status_http, duracao_ms),
        )
    except Exception:
        pass

    return response


@app.before_request
def iniciar_timer():
    g.request_inicio = perf_counter()


@app.after_request
def registrar_metricas(response):
    inicio = getattr(g, "request_inicio", None)
    if inicio is None:
        return response

    duracao_ms = round((perf_counter() - inicio) * 1000, 2)
    _registrar_metricas_requisicao(response, duracao_ms=duracao_ms)

    current_app.logger.info(
        f"{request.method} {request.path} {response.status_code} {duracao_ms}ms"
    )

    if duracao_ms > 2000:
        registrar_evento_seguro(
            "APP_ENDPOINT_LENTO",
            categoria="observabilidade",
            status="sucesso",
            recurso=request.path,
            detalhes={
                "duracao_ms": duracao_ms,
                "status_code": response.status_code,
                "metodo": request.method,
                "endpoint": request.path,
            },
        )

    if response.status_code >= 500 and not getattr(g, "erro_ja_registrado", False):
        registrar_evento_seguro(
            "APP_ENDPOINT_ERRO",
            categoria="observabilidade",
            status="falha",
            recurso=request.path,
            detalhes={
                "status_code": response.status_code,
                "duracao_ms": duracao_ms,
                "metodo": request.method,
                "endpoint": request.path,
                "query_params": dict(request.args),
            },
        )

    return response


@app.errorhandler(429)
@audit_event()
def limite_excedido(e):
    registrar_evento_seguro(
        "APP_LIMITE_EXCEDIDO",
        categoria="SEGURANÇA",
        status="falha",
        recurso=request.path,
        detalhes={
            "erro": str(e),
            "tipo_erro": type(e).__name__,
        },
    )
    return render_template("429.html"), 429


@app.errorhandler(RequestEntityTooLarge)
def upload_excedido(e):
    registrar_evento_seguro(
        "APP_UPLOAD_EXCEDIDO",
        categoria="seguranca",
        status="falha",
        recurso=request.path,
        detalhes={
            "limite_mb": round(app.config["MAX_CONTENT_LENGTH"] / 1024 / 1024, 2),
            "content_length": request.content_length,
        },
    )
    flash("Arquivo excede o tamanho máximo permitido", "error")
    return redirect(request.referrer or url_for("painel"))


@app.errorhandler(Exception)
def erro_global(e):
    if isinstance(e, HTTPException):
        return e

    g.erro_ja_registrado = True
    registrar_evento_seguro(
        "APP_ERRO_INTERNO",
        categoria="observabilidade",
        status="falha",
        recurso=request.path,
        detalhes={
            "erro": str(e),
            "tipo_erro": type(e).__name__,
        },
    )
    current_app.logger.exception("Erro interno não tratado")
    raise e


# ============================================
# FILTROS JINJA2
# ============================================
@app.template_filter('formato_cpf')
def formato_cpf_filter(s):
    return formatar_cpf(s)


@app.template_filter('formato_rg')
def formato_rg_filter(s):
    return formatar_rg(s)


# ============================================
# WHOOSH WRAPPERS
# ============================================
def reindexar_funcionario(funcionario):
    _svc_reindexar_funcionario(ix, funcionario)


def reindexar_todos():
    global ix
    if ix:
        ix.close()

    try:
        if os.path.exists(CAMINHO_INDICE):
            shutil.rmtree(CAMINHO_INDICE)
        os.mkdir(CAMINHO_INDICE)
        ix = create_in(CAMINHO_INDICE, schema)
    except Exception:
        ix = open_dir(CAMINHO_INDICE)
        writer = ix.writer()
        writer.delete_by_query(Every())
        writer.commit()

    app.config['WHOOSH_IX'] = ix
    _svc_reindexar_todos(ix)


# ============================================
# CRIAÇÃO DAS TABELAS E ADMIN
# ============================================
with app.app_context():
    try:
        db.create_all()

        admin = Usuario.query.filter_by(login='admin').first()
        if not admin:
            admin = Usuario(login='admin', is_admin=True, is_superadmin=True, perfil='DIRETORIA')
            admin.set_password(os.getenv('ADMIN_PASSWORD', 'troque-essa-senha'))
            db.session.add(admin)
            db.session.commit()
        else:
            alterado = False
            if not admin.is_admin:
                admin.is_admin = True
                alterado = True
            if not admin.is_superadmin:
                admin.is_superadmin = True
                alterado = True
            if not admin.perfil:
                admin.perfil = 'DIRETORIA'
                alterado = True
            if alterado:
                db.session.commit()
    except Exception as e:
        app.logger.error(f"Falha no bootstrap do banco: {e}")


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(Usuario, int(user_id))


def _readiness_status() -> tuple[bool, dict[str, str]]:
    pronto = True
    detalhes: dict[str, str] = {}

    try:
        db.session.execute(text("SELECT 1"))
        detalhes["database"] = "ok"
    except Exception:
        db.session.rollback()
        detalhes["database"] = "erro"
        pronto = False

    indice_ok = os.path.isdir(CAMINHO_INDICE) and app.config.get('WHOOSH_IX') is not None
    detalhes["indice"] = "ok" if indice_ok else "erro"
    if not indice_ok:
        pronto = False

    return pronto, detalhes


@app.get('/healthz')
def healthz():
    current_app.logger.info(
        "healthz ok",
        extra={
            "category": "observabilidade",
            "request_id": getattr(g, "audit_request_id", None),
            "method": request.method,
            "path": request.path,
            "status_code": 200,
            "duration_ms": None,
            "ip": request.headers.get("X-Forwarded-For", request.remote_addr) or "",
        },
    )
    return jsonify({"status": "ok"}), 200


@app.get('/readyz')
def readyz():
    pronto, detalhes = _readiness_status()
    current_app.logger.info(
        f"readyz {'ready' if pronto else 'not_ready'}",
        extra={
            "category": "observabilidade",
            "database": detalhes.get("database"),
            "indice": detalhes.get("indice"),
        },
    )
    payload = {"status": "ready" if pronto else "not_ready", **detalhes}
    return jsonify(payload), (200 if pronto else 503)


@app.get('/metrics')
def metrics():
    return _formatar_metricas_prometheus(), 200, {
        "Content-Type": "text/plain; version=0.0.4; charset=utf-8"
    }


def _calcular_metricas_painel(funcionarios: list[Funcionario]) -> dict[str, Any]:
    ativos = [f for f in funcionarios if f.ativo]
    inativos = [f for f in funcionarios if not f.ativo]
    efetivos_ativos = [f for f in ativos if (f.vinculo or '').upper() == 'EFETIVO']
    terceirizados_ativos = [f for f in ativos if (f.vinculo or '').upper() == 'TERCEIRIZADO']

    total_ativos = len(ativos)
    total_efetivos = len(efetivos_ativos)
    total_terceirizados = len(terceirizados_ativos)

    pct_efetivos = round((total_efetivos / total_ativos) * 100, 1) if total_ativos else 0.0
    pct_terceirizados = round((total_terceirizados / total_ativos) * 100, 1) if total_ativos else 0.0

    departamentos_ativos = {
        (f.departamento or '').strip()
        for f in ativos
        if (f.departamento or '').strip()
    }
    contratos_ativos = {
        (f.numero_contrato or '').strip()
        for f in terceirizados_ativos
        if (f.numero_contrato or '').strip()
    }

    corte_90d = date.today() - timedelta(days=90)
    integracoes_recentes = 0
    for f in ativos:
        dt_ref = f.data_integracao or f.data_admissao or f.data_inicio
        if dt_ref and dt_ref >= corte_90d:
            integracoes_recentes += 1

    total_geral = len(funcionarios)
    taxa_atividade = round((total_ativos / total_geral) * 100, 1) if total_geral else 0.0

    # Distribuição por Diretoria
    mapa_dir: dict[str, dict[str, Any]] = {}
    for f in ativos:
        raw_dir = (f.diretoria or 'NÃO ATRIBUÍDA').strip()
        if ' - ' in raw_dir:
            codigo, nome = [p.strip() for p in raw_dir.split(' - ', 1)]
        else:
            codigo, nome = raw_dir[:12], raw_dir
        bucket = mapa_dir.setdefault(raw_dir, {
            'raw': raw_dir,
            'codigo': codigo,
            'nome': nome,
            'total': 0,
            'efetivos': 0,
            'terceirizados': 0,
        })
        bucket['total'] += 1
        if (f.vinculo or '').upper() == 'EFETIVO':
            bucket['efetivos'] += 1
        else:
            bucket['terceirizados'] += 1

    por_diretoria = sorted(mapa_dir.values(), key=lambda x: x['total'], reverse=True)
    max_dir = max((d['total'] for d in por_diretoria), default=1)
    for d in por_diretoria:
        d['pct'] = round((d['total'] / max_dir) * 100, 1) if max_dir else 0.0
        d['share'] = round((d['total'] / total_ativos) * 100, 1) if total_ativos else 0.0

    # Top Departamentos
    contagem_dep = Counter((f.departamento or 'Não informado').strip() for f in ativos)
    por_departamento = []
    for nome_dep, qtd in contagem_dep.most_common(6):
        por_departamento.append({
            'nome': nome_dep,
            'total': qtd,
            'pct': round((qtd / total_ativos) * 100, 1) if total_ativos else 0.0,
        })

    # Ecossistema de Fornecedores
    mapa_forn: dict[str, dict[str, Any]] = {}
    for f in terceirizados_ativos:
        emp = (f.empresa_contratada or 'Fornecedor Não Informado').strip()
        item = mapa_forn.setdefault(emp, {'empresa': emp, 'contratos': set(), 'colaboradores_count': 0})
        item['colaboradores_count'] += 1
        if (f.numero_contrato or '').strip():
            item['contratos'].add(f.numero_contrato.strip())

    fornecedores_ativos = [
        {
            'empresa': v['empresa'],
            'contratos_count': len(v['contratos']),
            'colaboradores_count': v['colaboradores_count'],
        }
        for v in sorted(mapa_forn.values(), key=lambda x: x['colaboradores_count'], reverse=True)[:5]
    ]

    # Últimas integrações / admissões
    ultimas_admissoes = sorted(
        ativos,
        key=lambda f: (f.data_admissao or f.data_inicio or f.data_integracao or date.min, f.id or 0),
        reverse=True,
    )[:5]

    kpis = {
        'total_registros': total_geral,
        'total_ativos': total_ativos,
        'total_inativos': len(inativos),
        'efetivos_ativos': total_efetivos,
        'terceirizados_ativos': total_terceirizados,
        'pct_efetivos': pct_efetivos,
        'pct_terceirizados': pct_terceirizados,
        'total_departamentos': len(departamentos_ativos),
        'total_contratos': len(contratos_ativos),
        'integracoes_recentes': integracoes_recentes,
        'taxa_atividade': taxa_atividade,
    }

    return {
        'kpis': kpis,
        'por_diretoria': por_diretoria,
        'por_departamento': por_departamento,
        'fornecedores_ativos': fornecedores_ativos,
        'ultimas_admissoes': ultimas_admissoes,
    }


# ============================================
# ROTAS ADMINISTRATIVAS E DASHBOARD
# ============================================
@app.route('/painel')
@login_required
@audit_event()
def painel():
    perfil = obter_perfil_usuario(current_user)
    ordem_nome = (
        func.lower(func.trim(func.coalesce(Funcionario.nome_completo, ''))),
        Funcionario.id.asc(),
    )

    if current_user.is_superadmin or perfil in PERFIS_ACESSO_TOTAL:
        funcionarios = Funcionario.query.order_by(*ordem_nome).all()
    elif perfil in MAPA_PERFIL_DIRETORIA:
        dir_cod = MAPA_PERFIL_DIRETORIA[perfil]
        funcionarios = Funcionario.query.filter(
            func.upper(Funcionario.vinculo) == 'TERCEIRIZADO',
            or_(
                func.upper(func.coalesce(Funcionario.diretoria, '')).like(f'%{dir_cod}%'),
                func.upper(func.coalesce(Funcionario.departamento, '')).like(f'%{dir_cod}%'),
                func.upper(func.coalesce(Funcionario.unidade, '')).like(f'%{dir_cod}%'),
            ),
        ).order_by(*ordem_nome).all()
    else:
        funcionarios = []

    analytics = _calcular_metricas_painel(funcionarios)

    resumo_auditoria = None
    if getattr(current_user, 'is_superadmin', False):
        corte_24h = datetime.now(UTC).replace(tzinfo=None) - timedelta(hours=24)
        logs_24h = LogAuditoria.query.filter(LogAuditoria.criado_em >= corte_24h).count()
        alertas_24h = LogAuditoria.query.filter(
            LogAuditoria.criado_em >= corte_24h,
            or_(LogAuditoria.categoria == 'alerta', LogAuditoria.acao.like('SEC_ALERTA_%')),
        ).count()
        ips_bloqueados = _ips_bloqueados_atualmente()
        pronto, detalhes_ready = _readiness_status()
        resumo_auditoria = {
            'logs_24h': logs_24h,
            'alertas_24h': alertas_24h,
            'ips_bloqueados': len(ips_bloqueados),
            'sistema_online': pronto,
            'detalhes': detalhes_ready,
        }

    return render_template(
        'painel.html',
        funcionarios=funcionarios,
        perfil_usuario=perfil,
        resumo_auditoria=resumo_auditoria,
        **analytics,
    )


@app.route('/observabilidade')
@login_required
@superadmin_required
@audit_event()
def observabilidade():
    with _METRICAS_LOCK:
        request_total = _METRICAS.get('http_requests_total', 0)
        errors_4xx = _METRICAS.get('http_client_errors_total', 0)
        errors_5xx = _METRICAS.get('http_server_errors_total', 0)
        soma = _METRICAS.get('http_request_duration_ms_sum', 0)
        count = _METRICAS.get('http_request_duration_ms_count', 0)

    latencia_media = round(soma / count, 2) if count else 0

    top_rotas = []
    with _METRICAS_LOCK:
        for chave, valor in _METRICAS.items():
            if chave.startswith("http_requests_by_route_total|"):
                rota = chave.split("|", 1)[1]
                if rota not in ["static", "observabilidade", "metrics", "healthz", "readyz"]:
                    top_rotas.append((rota, valor))

    top_rotas.sort(key=lambda x: x[1], reverse=True)

    uptime_segundos = int((datetime.now(UTC) - APP_START_TIME).total_seconds())
    horas = uptime_segundos // 3600
    minutos = (uptime_segundos % 3600) // 60
    segundos = uptime_segundos % 60
    uptime_formatado = f"{horas}h {minutos}m {segundos}s"

    pronto, detalhes = _readiness_status()

    return render_template(
        'observabilidade.html',
        request_total=request_total,
        errors_4xx=errors_4xx,
        errors_5xx=errors_5xx,
        latencia_media=latencia_media,
        top_rotas=top_rotas[:10],
        pronto=pronto,
        detalhes=detalhes,
        uptime=uptime_formatado,
    )


# INICIALIZAÇÃO
if __name__ == '__main__':
    from waitress import serve
    porta = int(os.getenv('PORT', '8080'))
    serve(app, host='0.0.0.0', port=porta)
