from datetime import timedelta

from sqlalchemy import select, text

from core.db import ahora
from core.models import Alerta, Notificacion
from tests.conftest import headers

STOCK = {"tipo": "STOCK_BAJO_INSUMO", "productoId": 7, "nombre": "Harina", "stockActual": 2, "stockMinimo": 10}


def test_sin_key_da_401(client):
    assert client.post("/notificaciones", json=STOCK).status_code == 401


def test_key_invalida_da_401(client, keys):
    r = client.post("/notificaciones", json=STOCK, headers=headers("ntf_falsa"))
    assert r.status_code == 401


def test_emisor_no_autorizado_da_403(client, keys):
    r = client.post("/notificaciones", json=STOCK, headers=headers(keys["fabricacion"]))
    assert r.status_code == 403


def test_payload_invalido_da_422(client, keys):
    r = client.post(
        "/notificaciones",
        json={"tipo": "STOCK_BAJO_INSUMO", "productoId": 7},
        headers=headers(keys["inventario"]),
    )
    assert r.status_code == 422


def test_codigo_condicion_largo_da_422(client, keys):
    r = client.post(
        "/notificaciones",
        json={"tipo": "CONDICION_URGENTE", "codigoCondicion": "x" * 31, "descripcion": "algo"},
        headers=headers(keys["fabricacion"]),
    )
    assert r.status_code == 422


def test_crea_y_publica(client, keys, publisher):
    r = client.post("/notificaciones", json=STOCK, headers=headers(keys["inventario"]))
    assert r.status_code == 201
    assert publisher.mensajes[0][0] == "inventario"
    assert publisher.mensajes[0][1]["notificacionId"] == r.json()["id"]


def test_dedupe(client, keys):
    h = headers(keys["inventario"])
    r1 = client.post("/notificaciones", json=STOCK, headers=h)
    r2 = client.post("/notificaciones", json=STOCK, headers=h)
    assert (r1.status_code, r2.status_code) == (201, 200)
    assert r1.json()["id"] == r2.json()["id"]
    assert r2.json()["duplicada"] is True


def test_otra_clave_crea_otra(client, keys):
    h = headers(keys["inventario"])
    client.post("/notificaciones", json=STOCK, headers=h)
    r = client.post("/notificaciones", json={**STOCK, "productoId": 8}, headers=h)
    assert r.status_code == 201


def test_repuesto_cierra_y_permite_nueva(client, keys):
    h = headers(keys["inventario"])
    r1 = client.post("/notificaciones", json=STOCK, headers=h)
    cierre = client.post("/notificaciones", json={**STOCK, "evento": "REPUESTO"}, headers=h)
    assert cierre.status_code == 200
    assert cierre.json()["alertas_cerradas"] == 1
    r3 = client.post("/notificaciones", json=STOCK, headers=h)
    assert r3.status_code == 201
    assert r3.json()["id"] != r1.json()["id"]


def test_alerta_vencida_crea_nueva(client, keys, session):
    h = headers(keys["inventario"])
    r1 = client.post("/notificaciones", json=STOCK, headers=h)
    session.execute(text("UPDATE alertas SET expira_at = :t"), {"t": ahora() - timedelta(minutes=1)})
    session.commit()
    r2 = client.post("/notificaciones", json=STOCK, headers=h)
    assert r2.status_code == 201
    assert r2.json()["id"] != r1.json()["id"]
    assert len(session.scalars(select(Alerta)).all()) == 2
    assert len(session.scalars(select(Alerta).where(Alerta.cerrada_at.is_(None))).all()) == 1


def test_acumulacion_usa_clave_fija(client, keys):
    h = headers(keys["inventario"])
    cuerpo = {"tipo": "ACUMULACION_PEDIDOS", "cantidadPedidos": 30, "umbral": 20}
    assert client.post("/notificaciones", json=cuerpo, headers=h).status_code == 201
    assert client.post("/notificaciones", json={**cuerpo, "cantidadPedidos": 31}, headers=h).status_code == 200


def test_correos_a_destinatarios_suscritos(client, keys, mailer, session):
    h = headers(keys["inventario"])
    client.post(
        "/notificaciones/destinatarios",
        json={"nombre": "Ana", "email": "ana@x.com", "tipos": ["STOCK_BAJO_INSUMO"]},
        headers=h,
    )
    client.post(
        "/notificaciones/destinatarios",
        json={"nombre": "Beto", "email": "beto@x.com", "tipos": ["ACUMULACION_PEDIDOS"]},
        headers=h,
    )
    mailer.fallar_a = {"ana@x.com"}
    client.post("/notificaciones", json=STOCK, headers=h)
    assert mailer.enviados == []
    n = session.scalars(select(Notificacion)).one()
    assert [(e.email, e.intentos) for e in n.envios] == [("ana@x.com", 1)]


def test_clave_demasiado_larga_da_422(client, keys, session):
    session.execute(
        text("UPDATE tipos_notificacion SET campo_clave = 'descripcion' WHERE codigo = 'CONDICION_URGENTE'")
    )
    session.commit()
    r = client.post(
        "/notificaciones",
        json={"tipo": "CONDICION_URGENTE", "codigoCondicion": "A", "descripcion": "x" * 101},
        headers=headers(keys["fabricacion"]),
    )
    assert r.status_code == 422
    session.execute(
        text("UPDATE tipos_notificacion SET campo_clave = 'codigoCondicion' WHERE codigo = 'CONDICION_URGENTE'")
    )
    session.commit()


def test_clave_ausente_da_422(client, keys, session):
    session.execute(text("UPDATE tipos_notificacion SET campo_clave = 'otro' WHERE codigo = 'ACUMULACION_PEDIDOS'"))
    session.commit()
    r = client.post(
        "/notificaciones",
        json={"tipo": "ACUMULACION_PEDIDOS", "cantidadPedidos": 3, "umbral": 2},
        headers=headers(keys["inventario"]),
    )
    session.execute(text("UPDATE tipos_notificacion SET campo_clave = NULL WHERE codigo = 'ACUMULACION_PEDIDOS'"))
    session.commit()
    assert r.status_code == 422


def test_body_grande_da_413(client, keys):
    r = client.post(
        "/notificaciones",
        content=b'{"tipo": "X", "relleno": "' + b"a" * 70_000 + b'"}',
        headers={**headers(keys["inventario"]), "Content-Type": "application/json"},
    )
    assert r.status_code == 413
