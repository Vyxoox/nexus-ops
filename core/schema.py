from whoosh.fields import Schema, TEXT, KEYWORD, ID, DATETIME, BOOLEAN
from whoosh.analysis import StandardAnalyzer, CharsetFilter
from whoosh.support.charset import accent_map

# Analyzer com lowercasing e remoção de acentos
analisador = StandardAnalyzer() | CharsetFilter(accent_map)

schema = Schema(
    # ===== Identificadores =====
    id=ID(stored=True, unique=True),
    matricula=ID(stored=True),
    cpf=ID(stored=True),
    rg=ID(stored=True),
    cin=ID(stored=True),
    titulo_eleitor=ID(stored=True),
    pis_pasep=ID(stored=True),

    # ===== Dados pessoais =====
    nome_completo=TEXT(analyzer=analisador, stored=True),
    data_nasc=DATETIME(stored=True),
    endereco_residencial=TEXT(analyzer=analisador, stored=True),
    telefone_pessoal=ID(stored=True),
    email_pessoal=ID(stored=True),
    email_corporativo=ID(stored=True),
    ramal=ID(stored=True),

    # ===== Vínculo =====
    vinculo=KEYWORD(stored=True),
    tipo=KEYWORD(stored=True),
    subtipo_vinculo=KEYWORD(stored=True),
    forma_ingresso=KEYWORD(stored=True),
    registro_interno=ID(stored=True),

    # ===== Cargos =====
    cargo_atual=TEXT(analyzer=analisador, stored=True),
    cargo_anterior=TEXT(analyzer=analisador, stored=True),

    # ===== Estrutura organizacional =====
    unidade=TEXT(analyzer=analisador, stored=True),
    departamento=TEXT(analyzer=analisador, stored=True),
    diretoria=KEYWORD(stored=True),

    # ===== Datas =====
    data_integracao=DATETIME(stored=True),
    data_inicio=DATETIME(stored=True),
    data_admissao=DATETIME(stored=True),
    data_desligamento=DATETIME(stored=True),

    # ===== Situação =====
    situacao=TEXT(analyzer=analisador, stored=True),
    ativo=BOOLEAN(stored=True),

    # ===== Documentos / contrato =====
    documento_vinculo=TEXT(analyzer=analisador, stored=True),

    # ===== Fornecedor / terceirizados =====
    empresa_contratada=TEXT(analyzer=analisador, stored=True),
    numero_contrato=ID(stored=True),
    gestor_contrato=TEXT(analyzer=analisador, stored=True),
    lider_tecnico=TEXT(analyzer=analisador, stored=True),
    analista_contratos=TEXT(analyzer=analisador, stored=True),
    representante_fornecedor=TEXT(analyzer=analisador, stored=True),
)
