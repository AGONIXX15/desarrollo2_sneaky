import logging
from datetime import timedelta

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from core.alertas import cerrar_vencidas
from core.config import get_settings
from core.db import ahora
from core.mailer import Mailer, componer_correo
from core.models import Callback, EnvioCorreo, Notificacion
from core.publisher import Publisher
from core.webhooks import entregar_webhook

log = logging.getLogger(__name__)
LOTE = 100


def publicar_notificacion(session: Session, publisher: Publisher, notif: Notificacion) -> bool:
    """Intenta publicar y deja el resultado en la fila. No hace commit."""
    try:
        publisher.publicar(
            notif.destino.nombre, {"notificacionId": str(notif.id), "tipo": notif.tipo}
        )
    except Exception as e:
        notif.intentos_publicacion += 1
        notif.ultimo_error_publicacion = str(e)[:500]
        log.warning("publicacion fallida notificacion=%s: %s", notif.id, e)
        return False
    notif.publicada_at = ahora()
    notif.ultimo_error_publicacion = None
    return True


def enviar_correo(session: Session, mailer: Mailer, envio: EnvioCorreo) -> bool:
    """Intenta enviar y deja el resultado en la fila. No hace commit."""
    asunto, texto = componer_correo(envio.notificacion, envio.destinatario.nombre)
    try:
        mailer.enviar(envio.email, envio.destinatario.nombre, asunto, texto)
    except Exception as e:
        envio.intentos += 1
        envio.proximo_intento_at = ahora() + timedelta(minutes=get_settings().reintento_minutos)
        envio.ultimo_error = str(e)[:500]
        log.warning("correo fallido envio=%s: %s", envio.id, e)
        return False
    envio.enviado_at = ahora()
    envio.ultimo_error = None
    return True


def ejecutar_ciclo(
    session: Session, publisher: Publisher, mailer: Mailer, http_client: httpx.Client
) -> dict:
    max_intentos = get_settings().max_intentos
    resumen = {
        "publicadas": 0,
        "publicacion_fallidas": 0,
        "correos_enviados": 0,
        "correos_fallidos": 0,
        "webhooks_entregados": 0,
        "webhooks_fallidos": 0,
        "alertas_cerradas": 0,
    }

    pendientes = session.scalars(
        select(Notificacion)
        .where(Notificacion.publicada_at.is_(None), Notificacion.intentos_publicacion < max_intentos)
        .order_by(Notificacion.creada_at)
        .limit(LOTE)
        .with_for_update(skip_locked=True, of=Notificacion)
    ).all()
    for notif in pendientes:
        ok = publicar_notificacion(session, publisher, notif)
        resumen["publicadas" if ok else "publicacion_fallidas"] += 1
    session.commit()

    envios = session.scalars(
        select(EnvioCorreo)
        .where(
            EnvioCorreo.enviado_at.is_(None),
            EnvioCorreo.intentos < max_intentos,
            EnvioCorreo.proximo_intento_at <= ahora(),
        )
        .order_by(EnvioCorreo.id)
        .limit(LOTE)
        .with_for_update(skip_locked=True, of=EnvioCorreo)
    ).all()
    for envio in envios:
        ok = enviar_correo(session, mailer, envio)
        resumen["correos_enviados" if ok else "correos_fallidos"] += 1
    session.commit()

    filas = session.execute(
        select(Notificacion, Callback)
        .join(Callback, Callback.equipo_id == Notificacion.equipo_destino_id)
        .where(
            Notificacion.publicada_at.is_not(None),
            Notificacion.entregada_at.is_(None),
            Notificacion.intentos_entrega < max_intentos,
            Notificacion.proximo_intento_entrega_at <= ahora(),
        )
        .order_by(Notificacion.creada_at)
        .limit(LOTE)
        .with_for_update(skip_locked=True, of=Notificacion)
    ).all()
    for notif, callback in filas:
        ok = entregar_webhook(session, notif, callback, http_client)
        resumen["webhooks_entregados" if ok else "webhooks_fallidos"] += 1
    session.commit()

    resumen["alertas_cerradas"] = cerrar_vencidas(session)
    session.commit()
    return resumen
