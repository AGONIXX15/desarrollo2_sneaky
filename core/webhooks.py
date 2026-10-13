import json
import logging
from datetime import timedelta

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from core.config import get_settings
from core.db import ahora
from core.models import Callback, Notificacion
from core.seguridad import firmar

log = logging.getLogger(__name__)


def cuerpo_webhook(notif: Notificacion) -> bytes:
    return json.dumps(
        {
            "id": str(notif.id),
            "tipo": notif.tipo,
            "equipoEmisor": notif.emisor.nombre,
            "equipoDestino": notif.destino.nombre,
            "creadaAt": notif.creada_at.isoformat(),
            "datos": notif.payload,
        },
        sort_keys=True,
    ).encode()


def callback_de(session: Session, equipo_id: int) -> Callback | None:
    return session.scalar(select(Callback).where(Callback.equipo_id == equipo_id))


def entregar_webhook(
    session: Session, notif: Notificacion, callback: Callback, http_client: httpx.Client
) -> bool:
    """Hace el POST firmado y deja el resultado en la notificación. No hace commit."""
    cfg = get_settings()
    cuerpo = cuerpo_webhook(notif)
    headers = {
        "Content-Type": "application/json",
        "X-Notification-Id": str(notif.id),
        "X-Signature": firmar(cuerpo, callback.secreto),
    }
    try:
        resp = http_client.post(
            callback.url, content=cuerpo, headers=headers, timeout=cfg.webhook_timeout
        )
        if not resp.is_success:
            raise RuntimeError(f"respuesta {resp.status_code}")
    except Exception as e:
        notif.intentos_entrega += 1
        notif.proximo_intento_entrega_at = ahora() + timedelta(minutes=cfg.reintento_minutos)
        notif.ultimo_error_entrega = str(e)[:500]
        log.warning("webhook fallido notificacion=%s intento=%s: %s", notif.id, notif.intentos_entrega, e)
        return False
    notif.entregada_at = ahora()
    notif.ultimo_error_entrega = None
    return True


def procesar_mensaje(session_factory, http_client: httpx.Client, datos: dict) -> None:
    """Lo que hace el worker con cada mensaje de la cola."""
    with session_factory() as session:
        notif = session.get(Notificacion, datos["notificacionId"])
        if notif is None or notif.entregada_at is not None:
            return
        callback = callback_de(session, notif.equipo_destino_id)
        if callback is None:
            log.info("sin callback para %s, el equipo consulta por GET", notif.destino.nombre)
            return
        entregar_webhook(session, notif, callback, http_client)
        session.commit()
