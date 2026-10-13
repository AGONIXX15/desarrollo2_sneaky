from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from app.deps import get_equipo, get_session
from core.config import get_settings
from core.db import ahora
from core.models import Alerta, Equipo, Notificacion
from core.schemas import NotificacionResumen, Pagina
from core.webhooks import callback_de

router = APIRouter(prefix="/notificaciones/estado", tags=["estado"])

ESTADOS = ("pendiente_publicacion", "publicacion_fallida", "publicada", "entregada", "entrega_fallida")


def estado_de(n: Notificacion) -> str:
    maximo = get_settings().max_intentos
    if n.entregada_at is not None:
        return "entregada"
    if n.publicada_at is None:
        return "publicacion_fallida" if n.intentos_publicacion >= maximo else "pendiente_publicacion"
    if n.intentos_entrega >= maximo:
        return "entrega_fallida"
    return "publicada"


def _filtro_estado(estado: str):
    maximo = get_settings().max_intentos
    N = Notificacion
    return {
        "entregada": N.entregada_at.is_not(None),
        "pendiente_publicacion": and_(
            N.entregada_at.is_(None), N.publicada_at.is_(None), N.intentos_publicacion < maximo
        ),
        "publicacion_fallida": and_(
            N.entregada_at.is_(None), N.publicada_at.is_(None), N.intentos_publicacion >= maximo
        ),
        "entrega_fallida": and_(N.entregada_at.is_(None), N.publicada_at.is_not(None), N.intentos_entrega >= maximo),
        "publicada": and_(N.entregada_at.is_(None), N.publicada_at.is_not(None), N.intentos_entrega < maximo),
    }[estado]


def _resumen(n: Notificacion) -> NotificacionResumen:
    return NotificacionResumen(
        id=n.id,
        tipo=n.tipo,
        emisor=n.emisor.nombre,
        destino=n.destino.nombre,
        estado=estado_de(n),
        creada_at=n.creada_at,
        leida_at=n.leida_at,
        payload=n.payload,
    )


def _visible(session: Session, equipo: Equipo, id_: UUID) -> Notificacion:
    n = session.get(Notificacion, id_)
    if n is None or (not equipo.es_admin and n.equipo_destino_id != equipo.id):
        raise HTTPException(404, "Notificación no encontrada")
    return n


@router.get("", response_model=Pagina)
def listar(
    tipo: str | None = None,
    estado: str | None = None,
    desde: datetime | None = None,
    hasta: datetime | None = None,
    productoId: str | None = None,
    pagina: int = Query(1, ge=1),
    tamano: int = Query(20, ge=1, le=100),
    equipo: Equipo = Depends(get_equipo),
    session: Session = Depends(get_session),
):
    if estado is not None and estado not in ESTADOS:
        raise HTTPException(422, f"estado debe ser uno de {list(ESTADOS)}")
    filtros = []
    if not equipo.es_admin:
        filtros.append(Notificacion.equipo_destino_id == equipo.id)
    if tipo:
        filtros.append(Notificacion.tipo == tipo)
    if estado:
        filtros.append(_filtro_estado(estado))
    if desde:
        filtros.append(Notificacion.creada_at >= desde)
    if hasta:
        filtros.append(Notificacion.creada_at <= hasta)
    if productoId is not None:
        filtros.append(Notificacion.payload["productoId"].astext == productoId)

    total = session.scalar(select(func.count()).select_from(Notificacion).where(*filtros))
    filas = session.scalars(
        select(Notificacion)
        .where(*filtros)
        .order_by(Notificacion.creada_at.desc())
        .offset((pagina - 1) * tamano)
        .limit(tamano)
    ).all()
    return Pagina(items=[_resumen(n) for n in filas], total=total, pagina=pagina, tamano=tamano)


@router.get("/{id_}")
def detalle(id_: UUID, equipo: Equipo = Depends(get_equipo), session: Session = Depends(get_session)):
    n = _visible(session, equipo, id_)
    maximo = get_settings().max_intentos
    alerta = session.scalar(select(Alerta).where(Alerta.notificacion_id == n.id))
    base = _resumen(n).model_dump(mode="json")
    base.update(
        publicacion={
            "publicada_at": n.publicada_at,
            "intentos": n.intentos_publicacion,
            "error": "error al publicar" if n.ultimo_error_publicacion else None,
            "fallida": n.publicada_at is None and n.intentos_publicacion >= maximo,
        },
        entrega={
            "entregada_at": n.entregada_at,
            "intentos": n.intentos_entrega,
            "proximo_intento_at": n.proximo_intento_entrega_at,
            "error": "error de entrega" if n.ultimo_error_entrega else None,
            "fallida": n.entregada_at is None and n.intentos_entrega >= maximo,
            "con_callback": callback_de(session, n.equipo_destino_id) is not None,
        },
        correos=[
            {
                "email": e.email,
                "enviado_at": e.enviado_at,
                "intentos": e.intentos,
                "proximo_intento_at": e.proximo_intento_at,
                "error": "error al enviar el correo" if e.ultimo_error else None,
                "fallido": e.enviado_at is None and e.intentos >= maximo,
            }
            for e in n.envios
        ],
        alerta=None
        if alerta is None
        else {
            "clave": alerta.clave,
            "expira_at": alerta.expira_at,
            "cerrada_at": alerta.cerrada_at,
            "activa": alerta.cerrada_at is None and alerta.expira_at > ahora(),
        },
    )
    return _fechas_iso(base)


def _fechas_iso(obj):
    if isinstance(obj, datetime):
        from core.schemas import _a_utc

        return _a_utc(obj)
    if isinstance(obj, dict):
        return {k: _fechas_iso(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_fechas_iso(v) for v in obj]
    return obj


@router.patch("/{id_}/leida", response_model=NotificacionResumen)
def marcar_leida(id_: UUID, equipo: Equipo = Depends(get_equipo), session: Session = Depends(get_session)):
    n = _visible(session, equipo, id_)
    if n.equipo_destino_id != equipo.id:
        raise HTTPException(403, "Solo el equipo destino puede marcarla como leída")
    if n.leida_at is None:
        n.leida_at = ahora()
        session.commit()
    return _resumen(n)
