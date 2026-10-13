import smtplib
from email.message import EmailMessage
from typing import Protocol
from zoneinfo import ZoneInfo

import httpx

from core.config import Settings
from core.models import Notificacion

BREVO_URL = "https://api.brevo.com/v3/smtp/email"
ZONA_COLOMBIA = ZoneInfo("America/Bogota")


class Mailer(Protocol):
    def enviar(self, email: str, nombre: str, asunto: str, texto: str) -> None:
        """Lanza excepción si no se pudo enviar."""
        ...


def fecha_colombia(fecha) -> str:
    return fecha.astimezone(ZONA_COLOMBIA).strftime("%d/%m/%Y %H:%M")


def componer_correo(notif: Notificacion, nombre: str) -> tuple[str, str]:
    legible = notif.tipo.replace("_", " ").capitalize()
    asunto = f"Notificación: {legible}"
    lineas = [
        f"Hola {nombre},",
        "",
        f"{legible}. Registrada el {fecha_colombia(notif.creada_at)} (hora Colombia).",
        "",
        "Datos:",
    ]
    lineas += [f"- {k}: {v}" for k, v in notif.payload.items()]
    return asunto, "\n".join(lineas)


class BrevoMailer:
    def __init__(self, api_key: str, remitente: str, nombre_remitente: str):
        self.api_key = api_key
        self.remitente = remitente
        self.nombre_remitente = nombre_remitente

    def enviar(self, email: str, nombre: str, asunto: str, texto: str) -> None:
        resp = httpx.post(
            BREVO_URL,
            headers={"api-key": self.api_key, "accept": "application/json"},
            json={
                "sender": {"email": self.remitente, "name": self.nombre_remitente},
                "to": [{"email": email, "name": nombre}],
                "subject": asunto,
                "textContent": texto,
            },
            timeout=15,
        )
        resp.raise_for_status()


class SmtpMailer:
    def __init__(self, host: str, puerto: int, remitente: str):
        self.host = host
        self.puerto = puerto
        self.remitente = remitente

    def enviar(self, email: str, nombre: str, asunto: str, texto: str) -> None:
        msg = EmailMessage()
        msg["From"] = self.remitente
        msg["To"] = f"{nombre} <{email}>"
        msg["Subject"] = asunto
        msg.set_content(texto)
        with smtplib.SMTP(self.host, self.puerto, timeout=10) as smtp:
            smtp.send_message(msg)


def crear_mailer(settings: Settings) -> Mailer:
    if settings.mail_backend == "brevo":
        return BrevoMailer(settings.brevo_api_key, settings.mail_from, settings.mail_from_name)
    if settings.mail_backend == "smtp":
        return SmtpMailer(settings.smtp_host, settings.smtp_port, settings.mail_from)
    raise ValueError(f"MAIL_BACKEND desconocido: {settings.mail_backend}")
