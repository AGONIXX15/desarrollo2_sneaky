from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field, PlainSerializer


def _a_utc(d: datetime) -> str:
    if d.tzinfo is None:
        d = d.replace(tzinfo=UTC)
    return d.astimezone(UTC).isoformat().replace("+00:00", "Z")


FechaUTC = Annotated[datetime, PlainSerializer(_a_utc, return_type=str)]


class DestinatarioIn(BaseModel):
    nombre: str = Field(min_length=1, max_length=120)
    email: EmailStr = Field(max_length=254)
    tipos: list[str] = Field(max_length=50)


class DestinatarioOut(BaseModel):
    id: int
    nombre: str
    email: str
    activo: bool
    tipos: list[str]
    equipo: str


class CallbackIn(BaseModel):
    url: str


class CallbackOut(BaseModel):
    url: str
    secreto: str


class RegistroOut(BaseModel):
    id: UUID | None
    duplicada: bool = False
    alertas_cerradas: int = 0


class NotificacionResumen(BaseModel):
    id: UUID
    tipo: str
    emisor: str
    destino: str
    estado: str
    creada_at: FechaUTC
    leida_at: FechaUTC | None
    payload: dict


class Pagina(BaseModel):
    items: list[NotificacionResumen]
    total: int
    pagina: int
    tamano: int
