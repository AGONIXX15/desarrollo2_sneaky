from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session

from app.deps import get_session, requiere_equipo_normal
from core.db import ahora
from core.models import Callback, Equipo
from core.schemas import CallbackEstado, CallbackIn, CallbackOut, CallbackPatch
from core.seguridad import UrlInvalida, generar_secreto, validar_url_callback
from core.webhooks import callback_de

router = APIRouter(prefix="/notificaciones/callbacks", tags=["callbacks"])


def _propio(session: Session, equipo: Equipo) -> Callback:
    cb = callback_de(session, equipo.id)
    if cb is None:
        raise HTTPException(404, "El equipo no tiene un callback registrado")
    return cb


@router.put("", response_model=CallbackOut, response_model_exclude_none=True)
def registrar(
    datos: CallbackIn,
    respuesta: Response,
    equipo: Equipo = Depends(requiere_equipo_normal),
    session: Session = Depends(get_session),
):
    try:
        validar_url_callback(datos.url)
    except UrlInvalida as e:
        raise HTTPException(422, str(e)) from None
    cb = callback_de(session, equipo.id)
    secreto = None
    if cb is None:
        secreto = generar_secreto()
        cb = Callback(equipo_id=equipo.id, url=datos.url, secreto=secreto, activo=True, actualizado_at=ahora())
        session.add(cb)
        respuesta.status_code = 201
    else:
        cb.url, cb.actualizado_at = datos.url, ahora()
        if datos.regenerarSecreto:
            secreto = cb.secreto = generar_secreto()
    session.commit()
    # el secreto solo se devuelve al crearlo o regenerarlo
    return CallbackOut(url=cb.url, activo=cb.activo, actualizado_at=cb.actualizado_at, secreto=secreto)


@router.get("", response_model=CallbackEstado)
def consultar(equipo: Equipo = Depends(requiere_equipo_normal), session: Session = Depends(get_session)):
    cb = _propio(session, equipo)
    return CallbackEstado(url=cb.url, activo=cb.activo, actualizado_at=cb.actualizado_at)


@router.patch("", response_model=CallbackEstado)
def cambiar_estado(
    datos: CallbackPatch,
    equipo: Equipo = Depends(requiere_equipo_normal),
    session: Session = Depends(get_session),
):
    cb = _propio(session, equipo)
    cb.activo = datos.activo
    cb.actualizado_at = ahora()
    session.commit()
    return CallbackEstado(url=cb.url, activo=cb.activo, actualizado_at=cb.actualizado_at)
