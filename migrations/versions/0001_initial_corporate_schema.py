"""Initial corporate schema

Revision ID: 0001_initial
Revises:
Create Date: 2026-11-25 16:20:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = '0001_initial'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'usuarios',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('login', sa.String(length=80), nullable=False),
        sa.Column('hash_senha', sa.String(length=255), nullable=False),
        sa.Column('perfil', sa.String(length=20), nullable=False),
        sa.Column('permissoes', sa.Text(), nullable=True),
        sa.Column('is_admin', sa.Boolean(), nullable=False),
        sa.Column('is_superadmin', sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('login'),
    )

    op.create_table(
        'funcionarios',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('nome_completo', sa.String(length=200), nullable=False),
        sa.Column('cpf', sa.String(length=11), nullable=False),
        sa.Column('rg', sa.String(length=20), nullable=True),
        sa.Column('cin', sa.String(length=30), nullable=True),
        sa.Column('titulo_eleitor', sa.String(length=20), nullable=True),
        sa.Column('pis_pasep', sa.String(length=20), nullable=True),
        sa.Column('data_nasc', sa.Date(), nullable=True),
        sa.Column('endereco_residencial', sa.String(length=255), nullable=True),
        sa.Column('telefone_pessoal', sa.String(length=20), nullable=True),
        sa.Column('email_pessoal', sa.String(length=150), nullable=True),
        sa.Column('email_corporativo', sa.String(length=150), nullable=True),
        sa.Column('ramal', sa.String(length=20), nullable=True),
        sa.Column('vinculo', sa.String(length=20), nullable=False),
        sa.Column('tipo', sa.String(length=30), nullable=True),
        sa.Column('subtipo_vinculo', sa.String(length=50), nullable=True),
        sa.Column('forma_ingresso', sa.String(length=40), nullable=True),
        sa.Column('registro_interno', sa.String(length=50), nullable=True),
        sa.Column('matricula', sa.String(length=50), nullable=True),
        sa.Column('cargo_atual', sa.String(length=200), nullable=True),
        sa.Column('cargo_anterior', sa.String(length=200), nullable=True),
        sa.Column('unidade', sa.String(length=200), nullable=True),
        sa.Column('departamento', sa.String(length=200), nullable=True),
        sa.Column('diretoria', sa.String(length=200), nullable=True),
        sa.Column('data_integracao', sa.Date(), nullable=True),
        sa.Column('data_inicio', sa.Date(), nullable=True),
        sa.Column('data_admissao', sa.Date(), nullable=True),
        sa.Column('situacao', sa.String(length=200), nullable=True),
        sa.Column('data_desligamento', sa.Date(), nullable=True),
        sa.Column('documento_vinculo', sa.String(length=200), nullable=True),
        sa.Column('empresa_contratada', sa.String(length=200), nullable=True),
        sa.Column('numero_contrato', sa.String(length=200), nullable=True),
        sa.Column('gestor_contrato', sa.String(length=200), nullable=True),
        sa.Column('lider_tecnico', sa.String(length=200), nullable=True),
        sa.Column('analista_contratos', sa.String(length=200), nullable=True),
        sa.Column('representante_fornecedor', sa.String(length=200), nullable=True),
        sa.Column('ativo', sa.Boolean(), nullable=True),
        sa.Column('data_criacao', sa.DateTime(), nullable=True),
        sa.Column('data_atualizacao', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('cpf'),
        sa.UniqueConstraint('matricula'),
    )

    op.create_table(
        'logs_auditoria',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('usuario_id', sa.Integer(), nullable=True),
        sa.Column('usuario_login', sa.String(length=80), nullable=True),
        sa.Column('acao', sa.String(length=120), nullable=False),
        sa.Column('categoria', sa.String(length=50), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('recurso', sa.String(length=80), nullable=True),
        sa.Column('recurso_id', sa.String(length=80), nullable=True),
        sa.Column('metodo_http', sa.String(length=10), nullable=True),
        sa.Column('rota', sa.String(length=255), nullable=True),
        sa.Column('ip_origem', sa.String(length=45), nullable=True),
        sa.Column('user_agent', sa.String(length=255), nullable=True),
        sa.Column('detalhes', sa.Text(), nullable=True),
        sa.Column('criado_em', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['usuario_id'], ['usuarios.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_logs_auditoria_acao', 'logs_auditoria', ['acao'])
    op.create_index('ix_logs_auditoria_categoria', 'logs_auditoria', ['categoria'])
    op.create_index('ix_logs_auditoria_criado_em', 'logs_auditoria', ['criado_em'])
    op.create_index('ix_logs_auditoria_recurso', 'logs_auditoria', ['recurso'])
    op.create_index('ix_logs_auditoria_recurso_id', 'logs_auditoria', ['recurso_id'])
    op.create_index('ix_logs_auditoria_status', 'logs_auditoria', ['status'])
    op.create_index('ix_logs_auditoria_usuario_id', 'logs_auditoria', ['usuario_id'])
    op.create_index('ix_logs_auditoria_usuario_login', 'logs_auditoria', ['usuario_login'])


def downgrade():
    op.drop_table('logs_auditoria')
    op.drop_table('funcionarios')
    op.drop_table('usuarios')
