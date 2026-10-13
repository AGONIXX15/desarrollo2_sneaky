import json
import logging
import os

import httpx

from core.config import get_settings
from core.db import crear_engine, crear_session_factory
from core.mailer import crear_mailer
from core.publisher import AmqpPublisher

log = logging.getLogger()
log.setLevel(logging.INFO)

# variable de entorno -> variable que trae el nombre del parámetro en SSM
SECRETOS_SSM = {
    "DATABASE_URL": "DATABASE_URL_PARAM",
    "AMQP_URL": "AMQP_URL_PARAM",
    "BREVO_API_KEY": "BREVO_API_KEY_PARAM",
    "RENDER_HEALTH_URL": "RENDER_HEALTH_URL_PARAM",
}


def cargar_ssm() -> None:
    """Lee los SecureString en runtime. SAM no permite resolverlos en Environment."""
    pendientes = {
        var: os.environ[param]
        for var, param in SECRETOS_SSM.items()
        if os.environ.get(param) and not os.environ.get(var)
    }
    if pendientes:
        import boto3

        resp = boto3.client("ssm").get_parameters(Names=list(pendientes.values()), WithDecryption=True)
        if resp.get("InvalidParameters"):
            raise RuntimeError(f"Parámetros SSM que no existen: {resp['InvalidParameters']}")
        por_nombre = {p["Name"]: p["Value"] for p in resp["Parameters"]}
        for var, nombre in pendientes.items():
            os.environ[var] = por_nombre[nombre]
        get_settings.cache_clear()

    obligatorias = ["DATABASE_URL", "AMQP_URL"]
    if os.environ.get("MAIL_BACKEND", "smtp") == "brevo":
        obligatorias.append("BREVO_API_KEY")
    faltan = [v for v in obligatorias if not os.environ.get(v)]
    if faltan:
        raise RuntimeError(f"Faltan variables de configuración: {faltan}")


def construir_dependencias():
    """Devuelve (session, publisher, mailer, http_client). Los tests lo reemplazan."""
    cargar_ssm()
    cfg = get_settings()
    session = crear_session_factory(crear_engine(cfg.database_url, sin_pool=True))()
    return (
        session,
        AmqpPublisher(cfg.amqp_url, cfg.amqp_exchange),
        crear_mailer(cfg),
        httpx.Client(timeout=cfg.webhook_timeout),
    )


MARGEN_SEGUNDOS = 40  # un webhook puede tardar 10 s y luego viene el ping a Render


def _limite(context) -> float | None:
    if context is None:
        return None
    return max(5.0, context.get_remaining_time_in_millis() / 1000 - MARGEN_SEGUNDOS)


def handler(event, context):
    from core.ciclo import ejecutar_ciclo

    session, publisher, mailer, http_client = construir_dependencias()
    try:
        resumen = ejecutar_ciclo(session, publisher, mailer, http_client, limite_segundos=_limite(context))
        url = get_settings().render_health_url
        if url:
            try:
                resumen["render_health"] = http_client.get(url, timeout=15).status_code
            except Exception as e:
                # que Render no responda no debe contar como fallo del ciclo
                resumen["render_health"] = f"error: {e}"
        print(json.dumps({"mensaje": "ciclo ejecutado", **resumen}))
        return resumen
    finally:
        session.close()
        http_client.close()
