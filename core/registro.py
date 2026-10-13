import logging
from dataclasses import dataclass
from datetime import timedelta
from uuid import UUID

from jsonschema import Draft202012Validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from core.alertas import MOTIVO_EMISOR, alerta_activa, cerrar_vencidas, clave_de, expiracion
from core.ciclo import enviar_correo, publicar_notificacion
from core.db import ahora
from core.mailer import Mailer
from core.models import (
    Alerta,
    Destinatario,
    EnvioCorreo,
    Equipo,
    Notificacion,
    TipoNotificacion,
    destinatario_tipos,
)
from core.publisher import Publisher

log = logging.getLogger(__name__)

EVENTO_DEFECTO = "DETECTADA"
EVENTOS_CIERRE = {"REPUESTO", "RESUELTA"}
EVENTOS = EVENTOS_CIERRE | {EVENTO_DEFECTO}


class ErrorRegistro(Exception):
    def __init__(self, status: int, detalle):
        self.status = status
        self.detalle = detalle


@dataclass
class Resultado:
    status: int
    notificacion_id: UUID | None
    duplicada: bool = False
    alertas_cerradas: int = 0


def registrar(session: Session, equipo: Equipo, cuerpo: dict) -> Resultado:
    codigo = cuerpo.get("tipo")
    if not isinstance(codigo, str):
        raise ErrorRegistro(422, "Falta el campo tipo")
    tipo = session.get(TipoNotificacion, codigo)
    if tipo is None or not tipo.activo:
        raise ErrorRegistro(422, f"Tipo desconocido: {codigo}")
    if tipo.equipo_emisor_id != equipo.id:
        raise ErrorRegistro(403, "Tu equipo no puede emitir este tipo")

    evento = cuerpo.get("evento", EVENTO_DEFECTO)
    if evento not in EVENTOS:
        raise ErrorRegistro(422, f"Evento inválido, se espera uno de {sorted(EVENTOS)}")
    datos = {k: v for k, v in cuerpo.items() if k not in ("tipo", "evento")}

    errores = [
        {"campo": ".".join(str(p) for p in e.absolute_path), "mensaje": e.message}
        for e in Draft202012Validator(tipo.schema).iter_errors(datos)
    ]
    if errores:
        raise ErrorRegistro(422, errores)

    try:
        clave = clave_de(tipo, datos)
    except KeyError:
        raise ErrorRegistro(422, f"Falta el campo clave {tipo.campo_clave}") from None
    if not clave or len(clave) > 100:
        raise ErrorRegistro(422, "La clave de la alerta debe tener entre 1 y 100 caracteres")
    cerrar_vencidas(session, tipo.codigo, clave)

    activa = alerta_activa(session, tipo.codigo, clave)
    if evento in EVENTOS_CIERRE:
        if activa is None:
            session.commit()
            return Resultado(200, None, alertas_cerradas=0)
        activa.cerrada_at = ahora()
        activa.motivo_resolucion = MOTIVO_EMISOR
        session.commit()
        return Resultado(200, activa.notificacion_id, alertas_cerradas=1)

    if activa is not None:
        session.commit()
        return Resultado(200, activa.notificacion_id, duplicada=True)

    try:
        with session.begin_nested():
            notif = Notificacion(
                tipo=tipo.codigo,
                equipo_emisor_id=tipo.equipo_emisor_id,
                equipo_destino_id=tipo.equipo_destino_id,
                payload=datos,
                creada_at=ahora(),
            )
            session.add(notif)
            session.flush()
            session.add(
                Alerta(
                    tipo=tipo.codigo,
                    clave=clave,
                    notificacion_id=notif.id,
                    creada_at=ahora(),
                    expira_at=expiracion(tipo),
                )
            )
            session.flush()
    except IntegrityError:
        # otra petición creó la alerta justo antes que nosotros
        existente = alerta_activa(session, tipo.codigo, clave)
        session.commit()
        if existente is None:
            raise
        return Resultado(200, existente.notificacion_id, duplicada=True)

    destinatarios = session.scalars(
        select(Destinatario)
        .join(destinatario_tipos, destinatario_tipos.c.destinatario_id == Destinatario.id)
        .where(
            destinatario_tipos.c.tipo_codigo == tipo.codigo,
            Destinatario.activo.is_(True),
            Destinatario.equipo_id == tipo.equipo_destino_id,
        )
    ).all()
    # el primer intento lo hace la tarea de fondo; el ciclo solo toma estos envíos si pasan 5 min
    for d in destinatarios:
        session.add(
            EnvioCorreo(
                notificacion_id=notif.id,
                destinatario_id=d.id,
                email=d.email,
                proximo_intento_at=ahora() + timedelta(minutes=5),
            )
        )
    session.commit()
    return Resultado(201, notif.id)


def procesar_despues_de_registrar(session_factory, publisher: Publisher, mailer: Mailer, notificacion_id: UUID) -> None:
    """Tarea de fondo: publica en la cola y manda los correos. Nada de esto debe tumbar la API."""
    try:
        with session_factory() as session:
            notif = session.scalar(
                select(Notificacion).where(Notificacion.id == notificacion_id).with_for_update(skip_locked=True)
            )
            # si es None otro proceso (el ciclo) ya la tiene tomada
            if notif is not None and notif.publicada_at is None:
                publicar_notificacion(session, publisher, notif)
            session.commit()
    except Exception:
        log.exception("error publicando notificacion %s", notificacion_id)

    try:
        with session_factory() as session:
            envios = session.scalars(
                select(EnvioCorreo)
                .where(
                    EnvioCorreo.notificacion_id == notificacion_id,
                    EnvioCorreo.enviado_at.is_(None),
                )
                .with_for_update(skip_locked=True)
            ).all()
            if not envios:
                log.info("notificacion %s sin destinatarios, no se envían correos", notificacion_id)
            for envio in envios:
                enviar_correo(session, mailer, envio)
                session.commit()
    except Exception:
        log.exception("error enviando correos de %s", notificacion_id)
