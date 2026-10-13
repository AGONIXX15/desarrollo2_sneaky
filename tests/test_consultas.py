from datetime import timedelta

import pytest
from sqlalchemy import select

from core.ciclo import ejecutar_ciclo
from core.db import ahora
from core.models import Callback, Notificacion
from tests.conftest import headers

STOCK = {"tipo": "STOCK_BAJO_INSUMO", "productoId": 7, "nombre": "Harina", "stockActual": 2, "stockMinimo": 10}
URGENTE = {"tipo": "CONDICION_URGENTE", "codigoCondicion": "HORNO", "descripcion": "Horno apagado"}


@pytest.fixture
def datos(client, keys):
    client.post("/notificaciones", json=STOCK, headers=headers(keys["inventario"]))
    client.post("/notificaciones", json=URGENTE, headers=headers(keys["fabricacion"]))


def test_listado_filtra_por_destino(client, keys, datos):
    r = client.get("/notificaciones/estado", headers=headers(keys["fabricacion"]))
    assert [n["tipo"] for n in r.json()["items"]] == ["CONDICION_URGENTE"]
    r = client.get("/notificaciones/estado", headers=headers(keys["inventario"]))
    assert [n["tipo"] for n in r.json()["items"]] == ["STOCK_BAJO_INSUMO"]


def test_admin_ve_todo(client, keys, datos):
    r = client.get("/notificaciones/estado", headers=headers(keys["notificaciones"]))
    assert r.json()["total"] == 2


def test_filtros(client, keys, datos):
    h = headers(keys["notificaciones"])
    assert client.get("/notificaciones/estado?productoId=7", headers=h).json()["total"] == 1
    assert client.get("/notificaciones/estado?tipo=CONDICION_URGENTE", headers=h).json()["total"] == 1
    assert client.get("/notificaciones/estado?estado=publicada", headers=h).json()["total"] == 2
    assert client.get("/notificaciones/estado?estado=entregada", headers=h).json()["total"] == 0
    assert client.get("/notificaciones/estado?estado=raro", headers=h).status_code == 422
    assert client.get("/notificaciones/estado?tamano=101", headers=h).status_code == 422


def test_detalle_y_leida(client, keys, datos):
    h = headers(keys["inventario"])
    id_ = client.get("/notificaciones/estado", headers=h).json()["items"][0]["id"]
    d = client.get(f"/notificaciones/estado/{id_}", headers=h).json()
    assert d["estado"] == "publicada"
    assert d["alerta"]["clave"] == "7"
    assert d["alerta"]["motivo_resolucion"] is None
    assert d["creada_at"].endswith("Z")
    assert client.patch(f"/notificaciones/estado/{id_}/leida", headers=h).json()["leida_at"]
    # fabricacion no puede ver la de inventario
    assert client.get(f"/notificaciones/estado/{id_}", headers=headers(keys["fabricacion"])).status_code == 404


def test_destinatarios_solo_tipos_propios(client, keys):
    h = headers(keys["fabricacion"])
    r = client.post(
        "/notificaciones/destinatarios",
        json={"nombre": "Ana", "email": "ana@x.com", "tipos": ["STOCK_BAJO_INSUMO"]},
        headers=h,
    )
    assert r.status_code == 403
    r = client.post(
        "/notificaciones/destinatarios",
        json={"nombre": "Ana", "email": "ana@x.com", "tipos": ["CONDICION_URGENTE"]},
        headers=h,
    )
    assert r.status_code == 201
    id_ = r.json()["id"]
    assert client.patch(f"/notificaciones/destinatarios/{id_}", json={"activo": False}, headers=h).status_code == 200
    lista = client.get("/notificaciones/destinatarios", headers=h).json()
    assert lista["items"][0]["activo"] is False
    assert client.get("/notificaciones/destinatarios", headers=headers(keys["inventario"])).json()["items"] == []


