from sqlalchemy import select

from core.models import Notificacion
from lambda_retry import handler as lambda_handler
from tests.conftest import headers

STOCK = {"tipo": "STOCK_BAJO_INSUMO", "productoId": 7, "nombre": "Harina", "stockActual": 2, "stockMinimo": 10}


def test_handler_con_fakes(client, keys, publisher, mailer, http_mock, session, monkeypatch):
    publisher.falla = True
    client.post("/notificaciones", json=STOCK, headers=headers(keys["inventario"]))
    publisher.falla = False

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
