from flask import Blueprint, render_template, redirect, url_for, flash, request, current_app
from flask_login import login_required, current_user

from core import db
from core.audit_policy import audit_event
from models import Funcionario
from routes.verfunc import preencher_campos_comuns, validar_campos_condicionais
from services.foto_service import salvar_foto
from services.indexacao_service import reindexar_funcionario
from services.auditoria_services import registrar_evento_seguro
from services.normalizacao_service import normalizar_maiusculo
from routes.editfunc import (
    OPCOES_TIPO,
    OPCOES_SITUACAO,
    OPCOES_DEPARTAMENTO,
    OPCOES_FORMA_INGRESSO,
    OPCOES_UNIDADE,
    OPCOES_DIRETORIA,
    OPCOES_SUBTIPO_VINCULO,
)

criacao_bp = Blueprint('criacao', __name__)

SET_SUBTIPO = {normalizar_maiusculo(v) for v in OPCOES_SUBTIPO_VINCULO}
SET_UNIDADE = {normalizar_maiusculo(v) for v in OPCOES_UNIDADE}
SET_DEPARTAMENTO = {normalizar_maiusculo(v) for v in OPCOES_DEPARTAMENTO}
SET_DIRETORIA = {normalizar_maiusculo(v) for v in OPCOES_DIRETORIA}
SET_TIPO = {normalizar_maiusculo(v) for v in OPCOES_TIPO}
SET_FORMA_INGRESSO = {normalizar_maiusculo(v) for v in OPCOES_FORMA_INGRESSO}
SET_SITUACAO = {normalizar_maiusculo(v) for v in OPCOES_SITUACAO}


def _valor_em_lista(valor: str | None, opcoes_norm: set[str], *, obrigatorio: bool = False) -> bool:
    txt = normalizar_maiusculo(valor)
    if not txt:
        return not obrigatorio
    return txt in opcoes_norm


def _validar_selects_cadastro(form):
    regras = [
        ('subtipo_vinculo', SET_SUBTIPO, 'Subtipo de Vinculo'),
        ('unidade', SET_UNIDADE, 'Unidade'),
        ('departamento', SET_DEPARTAMENTO, 'Departamento'),
        ('diretoria', SET_DIRETORIA, 'Diretoria'),
        ('tipo', SET_TIPO, 'Tipo de contrato'),
        ('forma_ingresso', SET_FORMA_INGRESSO, 'Forma de ingresso'),
        ('situacao', SET_SITUACAO, 'Situacao'),
    ]
    for campo, opcoes, rotulo in regras:
        if not _valor_em_lista(form.get(campo), opcoes, obrigatorio=True):
            return campo, f'{rotulo} inválido.'
    return None, None


def _render_form_cadastro(template_name: str):
    return render_template(
        template_name,
        opcoes_tipo=OPCOES_TIPO,
        opcoes_situacao=OPCOES_SITUACAO,
        opcoes_departamento=OPCOES_DEPARTAMENTO,
        opcoes_forma_ingresso=OPCOES_FORMA_INGRESSO,
        opcoes_unidade=OPCOES_UNIDADE,
        opcoes_diretoria=OPCOES_DIRETORIA,
        opcoes_subtipo_vinculo=OPCOES_SUBTIPO_VINCULO,
    )


