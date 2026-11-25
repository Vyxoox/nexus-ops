from flask import Blueprint, flash, redirect, url_for, request, render_template, session, current_app
from flask_login import login_required, current_user

from core import db
from core.audit_policy import audit_event
from models import Funcionario
from routes.verfunc import preencher_campos_comuns, validar_campos_condicionais
from services.normalizacao_service import normalizar_maiusculo
from services.foto_service import salvar_foto, remover_foto
from services.indexacao_service import reindexar_funcionario
from services.auditoria_services import registrar_evento_seguro, gerar_diff_antes_depois

editfunc_bp = Blueprint('editfunc', __name__)

OPCOES_SUBTIPO_VINCULO = [
    'ADMINISTRATIVO',
    'OPERACIONAL',
    'TECNOLOGIA & DADOS',
]

OPCOES_UNIDADE = [
    'MATRIZ - SÃO PAULO (SP)',
    'HUB TECNOLOGIA - CAMPINAS (SP)',
    'CENTRO OPERACIONAL - CURITIBA (PR)',
    'FILIAL CORPORATIVA - BELO HORIZONTE (MG)',
    'REMOTO / HÍBRIDO NACIONAL',
]

OPCOES_DEPARTAMENTO = [
    'PESSOAS & CULTURA (RH)',
    'ENGENHARIA DE SOFTWARE & DADOS',
    'INFRAESTRUTURA & CIBERSEGURANÇA',
    'FINANÇAS & CONTROLADORIA',
    'SUPRIMENTOS & CONTRATOS',
    'OPERAÇÕES & LOGÍSTICA',
    'QUALIDADE & PROCESSOS',
    'JURÍDICO & COMPLIANCE',
]

OPCOES_DIRETORIA = [
    'DIR.PESSOAS - DIRETORIA DE PESSOAS & CULTURA',
    'DIR.TECH - DIRETORIA DE TECNOLOGIA & DADOS',
    'DIR.FIN - DIRETORIA FINANCEIRA & ADMINISTRATIVA',
    'DIR.OPS - DIRETORIA DE OPERAÇÕES & LOGÍSTICA',
]

OPCOES_TIPO = [
    'CLT',
    'EXECUTIVO',
    'ESTÁGIO',
    'TEMPORÁRIO',
    'TERCEIRIZADO',
]

OPCOES_FORMA_INGRESSO = [
    'Processo Seletivo Externo',
    'Recrutamento Interno',
    'Hunting Executivo',
    'Contrato de Prestação de Serviços',
]

OPCOES_SITUACAO = [
    'Ativo',
    'Inativo - Desligamento Voluntário',
    'Inativo - Rescisão Contratual',
    'Inativo - Término de Contrato',
    'Inativo - Aposentadoria',
    'Inativo - Outros',
]

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


def _validar_selects_edicao(form) -> tuple[str | None, str | None]:
    regras = [
        ('subtipo_vinculo', SET_SUBTIPO, 'Subtipo de vínculo inválido.'),
        ('unidade', SET_UNIDADE, 'Unidade inválida.'),
        ('departamento', SET_DEPARTAMENTO, 'Departamento inválido.'),
        ('diretoria', SET_DIRETORIA, 'Diretoria inválida.'),
        ('tipo', SET_TIPO, 'Tipo de contratação inválido.'),
        ('forma_ingresso', SET_FORMA_INGRESSO, 'Forma de ingresso inválida.'),
        ('situacao', SET_SITUACAO, 'Situação do colaborador inválida.'),
    ]
    for campo, opcoes, msg in regras:
        if not _valor_em_lista(form.get(campo), opcoes, obrigatorio=True):
            return campo, msg
    return None, None


