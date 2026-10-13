import logging
from collections.abc import Iterator
from functools import lru_cache

import httpx
from fastapi import Depends, Header, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from core.config import get_settings
from core.db import get_session_factory as _factory
from core.mailer import Mailer, crear_mailer
from core.models import ApiKey, Equipo
from core.publisher import AmqpPublisher, Publisher
from core.seguridad import hash_api_key

log = logging.getLogger(__name__)


def get_session_factory() -> sessionmaker[Session]:
    return _factory()


def get_session(factory=Depends(get_session_factory)) -> Iterator[Session]:
    with factory() as session:
        yield session


@lru_cache
def _publisher() -> Publisher:
    cfg = get_settings()
    return AmqpPublisher(cfg.amqp_url, cfg.amqp_exchange)


def get_publisher() -> Publisher:
    return _publisher()


@lru_cache
def _mailer() -> Mailer:
    return crear_mailer(get_settings())


def get_mailer() -> Mailer:
    return _mailer()


@lru_cache
def _http() -> httpx.Client:
    return httpx.Client(timeout=get_settings().webhook_timeout)


def get_http_client() -> httpx.Client:
    return _http()


def get_equipo(x_api_key: str | None = Header(default=None), session: Session = Depends(get_session)) -> Equipo:
    if not x_api_key:
        log.warning("solicitud rechazada: falta el header X-API-Key")
        raise HTTPException(401, "Falta el header X-API-Key")
    key = session.scalar(select(ApiKey).where(ApiKey.hash == hash_api_key(x_api_key), ApiKey.activa.is_(True)))
    if key is None:
        log.warning("api key rechazada: no coincide con ninguna key activa")
        raise HTTPException(401, "API key inválida")
    return key.equipo


def requiere_admin(equipo: Equipo = Depends(get_equipo)) -> Equipo:
    if not equipo.es_admin:
        raise HTTPException(403, "Solo el equipo de notificaciones puede hacer esto")
    return equipo


def requiere_equipo_normal(equipo: Equipo = Depends(get_equipo)) -> Equipo:
    if equipo.es_admin:
        raise HTTPException(403, "El admin no tiene destinatarios ni callback propios")
    return equipo
