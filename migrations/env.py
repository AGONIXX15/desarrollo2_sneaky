from alembic import context
from sqlalchemy import create_engine

from core.config import get_settings
from core.db import normalizar_url
from core.models import Base

config = context.config
target_metadata = Base.metadata


def _url() -> str:
    return normalizar_url(config.get_main_option("sqlalchemy.url") or get_settings().database_url)


def run_migrations_online() -> None:
    engine = create_engine(_url())
    with engine.connect() as conexion:
        context.configure(connection=conexion, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


run_migrations_online()
