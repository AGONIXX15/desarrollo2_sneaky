import hashlib
import hmac
import json
from datetime import timedelta

from sqlalchemy import select

from core.ciclo import ejecutar_ciclo
from core.db import ahora
from core.models import Callback, EnvioCorreo, Notificacion
from core.webhooks import procesar_mensaje
from tests.conftest import headers

STOCK = {"tipo": "STOCK_BAJO_INSUMO", "productoId": 7, "nombre": "Harina", "stockActual": 2, "stockMinimo": 10}


def suscribir(client, key):
    client.post(
        "/notificaciones/destinatarios",
        json={"nombre": "Ana", "email": "ana@x.com", "tipos": ["STOCK_BAJO_INSUMO"]},
        headers=headers(key),
    )


def test_ciclo_republica(client, keys, publisher, mailer, http_mock, session):
    publisher.falla = True
    r = client.post("/notificaciones", json=STOCK, headers=headers(keys["inventario"]))
    assert r.status_code == 201
    n = session.scalars(select(Notificacion)).one()
    assert n.publicada_at is None and n.intentos_publicacion == 1

    publisher.falla = False
    resumen = ejecutar_ciclo(session, publisher, mailer, http_mock.cliente)
    session.refresh(n)
    assert n.publicada_at is not None
    assert resumen["publicadas"] == 1
    assert publisher.mensajes[0][0] == "inventario"


def test_publicacion_deja_de_reintentar_tras_3_fallos(client, keys, publisher, mailer, http_mock, session):
    publisher.falla = True
    client.post("/notificaciones", json=STOCK, headers=headers(keys["inventario"]))
    for _ in range(5):
        ejecutar_ciclo(session, publisher, mailer, http_mock.cliente)
    n = session.scalars(select(Notificacion)).one()
    session.refresh(n)
    assert n.intentos_publicacion == 3
    estado = client.get("/notificaciones/estado", headers=headers(keys["inventario"])).json()
    assert estado["items"][0]["estado"] == "publicacion_fallida"


def test_ciclo_reenvia_correo(client, keys, publisher, mailer, http_mock, session):
    suscribir(client, keys["inventario"])
    mailer.falla = True
    client.post("/notificaciones", json=STOCK, headers=headers(keys["inventario"]))
    envio = session.scalars(select(EnvioCorreo)).one()
    assert envio.intentos == 1 and envio.enviado_at is None

    mailer.falla = False
    # todavía no vence el proximo_intento_at
    ejecutar_ciclo(session, publisher, mailer, http_mock.cliente)
    assert mailer.enviados == []

    envio.proximo_intento_at = ahora() - timedelta(seconds=1)
    session.commit()
    resumen = ejecutar_ciclo(session, publisher, mailer, http_mock.cliente)
    session.refresh(envio)
    assert envio.enviado_at is not None
    assert resumen["correos_enviados"] == 1
    assert "hora Colombia" in mailer.enviados[0]["texto"]


def test_correo_se_rinde_tras_3_fallos(client, keys, publisher, mailer, http_mock, session):
    suscribir(client, keys["inventario"])
    mailer.falla = True
    client.post("/notificaciones", json=STOCK, headers=headers(keys["inventario"]))
    envio = session.scalars(select(EnvioCorreo)).one()
    for _ in range(5):
        envio.proximo_intento_at = ahora() - timedelta(seconds=1)
        session.commit()
        ejecutar_ciclo(session, publisher, mailer, http_mock.cliente)
        session.refresh(envio)
    assert envio.intentos == 3
    assert envio.enviado_at is None


def registrar_callback(client, key):
    r = client.put("/notificaciones/callbacks", json={"url": "https://8.8.8.8/hook"}, headers=headers(key))
    return r.json()["secreto"]


def test_webhook_firma_hmac(client, keys, factory, http_mock):
    secreto = registrar_callback(client, keys["inventario"])
    client.post("/notificaciones", json=STOCK, headers=headers(keys["inventario"]))
    with factory() as s:
        n = s.scalars(select(Notificacion)).one()
        procesar_mensaje(factory, http_mock.cliente, {"notificacionId": str(n.id)})
        s.refresh(n)
        assert n.entregada_at is not None
    req = http_mock.peticiones[0]
    esperado = hmac.new(secreto.encode(), req.content, hashlib.sha256).hexdigest()
    assert req.headers["X-Signature"] == esperado
    assert req.headers["X-Notification-Id"] == str(n.id)
    assert json.loads(req.content)["datos"]["productoId"] == 7


def test_webhook_fallido_y_reintento_por_ciclo(client, keys, publisher, mailer, factory, http_mock, session):
    registrar_callback(client, keys["inventario"])
    client.post("/notificaciones", json=STOCK, headers=headers(keys["inventario"]))
    n = session.scalars(select(Notificacion)).one()
    http_mock.status = 500
    procesar_mensaje(factory, http_mock.cliente, {"notificacionId": str(n.id)})
    session.refresh(n)
    assert n.intentos_entrega == 1 and n.proximo_intento_entrega_at > ahora()

    http_mock.status = 200
    n.proximo_intento_entrega_at = ahora() - timedelta(seconds=1)
    session.commit()
    resumen = ejecutar_ciclo(session, publisher, mailer, http_mock.cliente)
    session.refresh(n)
    assert n.entregada_at is not None
    assert resumen["webhooks_entregados"] == 1


def test_sin_callback_no_es_error(client, keys, factory, http_mock, session):
    client.post("/notificaciones", json=STOCK, headers=headers(keys["inventario"]))
    n = session.scalars(select(Notificacion)).one()
    procesar_mensaje(factory, http_mock.cliente, {"notificacionId": str(n.id)})
    session.refresh(n)
    assert n.intentos_entrega == 0 and http_mock.peticiones == []
    assert session.scalars(select(Callback)).first() is None


def test_endpoint_ciclo_solo_admin(client, keys):
    assert client.post("/notificaciones/ciclo", headers=headers(keys["inventario"])).status_code == 403
    r = client.post("/notificaciones/ciclo", headers=headers(keys["notificaciones"]))
    assert r.status_code == 200 and "publicadas" in r.json()
