from whoosh.index import open_dir
from whoosh.qparser import MultifieldParser, OrGroup
from whoosh.query import Term, And

CAMINHO_INDICE = "indice_colaboradores"


def buscar(termo=None, vinculo=None, diretoria=None, departamento=None, cargo=None):
    ix = open_dir(CAMINHO_INDICE)
    with ix.searcher() as searcher:
        queries = []

        if termo:
            parser = MultifieldParser(
                ["nome_completo", "cargo_atual", "cpf", "rg", "cargo_anterior", "unidade", "departamento"],
                schema=ix.schema,
                group=OrGroup,
            )
            queries.append(parser.parse(termo))

        if vinculo:
            queries.append(Term("vinculo", vinculo))
        if diretoria:
            queries.append(Term("diretoria", diretoria))
        if departamento:
            queries.append(Term("departamento", departamento))
        if cargo:
            queries.append(Term("cargo_atual", cargo))

        if not queries:
            print("Nenhum critério informado.")
            return

        query_final = And(queries) if len(queries) > 1 else queries[0]
        results = searcher.search(query_final, limit=30)

        print(f"Resultados encontrados: {len(results)}")
        for r in results:
            print(f"\n--- {r['nome_completo']} ---")
            print(f"Vínculo: {r['vinculo']}")
            if r['vinculo'] == 'EFETIVO':
                print(f"Matrícula: {r.get('matricula', '')}")
                print(f"Cargo anterior: {r.get('cargo_anterior', '')}")
                print(f"Cargo atual: {r.get('cargo_atual', '')}")
                print(f"Diretoria: {r.get('diretoria', '')}")
            else:
                print(f"Empresa: {r.get('empresa_contratada', '')}")
                print(f"Cargo: {r.get('cargo_atual', '')}")
                print(f"Subtipo: {r.get('subtipo_vinculo', '')}")
            print(f"Unidade: {r.get('unidade', '')}")
            print(f"Departamento: {r.get('departamento', '')}")


if __name__ == "__main__":
    while True:
        print("\n" + "=" * 50)
        termo = input("Termo de busca (ou Enter para ignorar): ").strip()
        vinculo = input("Filtrar por vínculo (efetivo/terceirizado): ").strip().upper()
        diretoria = input("Filtrar por diretoria (ex: DIR.TECH): ").strip()
        departamento = input("Filtrar por departamento: ").strip()
        cargo = input("Filtrar por cargo atual: ").strip()

        if not termo and not vinculo and not diretoria and not departamento and not cargo:
            print("Saindo...")
            break

        buscar(
            termo or None,
            vinculo or None,
            diretoria or None,
            departamento or None,
            cargo or None,
        )
