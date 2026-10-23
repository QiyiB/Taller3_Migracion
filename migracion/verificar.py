
import random
import sys
from decimal import Decimal
from pathlib import Path

import pyodbc
from bson import json_util
from pymongo import MongoClient

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))
import config  # noqa: E402

EVIDENCIAS = RAIZ / "evidencias"
resultados = []  # (sección, control, valor SQL, valor Mongo, ok)


def registrar(seccion, control, sql, mongo):
    ok = sql == mongo
    resultados.append((seccion, control, sql, mongo, ok))


def escalar(cur, sql):
    cur.execute(sql)
    return cur.fetchone()[0]


def suma_mongo(coleccion, pipeline):
    r = list(coleccion.aggregate(pipeline + [{"$group": {"_id": None, "v": {"$sum": "$v"}}}]))
    valor = r[0]["v"] if r else 0
    return valor.to_decimal() if hasattr(valor, "to_decimal") else valor


def dec(v):
    if v is None:
        return None
    return v.to_decimal() if hasattr(v, "to_decimal") else Decimal(v)


def main():
    cur = pyodbc.connect(config.SQLSERVER_CONN).cursor()
    db = MongoClient(config.MONGO_URI)[config.MONGO_DB]

    # ---------------- 1. Conteos
    s = "1. Conteos"
    for tabla, col in [("Categorias", "categorias"), ("Proveedores", "proveedores"), ("Productos", "productos"),
                       ("Clientes", "clientes"), ("Pedidos", "pedidos"), ("Resenas", "resenas")]:
        registrar(s, f"{tabla} -> {col}", escalar(cur, f"SELECT COUNT(*) FROM dbo.{tabla}"),
                  db[col].count_documents({}))
    registrar(s, "Direcciones -> clientes.direcciones[]", escalar(cur, "SELECT COUNT(*) FROM dbo.Direcciones"),
              suma_mongo(db.clientes, [{"$project": {"v": {"$size": "$direcciones"}}}]))
    registrar(s, "DetallePedido -> pedidos.items[]", escalar(cur, "SELECT COUNT(*) FROM dbo.DetallePedido"),
              suma_mongo(db.pedidos, [{"$project": {"v": {"$size": "$items"}}}]))
    registrar(s, "Pagos -> pedidos.pagos[]", escalar(cur, "SELECT COUNT(*) FROM dbo.Pagos"),
              suma_mongo(db.pedidos, [{"$project": {"v": {"$size": "$pagos"}}}]))
    registrar(s, "Envios -> pedidos.envio", escalar(cur, "SELECT COUNT(*) FROM dbo.Envios"),
              db.pedidos.count_documents({"envio": {"$exists": True}}))
    for estado in ["Pendiente", "Pagado", "Enviado", "Entregado", "Cancelado"]:
        registrar(s, f"Pedidos en estado {estado}",
                  escalar(cur, f"SELECT COUNT(*) FROM dbo.Pedidos WHERE Estado = '{estado}'"),
                  db.pedidos.count_documents({"estado": estado}))

    # ---------------- 2. Sumas de control
    s = "2. Sumas de control"
    registrar(s, "SUM(Pedidos.Total) = SUM(totales.total)",
              escalar(cur, "SELECT SUM(Total) FROM dbo.Pedidos"),
              suma_mongo(db.pedidos, [{"$project": {"v": "$totales.total"}}]))
    registrar(s, "SUM(DetallePedido.Subtotal) = SUM(items.subtotal)",
              escalar(cur, "SELECT SUM(Subtotal) FROM dbo.DetallePedido"),
              suma_mongo(db.pedidos, [{"$unwind": "$items"}, {"$project": {"v": "$items.subtotal"}}]))
    registrar(s, "SUM(DetallePedido.Cantidad) = SUM(items.cantidad)",
              escalar(cur, "SELECT SUM(Cantidad) FROM dbo.DetallePedido"),
              suma_mongo(db.pedidos, [{"$unwind": "$items"}, {"$project": {"v": "$items.cantidad"}}]))
    registrar(s, "SUM(Pagos.Monto) aprobados = SUM(pagos.monto) aprobados",
              escalar(cur, "SELECT SUM(Monto) FROM dbo.Pagos WHERE Estado = 'Aprobado'"),
              suma_mongo(db.pedidos, [{"$unwind": "$pagos"}, {"$match": {"pagos.estado": "Aprobado"}},
                                      {"$project": {"v": "$pagos.monto"}}]))
    registrar(s, "SUM(Productos.Stock) = SUM(stock)", escalar(cur, "SELECT SUM(Stock) FROM dbo.Productos"),
              suma_mongo(db.productos, [{"$project": {"v": "$stock"}}]))
    registrar(s, "SUM(Resenas.Calificacion) = SUM(calificacion)",
              escalar(cur, "SELECT SUM(CAST(Calificacion AS INT)) FROM dbo.Resenas"),
              suma_mongo(db.resenas, [{"$project": {"v": "$calificacion"}}]))

    # ---------------- 3. Integridad referencial (debe haber 0 huérfanos)
    s = "3. Integridad referencial (huérfanos)"

    def huerfanos(col, campo, destino, desenrollar=None):
        p = [{"$unwind": desenrollar}] if desenrollar else []
        p += [{"$lookup": {"from": destino, "localField": campo, "foreignField": "_id", "as": "ref"}},
              {"$match": {"ref": {"$size": 0}}}, {"$count": "n"}]
        r = list(db[col].aggregate(p))
        return r[0]["n"] if r else 0

    registrar(s, "pedidos.cliente_id -> clientes", 0, huerfanos("pedidos", "cliente_id", "clientes"))
    registrar(s, "pedidos.items.producto_id -> productos", 0,
              huerfanos("pedidos", "items.producto_id", "productos", "$items"))
    registrar(s, "productos.categoria_id -> categorias", 0, huerfanos("productos", "categoria_id", "categorias"))
    registrar(s, "productos.proveedor_id -> proveedores", 0, huerfanos("productos", "proveedor_id", "proveedores"))
    registrar(s, "resenas.producto_id -> productos", 0, huerfanos("resenas", "producto_id", "productos"))
    registrar(s, "resenas.cliente_id -> clientes", 0, huerfanos("resenas", "cliente_id", "clientes"))

    # ---------------- 4. Estructuras embebidas
    s = "4. Estructuras embebidas"
    registrar(s, "Pedidos con SUM(items.subtotal) <> totales.subtotal", 0, db.pedidos.count_documents(
        {"$expr": {"$ne": [{"$sum": "$items.subtotal"}, "$totales.subtotal"]}}))
    registrar(s, "Pedidos con total <> subtotal + costo_envio", 0, db.pedidos.count_documents(
        {"$expr": {"$ne": ["$totales.total", {"$add": ["$totales.subtotal", "$totales.costo_envio"]}]}}))
    dir_ajena = list(db.pedidos.aggregate([
        {"$lookup": {"from": "clientes", "localField": "cliente_id", "foreignField": "_id", "as": "c"}},
        {"$unwind": "$c"},
        {"$match": {"$expr": {"$not": {"$in": ["$direccion_envio.direccion_id", "$c.direcciones.direccion_id"]}}}},
        {"$count": "n"}]))
    registrar(s, "Pedidos cuya dirección no pertenece al cliente", 0, dir_ajena[0]["n"] if dir_ajena else 0)
    registrar(s, "Clientes con != 1 dirección principal", 0, db.clientes.count_documents(
        {"$expr": {"$ne": [{"$size": {"$filter": {"input": "$direcciones", "cond": "$$this.es_principal"}}}, 1]}}))
    registrar(s, "Pedidos 'Entregado' sin envio.fecha_entrega", 0,
              db.pedidos.count_documents({"estado": "Entregado", "envio.fecha_entrega": {"$exists": False}}))
    calif = list(db.productos.aggregate([
        {"$lookup": {"from": "resenas", "localField": "_id", "foreignField": "producto_id", "as": "r"}},
        {"$match": {"$expr": {"$ne": ["$calificacion.total_resenas", {"$size": "$r"}]}}}, {"$count": "n"}]))
    registrar(s, "productos.calificacion.total_resenas desactualizado", 0, calif[0]["n"] if calif else 0)
    registrar(s, "Documentos de pedidos que no cumplen el $jsonSchema", 0, db.pedidos.count_documents(
        {"$nor": [db.get_collection("pedidos").options()["validator"]]}))

    # ---------------- 5. Muestra campo a campo
    ids = sorted(random.Random(7).sample(range(1, escalar(cur, "SELECT MAX(PedidoID) FROM dbo.Pedidos") + 1), 5))
    muestras = []
    for pid in ids:
        cur.execute("""SELECT p.ClienteID, p.Estado, p.FechaPedido, p.Total, d.Ciudad,
                              (SELECT COUNT(*) FROM dbo.DetallePedido WHERE PedidoID = p.PedidoID),
                              (SELECT COUNT(*) FROM dbo.Pagos WHERE PedidoID = p.PedidoID),
                              (SELECT NumeroGuia FROM dbo.Envios WHERE PedidoID = p.PedidoID)
                       FROM dbo.Pedidos p JOIN dbo.Direcciones d ON d.DireccionID = p.DireccionID
                       WHERE p.PedidoID = ?""", pid)
        f = cur.fetchone()
        doc = db.pedidos.find_one({"_id": pid})
        sql_vals = [f[0], f[1], f[2], Decimal(f[3]), f[4], f[5], f[6], f[7]]
        mongo_vals = [doc["cliente_id"], doc["estado"], doc["fecha"], dec(doc["totales"]["total"]),
                      doc["direccion_envio"]["ciudad"], len(doc["items"]), len(doc["pagos"]),
                      doc.get("envio", {}).get("numero_guia")]
        campos = ["cliente", "estado", "fecha", "total", "ciudad envío", "# líneas", "# pagos", "guía"]
        for c, a, b in zip(campos, sql_vals, mongo_vals):
            registrar("5. Muestra de pedidos", f"Pedido {pid} - {c}", a, b)
        # líneas del pedido, una a una
        cur.execute("""SELECT ProductoID, Cantidad, PrecioUnitario, Subtotal FROM dbo.DetallePedido
                       WHERE PedidoID = ? ORDER BY DetalleID""", pid)
        sql_items = [(r[0], r[1], Decimal(r[2]), Decimal(r[3])) for r in cur.fetchall()]
        mongo_items = [(i["producto_id"], i["cantidad"], dec(i["precio_unitario"]), dec(i["subtotal"]))
                       for i in doc["items"]]
        registrar("5. Muestra de pedidos", f"Pedido {pid} - líneas idénticas", True, sql_items == mongo_items)
        muestras.append(doc)

    escribir_reporte(db, muestras)
    fallos = [r for r in resultados if not r[4]]
    print(f"{len(resultados) - len(fallos)}/{len(resultados)} controles OK")
    for r in fallos:
        print("FALLA:", r)
    return 1 if fallos else 0


