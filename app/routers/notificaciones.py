from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Response
from sqlalchemy.orm import Session

from app.deps import (
    get_equipo,
    get_mailer,
    get_publisher,
    get_session,
    get_session_factory,
)
from core.models import Equipo
from core.registro import ErrorRegistro, procesar_despues_de_registrar, registrar
from core.schemas import RegistroOut

router = APIRouter(prefix="/notificaciones", tags=["notificaciones"])


@router.post("", response_model=RegistroOut)
def crear(
    cuerpo: dict,
    respuesta: Response,
    tareas: BackgroundTasks,
    equipo: Equipo = Depends(get_equipo),
    session: Session = Depends(get_session),
    factory=Depends(get_session_factory),
    publisher=Depends(get_publisher),
    mailer=Depends(get_mailer),
):
    try:
        res = registrar(session, equipo, cuerpo)
    except ErrorRegistro as e:
        raise HTTPException(e.status, e.detalle) from None
    respuesta.status_code = res.status
    if res.status == 201:
        tareas.add_task(procesar_despues_de_registrar, factory, publisher, mailer, res.notificacion_id)
    return RegistroOut(
        id=res.notificacion_id, duplicada=res.duplicada, alertas_cerradas=res.alertas_cerradas
    )
