
import sys
import time
from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import pyodbc
from bson.decimal128 import Decimal128
from pymongo import ASCENDING, DESCENDING, MongoClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import config  # noqa: E402

LOTE = 1000



def dinero(valor):
    """DECIMAL de SQL Server -> Decimal128 (conserva la precisión exacta, sin errores de float)."""
    return None if valor is None else Decimal128(Decimal(valor))


def fecha(valor):
    """MongoDB solo maneja fecha-hora: DATE se convierte a medianoche."""
    if valor is None or isinstance(valor, datetime):
        return valor
    if isinstance(valor, date):
        return datetime(valor.year, valor.month, valor.day)
    return valor


def sin_nulos(doc: dict) -> dict:
    """En un modelo documental un campo ausente expresa 'no aplica'; no se guardan NULL."""
    return {k: v for k, v in doc.items() if v is not None}


def leer(cursor, sql):
    cursor.execute(sql)
    columnas = [c[0] for c in cursor.description]
    return [dict(zip(columnas, fila)) for fila in cursor.fetchall()]


def agrupar(filas, llave):
    grupos = defaultdict(list)
    for fila in filas:
        grupos[fila[llave]].append(fila)
    return grupos


# ---------------------------------------------------------------- extracción
def extraer():
    con = pyodbc.connect(config.SQLSERVER_CONN)
    cur = con.cursor()
    t = {
        "categorias": leer(cur, "SELECT * FROM dbo.Categorias ORDER BY CategoriaID"),
        "proveedores": leer(cur, "SELECT * FROM dbo.Proveedores ORDER BY ProveedorID"),
        "productos": leer(cur, "SELECT * FROM dbo.Productos ORDER BY ProductoID"),
        "clientes": leer(cur, "SELECT * FROM dbo.Clientes ORDER BY ClienteID"),
        "direcciones": leer(cur, "SELECT * FROM dbo.Direcciones ORDER BY ClienteID, DireccionID"),
        "pedidos": leer(cur, "SELECT * FROM dbo.Pedidos ORDER BY PedidoID"),
        # el JOIN trae nombre y SKU del producto para guardarlos como "foto" en la línea del pedido
        "detalle": leer(cur, """SELECT d.*, p.SKU, p.Nombre
                                FROM dbo.DetallePedido d JOIN dbo.Productos p ON p.ProductoID = d.ProductoID
                                ORDER BY d.PedidoID, d.DetalleID"""),
        "pagos": leer(cur, "SELECT * FROM dbo.Pagos ORDER BY PedidoID, FechaPago, PagoID"),
        "envios": leer(cur, "SELECT * FROM dbo.Envios"),
        "resenas": leer(cur, "SELECT * FROM dbo.Resenas ORDER BY ResenaID"),
    }
    con.close()
    return t

