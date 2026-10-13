import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from app.deps import get_session_factory
from app.routers import admin, callbacks, destinatarios, estado, notificaciones, worker
from core.config import get_settings

LIMITE_BODY = 64 * 1024


class CuerpoGrande(Exception):
    pass


class LimiteBody:
    """Rechaza con 413 los POST a /notificaciones que pasen de 64 KB, con o sin Content-Length."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] != "POST" or scope["path"] != "/notificaciones":
            return await self.app(scope, receive, send)
        largo = dict(scope["headers"]).get(b"content-length")
        if largo and largo.isdigit() and int(largo) > LIMITE_BODY:
            return await self._rechazar(scope, receive, send)
        recibidos = 0

        async def contar(*args):
            nonlocal recibidos
            msg = await receive()
            recibidos += len(msg.get("body", b""))
            if recibidos > LIMITE_BODY:
                raise CuerpoGrande
            return msg

        try:
            await self.app(scope, contar, send)
        except CuerpoGrande:
            await self._rechazar(scope, receive, send)

    async def _rechazar(self, scope, receive, send):
        resp = JSONResponse({"detail": "El body no puede pasar de 64 KB"}, status_code=413)
        await resp(scope, receive, send)


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    tarea = None
    if settings.worker_enabled:
        tarea = asyncio.create_task(worker.correr_worker(settings, get_session_factory()))
    yield
    if tarea:
        tarea.cancel()
        try:
            await tarea
        except asyncio.CancelledError:
            pass


app = FastAPI(title="Servicio de notificaciones", lifespan=lifespan)
app.add_middleware(LimiteBody)
app.include_router(notificaciones.router)
app.include_router(destinatarios.router)
app.include_router(callbacks.router)
app.include_router(estado.router)
app.include_router(admin.router)


@app.get("/health")
def health():
    return {"status": "ok"}
