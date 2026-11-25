from __future__ import annotations

import os
import unittest
from datetime import date, timedelta
from unittest.mock import patch

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("SECRET_KEY", "test-secret")

from app import app, db  # noqa: E402
from models import Funcionario, Usuario  # noqa: E402


class TestPainelDashboard(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        app.config.update(
            TESTING=True,
            WTF_CSRF_ENABLED=False,
        )
        with app.app_context():
            db.create_all()

    def setUp(self) -> None:
        self.app_ctx = app.app_context()
        self.app_ctx.push()
        db.session.query(Funcionario).delete()
        db.session.query(Usuario).delete()
        db.session.commit()

        self.superadmin = Usuario(
            login="diretoria_demo",
            perfil="DIRETORIA",
            is_admin=True,
            is_superadmin=True,
        )
        self.superadmin.set_password("SenhaForte123!")

        self.tech_user = Usuario(
            login="tech_demo",
            perfil="TECH",
            is_admin=True,
            is_superadmin=False,
        )
        self.tech_user.set_password("SenhaForte123!")

        db.session.add_all([self.superadmin, self.tech_user])
        db.session.add_all([
            Funcionario(
                nome_completo="Ana Paula Souza",
                cpf="11111111101",
                vinculo="EFETIVO",
                matricula="NX-01",
                cargo_atual="Engenheira de Software",
                departamento="ENGENHARIA DE SOFTWARE & DADOS",
                diretoria="DIR.TECH - DIRETORIA DE TECNOLOGIA & DADOS",
                unidade="MATRIZ - SÃO PAULO (SP)",
                situacao="Ativo",
                ativo=True,
                data_admissao=date.today() - timedelta(days=10),
            ),
            Funcionario(
                nome_completo="Carlos Terceiro Tech",
                cpf="22222222202",
                vinculo="TERCEIRIZADO",
                cargo_atual="Especialista Cloud",
                departamento="INFRAESTRUTURA & CIBERSEGURANÇA",
                diretoria="DIR.TECH - DIRETORIA DE TECNOLOGIA & DADOS",
                unidade="HUB TECNOLOGIA - CAMPINAS (SP)",
                empresa_contratada="CloudOps Tecnologia Ltda",
                numero_contrato="CT-2026-01",
                gestor_contrato="Gestor Tech",
                lider_tecnico="Lider Tech",
                analista_contratos="Analista Tech",
                representante_fornecedor="Rep Tech",
                situacao="Ativo",
                ativo=True,
                data_admissao=date.today() - timedelta(days=15),
            ),
            Funcionario(
                nome_completo="Bruno Terceiro Ops",
                cpf="33333333303",
                vinculo="TERCEIRIZADO",
                cargo_atual="Supervisor Logístico",
                departamento="OPERAÇÕES & LOGÍSTICA",
                diretoria="DIR.OPS - DIRETORIA DE OPERAÇÕES & LOGÍSTICA",
                unidade="CENTRO OPERACIONAL - CURITIBA (PR)",
                empresa_contratada="Vanguard Facilities S.A.",
                numero_contrato="CT-2026-02",
                gestor_contrato="Gestor Ops",
                lider_tecnico="Lider Ops",
                analista_contratos="Analista Ops",
                representante_fornecedor="Rep Ops",
                situacao="Ativo",
                ativo=True,
            ),
        ])
        db.session.commit()
        self.client = app.test_client()

    def tearDown(self) -> None:
        db.session.remove()
        self.app_ctx.pop()

    def test_painel_global_exibe_kpis_e_sem_termos_publicos(self) -> None:
        with patch("flask_login.utils._get_user", return_value=self.superadmin), \
             patch("app.current_user", self.superadmin):
            resp = self.client.get("/painel")

        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)

        self.assertIn("Meu Painel de Gestão", html)
        self.assertIn("Nexus People &amp; Ops", html)
        self.assertIn("Ana Paula Souza", html)
        self.assertIn("Carlos Terceiro Tech", html)
        self.assertIn("Bruno Terceiro Ops", html)
        self.assertIn("CloudOps Tecnologia Ltda", html)

        for termo_proibido in ("Departamento de Estradas", "D.E.R", "CGR.9", "Ouvidoria", "Servidor"):
            self.assertNotIn(termo_proibido, html)

    def test_painel_escopado_tech_filtra_apenas_terceirizados_tech(self) -> None:
        with patch("flask_login.utils._get_user", return_value=self.tech_user), \
             patch("app.current_user", self.tech_user):
            resp = self.client.get("/painel")

        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)

        self.assertIn("Carlos Terceiro Tech", html)
        self.assertNotIn("Ana Paula Souza", html)
        self.assertNotIn("Bruno Terceiro Ops", html)


if __name__ == "__main__":
    unittest.main()