def transformar(t):
    docs = {}

    docs["categorias"] = [
        sin_nulos({"_id": c["CategoriaID"], "nombre": c["Nombre"], "descripcion": c["Descripcion"]})
        for c in t["categorias"]
    ]

    docs["proveedores"] = [
        {
            "_id": p["ProveedorID"],
            "razon_social": p["RazonSocial"],
            "nit": p["NIT"],
            "contacto": sin_nulos({"email": p["Email"], "telefono": p["Telefono"]}),
            "ubicacion": {"ciudad": p["Ciudad"], "pais": p["Pais"]},
        }
        for p in t["proveedores"]
    ]

    # Patrón "computed": promedio y número de reseñas precalculados en el producto
    resenas_por_producto = agrupar(t["resenas"], "ProductoID")
    docs["productos"] = []
    for p in t["productos"]:
        notas = [r["Calificacion"] for r in resenas_por_producto.get(p["ProductoID"], [])]
        docs["productos"].append(sin_nulos({
            "_id": p["ProductoID"],
            "sku": p["SKU"],
            "nombre": p["Nombre"],
            "descripcion": p["Descripcion"],
            "precio": dinero(p["Precio"]),
            "costo": dinero(p["Costo"]),
            "stock": p["Stock"],
            "activo": bool(p["Activo"]),
            "fecha_creacion": fecha(p["FechaCreacion"]),
            "categoria_id": p["CategoriaID"],    # REFERENCIA -> categorias
            "proveedor_id": p["ProveedorID"],    # REFERENCIA -> proveedores
            "calificacion": {
                "promedio": round(sum(notas) / len(notas), 2) if notas else None,
                "total_resenas": len(notas),
            } if notas else {"total_resenas": 0},
        }))

    # Clientes con sus direcciones EMBEBIDAS (relación 1:N acotada, siempre se leen juntas)
    direcciones_por_cliente = agrupar(t["direcciones"], "ClienteID")
    direccion_por_id = {d["DireccionID"]: d for d in t["direcciones"]}
    docs["clientes"] = []
    for c in t["clientes"]:
        docs["clientes"].append(sin_nulos({
            "_id": c["ClienteID"],
            "nombres": c["Nombres"],
            "apellidos": c["Apellidos"],
            "email": c["Email"],
            "telefono": c["Telefono"],
            "fecha_nacimiento": fecha(c["FechaNacimiento"]),
            "fecha_registro": c["FechaRegistro"],
            "segmento": c["Segmento"],
            "direcciones": [
                sin_nulos({
                    "direccion_id": d["DireccionID"],
                    "alias": d["Alias"],
                    "linea": d["Linea"],
                    "ciudad": d["Ciudad"],
                    "departamento": d["Departamento"],
                    "codigo_postal": d["CodigoPostal"],
                    "es_principal": bool(d["EsPrincipal"]),
                })
                for d in direcciones_por_cliente.get(c["ClienteID"], [])
            ],
        }))

    # Pedidos: 4 tablas (Pedidos, DetallePedido, Pagos, Envios) + copia de la dirección
    detalle_por_pedido = agrupar(t["detalle"], "PedidoID")
    pagos_por_pedido = agrupar(t["pagos"], "PedidoID")
    envio_por_pedido = {e["PedidoID"]: e for e in t["envios"]}
    docs["pedidos"] = []
    for p in t["pedidos"]:
        d = direccion_por_id[p["DireccionID"]]
        e = envio_por_pedido.get(p["PedidoID"])
        docs["pedidos"].append(sin_nulos({
            "_id": p["PedidoID"],
            "cliente_id": p["ClienteID"],         # REFERENCIA -> clientes
            "fecha": p["FechaPedido"],
            "estado": p["Estado"],
            # Copia (snapshot) de la dirección al momento de la compra: si el cliente
            # la edita después, el pedido conserva a dónde se envió realmente.
            "direccion_envio": {
                "direccion_id": d["DireccionID"],
                "linea": d["Linea"],
                "ciudad": d["Ciudad"],
                "departamento": d["Departamento"],
                "codigo_postal": d["CodigoPostal"],
            },
            "items": [
                {
                    "producto_id": it["ProductoID"],   # REFERENCIA -> productos
                    "sku": it["SKU"],                   # snapshot para mostrar el pedido sin $lookup
                    "nombre": it["Nombre"],
                    "cantidad": it["Cantidad"],
                    "precio_unitario": dinero(it["PrecioUnitario"]),
                    "descuento_pct": dinero(it["Descuento"]),
                    "subtotal": dinero(it["Subtotal"]),
                }
                for it in detalle_por_pedido[p["PedidoID"]]
            ],
            "totales": {
                "subtotal": dinero(p["Subtotal"]),
                "costo_envio": dinero(p["CostoEnvio"]),
                "total": dinero(p["Total"]),
            },
            "pagos": [
                {
                    "pago_id": g["PagoID"],
                    "metodo": g["Metodo"],
                    "estado": g["Estado"],
                    "monto": dinero(g["Monto"]),
                    "fecha": g["FechaPago"],
                    "referencia": g["Referencia"],
                }
                for g in pagos_por_pedido.get(p["PedidoID"], [])
            ],
            "envio": sin_nulos({
                "envio_id": e["EnvioID"],
                "transportadora": e["Transportadora"],
                "numero_guia": e["NumeroGuia"],
                "fecha_despacho": e["FechaDespacho"],
                "fecha_entrega_estimada": e["FechaEntregaEstimada"],
                "fecha_entrega": e["FechaEntrega"],
                "estado": e["Estado"],
            }) if e else None,
        }))

    docs["resenas"] = [
        sin_nulos({
            "_id": r["ResenaID"],
            "producto_id": r["ProductoID"],      # REFERENCIA -> productos
            "cliente_id": r["ClienteID"],        # REFERENCIA -> clientes
            "calificacion": r["Calificacion"],
            "comentario": r["Comentario"],
            "fecha": r["Fecha"],
        })
        for r in t["resenas"]
    ]
    return docs


