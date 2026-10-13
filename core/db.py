from datetime import UTC, datetime
from functools import lru_cache

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import NullPool

from core.config import get_settings


def ahora() -> datetime:
    return datetime.now(UTC)


def normalizar_url(url: str) -> str:
    # Neon y Render entregan postgresql:// a secas; SQLAlchemy necesita elegir el driver
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    if url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://"):]
    return url


def crear_engine(url: str, sin_pool: bool = False) -> Engine:
    if sin_pool:
        # la Lambda se conecta al pooler de Neon, no hace falta otro pool encima
        return create_engine(normalizar_url(url), poolclass=NullPool)
    return create_engine(normalizar_url(url), pool_pre_ping=True)


def crear_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(engine, expire_on_commit=False)


@lru_cache
def get_session_factory() -> sessionmaker[Session]:
    return crear_session_factory(crear_engine(get_settings().database_url))
