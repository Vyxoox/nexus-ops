from flask_login import current_user
from whoosh.qparser import MultifieldParser
from whoosh.query import Term, Or, Every, And
from whoosh.query.qcore import QueryError

from services.normalizacao_service import (
    normalizar_cpf,
    normalizar_rg,
    normalizar_maiusculo,
    escape_whoosh_query,
)

PERFIS_ACESSO_TOTAL = {'DIRETORIA', 'RH'}
MAPA_PERFIL_DIRETORIA = {
    'TECH': 'DIR.TECH',
    'OPERACOES': 'DIR.OPS',
    'FINANCEIRO': 'DIR.FIN',
}

CAMPOS_PESQUISA = [
    "nome_completo", "cpf", "rg", "matricula", "cargo_atual",
    "cargo_anterior", "unidade", "departamento", "diretoria",
    "empresa_contratada", "numero_contrato", "subtipo_vinculo",
    "email_corporativo", "ramal", "situacao",
    "registro_interno", "documento_vinculo",
]


def _prioridade_vinculo(resultado):
    vinculo = str(resultado.get("vinculo", "") or "").upper()
    if vinculo == "EFETIVO":
        return 0
    if vinculo == "TERCEIRIZADO":
        return 1
    return 2


def _chave_ordenacao(resultado, separar_por_vinculo=False):
    chave_base = (
        str(resultado.get("nome_completo", "") or "").strip().casefold(),
        str(resultado.get("cpf", "") or "").strip(),
    )
    if separar_por_vinculo:
        return (_prioridade_vinculo(resultado),) + chave_base
    return chave_base


def obter_perfil_usuario(user):
    if not user or not getattr(user, 'is_authenticated', False):
        return ''
    perfil_raw = (user.perfil or user.login or '').strip()
    return perfil_raw.upper()


def obter_diretoria_permissao(user):
    if not user or not getattr(user, 'is_authenticated', False):
        return ''

    perfil = obter_perfil_usuario(user)
    return MAPA_PERFIL_DIRETORIA.get(perfil, '')


def _resultado_permitido_por_diretoria(resultado, diretoria_req):
    if not diretoria_req:
        return False

    dir_upper = diretoria_req.upper()
    dir_val = str(resultado.get("diretoria", "") or "").upper()
    dep_val = str(resultado.get("departamento", "") or "").upper()
    uni_val = str(resultado.get("unidade", "") or "").upper()

    return (
        dir_upper in dir_val
        or dir_upper in dep_val
        or dir_upper in uni_val
    )


def executar_busca(ix, query, vinculo_selecionado):
    with ix.searcher() as searcher:
        diretoria_req_usuario = ''
        separar_por_vinculo = not vinculo_selecionado or vinculo_selecionado.lower() == 'todos'

        if query:
            query_cpf = normalizar_cpf(query)
            query_rg = normalizar_rg(query)

            parser = MultifieldParser(CAMPOS_PESQUISA, schema=ix.schema)
            try:
                q_obj = parser.parse(escape_whoosh_query(query))
            except QueryError:
                q_obj = parser.parse(escape_whoosh_query(query.replace('"', '')))

            extras = []
            if query_cpf:
                extras.append(Term("cpf", query_cpf))
            if query_rg:
                extras.append(Term("rg", query_rg))
            if extras:
                q_obj = Or([q_obj] + extras)
        else:
            q_obj = Every()

        if vinculo_selecionado and vinculo_selecionado.lower() != 'todos':
            q_vinculo = Term("vinculo", normalizar_maiusculo(vinculo_selecionado))
            q_obj = And([q_obj, q_vinculo])

        if current_user.is_authenticated:
            perfil = obter_perfil_usuario(current_user)

            if (
                getattr(current_user, 'is_superadmin', False)
                or perfil in PERFIS_ACESSO_TOTAL
                or (getattr(current_user, 'is_admin', False) and not (current_user.perfil or '').strip())
            ):
                q_final = q_obj
            elif perfil in MAPA_PERFIL_DIRETORIA:
                diretoria_req = obter_diretoria_permissao(current_user)
                if not diretoria_req:
                    q_final = Term("id", "__no_access__")
                else:
                    diretoria_req_usuario = diretoria_req
                    q_final = And([
                        q_obj,
                        Term("vinculo", "TERCEIRIZADO"),
                    ])
            else:
                q_final = Term("id", "__no_access__")
        else:
            q_final = Term("id", "__no_access__")

        results = searcher.search(q_final, limit=None)
        resultados = [dict(r) for r in results]

        if diretoria_req_usuario:
            resultados = [
                r for r in resultados
                if _resultado_permitido_por_diretoria(r, diretoria_req_usuario)
            ]

        if not query:
            resultados.sort(key=lambda r: _chave_ordenacao(r, separar_por_vinculo))
            return resultados

        q_lower = query.lower()
        query_cpf = normalizar_cpf(query)
        query_rg = normalizar_rg(query)

        resultados_finais = []
        for r in resultados:
            for c in CAMPOS_PESQUISA:
                val = str(r.get(c, '')).lower()
                if q_lower in val or (query_cpf and query_cpf in val) or (query_rg and query_rg in val):
                    resultados_finais.append(r)
                    break

        resultados_finais.sort(key=lambda r: _chave_ordenacao(r, separar_por_vinculo))
        return resultados_finais
