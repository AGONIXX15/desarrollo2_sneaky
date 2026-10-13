import json
import logging
from typing import Protocol

import pika

log = logging.getLogger(__name__)


class Publisher(Protocol):
    def publicar(self, equipo_destino: str, mensaje: dict) -> None:
        """Lanza excepción si no se pudo publicar."""
        ...


class AmqpPublisher:
    """Publica en el exchange direct. Abre una conexión por mensaje, que para este volumen alcanza."""

    def __init__(self, url: str, exchange: str = "notificaciones"):
        self.url = url
        self.exchange = exchange

    def publicar(self, equipo_destino: str, mensaje: dict) -> None:
        params = pika.URLParameters(self.url)
        params.socket_timeout = 5
        params.connection_attempts = 1
        conexion = pika.BlockingConnection(params)
        try:
            canal = conexion.channel()
            canal.exchange_declare(self.exchange, exchange_type="direct", durable=True)
            cola = f"notif.{equipo_destino}"
            canal.queue_declare(cola, durable=True)
            canal.queue_bind(cola, self.exchange, routing_key=equipo_destino)
            canal.confirm_delivery()
            canal.basic_publish(
                self.exchange,
                equipo_destino,
                json.dumps(mensaje).encode(),
                properties=pika.BasicProperties(
                    content_type="application/json", delivery_mode=2
                ),
                mandatory=True,
            )
        finally:
            conexion.close()
