import os
import shutil
from whoosh.index import create_in

from app import app
from core.schema import schema
from services.indexacao_service import reindexar_todos


def main() -> None:
    caminho_indice = app.config.get('WHOOSH_INDEX_DIR') or os.getenv('WHOOSH_INDEX_DIR', 'indice_colaboradores')
    if os.path.exists(caminho_indice):
        shutil.rmtree(caminho_indice)
    os.makedirs(caminho_indice, exist_ok=True)
    ix = create_in(caminho_indice, schema)

    with app.app_context():
        reindexar_todos(ix)
        app.config['WHOOSH_IX'] = ix

    print(f"Índice corporativo reconstruído com sucesso em: {caminho_indice}")


if __name__ == '__main__':
    main()
