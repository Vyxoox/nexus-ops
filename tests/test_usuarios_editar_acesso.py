from __future__ import annotations

import json
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from flask import Flask

from core.extensions import db
from models import Usuario
from routes.usuarios import usuario_bp


class TestUsuariosEditarAcesso(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        cls.app = Flask(__name__, template_folder=str(repo_root / "templates"))
        cls.app.config.update(
            SECRET_KEY="test-secret",
            SQLALCHEMY_DATABASE_URI="sqlite:///:memory:",
            SQLALCHEMY_TRACK_MODIFICATIONS=False,
            TESTING=True,
            WTF_CSRF_ENABLED=False,
            LOGIN_DISABLED=True,
        )
        cls.app.jinja_env.globals["csrf_token"] = lambda: ""

        db.init_app(cls.app)
        cls.app.add_url_rule("/painel", endpoint="painel", view_func=lambda: "painel teste")
        cls.app.register_blueprint(usuario_bp)

        with cls.app.app_context():
            db.create_all()

    @classmethod
    def tearDownClass(cls) -> None:
        with cls.app.app_context():
            db.session.remove()
            db.drop_all()

    def setUp(self) -> None:
        self.app_ctx = self.app.app_context()
        self.app_ctx.push()

        db.session.query(Usuario).delete()
        db.session.commit()

        alvo = Usuario(
            login="admin_alvo",
            perfil="DIRETORIA",
            permissoes=json.dumps(["auditoria_logs"], ensure_ascii=False),
            is_admin=True,
            is_superadmin=False,
        )
        alvo.set_password("SenhaInicial123")
        db.session.add(alvo)
        db.session.commit()

        self.alvo_id = alvo.id
        self.client = self.app.test_client()

    def tearDown(self) -> None:
        db.session.remove()
        self.app_ctx.pop()

    def _superadmin_fake(self):
        return SimpleNamespace(
            is_authenticated=True,
            is_superadmin=True,
            id=999,
            login="superadmin_teste",
            perfil="DIRETORIA",
            permissoes=json.dumps(["reindexar"], ensure_ascii=False),
        )

    def test_get_lista_admin_renderiza(self) -> None:
        with patch("core.authz.current_user", self._superadmin_fake()):
            resp = self.client.get("/usuarios")

        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"Editar acesso", resp.data)

    def test_get_editar_acesso_renderiza(self) -> None:
        with patch("routes.usuarios.current_user", self._superadmin_fake()), \
             patch("core.authz.current_user", self._superadmin_fake()):
            resp = self.client.get(f"/usuarios/{self.alvo_id}/editar-acesso")

        self.assertEqual(resp.status_code, 200)
        self.assertIn("Editar Acesso", resp.get_data(as_text=True))

    def test_post_falha_perfil_invalido(self) -> None:
        with patch("routes.usuarios.current_user", self._superadmin_fake()), \
             patch("core.authz.current_user", self._superadmin_fake()), \
             patch("routes.usuarios.registrar_evento_seguro") as audit_mock:
            resp = self.client.post(
                f"/usuarios/{self.alvo_id}/editar-acesso",
                data={"perfil": "INVALIDO", "permissoes": ["auditoria_logs"]},
                follow_redirects=False,
            )

        self.assertEqual(resp.status_code, 302)

        alvo = db.session.get(Usuario, self.alvo_id)
        self.assertEqual(alvo.perfil, "DIRETORIA")

        self.assertEqual(audit_mock.call_args.args[0], "USUARIO_EDITAR_ACESSO_FALHA")
        detalhes = audit_mock.call_args.kwargs["detalhes"]
        self.assertEqual(detalhes["motivo"], "perfil_invalido")

    def test_post_sucesso_edita_perfil_e_permissoes(self) -> None:
        with patch("routes.usuarios.current_user", self._superadmin_fake()), \
             patch("core.authz.current_user", self._superadmin_fake()), \
             patch("routes.usuarios.registrar_evento_seguro") as audit_mock:
            resp = self.client.post(
                f"/usuarios/{self.alvo_id}/editar-acesso",
                data={"perfil": "RH", "permissoes": ["auditoria_logs", "reindexar"]},
                follow_redirects=False,
            )

        self.assertEqual(resp.status_code, 302)

        alvo = db.session.get(Usuario, self.alvo_id)
        self.assertEqual(alvo.perfil, "RH")
        perms = json.loads(alvo.permissoes or "[]")
        self.assertEqual(sorted(perms), ["auditoria_logs", "reindexar"])

        self.assertEqual(audit_mock.call_args.args[0], "USUARIO_EDITAR_ACESSO_SUCESSO")
        detalhes = audit_mock.call_args.kwargs["detalhes"]
        self.assertEqual(detalhes["usuario_alvo"], "admin_alvo")
        self.assertGreaterEqual(int(detalhes["total_alteracoes"]), 1)

    def test_get_editar_acesso_proprio_perfil_bloqueado(self) -> None:
        fake_super = self._superadmin_fake()
        with self.app.app_context():
            u = Usuario(
                id=fake_super.id,
                login=fake_super.login,
                is_superadmin=True,
                perfil="RH",
                is_admin=True,
            )
            u.set_password("SenhaTeste123")
            db.session.add(u)
            db.session.commit()

        with patch("routes.usuarios.current_user", fake_super), \
             patch("core.authz.current_user", fake_super):
            resp = self.client.get(f"/usuarios/{fake_super.id}/editar-acesso")

        self.assertEqual(resp.status_code, 302)
        self.assertTrue(resp.headers["Location"].endswith("/usuarios"))

        with self.client.session_transaction() as sess:
            flashes = dict(sess['_flashes'])
            self.assertIn('Você não pode editar o seu próprio perfil de acesso', flashes.get('warning', ''))

    def test_post_falha_rebaixar_ultimo_superadmin(self) -> None:
        with self.app.app_context():
            u_alvo = db.session.get(Usuario, self.alvo_id)
            u_alvo.is_superadmin = True
            u_alvo.perfil = 'RH'
            db.session.commit()

        with patch("routes.usuarios.current_user", self._superadmin_fake()), \
             patch("core.authz.current_user", self._superadmin_fake()), \
             patch("routes.usuarios.Usuario.query") as query_mock:
            query_mock.filter.return_value.count.return_value = 0

            resp = self.client.post(
                f"/usuarios/{self.alvo_id}/editar-acesso",
                data={
                    'perfil': 'TECH',
                    'permissoes': ['auditoria_logs'],
                },
            )

        self.assertEqual(resp.status_code, 302)
        with self.client.session_transaction() as sess:
            flashes = dict(sess['_flashes'])
            self.assertIn('Não é possível alterar o perfil do único Superadmin', flashes.get('error', ''))


if __name__ == "__main__":
    unittest.main()
