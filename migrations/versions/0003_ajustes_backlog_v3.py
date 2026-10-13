"""callbacks.activo y limites de longitud en los esquemas de cada tipo

Revision ID: 0003
Revises: 0002
"""
import json

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

ENTERO = {"type": "integer", "minimum": 0, "maximum": 1000000}

NUEVOS = {
    "STOCK_BAJO_INSUMO": None,
    "STOCK_BAJO_PRODUCTO": None,
    "CONDICION_URGENTE": {
        "type": "object",
        "required": ["codigoCondicion", "descripcion"],
        "properties": {
            "codigoCondicion": {"type": "string", "pattern": "^[A-Za-z0-9-]{1,30}$"},
            "descripcion": {"type": "string", "minLength": 1, "maxLength": 100},
        },
    },
    "ACUMULACION_PEDIDOS": {
        "type": "object",
        "required": ["cantidadPedidos", "umbral"],
        "properties": {"cantidadPedidos": ENTERO, "umbral": ENTERO},
    },
}
NUEVOS["STOCK_BAJO_INSUMO"] = NUEVOS["STOCK_BAJO_PRODUCTO"] = {
    "type": "object",
    "required": ["productoId", "nombre", "stockActual", "stockMinimo"],
    "properties": {
        "productoId": {
            "oneOf": [
                {"type": "integer", "minimum": 0},
                {"type": "string", "pattern": "^[A-Za-z0-9-]{1,50}$"},
            ]
        },
        "nombre": {"type": "string", "minLength": 1, "maxLength": 100},
        "stockActual": ENTERO,
        "stockMinimo": ENTERO,
    },
}

ANTERIORES = {
    "STOCK": {
        "type": "object",
        "required": ["productoId", "nombre", "stockActual", "stockMinimo"],
        "properties": {
            "productoId": {"type": ["integer", "string"]},
            "nombre": {"type": "string", "minLength": 1},
            "stockActual": {"type": "number"},
            "stockMinimo": {"type": "number"},
        },
    },
    "CONDICION_URGENTE": {
        "type": "object",
        "required": ["codigoCondicion", "descripcion"],
        "properties": {
            "codigoCondicion": {"type": "string", "minLength": 1, "maxLength": 30},
            "descripcion": {"type": "string", "minLength": 1},
        },
    },
    "ACUMULACION_PEDIDOS": {
        "type": "object",
        "required": ["cantidadPedidos", "umbral"],
        "properties": {
            "cantidadPedidos": {"type": "integer", "minimum": 0},
            "umbral": {"type": "integer", "minimum": 0},
        },
    },
}


def _guardar(esquemas: dict) -> None:
    conn = op.get_bind()
    for codigo, esquema in esquemas.items():
        conn.execute(
            sa.text("UPDATE tipos_notificacion SET schema = CAST(:s AS jsonb) WHERE codigo = :c"),
            {"s": json.dumps(esquema), "c": codigo},
        )


def upgrade() -> None:
    op.add_column("callbacks", sa.Column("activo", sa.Boolean, nullable=False, server_default=sa.true()))
    _guardar(NUEVOS)


def downgrade() -> None:
    _guardar(
        {
            "STOCK_BAJO_INSUMO": ANTERIORES["STOCK"],
            "STOCK_BAJO_PRODUCTO": ANTERIORES["STOCK"],
            "CONDICION_URGENTE": ANTERIORES["CONDICION_URGENTE"],
            "ACUMULACION_PEDIDOS": ANTERIORES["ACUMULACION_PEDIDOS"],
        }
    )
    op.drop_column("callbacks", "activo")