@pytest.mark.parametrize(
    "url",
    [
        "http://8.8.8.8/hook",
        "https://localhost/hook",
        "https://127.0.0.1/hook",
        "https://10.0.0.5/hook",
        "https://192.168.1.2/hook",
        "https://169.254.169.254/x",
    ],
)
def test_callback_rechaza_urls_no_publicas(client, keys, url):
    r = client.put("/notificaciones/callbacks", json={"url": url}, headers=headers(keys["inventario"]))
    assert r.status_code == 422


def test_callback_valido_devuelve_secreto(client, keys):
    r = client.put(
        "/notificaciones/callbacks", json={"url": "https://8.8.8.8/hook"}, headers=headers(keys["inventario"])
    )
    assert r.status_code == 201
    assert len(r.json()["secreto"]) == 64


def test_callback_conserva_el_secreto_hasta_regenerarlo(client, keys, session):
    h = headers(keys["inventario"])
    secreto = client.put("/notificaciones/callbacks", json={"url": "https://8.8.8.8/a"}, headers=h).json()["secreto"]
    r = client.put("/notificaciones/callbacks", json={"url": "https://8.8.8.8/b"}, headers=h)
    assert r.status_code == 200 and "secreto" not in r.json() and r.json()["url"] == "https://8.8.8.8/b"
    assert session.scalars(select(Callback)).one().secreto == secreto
    r = client.put("/notificaciones/callbacks", json={"url": "https://8.8.8.8/b", "regenerarSecreto": True}, headers=h)
    assert r.status_code == 200 and r.json()["secreto"] != secreto
    assert session.scalars(select(Callback)).one().secreto == r.json()["secreto"]


def test_consultar_callback_no_devuelve_el_secreto(client, keys):
    h = headers(keys["inventario"])
    assert client.get("/notificaciones/callbacks", headers=h).status_code == 404
    client.put("/notificaciones/callbacks", json={"url": "https://8.8.8.8/hook"}, headers=h)
    r = client.get("/notificaciones/callbacks", headers=h)
    assert r.status_code == 200
    assert r.json()["url"] == "https://8.8.8.8/hook" and r.json()["activo"] is True and "secreto" not in r.json()
    assert client.get("/notificaciones/callbacks", headers=headers(keys["notificaciones"])).status_code == 403


def test_callback_desactivado_no_recibe_hasta_reactivarlo(client, keys, publisher, mailer, http_mock, session):
    h = headers(keys["inventario"])
    client.put("/notificaciones/callbacks", json={"url": "https://8.8.8.8/hook"}, headers=h)
    assert client.patch("/notificaciones/callbacks", json={"activo": False}, headers=h).json()["activo"] is False
    client.post("/notificaciones", json=STOCK, headers=h)
    n = session.scalars(select(Notificacion)).one()
    n.proximo_intento_entrega_at = ahora() - timedelta(seconds=1)
    session.commit()
    assert ejecutar_ciclo(session, publisher, mailer, http_mock.cliente)["webhooks_entregados"] == 0
    assert http_mock.peticiones == []
    client.patch("/notificaciones/callbacks", json={"activo": True}, headers=h)
    assert ejecutar_ciclo(session, publisher, mailer, http_mock.cliente)["webhooks_entregados"] == 1


def test_destinatario_con_email_invalido_da_422(client, keys):
    r = client.post(
        "/notificaciones/destinatarios",
        json={"nombre": "Ana", "email": "no-es-email", "tipos": []},
        headers=headers(keys["inventario"]),
    )
    assert r.status_code == 422


def nuevo_destinatario(client, h, email="ana@x.com", tipos=("STOCK_BAJO_INSUMO",)):
    return client.post(
        "/notificaciones/destinatarios", json={"nombre": "Ana", "email": email, "tipos": list(tipos)}, headers=h
    )