def _processar_cadastro(vinculo: str, template_name: str, acao_prefixo: str, label_sucesso: str):
    if not current_user.is_admin:
        registrar_evento_seguro(
            f'{acao_prefixo}_NEGADO',
            categoria='seguranca',
            status='falha',
            recurso='funcionario',
        )
        flash('Acesso negado: você não tem privilégios administrativos.', 'error')
        return redirect(url_for('painel'))

    if request.method != 'POST':
        return _render_form_cadastro(template_name)

    func = Funcionario(vinculo=vinculo)
    preencher_campos_comuns(func, request.form)

    campo_invalido, erro_select = _validar_selects_cadastro(request.form)
    if erro_select:
        registrar_evento_seguro(
            f'{acao_prefixo}_FALHA',
            categoria='cadastro',
            status='falha',
            recurso='funcionario',
            detalhes={
                'motivo': 'validacao_allowlist_cadastro',
                'campo': campo_invalido,
                'valor': request.form.get(campo_invalido),
                'funcionario_vinculo': vinculo,
            },
        )
        flash(erro_select, 'error')
        return redirect(request.url)

    func.vinculo = vinculo

    erro = validar_campos_condicionais(func, vinculo)
    if erro:
        registrar_evento_seguro(
            f'{acao_prefixo}_FALHA',
            categoria='cadastro',
            status='falha',
            recurso='funcionario',
            detalhes={
                'motivo': 'validacao_campos_condicionais',
                'funcionario_vinculo': vinculo,
                'nome_informado': request.form.get('nome_completo'),
                'cpf_informado': request.form.get('cpf'),
            },
        )
        flash(erro, 'error')
        return redirect(request.url)

    try:
        db.session.add(func)
        db.session.flush()
        foto = request.files.get('foto')
        salvar_foto(current_app.root_path, foto, func.id)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        if 'IntegrityError' in type(e).__name__ or (hasattr(e, 'orig') and 'IntegrityError' in type(e.orig).__name__):
            msg_erro = str(e.orig) if hasattr(e, 'orig') else str(e)
            if 'matricula' in msg_erro.lower():
                flash('Já existe um colaborador com esta matrícula.', 'error')
            elif 'cpf' in msg_erro.lower():
                flash('Já existe um colaborador com este CPF.', 'error')
            else:
                flash('Erro: registro duplicado. Verifique os dados e tente novamente.', 'error')
            current_app.logger.warning('IntegrityError ao cadastrar %s: %s', vinculo.lower(), e)
            return redirect(request.url)
        current_app.logger.exception('Erro inesperado ao cadastrar %s', vinculo.lower())
        flash('Erro inesperado ao salvar. Tente novamente.', 'error')
        return redirect(request.url)

    detalhes_sucesso = {
        'funcionario_nome': func.nome_completo,
        'funcionario_vinculo': func.vinculo,
        'cpf': func.cpf,
        'diretoria': func.diretoria,
        'tem_foto': bool(foto and getattr(foto, 'filename', '')),
    }
    if vinculo == 'EFETIVO':
        detalhes_sucesso['matricula'] = func.matricula
    else:
        detalhes_sucesso['empresa_contratada'] = func.empresa_contratada
        detalhes_sucesso['numero_contrato'] = func.numero_contrato

    registrar_evento_seguro(
        f'{acao_prefixo}_SUCESSO',
        categoria='cadastro',
        status='sucesso',
        recurso='funcionario',
        recurso_id=str(func.id),
        detalhes=detalhes_sucesso,
    )

    try:
        ix = current_app.config['WHOOSH_IX']
        reindexar_funcionario(ix, func)
    except Exception as e:
        registrar_evento_seguro(
            'WHOOSH_REINDEXAR_FALHA',
            categoria='observabilidade',
            status='falha',
            recurso='indice_busca',
            recurso_id=str(func.id),
            detalhes={'erro': str(e), 'funcionario_nome': func.nome_completo},
        )
        current_app.logger.exception('Falha ao reindexar colaborador')

    flash(label_sucesso, 'success')
    return redirect(url_for('painel'))


@criacao_bp.route('/funcionario/novo/efetivo', methods=['GET', 'POST'])
@login_required
@audit_event()
def novo_efetivo():
    return _processar_cadastro(
        vinculo='EFETIVO',
        template_name='form_efetivo.html',
        acao_prefixo='FUNCIONARIO_CADASTRAR_EFETIVO',
        label_sucesso='Colaborador efetivo cadastrado com sucesso!',
    )


@criacao_bp.route('/funcionario/novo/terceirizado', methods=['GET', 'POST'])
@login_required
@audit_event()
def novo_terceirizado():
    return _processar_cadastro(
        vinculo='TERCEIRIZADO',
        template_name='form_terceirizado.html',
        acao_prefixo='FUNCIONARIO_CADASTRAR_TERCEIRIZADO',
        label_sucesso='Terceirizado cadastrado com sucesso!',
    )


@criacao_bp.route('/funcionario/novo', methods=['GET', 'POST'])
@login_required
@audit_event()
def novo_funcionario():
    return redirect(url_for('painel'))
