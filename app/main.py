import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.deps import get_session_factory
from app.routers import admin, callbacks, destinatarios, estado, notificaciones, worker
from core.config import get_settings

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
app.include_router(notificaciones.router)
app.include_router(destinatarios.router)
app.include_router(callbacks.router)
app.include_router(estado.router)
app.include_router(admin.router)


@app.get("/health")
def health():
    return {"status": "ok"}