# ---------------------------------------------------------------- carga
VALIDADOR_PEDIDOS = {
    "$jsonSchema": {
        "bsonType": "object",
        "required": ["_id", "cliente_id", "fecha", "estado", "direccion_envio", "items", "totales", "pagos"],
        "properties": {
            "cliente_id": {"bsonType": "int"},
            "fecha": {"bsonType": "date"},
            "estado": {"enum": ["Pendiente", "Pagado", "Enviado", "Entregado", "Cancelado"]},
            "items": {
                "bsonType": "array", "minItems": 1,
                "items": {
                    "bsonType": "object",
                    "required": ["producto_id", "cantidad", "precio_unitario", "subtotal"],
                    "properties": {"cantidad": {"bsonType": "int", "minimum": 1}},
                },
            },
            "pagos": {"bsonType": "array"},
            "totales": {"bsonType": "object", "required": ["subtotal", "costo_envio", "total"]},
        },
    }
}

VALIDADOR_CLIENTES = {
    "$jsonSchema": {
        "bsonType": "object",
        "required": ["_id", "nombres", "apellidos", "email", "segmento", "direcciones"],
        "properties": {
            "email": {"bsonType": "string"},
            "segmento": {"enum": ["Estandar", "Plata", "Oro"]},
            "direcciones": {"bsonType": "array", "minItems": 1},
        },
    }
}

INDICES = {
    "productos": [([("sku", ASCENDING)], {"unique": True}), ([("categoria_id", ASCENDING)], {}),
                  ([("proveedor_id", ASCENDING)], {}), ([("stock", ASCENDING)], {})],
    "clientes": [([("email", ASCENDING)], {"unique": True})],
    "pedidos": [([("cliente_id", ASCENDING), ("fecha", DESCENDING)], {}), ([("fecha", ASCENDING)], {}),
                ([("estado", ASCENDING)], {}), ([("items.producto_id", ASCENDING)], {}),
                ([("envio.transportadora", ASCENDING)], {})],
    "resenas": [([("producto_id", ASCENDING), ("cliente_id", ASCENDING)], {"unique": True}),
                ([("cliente_id", ASCENDING)], {})],
}


def cargar(docs):
    cliente = MongoClient(config.MONGO_URI)
    db = cliente[config.MONGO_DB]
    for nombre, lista in docs.items():
        db.drop_collection(nombre)  # migración idempotente: se puede ejecutar varias veces
        validador = {"pedidos": VALIDADOR_PEDIDOS, "clientes": VALIDADOR_CLIENTES}.get(nombre)
        if validador:
            db.create_collection(nombre, validator=validador, validationLevel="strict")
        for i in range(0, len(lista), LOTE):
            db[nombre].insert_many(lista[i:i + LOTE], ordered=True)
        for llaves, opciones in INDICES.get(nombre, []):
            db[nombre].create_index(llaves, **opciones)
        print(f"  {nombre:<12} {db[nombre].count_documents({}):>6} documentos")
    cliente.close()


if __name__ == "__main__":
    inicio = time.perf_counter()
    print("1/3 Extrayendo datos de SQL Server...")
    tablas = extraer()
    for k, v in tablas.items():
        print(f"  {k:<12} {len(v):>6} filas")
    print("2/3 Transformando al modelo documental...")
    documentos = transformar(tablas)
    print("3/3 Cargando en MongoDB...")
    cargar(documentos)
    print(f"Migración terminada en {time.perf_counter() - inicio:.1f} s")