def fmt(v):
    if isinstance(v, Decimal):
        return f"{v:,.2f}"
    return "" if v is None else str(v)


def escribir_reporte(db, muestras):
    EVIDENCIAS.mkdir(exist_ok=True)
    (EVIDENCIAS / "ejemplos").mkdir(exist_ok=True)
    for col in ["categorias", "proveedores", "productos", "clientes", "resenas"]:
        doc = db[col].find_one({"_id": 1})
        (EVIDENCIAS / "ejemplos" / f"{col}.json").write_text(
            json_util.dumps(doc, indent=2, ensure_ascii=False, json_options=json_util.RELAXED_JSON_OPTIONS),
            encoding="utf-8")
    # pedido de ejemplo: uno entregado con más de un pago (muestra todos los arrays)
    ejemplo = db.pedidos.find_one({"estado": "Entregado", "pagos.1": {"$exists": True}, "items.2": {"$exists": True}})
    (EVIDENCIAS / "ejemplos" / "pedidos.json").write_text(
        json_util.dumps(ejemplo, indent=2, ensure_ascii=False, json_options=json_util.RELAXED_JSON_OPTIONS),
        encoding="utf-8")

    lineas = ["# Verificación de la migración SQL Server → MongoDB", "",
              "Generado por `python migracion/verificar.py`.", ""]
    ok_total = sum(r[4] for r in resultados)
    lineas += [f"**Resultado: {ok_total}/{len(resultados)} controles correctos.**", ""]
    seccion_actual = None
    for seccion, control, a, b, ok in resultados:
        if seccion != seccion_actual:
            seccion_actual = seccion
            lineas += ["", f"## {seccion}", "", "| Control | SQL Server / esperado | MongoDB | OK |",
                       "|---|---:|---:|:-:|"]
        lineas.append(f"| {control} | {fmt(a)} | {fmt(b)} | {'✅' if ok else '❌'} |")
    lineas += ["", "## Colecciones e índices en MongoDB", "", "| Colección | Documentos | Índices |", "|---|---:|---|"]
    for col in sorted(db.list_collection_names()):
        indices = ", ".join(i["name"] for i in db[col].list_indexes())
        lineas.append(f"| {col} | {db[col].count_documents({})} | {indices} |")
    lineas += ["", f"Documentos de ejemplo de cada colección: `evidencias/ejemplos/`. "
                   f"Pedidos comparados en la muestra: {', '.join(str(m['_id']) for m in muestras)}.", ""]
    (EVIDENCIAS / "03_verificacion_migracion.md").write_text("\n".join(lineas), encoding="utf-8")


if __name__ == "__main__":
    sys.exit(main())
