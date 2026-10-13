import logging
import time
from datetime import timedelta

import httpx
from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from core.alertas import cerrar_vencidas
from core.config import get_settings
from core.db import ahora
from core.mailer import Mailer, componer_correo
from core.models import Callback, EnvioCorreo, Notificacion
from core.publisher import Publisher
from core.webhooks import entregar_webhook

log = logging.getLogger(__name__)
LOTE = 20
GRACIA_PRIMER_INTENTO = timedelta(minutes=1)


def publicar_notificacion(session: Session, publisher: Publisher, notif: Notificacion) -> bool:
    """Intenta publicar y deja el resultado en la fila. No hace commit."""
    try:
        publisher.publicar(notif.destino.nombre, {"notificacionId": str(notif.id), "tipo": notif.tipo})
    except Exception as e:
        notif.intentos_publicacion += 1
        notif.ultimo_error_publicacion = str(e)[:500]
        log.warning("publicacion fallida notificacion=%s: %s", notif.id, e)
        return False
    notif.publicada_at = ahora()
    notif.ultimo_error_publicacion = None
    # si el worker pierde el mensaje, el ciclo reintenta la entrega pasado este plazo
    notif.proximo_intento_entrega_at = ahora() + timedelta(minutes=get_settings().reintento_minutos)
    return True


def enviar_correo(session: Session, mailer: Mailer, envio: EnvioCorreo) -> bool:
    """Intenta enviar y deja el resultado en la fila. No hace commit."""
    try:
        asunto, texto = componer_correo(envio.notificacion, envio.destinatario.nombre)
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


def _por_fila(session: Session, consulta: Select, modelo, vencido, procesar) -> None:
    """Toma de a una fila con SKIP LOCKED y hace commit por fila, así no se sostienen locks durante el I/O."""
    vistas: set = set()
    for _ in range(LOTE):
        if vencido():
            break
        fila = session.execute(
            consulta.where(modelo.id.not_in(vistas)).limit(1).with_for_update(skip_locked=True, of=modelo)
        ).first()
        if fila is None:
            break
        vistas.add(fila[0].id)
        procesar(*fila)
        session.commit()


def ejecutar_ciclo(
    session: Session,
    publisher: Publisher,
    mailer: Mailer,
    http_client: httpx.Client,
    limite_segundos: float | None = None,
) -> dict:
    """Un recorrido de reintentos. Si pasa limite_segundos deja de tomar filas nuevas."""
    max_intentos = get_settings().max_intentos
    fin = None if limite_segundos is None else time.monotonic() + limite_segundos

    def vencido() -> bool:
        return fin is not None and time.monotonic() >= fin

    resumen = {
        "publicadas": 0,
        "publicacion_fallidas": 0,
        "correos_enviados": 0,
        "correos_fallidos": 0,
        "webhooks_entregados": 0,
        "webhooks_fallidos": 0,
        "alertas_cerradas": 0,
        "cortado_por_tiempo": False,
    }

    def contar(ok: bool, bien: str, mal: str) -> None:
        resumen[bien if ok else mal] += 1

    # las recién creadas las publica la tarea de fondo de la API, no las pisamos
    publicaciones = (
        select(Notificacion)
        .where(
            Notificacion.publicada_at.is_(None),
            Notificacion.intentos_publicacion < max_intentos,
            Notificacion.creada_at <= ahora() - GRACIA_PRIMER_INTENTO,
        )
        .order_by(Notificacion.creada_at)
    )
    _por_fila(
        session,
        publicaciones,
        Notificacion,
        vencido,
        lambda n: contar(publicar_notificacion(session, publisher, n), "publicadas", "publicacion_fallidas"),
    )

    envios = (
        select(EnvioCorreo)
        .where(
            EnvioCorreo.enviado_at.is_(None),
            EnvioCorreo.intentos < max_intentos,
            EnvioCorreo.proximo_intento_at <= ahora(),
        )
        .order_by(EnvioCorreo.id)
    )
    _por_fila(
        session,
        envios,
        EnvioCorreo,
        vencido,
        lambda e: contar(enviar_correo(session, mailer, e), "correos_enviados", "correos_fallidos"),
    )

    webhooks = (
        select(Notificacion, Callback)
        .join(Callback, Callback.equipo_id == Notificacion.equipo_destino_id)
        .where(
            Notificacion.publicada_at.is_not(None),
            Notificacion.entregada_at.is_(None),
            Notificacion.intentos_entrega < max_intentos,
            Notificacion.proximo_intento_entrega_at <= ahora(),
        )
        .order_by(Notificacion.creada_at)
    )
    _por_fila(
        session,
        webhooks,
        Notificacion,
        vencido,
        lambda n, cb: contar(entregar_webhook(session, n, cb, http_client), "webhooks_entregados", "webhooks_fallidos"),
    )

    resumen["cortado_por_tiempo"] = vencido()
    resumen["alertas_cerradas"] = cerrar_vencidas(session)
    session.commit()
    return resumen
