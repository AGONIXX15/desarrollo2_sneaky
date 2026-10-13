"""esquema inicial y seed de equipos y tipos

Revision ID: 0001
Revises:
"""
import json

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

TS = sa.DateTime(timezone=True)


def _schema_stock() -> dict:
    return {
        "type": "object",
        "required": ["productoId", "nombre", "stockActual", "stockMinimo"],
        "properties": {
            "productoId": {"type": ["integer", "string"]},
            "nombre": {"type": "string", "minLength": 1},
            "stockActual": {"type": "number"},
            "stockMinimo": {"type": "number"},
        },
    }


SCHEMAS = {
    "STOCK_BAJO_INSUMO": _schema_stock(),
    "STOCK_BAJO_PRODUCTO": _schema_stock(),
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

# codigo, emisor, destino, campo_clave, ttl en minutos
TIPOS = [
    ("STOCK_BAJO_INSUMO", "inventario", "inventario", "productoId", 1440),
    ("STOCK_BAJO_PRODUCTO", "fabricacion", "fabricacion", "productoId", 1440),
    ("CONDICION_URGENTE", "fabricacion", "fabricacion", "codigoCondicion", 60),
    ("ACUMULACION_PEDIDOS", "inventario", "inventario", None, 60),
]


def upgrade() -> None:
    op.create_table(
        "equipos",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("nombre", sa.String(50), nullable=False, unique=True),
        sa.Column("es_admin", sa.Boolean, nullable=False, server_default=sa.false()),
    )
    op.create_table(
        "api_keys",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("equipo_id", sa.Integer, sa.ForeignKey("equipos.id"), nullable=False),
        sa.Column("hash", sa.String(64), nullable=False, unique=True),
        sa.Column("prefijo", sa.String(16), nullable=False),
        sa.Column("activa", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("creada_at", TS, nullable=False),
    )
    op.create_table(
        "tipos_notificacion",
        sa.Column("codigo", sa.String(60), primary_key=True),
        sa.Column("equipo_emisor_id", sa.Integer, sa.ForeignKey("equipos.id"), nullable=False),
        sa.Column("equipo_destino_id", sa.Integer, sa.ForeignKey("equipos.id"), nullable=False),
        sa.Column("schema", JSONB, nullable=False),
        sa.Column("campo_clave", sa.String(60)),
        sa.Column("ttl_alerta_min", sa.Integer, nullable=False, server_default="1440"),
        sa.Column("activo", sa.Boolean, nullable=False, server_default=sa.true()),
    )
    op.create_table(
        "destinatarios",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("equipo_id", sa.Integer, sa.ForeignKey("equipos.id"), nullable=False),
        sa.Column("nombre", sa.String(120), nullable=False),
        sa.Column("email", sa.String(254), nullable=False),
        sa.Column("activo", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("creado_at", TS, nullable=False),
    )
    op.create_table(
        "destinatario_tipos",
        sa.Column(
            "destinatario_id",
            sa.Integer,
            sa.ForeignKey("destinatarios.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "tipo_codigo",
            sa.String(60),
            sa.ForeignKey("tipos_notificacion.codigo"),
            primary_key=True,
        ),
    )
    op.create_table(
        "callbacks",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("equipo_id", sa.Integer, sa.ForeignKey("equipos.id"), nullable=False, unique=True),
        sa.Column("url", sa.Text, nullable=False),
        sa.Column("secreto", sa.String(128), nullable=False),
        sa.Column("actualizado_at", TS, nullable=False),
    )
    op.create_table(
        "notificaciones",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tipo", sa.String(60), sa.ForeignKey("tipos_notificacion.codigo"), nullable=False),
        sa.Column("equipo_emisor_id", sa.Integer, sa.ForeignKey("equipos.id"), nullable=False),
        sa.Column("equipo_destino_id", sa.Integer, sa.ForeignKey("equipos.id"), nullable=False),
        sa.Column("payload", JSONB, nullable=False),
        sa.Column("creada_at", TS, nullable=False),
        sa.Column("publicada_at", TS),
        sa.Column("intentos_publicacion", sa.Integer, nullable=False, server_default="0"),
        sa.Column("ultimo_error_publicacion", sa.Text),
        sa.Column("entregada_at", TS),
        sa.Column("intentos_entrega", sa.Integer, nullable=False, server_default="0"),
        sa.Column("proximo_intento_entrega_at", TS),
        sa.Column("ultimo_error_entrega", sa.Text),
        sa.Column("leida_at", TS),
    )
    op.create_index("ix_notificaciones_creada_at", "notificaciones", ["creada_at"])
    op.create_index("ix_notificaciones_tipo", "notificaciones", ["tipo"])
    op.create_index("ix_notificaciones_destino", "notificaciones", ["equipo_destino_id"])
    op.create_table(
        "envios_correo",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "notificacion_id",
            UUID(as_uuid=True),
            sa.ForeignKey("notificaciones.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("destinatario_id", sa.Integer, sa.ForeignKey("destinatarios.id"), nullable=False),
        sa.Column("email", sa.String(254), nullable=False),
        sa.Column("enviado_at", TS),
        sa.Column("intentos", sa.Integer, nullable=False, server_default="0"),
        sa.Column("proximo_intento_at", TS),
        sa.Column("ultimo_error", sa.Text),
    )
    op.create_table(
        "alertas",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("tipo", sa.String(60), sa.ForeignKey("tipos_notificacion.codigo"), nullable=False),
        sa.Column("clave", sa.String(100), nullable=False),
        sa.Column(
            "notificacion_id",
            UUID(as_uuid=True),
            sa.ForeignKey("notificaciones.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("creada_at", TS, nullable=False),
        sa.Column("expira_at", TS, nullable=False),
        sa.Column("cerrada_at", TS),
    )
    op.create_index(
        "uq_alertas_activa",
        "alertas",
        ["tipo", "clave"],
        unique=True,
        postgresql_where=sa.text("cerrada_at IS NULL"),
    )

    conn = op.get_bind()
    for nombre, admin in [("inventario", False), ("fabricacion", False), ("notificaciones", True)]:
        conn.execute(
            sa.text("INSERT INTO equipos (nombre, es_admin) VALUES (:n, :a)"), {"n": nombre, "a": admin}
        )
    ids = {r.nombre: r.id for r in conn.execute(sa.text("SELECT id, nombre FROM equipos"))}
    for codigo, emisor, destino, clave, ttl in TIPOS:
        conn.execute(
            sa.text(
                "INSERT INTO tipos_notificacion (codigo, equipo_emisor_id, equipo_destino_id, schema,"
                " campo_clave, ttl_alerta_min, activo) VALUES (:c, :e, :d, CAST(:s AS jsonb), :k, :t, true)"
            ),
            {
                "c": codigo,
                "e": ids[emisor],
                "d": ids[destino],
                "s": json.dumps(SCHEMAS[codigo]),
                "k": clave,
                "t": ttl,
            },
        )


def downgrade() -> None:
    for tabla in [
        "alertas",
        "envios_correo",
        "notificaciones",
        "callbacks",
        "destinatario_tipos",
        "destinatarios",
        "tipos_notificacion",
        "api_keys",
        "equipos",
    ]:
        op.drop_table(tabla)
