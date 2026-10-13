from math import ceil

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.deps import get_equipo, get_session, requiere_equipo_normal
from core.db import ahora
from core.models import Destinatario, Equipo, TipoNotificacion
from core.schemas import DestinatarioIn, DestinatarioOut, DestinatarioPatch, PaginaDestinatarios

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
    tipos = _resolver_tipos(session, equipo, datos.tipos)
    existente = session.scalar(
        select(Destinatario).where(
            Destinatario.equipo_id == equipo.id,
            func.lower(Destinatario.email) == datos.email.lower(),
            Destinatario.activo.is_(True),
        )
    )
    if existente is not None:
        raise HTTPException(409, {"mensaje": "El destinatario ya está registrado", "id": existente.id})
    d = Destinatario(equipo_id=equipo.id, nombre=datos.nombre, email=datos.email, creado_at=ahora(), tipos=tipos)
    session.add(d)
    session.commit()
    return _salida(d, session)


@router.get("", response_model=PaginaDestinatarios)
def listar(
    activo: bool | None = None,
    pagina: int = Query(1, ge=1),
    tamano: int = Query(20, ge=1, le=100),
    equipo: Equipo = Depends(get_equipo),
    session: Session = Depends(get_session),
):
    filtros = []
    if not equipo.es_admin:
        filtros.append(Destinatario.equipo_id == equipo.id)
    if activo is not None:
        filtros.append(Destinatario.activo.is_(activo))
    total = session.scalar(select(func.count()).select_from(Destinatario).where(*filtros))
    filas = session.scalars(
        select(Destinatario)
        .where(*filtros)
        .order_by(Destinatario.id.desc())
        .offset((pagina - 1) * tamano)
        .limit(tamano)
    ).all()
    return PaginaDestinatarios(
        items=[_salida(d, session) for d in filas],
        total=total,
        pagina=pagina,
        tamano=tamano,
        totalPaginas=ceil(total / tamano),
    )


@router.patch("/{id_}", response_model=DestinatarioOut)
def actualizar(
    id_: int,
    datos: DestinatarioPatch,
    equipo: Equipo = Depends(requiere_equipo_normal),
    session: Session = Depends(get_session),
):
    campos = datos.model_dump(exclude_unset=True)
    if not campos or any(v is None for v in campos.values()):
        raise HTTPException(422, "Envía al menos uno de nombre, tipos o activo, sin valores vacíos")
    d = _propio(session, equipo, id_)
    if "tipos" in campos:
        d.tipos = _resolver_tipos(session, equipo, campos["tipos"])
    if "nombre" in campos:
        d.nombre = campos["nombre"]
    if "activo" in campos:
        d.activo = campos["activo"]
    session.commit()
    return _salida(d, session)
