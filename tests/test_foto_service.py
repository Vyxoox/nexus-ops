import io
import os
import tempfile
import unittest

from flask import Flask
from PIL import Image
from werkzeug.datastructures import FileStorage

from services.foto_service import salvar_foto


class TestFotoService(unittest.TestCase):
    """Testes unitários para validação e processamento de fotos com Pillow."""

    def setUp(self) -> None:
        self.app = Flask(__name__)

    def test_salvar_foto_png_valido(self) -> None:
        buf = io.BytesIO()
        Image.new('RGB', (800, 600), color='navy').save(buf, format='PNG')
        buf.seek(0)
        arquivo = FileStorage(stream=buf, filename='foto.png')

        with tempfile.TemporaryDirectory() as tmp_dir:
            with self.app.app_context():
                salvar_foto(tmp_dir, arquivo, 1)

            caminho = os.path.join(tmp_dir, 'static', 'fotos_funcionarios', '1.jpg')
            self.assertTrue(os.path.exists(caminho))
            with Image.open(caminho) as img_salva:
                self.assertEqual(img_salva.format, 'JPEG')
                self.assertLessEqual(img_salva.width, 500)
                self.assertLessEqual(img_salva.height, 500)

    def test_salvar_foto_formato_nao_permitido_gif(self) -> None:
        buf = io.BytesIO()
        Image.new('RGB', (64, 64), color='red').save(buf, format='GIF')
        buf.seek(0)
        arquivo = FileStorage(stream=buf, filename='animacao.gif')

        with tempfile.TemporaryDirectory() as tmp_dir:
            with self.app.app_context():
                with self.assertRaisesRegex(ValueError, r'^Tipo de arquivo inválido\.$'):
                    salvar_foto(tmp_dir, arquivo, 1)

    def test_salvar_foto_arquivo_corrompido(self) -> None:
        buf = io.BytesIO(b'nao e uma imagem')
        arquivo = FileStorage(stream=buf, filename='corrompida.jpg')

        with tempfile.TemporaryDirectory() as tmp_dir:
            with self.app.app_context():
                with self.assertRaisesRegex(ValueError, r'^Imagem Inválida\.$'):
                    salvar_foto(tmp_dir, arquivo, 1)


if __name__ == '__main__':
    unittest.main()
