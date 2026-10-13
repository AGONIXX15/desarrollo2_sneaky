from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.deps import get_equipo, get_session, requiere_equipo_normal
from core.db import ahora
from core.models import Destinatario, Equipo, TipoNotificacion
from core.schemas import DestinatarioIn, DestinatarioOut

router = APIRouter(prefix="/notificaciones/destinatarios", tags=["destinatarios"])


def _salida(d: Destinatario, session: Session) -> DestinatarioOut:
    equipo = session.get(Equipo, d.equipo_id)
    return DestinatarioOut(
        id=d.id,
        nombre=d.nombre,
        email=d.email,
        activo=d.activo,
        tipos=sorted(t.codigo for t in d.tipos),
        equipo=equipo.nombre,
    )


def _resolver_tipos(session: Session, equipo: Equipo, codigos: list[str]) -> list[TipoNotificacion]:
    tipos = []
    for codigo in dict.fromkeys(codigos):
        tipo = session.get(TipoNotificacion, codigo)
        if tipo is None:
            raise HTTPException(422, f"Tipo desconocido: {codigo}")
        if tipo.equipo_destino_id != equipo.id:
            raise HTTPException(403, f"El tipo {codigo} no es de tu equipo")
        tipos.append(tipo)
    return tipos


def _propio(session: Session, equipo: Equipo, id_: int) -> Destinatario:
    d = session.get(Destinatario, id_)
    if d is None or (not equipo.es_admin and d.equipo_id != equipo.id):
        raise HTTPException(404, "Destinatario no encontrado")
    return d


@router.post("", status_code=201, response_model=DestinatarioOut)
def crear(
    datos: DestinatarioIn,
    equipo: Equipo = Depends(requiere_equipo_normal),
    session: Session = Depends(get_session),
):
    d = Destinatario(
        equipo_id=equipo.id,
        nombre=datos.nombre,
        email=datos.email,
        creado_at=ahora(),
        tipos=_resolver_tipos(session, equipo, datos.tipos),
    )
    session.add(d)
    session.commit()
    return _salida(d, session)


@router.get("", response_model=list[DestinatarioOut])
def listar(equipo: Equipo = Depends(get_equipo), session: Session = Depends(get_session)):
    q = select(Destinatario).order_by(Destinatario.id)
    if not equipo.es_admin:
        q = q.where(Destinatario.equipo_id == equipo.id)
    return [_salida(d, session) for d in session.scalars(q)]


@router.put("/{id_}", response_model=DestinatarioOut)
def actualizar(
    id_: int,
    datos: DestinatarioIn,
    equipo: Equipo = Depends(requiere_equipo_normal),
    session: Session = Depends(get_session),
):
    d = _propio(session, equipo, id_)
    if not d.activo:
        raise HTTPException(404, "Destinatario no encontrado")
    d.nombre = datos.nombre
    d.email = datos.email
    d.tipos = _resolver_tipos(session, equipo, datos.tipos)
    session.commit()
    return _salida(d, session)


@router.delete("/{id_}", status_code=204)
def borrar(
    id_: int,
    equipo: Equipo = Depends(requiere_equipo_normal),
    session: Session = Depends(get_session),
):
    d = _propio(session, equipo, id_)
    d.activo = False
    session.commit()
