import os

os.environ["WORKER_ENABLED"] = "false"
os.environ["MAIL_BACKEND"] = "smtp"

from pathlib import Path

import httpx
import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from pytest_postgresql import factories
from pytest_postgresql.janitor import DatabaseJanitor
from sqlalchemy import select, text

from app.deps import (
    get_http_client,
    get_mailer,
    get_publisher,
    get_session_factory,
)
from app.main import app
from core.db import crear_engine, crear_session_factory
from core.models import Equipo
from scripts.crear_api_key import crear_key

RAIZ = Path(__file__).resolve().parent.parent

postgres_proc = factories.postgresql_proc(executable="/usr/bin/pg_ctl", port=None)


class FakePublisher:
    def __init__(self):
        self.mensajes: list[tuple[str, dict]] = []
        self.falla = False

    def publicar(self, equipo_destino, mensaje):
        if self.falla:
            raise ConnectionError("rabbit caído")
        self.mensajes.append((equipo_destino, mensaje))


class FakeMailer:
    def __init__(self):
        self.enviados: list[dict] = []
        self.falla = False
        self.fallar_a: set[str] = set()

    def enviar(self, email, nombre, asunto, texto):
        if self.falla or email in self.fallar_a:
            raise RuntimeError("brevo caído")
        self.enviados.append({"email": email, "nombre": nombre, "asunto": asunto, "texto": texto})


@pytest.fixture(scope="session")
def db_url(postgres_proc):
    p = postgres_proc
    janitor = DatabaseJanitor(
        user=p.user, host=p.host, port=p.port, dbname="notif_test", version=p.version,
        password=p.password,
    )
    janitor.init()
    url = f"postgresql://{p.user}@{p.host}:{p.port}/notif_test"
    cfg = Config(str(RAIZ / "alembic.ini"))
    cfg.set_main_option("script_location", str(RAIZ / "migrations"))
    cfg.set_main_option("sqlalchemy.url", url)
    command.upgrade(cfg, "head")
    yield url
    janitor.drop()


@pytest.fixture(scope="session")
def engine(db_url):
    eng = crear_engine(db_url)
    yield eng
    eng.dispose()


@pytest.fixture
def factory(engine):
    f = crear_session_factory(engine)
    yield f
    with engine.begin() as c:
        c.execute(
            text(
                "TRUNCATE alertas, envios_correo, notificaciones, destinatario_tipos,"
                " destinatarios, callbacks, api_keys RESTART IDENTITY CASCADE"
            )
        )


@pytest.fixture
def session(factory):
    with factory() as s:
        yield s


@pytest.fixture
def publisher():
    return FakePublisher()


@pytest.fixture
def mailer():
    return FakeMailer()


@pytest.fixture
def http_mock():
    """Cliente httpx falso: guarda las peticiones y responde con self.status."""

    class Estado:
        status = 200
        peticiones: list[httpx.Request] = []

    estado = Estado()
    estado.peticiones = []

    def responder(request: httpx.Request):
        estado.peticiones.append(request)
        return httpx.Response(estado.status)

    estado.cliente = httpx.Client(transport=httpx.MockTransport(responder))
    return estado


@pytest.fixture
def client(factory, publisher, mailer, http_mock):
    app.dependency_overrides[get_session_factory] = lambda: factory
    app.dependency_overrides[get_publisher] = lambda: publisher
    app.dependency_overrides[get_mailer] = lambda: mailer
    app.dependency_overrides[get_http_client] = lambda: http_mock.cliente
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def keys(session, factory):
    resultado = {}
    for nombre in ("inventario", "fabricacion", "notificaciones"):
        resultado[nombre] = crear_key(session, nombre)
    return resultado


def headers(key):
    return {"X-API-Key": key}


@pytest.fixture
def equipo_id(session):
    return {e.nombre: e.id for e in session.scalars(select(Equipo))}
