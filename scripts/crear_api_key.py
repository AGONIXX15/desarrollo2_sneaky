"""Genera una API key para un equipo. La muestra una sola vez.

Uso: uv run python scripts/crear_api_key.py inventario
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select

from core.config import get_settings
from core.db import ahora, crear_engine, crear_session_factory
from core.models import ApiKey, Equipo
from core.seguridad import generar_api_key, hash_api_key, prefijo_visible

MAX_ACTIVAS = 2


class LimiteDeKeys(Exception):
    pass


def crear_key(session, nombre_equipo: str) -> str:
    equipo = session.scalar(select(Equipo).where(Equipo.nombre == nombre_equipo).with_for_update())
    if equipo is None:
        raise ValueError(f"No existe el equipo {nombre_equipo}")
    activas = session.scalars(
        select(ApiKey).where(ApiKey.equipo_id == equipo.id, ApiKey.activa.is_(True))
    ).all()
    if len(activas) >= MAX_ACTIVAS:
        raise LimiteDeKeys(f"{nombre_equipo} ya tiene {MAX_ACTIVAS} keys activas")
    key = generar_api_key()
    session.add(
        ApiKey(
            equipo_id=equipo.id,
            hash=hash_api_key(key),
            prefijo=prefijo_visible(key),
            activa=True,
            creada_at=ahora(),
        )
    )
    session.commit()
    return key


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("equipo")
    args = parser.parse_args()
    factory = crear_session_factory(crear_engine(get_settings().database_url))
    try:
        with factory() as session:
            key = crear_key(session, args.equipo)
    except (ValueError, LimiteDeKeys) as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    print(f"API key para {args.equipo} (guárdala, no se vuelve a mostrar):")
    print(key)
    return 0


if __name__ == "__main__":
    sys.exit(main())
