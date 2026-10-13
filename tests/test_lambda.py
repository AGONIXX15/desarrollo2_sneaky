from sqlalchemy import select

from core.models import Notificacion
from lambda_retry import handler as lambda_handler
from tests.conftest import headers

STOCK = {"tipo": "STOCK_BAJO_INSUMO", "productoId": 7, "nombre": "Harina", "stockActual": 2, "stockMinimo": 10}


def test_handler_con_fakes(client, keys, publisher, mailer, http_mock, session, monkeypatch, envejecer):
    publisher.falla = True
    client.post("/notificaciones", json=STOCK, headers=headers(keys["inventario"]))
    publisher.falla = False
    envejecer()

    monkeypatch.setattr(
        lambda_handler,
        "construir_dependencias",
        lambda: (session, publisher, mailer, http_mock.cliente),
    )
    resumen = lambda_handler.handler({}, None)
    assert resumen["publicadas"] == 1
    session.expire_all()
    assert session.scalars(select(Notificacion)).one().publicada_at is not None


def test_handler_llama_al_health_de_render(monkeypatch, session, publisher, mailer, http_mock):
    from core.config import get_settings

    monkeypatch.setenv("RENDER_HEALTH_URL", "https://render.example/health")
    get_settings.cache_clear()
    try:
        monkeypatch.setattr(
            lambda_handler,
            "construir_dependencias",
            lambda: (session, publisher, mailer, http_mock.cliente),
        )
        resumen = lambda_handler.handler({}, None)
    finally:
        monkeypatch.delenv("RENDER_HEALTH_URL")
        get_settings.cache_clear()
    assert resumen["render_health"] == 200
    assert str(http_mock.peticiones[-1].url) == "https://render.example/health"


def test_handler_deja_subir_excepciones(monkeypatch, session, mailer, http_mock):
    import pytest

    def explota():
        raise RuntimeError("bd caída")

    monkeypatch.setattr(lambda_handler, "construir_dependencias", explota)
    with pytest.raises(RuntimeError):
        lambda_handler.handler({}, None)


def _stub_boto3(monkeypatch, respuesta):
    import sys
    import types

    class Cliente:
        def get_parameters(self, Names, WithDecryption):
            return respuesta

    monkeypatch.setitem(sys.modules, "boto3", types.SimpleNamespace(client=lambda _: Cliente()))


def test_ssm_parametro_inexistente_falla(monkeypatch):
    import pytest

    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("DATABASE_URL_PARAM", "/n/DATABASE_URL")
    _stub_boto3(monkeypatch, {"Parameters": [], "InvalidParameters": ["/n/DATABASE_URL"]})
    with pytest.raises(RuntimeError, match="no existen"):
        lambda_handler.cargar_ssm()


def test_ssm_falta_config_obligatoria(monkeypatch):
    import pytest

    for v in ("DATABASE_URL", "AMQP_URL", "BREVO_API_KEY"):
        monkeypatch.delenv(v, raising=False)
        monkeypatch.delenv(f"{v}_PARAM", raising=False)
    monkeypatch.setenv("MAIL_BACKEND", "brevo")
    monkeypatch.setenv("DATABASE_URL", "postgresql://x")
    with pytest.raises(RuntimeError, match="AMQP_URL"):
        lambda_handler.cargar_ssm()


def test_ssm_carga_valores(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("AMQP_URL", "amqp://x")
    monkeypatch.setenv("MAIL_BACKEND", "smtp")
    monkeypatch.setenv("DATABASE_URL_PARAM", "/n/DATABASE_URL")
    _stub_boto3(
        monkeypatch,
        {"Parameters": [{"Name": "/n/DATABASE_URL", "Value": "postgresql://neon"}], "InvalidParameters": []},
    )
    lambda_handler.cargar_ssm()
    import os

    assert os.environ["DATABASE_URL"] == "postgresql://neon"
    monkeypatch.delenv("DATABASE_URL")
