import smtplib
import unittest
from unittest.mock import MagicMock, patch

from flask import Flask

from services.email_services import enviar_email


class TestEmailService(unittest.TestCase):
    """Testes unitários para o serviço de envio de e-mails SMTP."""

    def setUp(self) -> None:
        self.app = Flask(__name__)
        self.app.config.update(
            SMTP_HOST='smtp.example.com',
            SMTP_PORT=587,
            SMTP_USER='noreply@example.com',
            SMTP_PASSWORD='app-password',
            SMTP_USE_TLS=True,
            SMTP_USE_SSL=False,
            SMTP_TIMEOUT=10,
        )

    @patch('services.email_services.smtplib.SMTP')
    def test_enviar_email_retorna_false_quando_quit_desconectado(self, smtp_cls: MagicMock) -> None:
        cliente = MagicMock()
        cliente.login.side_effect = smtplib.SMTPServerDisconnected('Connection unexpectedly closed')
        cliente.quit.side_effect = smtplib.SMTPServerDisconnected('please run connect() first')
        smtp_cls.return_value = cliente

        with self.app.app_context():
            resultado = enviar_email('destino@example.com', 'Assunto', 'Corpo')

        self.assertFalse(resultado)
        cliente.quit.assert_called_once_with()
        cliente.close.assert_called_once_with()

    @patch('services.email_services.smtplib.SMTP')
    def test_enviar_email_sucesso_tls(self, smtp_cls: MagicMock) -> None:
        cliente = MagicMock()
        smtp_cls.return_value = cliente

        with self.app.app_context():
            resultado = enviar_email('destino@example.com', 'Assunto', 'Corpo')

        self.assertTrue(resultado)
        smtp_cls.assert_called_once_with('smtp.example.com', 587, timeout=10)
        cliente.starttls.assert_called_once_with()
        cliente.login.assert_called_once_with('noreply@example.com', 'app-password')
        cliente.send_message.assert_called_once()
        cliente.quit.assert_called_once_with()
        cliente.close.assert_called_once_with()


if __name__ == '__main__':
    unittest.main()
