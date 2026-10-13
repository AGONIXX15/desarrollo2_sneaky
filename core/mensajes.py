"""Texto legible de una notificación. Se calcula al consultarla, no se guarda."""

LIMITE = 200


def mensaje_de(tipo: str, payload: dict) -> str:
    if tipo in ("STOCK_BAJO_INSUMO", "STOCK_BAJO_PRODUCTO"):
        texto = (
            f"Stock bajo de {payload.get('nombre')} ({payload.get('productoId')}): "
            f"{payload.get('stockActual')} unidades, mínimo {payload.get('stockMinimo')}"
        )
    elif tipo == "CONDICION_URGENTE":
        texto = f"Condición urgente {payload.get('codigoCondicion')}: {payload.get('descripcion')}"
    elif tipo == "ACUMULACION_PEDIDOS":
        texto = f"Acumulación de pedidos: {payload.get('cantidadPedidos')} pedidos (umbral {payload.get('umbral')})"
    else:
        texto = tipo.replace("_", " ").capitalize()
    return texto[:LIMITE]
