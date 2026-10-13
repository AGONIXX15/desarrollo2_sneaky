from datetime import timedelta

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from core.db import ahora
from core.models import Alerta, TipoNotificacion

CLAVE_FIJA = "unica"
MOTIVO_EMISOR = "EMISOR"
MOTIVO_EXPIRACION = "EXPIRACION"


def clave_de(tipo: TipoNotificacion, datos: dict) -> str:
    if tipo.campo_clave is None:
        return CLAVE_FIJA
    return str(datos[tipo.campo_clave])


def expiracion(tipo: TipoNotificacion):
    return ahora() + timedelta(minutes=tipo.ttl_alerta_min)


def cerrar_vencidas(session: Session, tipo: str | None = None, clave: str | None = None) -> int:
    ahora_ = ahora()
    q = (
        update(Alerta)
        .where(Alerta.cerrada_at.is_(None), Alerta.expira_at <= ahora_)
        .values(cerrada_at=ahora_, motivo_resolucion=MOTIVO_EXPIRACION)
    )
    if tipo is not None:
        q = q.where(Alerta.tipo == tipo, Alerta.clave == clave)
    return session.execute(q).rowcount


def alerta_activa(session: Session, tipo: str, clave: str) -> Alerta | None:
    return session.scalar(
        select(Alerta).where(Alerta.tipo == tipo, Alerta.clave == clave, Alerta.cerrada_at.is_(None)).with_for_update()
    )
