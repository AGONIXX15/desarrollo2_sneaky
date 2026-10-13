import asyncio
import json
import logging

import aio_pika
import httpx
from sqlalchemy import select

from core.config import Settings
from core.models import Equipo
from core.webhooks import procesar_mensaje

log = logging.getLogger(__name__)
REFRESCO_SEGUNDOS = 60


async def _atender(mensaje: aio_pika.abc.AbstractIncomingMessage, session_factory, http_client):
    try:
        datos = json.loads(mensaje.body)
        await asyncio.to_thread(procesar_mensaje, session_factory, http_client, datos)
    except Exception:
        log.exception("error procesando mensaje del webhook")
    finally:
        # siempre ack: el reintento lo hace el ciclo, no la cola
        await mensaje.ack()


def _nombres_equipos(session_factory) -> list[str]:
    with session_factory() as s:
        return list(s.scalars(select(Equipo.nombre).where(Equipo.es_admin.is_(False))))


async def correr_worker(settings: Settings, session_factory) -> None:
    http_client = httpx.Client(timeout=settings.webhook_timeout)
    while True:
        try:
            conexion = await aio_pika.connect_robust(settings.amqp_url)
            async with conexion:
                canal = await conexion.channel()
                await canal.set_qos(prefetch_count=10)
                exchange = await canal.declare_exchange(
                    settings.amqp_exchange, aio_pika.ExchangeType.DIRECT, durable=True
                )
                consumiendo: set[str] = set()
                while True:
                    # cada minuto mira si hay equipos nuevos para escuchar su cola
                    for nombre in await asyncio.to_thread(_nombres_equipos, session_factory):
                        if nombre in consumiendo:
                            continue
                        cola = await canal.declare_queue(f"notif.{nombre}", durable=True)
                        await cola.bind(exchange, routing_key=nombre)
                        await cola.consume(lambda m: _atender(m, session_factory, http_client))
                        consumiendo.add(nombre)
                        log.info("worker escuchando notif.%s", nombre)
                    await asyncio.sleep(REFRESCO_SEGUNDOS)
        except asyncio.CancelledError:
            http_client.close()
            raise
        except Exception as e:
            log.warning("worker sin conexión a la cola (%s), reintento en 10 s", e)
            await asyncio.sleep(10)
