from __future__ import annotations

import logging
import requests
import smtplib
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from app.core.config import get_settings

logger = logging.getLogger("uvicorn.error")


def send_telegram_message(bot_token: str, chat_id: str, message: str) -> None:
    if not bot_token or not chat_id:
        raise ValueError("Telegram Bot Token y Chat ID son requeridos.")
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "HTML"
    }
    response = requests.post(url, json=payload, timeout=10)
    response.raise_for_status()


def send_email_message(
    smtp_host: str,
    smtp_port: int,
    smtp_user: str,
    smtp_password: str,
    email_from: str,
    email_to: str,
    subject: str,
    html_body: str
) -> None:
    if not smtp_host or not smtp_user or not smtp_password or not email_from or not email_to:
        raise ValueError("Configuración SMTP incompleta.")

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = email_from
    msg["To"] = email_to

    # Adjuntar cuerpo HTML
    part = MIMEText(html_body, "html")
    msg.attach(part)

    # Soporte para múltiples destinatarios
    recipients = [r.strip() for r in email_to.split(",") if r.strip()]

    # Conexión SMTP estándar
    if smtp_port == 465:
        server = smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=10)
    else:
        server = smtplib.SMTP(smtp_host, smtp_port, timeout=10)
        server.ehlo()
        try:
            server.starttls()
            server.ehlo()
        except smtplib.SMTPException:
            logger.warning("STARTTLS no es soportado o falló, continuando con conexión plana.")

    if smtp_user and smtp_password:
        server.login(smtp_user, smtp_password)

    server.sendmail(email_from, recipients, msg.as_string())
    server.quit()


def notify_sync_result(result: dict | None, error: Exception | None = None) -> None:
    settings = get_settings()

    telegram_active = settings.telegram_enabled and settings.telegram_bot_token and settings.telegram_chat_id
    email_active = settings.email_enabled and settings.smtp_host and settings.email_from and settings.email_to

    if not telegram_active and not email_active:
        return

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    if error:
        subject = "⚠️ [Jira Report] Sincronización Fallida"
        telegram_msg = (
            f"⚠️ <b>[Jira Report] Sincronización Fallida</b>\n\n"
            f"<b>Fecha:</b> {now_str}\n"
            f"<b>Detalle del error:</b> {str(error)}"
        )
        html_body = f"""
        <html>
        <body style="font-family: Arial, sans-serif; background-color: #f9f9f9; padding: 20px; color: #333;">
            <div style="max-width: 600px; margin: 0 auto; background: #fff; border: 1px solid #e1e1e1; border-radius: 8px; padding: 24px;">
                <h2 style="color: #ef4444; margin-top: 0;">⚠️ Sincronización Fallida</h2>
                <hr style="border: 0; border-top: 1px solid #eee; margin: 16px 0;" />
                <p>Ocurrió un error al sincronizar los datos de Jira:</p>
                <p style="background: #fef2f2; border: 1px solid #fca5a5; border-radius: 4px; padding: 12px; font-family: monospace; color: #b91c1c;">
                    {str(error)}
                </p>
                <p style="font-size: 0.85em; color: #666; margin-top: 24px;">
                    Fecha y Hora: {now_str}
                </p>
            </div>
        </body>
        </html>
        """
    else:
        subject = "✅ [Jira Report] Sincronización Exitosa"
        issues_seen = result.get("issues_seen", 0) if result else 0
        issues_upserted = result.get("issues_upserted", 0) if result else 0
        worklogs_upserted = result.get("worklogs_upserted", 0) if result else 0

        telegram_msg = (
            f"✅ <b>[Jira Report] Sincronización Exitosa</b>\n\n"
            f"<b>Fecha:</b> {now_str}\n"
            f"• Tickets vistos: {issues_seen}\n"
            f"• Tickets actualizados/creados: {issues_upserted}\n"
            f"• Registros de horas actualizados: {worklogs_upserted}"
        )

        html_body = f"""
        <html>
        <body style="font-family: Arial, sans-serif; background-color: #f9f9f9; padding: 20px; color: #333;">
            <div style="max-width: 600px; margin: 0 auto; background: #fff; border: 1px solid #e1e1e1; border-radius: 8px; padding: 24px;">
                <h2 style="color: #10b981; margin-top: 0;">✅ Sincronización Exitosa</h2>
                <hr style="border: 0; border-top: 1px solid #eee; margin: 16px 0;" />
                <p>La sincronización periódica con Jira se ha ejecutado correctamente.</p>
                <table style="width: 100%; border-collapse: collapse; margin-top: 16px;">
                    <tr style="background: #f9f9f9;">
                        <td style="padding: 8px; border-bottom: 1px solid #eee; font-weight: bold;">Tickets Vistos:</td>
                        <td style="padding: 8px; border-bottom: 1px solid #eee;">{issues_seen}</td>
                    </tr>
                    <tr>
                        <td style="padding: 8px; border-bottom: 1px solid #eee; font-weight: bold;">Tickets Creados/Actualizados:</td>
                        <td style="padding: 8px; border-bottom: 1px solid #eee;">{issues_upserted}</td>
                    </tr>
                    <tr style="background: #f9f9f9;">
                        <td style="padding: 8px; border-bottom: 1px solid #eee; font-weight: bold;">Registros de Horas Sincronizados:</td>
                        <td style="padding: 8px; border-bottom: 1px solid #eee;">{worklogs_upserted}</td>
                    </tr>
                </table>
                <p style="font-size: 0.85em; color: #666; margin-top: 24px;">
                    Fecha y Hora: {now_str}
                </p>
            </div>
        </body>
        </html>
        """

    if telegram_active:
        try:
            send_telegram_message(settings.telegram_bot_token, settings.telegram_chat_id, telegram_msg)
            logger.info("Notificación de sincronización enviada por Telegram exitosamente.")
        except Exception as e:
            logger.error(f"Fallo al enviar notificación por Telegram: {e}")

    if email_active:
        try:
            send_email_message(
                settings.smtp_host,
                settings.smtp_port,
                settings.smtp_user,
                settings.smtp_password,
                settings.email_from,
                settings.email_to,
                subject,
                html_body
            )
            logger.info("Notificación de sincronización enviada por Correo exitosamente.")
        except Exception as e:
            logger.error(f"Fallo al enviar notificación por Correo: {e}")
