import smtplib
from email.message import EmailMessage
from flask import current_app


def enviar_email(destinatario, assunto, corpo):
    msg = EmailMessage()
    msg["Subject"] = assunto
    msg["From"] = current_app.config["SMTP_USER"]
    msg["To"] = destinatario
    msg.set_content(corpo)

    cliente_smtp = None
    try:
        if current_app.config["SMTP_USE_SSL"]:
            cliente_smtp = smtplib.SMTP_SSL(
                current_app.config["SMTP_HOST"],
                current_app.config["SMTP_PORT"],
                timeout=current_app.config["SMTP_TIMEOUT"],
            )
        else:
            cliente_smtp = smtplib.SMTP(
                current_app.config["SMTP_HOST"],
                current_app.config["SMTP_PORT"],
                timeout=current_app.config["SMTP_TIMEOUT"],
            )

            current_app.logger.info("Conectado ao host SMTP")

            if current_app.config["SMTP_USE_TLS"]:
                current_app.logger.info("Iniciando TLS")
                cliente_smtp.starttls()
                current_app.logger.info("TLS iniciado")

        if current_app.config["SMTP_USER"] and current_app.config["SMTP_PASSWORD"]:
            current_app.logger.info("Realizando autenticação SMTP")
            cliente_smtp.login(
                current_app.config["SMTP_USER"],
                current_app.config["SMTP_PASSWORD"],
            )
            current_app.logger.info("Autenticação SMTP concluída")

        cliente_smtp.send_message(msg)
        current_app.logger.info(f"E-mail enviado para {destinatario}")
        return True

    except Exception as e:
        current_app.logger.error(f"Erro SMTP ao enviar para {destinatario}: {str(e)}")
        return False

    finally:
        if cliente_smtp:
            cliente_smtp.quit()
