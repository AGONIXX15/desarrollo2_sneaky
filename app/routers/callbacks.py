from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.deps import get_session, requiere_equipo_normal
from core.db import ahora
from core.models import Callback, Equipo
from core.schemas import CallbackIn, CallbackOut
from core.seguridad import UrlInvalida, generar_secreto, validar_url_callback
from core.webhooks import callback_de

router = APIRouter(prefix="/notificaciones/callbacks", tags=["callbacks"])


@router.put("", response_model=CallbackOut)
def registrar(
    datos: CallbackIn,
    equipo: Equipo = Depends(requiere_equipo_normal),
    session: Session = Depends(get_session),
):
    try:
        validar_url_callback(datos.url)
    except UrlInvalida as e:
        raise HTTPException(422, str(e)) from None
    secreto = generar_secreto()
    cb = callback_de(session, equipo.id)
    if cb is None:
        cb = Callback(equipo_id=equipo.id, url=datos.url, secreto=secreto, actualizado_at=ahora())
        session.add(cb)
    else:
        cb.url, cb.secreto, cb.actualizado_at = datos.url, secreto, ahora()
    session.commit()
    return CallbackOut(url=cb.url, secreto=secreto)
