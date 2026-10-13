import pytest

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
    assert client.delete(f"/notificaciones/destinatarios/{id_}", headers=h).status_code == 204
    lista = client.get("/notificaciones/destinatarios", headers=h).json()
    assert lista[0]["activo"] is False
    assert client.get("/notificaciones/destinatarios", headers=headers(keys["inventario"])).json() == []


@pytest.mark.parametrize(
    "url",
    ["http://8.8.8.8/hook", "https://localhost/hook", "https://127.0.0.1/hook",
     "https://10.0.0.5/hook", "https://192.168.1.2/hook", "https://169.254.169.254/x"],
)
def test_callback_rechaza_urls_no_publicas(client, keys, url):
    r = client.put("/notificaciones/callbacks", json={"url": url}, headers=headers(keys["inventario"]))
    assert r.status_code == 422


def test_callback_valido_devuelve_secreto(client, keys):
    r = client.put(
        "/notificaciones/callbacks", json={"url": "https://8.8.8.8/hook"}, headers=headers(keys["inventario"])
    )
    assert r.status_code == 200
    assert len(r.json()["secreto"]) == 64
