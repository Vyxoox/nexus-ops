import os
from PIL import Image, UnidentifiedImageError
from flask import current_app

Image.MAX_IMAGE_PIXELS = 20_000_000
FORMATOS_PERMITIDOS = {'JPEG', 'PNG', 'WEBP'}


def caminho_foto_funcionario(root_path, funcionario_id):
    return os.path.join(root_path, 'static', 'fotos_funcionarios', f'{int(funcionario_id)}.jpg')


def salvar_foto(root_path, file, funcionario_id):
    if not file or file.filename == '':
        return

    pasta = os.path.join(root_path, 'static', 'fotos_funcionarios')
    os.makedirs(pasta, exist_ok=True)

    caminho = caminho_foto_funcionario(root_path, funcionario_id)
    file.seek(0)

    try:
        with Image.open(file) as img:
            if (img.format or '').upper() not in FORMATOS_PERMITIDOS:
                raise ValueError("Tipo de arquivo inválido.")
            img_convertida = img.convert("RGB")
            img_convertida.thumbnail((500, 500))
            img_convertida.save(caminho, "JPEG", quality=85, optimize=True)
    except ValueError:
        raise
    except UnidentifiedImageError:
        raise ValueError("Imagem Inválida.")
    except Exception as e:
        current_app.logger.exception(
            f"ERRO REAL: {type(e).__name__}"
        )
        raise ValueError("Erro ao processar imagem.")

def remover_foto(root_path, funcionario_id):
    caminho = caminho_foto_funcionario(root_path, funcionario_id)
    if os.path.exists(caminho):
        os.remove(caminho)
        return True
    return False
