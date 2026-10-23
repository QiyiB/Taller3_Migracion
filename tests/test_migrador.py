"""
Pruebas del migrador genérico.

  * PruebaPropuesta: reglas de Embedding/Referencing sobre un esquema armado en memoria
    (no necesita bases de datos).
  * PruebaIntegracion: migra TiendaOnline completa a la base 'tienda_online_prueba' y exige
    que todos los controles de verificación pasen (se omite si SQL Server o MongoDB no están).

Uso:  python -m unittest discover -s tests -v
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from migrador.esquema import Columna, Esquema, LlaveForanea, Tabla  # noqa: E402
from migrador.nombres import singular, snake  # noqa: E402
from migrador.propuesta import ARRAY, COLECCION, SUBDOCUMENTO, cambiar, proponer  # noqa: E402


def tabla(nombre, pk, filas=10, unicos=()):
    t = Tabla("dbo", nombre, [Columna(pk, "int", False, True, False)], [pk], [[pk], *unicos], filas)
    return t


def fk(nombre, hija, col_h, padre, col_p, unica=False, max_hijos=3):
    return LlaveForanea(nombre, f"dbo.{hija}", [col_h], f"dbo.{padre}", [col_p], unica, max_hijos, 1.5, 0)


def esquema_tienda() -> Esquema:
    e = Esquema("TiendaOnline")
    for n, pk in [("Categorias", "CategoriaID"), ("Proveedores", "ProveedorID"), ("Productos", "ProductoID"),
                  ("Clientes", "ClienteID"), ("Direcciones", "DireccionID"), ("Pedidos", "PedidoID"),
                  ("DetallePedido", "DetalleID"), ("Pagos", "PagoID"), ("Envios", "EnvioID"),
                  ("Resenas", "ResenaID")]:
        e.tablas[f"dbo.{n}"] = tabla(n, pk)
    e.fks = [fk("fk1", "Productos", "CategoriaID", "Categorias", "CategoriaID", max_hijos=25),
             fk("fk2", "Productos", "ProveedorID", "Proveedores", "ProveedorID", max_hijos=25),
             fk("fk3", "Direcciones", "ClienteID", "Clientes", "ClienteID"),
             fk("fk4", "Pedidos", "ClienteID", "Clientes", "ClienteID", max_hijos=30),
             fk("fk5", "Pedidos", "DireccionID", "Direcciones", "DireccionID", max_hijos=30),
             fk("fk6", "DetallePedido", "PedidoID", "Pedidos", "PedidoID", max_hijos=5),
             fk("fk7", "DetallePedido", "ProductoID", "Productos", "ProductoID", max_hijos=200),
             fk("fk8", "Pagos", "PedidoID", "Pedidos", "PedidoID", max_hijos=2),
             fk("fk9", "Envios", "PedidoID", "Pedidos", "PedidoID", unica=True, max_hijos=1),
             fk("fk10", "Resenas", "ProductoID", "Productos", "ProductoID", max_hijos=20),
             fk("fk11", "Resenas", "ClienteID", "Clientes", "ClienteID", max_hijos=8)]
    return e


class PruebaNombres(unittest.TestCase):
    def test_snake(self):
        self.assertEqual(snake("FechaPedido"), "fecha_pedido")
        self.assertEqual(snake("ClienteID"), "cliente_id")
        self.assertEqual(snake("SKU"), "sku")
        self.assertEqual(snake("DetallePedido"), "detalle_pedido")

    def test_singular(self):
        self.assertEqual(singular("envios"), "envio")
        self.assertEqual(singular("direcciones"), "direccion")
        self.assertEqual(singular("addresses"), "address")


class PruebaPropuesta(unittest.TestCase):
    def setUp(self):
        self.e = esquema_tienda()
        self.plan = proponer(self.e)

    def modo(self, t):
        return self.plan.decisiones[f"dbo.{t}"].modo

    def test_tablas_independientes_y_referenciadas_son_colecciones(self):
        for t in ["Categorias", "Proveedores", "Productos", "Clientes", "Pedidos", "Direcciones"]:
            self.assertEqual(self.modo(t), COLECCION, t)

    def test_detalle_y_pagos_se_embeben_como_array_en_pedidos(self):
        for t in ["DetallePedido", "Pagos"]:
            d = self.plan.decisiones[f"dbo.{t}"]
            self.assertEqual(d.modo, ARRAY, t)
            self.assertEqual(self.e.fk(d.fk).padre, "dbo.Pedidos")

    def test_envio_es_subdocumento(self):
        self.assertEqual(self.modo("Envios"), SUBDOCUMENTO)
        self.assertEqual(self.plan.decisiones["dbo.Envios"].nombre, "envio")

    def test_resenas_sin_dueno_claro_es_coleccion(self):
        self.assertEqual(self.modo("Resenas"), COLECCION)

    def test_muchos_hijos_por_padre_no_se_embebe(self):
        self.e.fk("fk8").max_hijos = 10_000
        self.assertEqual(proponer(self.e).decisiones["dbo.Pagos"].modo, COLECCION)

    def test_ruta_anidada_y_ciclo(self):
        cambiar(self.plan, self.e, "dbo.Pedidos", ARRAY, "fk4")       # pedidos dentro de clientes
        self.assertEqual(self.plan.ruta(self.e, "dbo.Envios"), [("pedidos", True), ("envio", False)])
        self.assertEqual(self.plan.errores(self.e), [])
        self.plan.decisiones["dbo.Clientes"].modo = ARRAY             # forzar un ciclo imposible
        self.plan.decisiones["dbo.Clientes"].fk = "fk4"
        self.assertTrue(self.plan.errores(self.e))


class PruebaIntegracion(unittest.TestCase):
    DESTINO = "tienda_online_prueba"

    @classmethod
    def setUpClass(cls):
        try:
            from pymongo import MongoClient

            from migrador.esquema import cadena_conexion, conectar, leer_esquema
            cls.con = conectar(cadena_conexion(r".\SQLEXPRESS", "TiendaOnline"))
            cls.cliente = MongoClient("mongodb://localhost:27017", serverSelectionTimeoutMS=3000)
            cls.cliente.admin.command("ping")
        except Exception as e:  # noqa: BLE001
            raise unittest.SkipTest(f"SQL Server o MongoDB no disponibles: {e}")
        cls.esquema = leer_esquema(cls.con)

    def setUp(self):
        self.cliente.drop_database(self.DESTINO)

    @classmethod
    def tearDownClass(cls):
        cls.cliente.drop_database(cls.DESTINO)

    def test_migracion_completa_pasa_todos_los_controles(self):
        from migrador.motor import Migrador
        from migrador.verificacion import resumen, verificar
        plan = proponer(self.esquema)
        db = self.cliente[self.DESTINO]
        res = Migrador(self.con, db, self.esquema, plan).ejecutar()
        controles = verificar(self.con, db, self.esquema, plan, res)
        fallas = [c for c in controles if c.ok is False]
        self.assertEqual(fallas, [], fallas)
        ok, total = resumen(controles)
        self.assertEqual(ok, total)
        self.assertEqual(db.pedidos.count_documents({"envio": {"$exists": True}}), 1866)

    def test_referencia_a_tabla_embebida(self):
        """Direcciones embebida en clientes: pedidos.direccion_id apunta a clientes.direcciones.direccion_id."""
        from migrador.motor import Migrador
        from migrador.verificacion import verificar
        plan = proponer(self.esquema)
        fk = next(f for f in self.esquema.fks if f.hija == "dbo.Direcciones")
        cambiar(plan, self.esquema, "dbo.Direcciones", ARRAY, fk.nombre)
        db = self.cliente[self.DESTINO]
        res = Migrador(self.con, db, self.esquema, plan).ejecutar()
        controles = verificar(self.con, db, self.esquema, plan, res)
        self.assertEqual([c for c in controles if c.ok is False], [])
        self.assertNotIn("direcciones", db.list_collection_names())
        self.assertTrue(any("direccion_id" in c.descripcion.lower() or "DireccionID" in c.descripcion
                            for c in controles if c.categoria == "Integridad referencial"))
