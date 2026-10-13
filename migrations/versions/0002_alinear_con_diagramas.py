"""motivo de resolucion de la alerta, una alerta por notificacion y emisor de STOCK_BAJO_PRODUCTO

Revision ID: 0002
Revises: 0001
"""
import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("alertas", sa.Column("motivo_resolucion", sa.String(20)))
    # las alertas ya cerradas: si se cerraron antes de vencer fue el emisor, si no fue la expiracion
    op.execute(
        "UPDATE alertas SET motivo_resolucion = CASE WHEN cerrada_at >= expira_at THEN 'EXPIRACION' ELSE 'EMISOR' END"
        " WHERE cerrada_at IS NOT NULL"
    )
    op.create_unique_constraint("uq_alertas_notificacion", "alertas", ["notificacion_id"])
    # el stock de producto lo reporta Inventario y lo recibe Fabricacion
    op.execute(
        "UPDATE tipos_notificacion SET equipo_emisor_id = (SELECT id FROM equipos WHERE nombre = 'inventario')"
        " WHERE codigo = 'STOCK_BAJO_PRODUCTO'"
    )


def downgrade() -> None:
    op.execute(
        "UPDATE tipos_notificacion SET equipo_emisor_id = (SELECT id FROM equipos WHERE nombre = 'fabricacion')"
        " WHERE codigo = 'STOCK_BAJO_PRODUCTO'"
    )
    op.drop_constraint("uq_alertas_notificacion", "alertas", type_="unique")
    op.drop_column("alertas", "motivo_resolucion")
