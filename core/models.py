import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    Column,
    ForeignKey,
    Index,
    Integer,
    String,
    Table,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.types import DateTime


class Base(DeclarativeBase):
    type_annotation_map = {datetime: DateTime(timezone=True)}


class Equipo(Base):
    __tablename__ = "equipos"

    id: Mapped[int] = mapped_column(primary_key=True)
    nombre: Mapped[str] = mapped_column(String(50), unique=True)
    es_admin: Mapped[bool] = mapped_column(Boolean, default=False)


class ApiKey(Base):
    __tablename__ = "api_keys"

    id: Mapped[int] = mapped_column(primary_key=True)
    equipo_id: Mapped[int] = mapped_column(ForeignKey("equipos.id"))
    hash: Mapped[str] = mapped_column(String(64), unique=True)
    prefijo: Mapped[str] = mapped_column(String(16))
    activa: Mapped[bool] = mapped_column(Boolean, default=True)
    creada_at: Mapped[datetime]

    equipo: Mapped[Equipo] = relationship()


class TipoNotificacion(Base):
    __tablename__ = "tipos_notificacion"

    codigo: Mapped[str] = mapped_column(String(60), primary_key=True)
    equipo_emisor_id: Mapped[int] = mapped_column(ForeignKey("equipos.id"))
    equipo_destino_id: Mapped[int] = mapped_column(ForeignKey("equipos.id"))
    schema: Mapped[dict] = mapped_column(JSONB)
    campo_clave: Mapped[str | None] = mapped_column(String(60), nullable=True)
    ttl_alerta_min: Mapped[int] = mapped_column(Integer, default=1440)
    activo: Mapped[bool] = mapped_column(Boolean, default=True)

    emisor: Mapped[Equipo] = relationship(foreign_keys=[equipo_emisor_id])
    destino: Mapped[Equipo] = relationship(foreign_keys=[equipo_destino_id])


destinatario_tipos = Table(
    "destinatario_tipos",
    Base.metadata,
    Column("destinatario_id", ForeignKey("destinatarios.id", ondelete="CASCADE"), primary_key=True),
    Column("tipo_codigo", ForeignKey("tipos_notificacion.codigo"), primary_key=True),
)


class Destinatario(Base):
    __tablename__ = "destinatarios"

    id: Mapped[int] = mapped_column(primary_key=True)
    equipo_id: Mapped[int] = mapped_column(ForeignKey("equipos.id"))
    nombre: Mapped[str] = mapped_column(String(120))
    email: Mapped[str] = mapped_column(String(254))
    activo: Mapped[bool] = mapped_column(Boolean, default=True)
    creado_at: Mapped[datetime]

    tipos: Mapped[list[TipoNotificacion]] = relationship(secondary=destinatario_tipos)


class Callback(Base):
    __tablename__ = "callbacks"

    id: Mapped[int] = mapped_column(primary_key=True)
    equipo_id: Mapped[int] = mapped_column(ForeignKey("equipos.id"), unique=True)
    url: Mapped[str] = mapped_column(Text)
    secreto: Mapped[str] = mapped_column(String(128))
    actualizado_at: Mapped[datetime]


class Notificacion(Base):
    __tablename__ = "notificaciones"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tipo: Mapped[str] = mapped_column(ForeignKey("tipos_notificacion.codigo"))
    equipo_emisor_id: Mapped[int] = mapped_column(ForeignKey("equipos.id"))
    equipo_destino_id: Mapped[int] = mapped_column(ForeignKey("equipos.id"))
    payload: Mapped[dict] = mapped_column(JSONB)
    creada_at: Mapped[datetime]

    publicada_at: Mapped[datetime | None]
    intentos_publicacion: Mapped[int] = mapped_column(Integer, default=0)
    ultimo_error_publicacion: Mapped[str | None] = mapped_column(Text)

    entregada_at: Mapped[datetime | None]
    intentos_entrega: Mapped[int] = mapped_column(Integer, default=0)
    proximo_intento_entrega_at: Mapped[datetime | None]
    ultimo_error_entrega: Mapped[str | None] = mapped_column(Text)

    leida_at: Mapped[datetime | None]

    emisor: Mapped[Equipo] = relationship(foreign_keys=[equipo_emisor_id])
    destino: Mapped[Equipo] = relationship(foreign_keys=[equipo_destino_id])
    envios: Mapped[list["EnvioCorreo"]] = relationship(back_populates="notificacion", order_by="EnvioCorreo.id")

    __table_args__ = (
        Index("ix_notificaciones_creada_at", "creada_at"),
        Index("ix_notificaciones_tipo", "tipo"),
        Index("ix_notificaciones_destino", "equipo_destino_id"),
    )


class EnvioCorreo(Base):
    __tablename__ = "envios_correo"

    id: Mapped[int] = mapped_column(primary_key=True)
    notificacion_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("notificaciones.id", ondelete="CASCADE")
    )
    destinatario_id: Mapped[int] = mapped_column(ForeignKey("destinatarios.id"))
    email: Mapped[str] = mapped_column(String(254))
    enviado_at: Mapped[datetime | None]
    intentos: Mapped[int] = mapped_column(Integer, default=0)
    proximo_intento_at: Mapped[datetime | None]
    ultimo_error: Mapped[str | None] = mapped_column(Text)

    notificacion: Mapped[Notificacion] = relationship(back_populates="envios")
    destinatario: Mapped[Destinatario] = relationship()


class Alerta(Base):
    __tablename__ = "alertas"

    id: Mapped[int] = mapped_column(primary_key=True)
    tipo: Mapped[str] = mapped_column(ForeignKey("tipos_notificacion.codigo"))
    clave: Mapped[str] = mapped_column(String(100))
    notificacion_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("notificaciones.id", ondelete="CASCADE"), unique=True
    )
    creada_at: Mapped[datetime]
    expira_at: Mapped[datetime]
    cerrada_at: Mapped[datetime | None]
    # EMISOR (evento REPUESTO o RESUELTA) o EXPIRACION; NULL mientras la alerta sigue activa
    motivo_resolucion: Mapped[str | None] = mapped_column(String(20))

    __table_args__ = (
        Index(
            "uq_alertas_activa",
            "tipo",
            "clave",
            unique=True,
            postgresql_where=text("cerrada_at IS NULL"),
        ),
    )
