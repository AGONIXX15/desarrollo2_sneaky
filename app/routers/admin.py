from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.deps import get_http_client, get_mailer, get_publisher, get_session, requiere_admin
from core.ciclo import ejecutar_ciclo
from core.models import Equipo

router = APIRouter(prefix="/notificaciones", tags=["admin"])


@router.post("/ciclo")
def ciclo(
    _: Equipo = Depends(requiere_admin),
    session: Session = Depends(get_session),
    publisher=Depends(get_publisher),
    mailer=Depends(get_mailer),
    http_client=Depends(get_http_client),
):
    return ejecutar_ciclo(session, publisher, mailer, http_client)