def test_patch_destinatario_da_de_baja_y_reactiva(client, keys):
    h = headers(keys["inventario"])
    d = nuevo_destinatario(client, h).json()
    url = f"/notificaciones/destinatarios/{d['id']}"
    assert client.patch(url, json={"activo": False}, headers=h).json()["activo"] is False
    r = client.patch(url, json={"activo": True, "nombre": "Ana Maria"}, headers=h)
    assert r.json()["activo"] is True and r.json()["nombre"] == "Ana Maria"
    assert r.json()["tipos"] == ["STOCK_BAJO_INSUMO"]


def test_patch_destinatario_valida_los_datos(client, keys):
    h = headers(keys["inventario"])
    url = f"/notificaciones/destinatarios/{nuevo_destinatario(client, h).json()['id']}"
    assert client.patch(url, json={}, headers=h).status_code == 422
    assert client.patch(url, json={"nombre": ""}, headers=h).status_code == 422
    assert client.patch(url, json={"tipos": []}, headers=h).status_code == 422
    assert client.patch(url, json={"tipos": ["CONDICION_URGENTE"]}, headers=h).status_code == 403
    assert client.patch("/notificaciones/destinatarios/9999", json={"activo": False}, headers=h).status_code == 404
    # otro equipo no lo ve
    assert client.patch(url, json={"activo": False}, headers=headers(keys["fabricacion"])).status_code == 404


def test_correo_repetido_da_409_con_el_id_existente(client, keys):
    h = headers(keys["inventario"])
    d = nuevo_destinatario(client, h).json()
    r = nuevo_destinatario(client, h, email="ANA@x.com")
    assert r.status_code == 409 and r.json()["detail"]["id"] == d["id"]
    client.patch(f"/notificaciones/destinatarios/{d['id']}", json={"activo": False}, headers=h)
    assert nuevo_destinatario(client, h).status_code == 201


def test_listado_de_destinatarios_pagina_y_filtra(client, keys):
    h = headers(keys["inventario"])
    for i in range(3):
        nuevo_destinatario(client, h, email=f"p{i}@x.com")
    client.patch("/notificaciones/destinatarios/1", json={"activo": False}, headers=h)
    r = client.get("/notificaciones/destinatarios?tamano=2", headers=h).json()
    assert (r["total"], r["totalPaginas"], r["pagina"], len(r["items"])) == (3, 2, 1, 2)
    assert [d["email"] for d in r["items"]] == ["p2@x.com", "p1@x.com"]
    assert client.get("/notificaciones/destinatarios?activo=false", headers=h).json()["total"] == 1
    assert client.get("/notificaciones/destinatarios?tamano=101", headers=h).status_code == 422
    assert client.get("/notificaciones/destinatarios", headers=headers(keys["notificaciones"])).json()["total"] == 3


def test_destinatario_sin_tipos_da_422(client, keys):
    assert nuevo_destinatario(client, headers(keys["inventario"]), tipos=()).status_code == 422


def test_admin_puede_marcar_leida(client, keys, datos):
    h = headers(keys["notificaciones"])
    id_ = client.get("/notificaciones/estado", headers=h).json()["items"][0]["id"]
    r = client.patch(f"/notificaciones/estado/{id_}/leida", headers=h)
    assert r.status_code == 200 and r.json()["leida_at"]


def test_listado_trae_mensaje_calculado_y_total_de_paginas(client, keys, datos):
    r = client.get("/notificaciones/estado?tamano=1", headers=headers(keys["notificaciones"])).json()
    assert r["totalPaginas"] == 2
    todos = client.get("/notificaciones/estado", headers=headers(keys["notificaciones"])).json()["items"]
    mensajes = {n["tipo"]: n["mensaje"] for n in todos}
    assert mensajes["STOCK_BAJO_INSUMO"] == "Stock bajo de Harina (7): 2 unidades, mínimo 10"
    assert mensajes["CONDICION_URGENTE"] == "Condición urgente HORNO: Horno apagado"


def test_callback_puerto_raro_rechazado(client, keys):
    r = client.put(
        "/notificaciones/callbacks", json={"url": "https://8.8.8.8:6379/x"}, headers=headers(keys["inventario"])
    )
    assert r.status_code == 422