@editfunc_bp.route('/funcionario/editar/<int:id>', methods=['GET', 'POST'])
@login_required
@audit_event()
def editar_funcionario(id):
    if not current_user.is_admin:
        registrar_evento_seguro(
            'FUNCIONARIO_EDITAR_NEGADO',
            categoria='seguranca',
            status='falha',
            recurso='funcionario',
            recurso_id=str(id),
        )
        flash('Acesso negado: você não tem privilégios administrativos.', 'error')
        return redirect(url_for('painel'))

    func = Funcionario.query.get_or_404(id)

    if request.method == 'POST':
        campos_auditoria = (
            'nome_completo', 'cpf', 'rg', 'vinculo', 'tipo', 'subtipo_vinculo',
            'forma_ingresso', 'matricula', 'cargo_atual', 'cargo_anterior',
            'unidade', 'departamento', 'diretoria', 'situacao', 'data_desligamento',
            'empresa_contratada', 'numero_contrato', 'gestor_contrato',
            'lider_tecnico', 'analista_contratos', 'representante_fornecedor',
        )
        valores_antes = {campo: getattr(func, campo, None) for campo in campos_auditoria}

        vinculo_norm = normalizar_maiusculo(request.form.get('vinculo'))
        func.vinculo = vinculo_norm
        preencher_campos_comuns(func, request.form)

        _, erro_select = _validar_selects_edicao(request.form)
        if erro_select:
            flash(erro_select, 'error')
            return redirect(url_for('editfunc.editar_funcionario', id=id))

        erro = validar_campos_condicionais(func, vinculo_norm)
        if erro:
            registrar_evento_seguro(
                'FUNCIONARIO_EDITAR_FALHA',
                categoria='cadastro',
                status='falha',
                recurso='funcionario',
                recurso_id=str(func.id),
                detalhes={'motivo': 'validacao_campos_condicionais', 'funcionario_vinculo': vinculo_norm},
            )
            flash(erro, 'error')
            return redirect(url_for('editfunc.editar_funcionario', id=id))

        try:
            foto = request.files.get('foto')
            db.session.commit()

            salvar_foto(current_app.root_path, foto, func.id)

            ix = current_app.config['WHOOSH_IX']
            reindexar_funcionario(ix, func)

            valores_depois = {campo: getattr(func, campo, None) for campo in campos_auditoria}
            alteracoes = gerar_diff_antes_depois(valores_antes, valores_depois, campos_auditoria)

            registrar_evento_seguro(
                'FUNCIONARIO_EDITAR_SUCESSO',
                categoria='cadastro',
                status='sucesso',
                recurso='funcionario',
                recurso_id=str(func.id),
                detalhes={
                    'funcionario_nome': func.nome_completo,
                    'funcionario_vinculo': func.vinculo,
                    'total_alteracoes': len(alteracoes),
                    'alteracoes': alteracoes,
                },
            )

            flash('Colaborador atualizado com sucesso!', 'success')
            return redirect(url_for('painel'))
        except Exception as e:
            db.session.rollback()
            registrar_evento_seguro(
                'FUNCIONARIO_EDITAR_FALHA',
                categoria='cadastro',
                status='falha',
                recurso='funcionario',
                recurso_id=str(func.id),
                detalhes={'motivo': 'erro_salvar', 'error': str(e)},
            )
            flash(f'Erro ao salvar no banco: {str(e)}', 'error')
            return redirect(url_for('editfunc.editar_funcionario', id=id))

    return render_template(
        'form_funcionario.html',
        func=func,
        opcoes_subtipo_vinculo=OPCOES_SUBTIPO_VINCULO,
        opcoes_unidade=OPCOES_UNIDADE,
        opcoes_diretoria=OPCOES_DIRETORIA,
        opcoes_departamento=OPCOES_DEPARTAMENTO,
        opcoes_tipo=OPCOES_TIPO,
        opcoes_forma_ingresso=OPCOES_FORMA_INGRESSO,
        opcoes_situacao=OPCOES_SITUACAO,
    )


@editfunc_bp.route('/funcionario/remover-foto/<int:id>', methods=['POST'])
@login_required
@audit_event()
def remover_foto_funcionario(id):
    if not current_user.is_admin:
        registrar_evento_seguro(
            'FUNCIONARIO_REMOVER_FOTO_NEGADO',
            categoria='seguranca',
            status='falha',
            recurso='funcionario',
            recurso_id=str(id),
        )
        session.pop('_flashes', None)
        flash('Acesso negado: você não tem privilégios administrativos.', 'error')
        return redirect(url_for('painel'))

    func = Funcionario.query.get_or_404(id)

    try:
        removida = remover_foto(current_app.root_path, func.id)

        session.pop('_flashes', None)
        if removida:
            registrar_evento_seguro(
                'FUNCIONARIO_REMOVER_FOTO_SUCESSO',
                categoria='cadastro',
                status='sucesso',
                recurso='funcionario',
                recurso_id=str(func.id),
                detalhes={'foto_removida': True},
            )
            flash('Foto removida com sucesso!', 'success')
        else:
            registrar_evento_seguro(
                'FUNCIONARIO_REMOVER_FOTO_SEM_ARQUIVO',
                categoria='cadastro',
                status='falha',
                recurso='funcionario',
                recurso_id=str(func.id),
                detalhes={'foto_removida': False},
            )
            flash('Este colaborador não possui foto cadastrada.', 'error')

    except Exception as e:
        registrar_evento_seguro(
            'FUNCIONARIO_REMOVER_FOTO_FALHA',
            categoria='cadastro',
            status='falha',
            recurso='funcionario',
            recurso_id=str(func.id),
            detalhes={'motivo': 'erro_remocao', 'error': str(e)},
        )
        session.pop('_flashes', None)
        flash(f'Erro ao remover foto: {str(e)}', 'error')

    return redirect(url_for('editfunc.editar_funcionario', id=func.id))
