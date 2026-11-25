from datetime import datetime, date

from whoosh.query import Every

from models import Funcionario
from services.normalizacao_service import (
    normalizar_cpf,
    normalizar_rg,
    normalizar_maiusculo,
    normalizar_titulo,
)


def normalizar_titulo_simples(valor):
    if valor is None:
        return ''
    s = str(valor).strip()
    if not s or s.lower() in ('none', 'nan', 'nat'):
        return ''
    return ' '.join(p.capitalize() for p in s.split())


def date_to_datetime(val):
    if val is None:
        return None
    if isinstance(val, datetime):
        return val
    if isinstance(val, date):
        return datetime.combine(val, datetime.min.time())
    return val


def _documento_funcionario(func: Funcionario) -> dict:
    return {
        'id': str(func.id),
        'matricula': func.matricula or '',
        'cpf': normalizar_cpf(func.cpf),
        'rg': normalizar_rg(func.rg or ''),
        'nome_completo': normalizar_titulo(func.nome_completo),
        'data_nasc': date_to_datetime(func.data_nasc),
        'endereco_residencial': (func.endereco_residencial or '').strip(),

        'vinculo': normalizar_maiusculo(func.vinculo),
        'tipo': normalizar_maiusculo(func.tipo or ''),
        'subtipo_vinculo': normalizar_maiusculo(func.subtipo_vinculo or ''),
        'forma_ingresso': normalizar_titulo(func.forma_ingresso or ''),

        'cargo_atual': normalizar_titulo(func.cargo_atual or ''),
        'cargo_anterior': normalizar_titulo(func.cargo_anterior or ''),

        'unidade': normalizar_titulo(func.unidade or ''),
        'departamento': normalizar_titulo(func.departamento or ''),
        'diretoria': normalizar_maiusculo(func.diretoria or ''),

        'data_integracao': date_to_datetime(func.data_integracao),
        'data_inicio': date_to_datetime(func.data_inicio),
        'data_admissao': date_to_datetime(func.data_admissao),
        'data_desligamento': date_to_datetime(func.data_desligamento),

        'email_corporativo': (func.email_corporativo or '').strip(),
        'email_pessoal': (func.email_pessoal or '').strip(),
        'telefone_pessoal': (func.telefone_pessoal or '').strip(),
        'ramal': (func.ramal or '').strip(),

        'cin': (func.cin or '').strip(),
        'titulo_eleitor': (func.titulo_eleitor or '').strip(),
        'pis_pasep': (func.pis_pasep or '').strip(),
        'registro_interno': (func.registro_interno or '').strip(),
        'situacao': normalizar_titulo(func.situacao or ''),
        'ativo': bool(func.ativo),
        'documento_vinculo': (func.documento_vinculo or '').strip(),

        'empresa_contratada': normalizar_titulo_simples(func.empresa_contratada or ''),
        'numero_contrato': (func.numero_contrato or '').strip(),
        'gestor_contrato': normalizar_titulo(func.gestor_contrato or ''),
        'lider_tecnico': normalizar_titulo(func.lider_tecnico or ''),
        'analista_contratos': normalizar_titulo(func.analista_contratos or ''),
        'representante_fornecedor': normalizar_titulo(func.representante_fornecedor or ''),
    }


def reindexar_funcionario(ix, funcionario):
    writer = ix.writer()
    writer.delete_by_term('id', str(funcionario.id))

    if funcionario.ativo:
        writer.add_document(**_documento_funcionario(funcionario))

    writer.commit()


def reindexar_todos(ix):
    writer = ix.writer()
    writer.delete_by_query(Every())

    for func in Funcionario.query.filter_by(ativo=True).all():
        writer.add_document(**_documento_funcionario(func))

    writer.commit()
