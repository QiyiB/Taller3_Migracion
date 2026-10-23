"""
Genera sql/02_carga_datos.sql con datos sintéticos y coherentes para TiendaOnline.

Los datos se generan con semilla fija, de modo que el script SQL resultante
es siempre el mismo. Reglas de negocio que se respetan:
  * Cada pedido usa una dirección que pertenece a su cliente.
  * El subtotal del pedido es la suma de sus líneas; envío gratis desde $150.000.
  * El estado del pedido es coherente con sus pagos y su envío
    (Pendiente sin pago aprobado, Pagado sin envío, Enviado en tránsito,
     Entregado con fecha de entrega, Cancelado sin envío).
  * Solo reseñan productos los clientes que los recibieron (pedido Entregado).

Uso:  python sql/generar_datos.py
"""
import random
import unicodedata
from datetime import date, datetime, timedelta
from pathlib import Path

random.seed(2026)

SALIDA = Path(__file__).with_name("02_carga_datos.sql")
INICIO = datetime(2025, 1, 1)
FIN = datetime(2026, 9, 30, 23, 59, 59)

N_CLIENTES = 800
N_PEDIDOS = 2000
PRODUCTOS_POR_CATEGORIA = 25

# ---------------------------------------------------------------- catálogos
CATEGORIAS = [
    ("Tecnología", "Accesorios y dispositivos electrónicos",
     ["Audífonos inalámbricos", "Mouse ergonómico", "Teclado mecánico", "Cargador rápido USB-C",
      "Parlante Bluetooth", "Smartwatch", "Power bank 20000 mAh", "Cámara web HD"], (39900, 899900)),
    ("Hogar", "Decoración, textiles y organización del hogar",
     ["Juego de sábanas", "Lámpara de escritorio", "Organizador multiuso", "Cortina blackout",
      "Almohada viscoelástica"], (19900, 249900)),
    ("Cocina", "Electrodomésticos y utensilios de cocina",
     ["Sartén antiadherente", "Licuadora", "Juego de cuchillos", "Cafetera de goteo",
      "Olla a presión", "Freidora de aire"], (29900, 549900)),
    ("Deportes", "Equipamiento deportivo y fitness",
     ["Mancuernas ajustables", "Colchoneta de yoga", "Balón de fútbol", "Bicicleta estática",
      "Banda de resistencia", "Termo deportivo"], (19900, 1299900)),
    ("Moda", "Ropa y accesorios",
     ["Camiseta básica", "Jean slim", "Chaqueta impermeable", "Gorra", "Bolso de mano",
      "Cinturón de cuero"], (29900, 349900)),
    ("Calzado", "Calzado deportivo, casual y formal",
     ["Tenis running", "Botas de cuero", "Sandalias", "Zapatos formales", "Tenis urbanos"], (59900, 499900)),
    ("Belleza", "Cuidado personal y belleza",
     ["Crema hidratante", "Protector solar", "Perfume", "Secador de cabello", "Plancha alisadora",
      "Kit de maquillaje"], (19900, 389900)),
    ("Juguetes", "Juguetes y juegos para todas las edades",
     ["Set de bloques", "Muñeca articulada", "Carro a control remoto", "Rompecabezas 1000 piezas",
      "Juego de mesa"], (24900, 299900)),
    ("Libros", "Libros físicos de distintos géneros",
     ["Novela", "Libro de cocina", "Guía de programación", "Libro infantil ilustrado", "Biografía"], (29900, 129900)),
    ("Mascotas", "Alimento y accesorios para mascotas",
     ["Cama para perro", "Rascador para gato", "Alimento premium 8 kg", "Juguete mordedor",
      "Arnés ajustable"], (14900, 289900)),
    ("Oficina", "Muebles y papelería de oficina",
     ["Silla ergonómica", "Escritorio plegable", "Agenda 2026", "Set de bolígrafos",
      "Archivador metálico"], (9900, 899900)),
    ("Salud", "Equipos de cuidado de la salud en casa",
     ["Tensiómetro digital", "Termómetro infrarrojo", "Botiquín completo", "Masajeador cervical",
      "Báscula digital"], (29900, 329900)),
]
MARCAS = ["Nova", "Andina", "Kora", "Vértice", "Zenit", "Tayrona", "Monteverde", "Aurora", "Cumbre", "Brisa"]
VARIANTES = ["Pro", "Plus", "Lite", "Max", "Classic", "Eco", "Go", "Prime", "Mini", "Edición 2026"]

CIUDADES = [  # (ciudad, departamento, prefijo postal, peso)
    ("Bogotá", "Cundinamarca", "110", 30), ("Medellín", "Antioquia", "050", 15),
    ("Cali", "Valle del Cauca", "760", 12), ("Barranquilla", "Atlántico", "080", 8),
    ("Cartagena", "Bolívar", "130", 6), ("Bucaramanga", "Santander", "680", 6),
    ("Pereira", "Risaralda", "660", 5), ("Manizales", "Caldas", "170", 4),
    ("Santa Marta", "Magdalena", "470", 4), ("Cúcuta", "Norte de Santander", "540", 4),
    ("Ibagué", "Tolima", "730", 3), ("Villavicencio", "Meta", "500", 3),
]
NOMBRES = ["Juan", "María", "Carlos", "Laura", "Andrés", "Valentina", "Santiago", "Camila", "Daniel",
           "Sofía", "Felipe", "Daniela", "Sebastián", "Isabella", "Mateo", "Mariana", "Alejandro",
           "Paula", "Nicolás", "Natalia", "David", "Gabriela", "Julián", "Manuela", "Diego", "Juliana",
           "Esteban", "Ana", "Tomás", "Luisa", "Miguel", "Carolina", "Samuel", "Sara", "Jorge", "Diana"]
APELLIDOS = ["Gómez", "Rodríguez", "Martínez", "García", "López", "González", "Hernández", "Pérez",
             "Sánchez", "Ramírez", "Torres", "Díaz", "Vargas", "Moreno", "Rojas", "Jiménez", "Castro",
             "Ruiz", "Ortiz", "Restrepo", "Ospina", "Muñoz", "Álvarez", "Romero", "Salazar", "Quintero",
             "Valencia", "Cárdenas", "Mejía", "Arango"]
DOMINIOS = ["gmail.com", "hotmail.com", "outlook.com", "yahoo.com", "correo.co"]

PROV_PREFIJOS = ["Distribuciones", "Importadora", "Comercializadora", "Grupo", "Suministros"]
PROV_NOMBRES = ["del Caribe", "Andina", "Pacífico", "Global", "Central", "del Norte", "Orinoquía",
                "Express", "Integral", "Nacional"]
PROV_UBICACION = [("Bogotá", "Colombia")] * 6 + [("Medellín", "Colombia")] * 4 + [
    ("Cali", "Colombia"), ("Barranquilla", "Colombia"), ("Shenzhen", "China"),
    ("Ciudad de México", "México"), ("Miami", "Estados Unidos")]

# transportadora: (prefijo guía, días estimados, media real, desviación, peso)
TRANSPORTADORAS = {
    "Servientrega": ("SVT", 3, 2.8, 1.0, 30),
    "Coordinadora": ("COO", 3, 3.2, 1.2, 25),
    "Interrapidísimo": ("INT", 4, 4.6, 1.8, 20),
    "Envía": ("ENV", 4, 3.9, 1.5, 12),
    "TCC": ("TCC", 3, 3.0, 0.9, 8),
    "Deprisa": ("DEP", 2, 2.6, 1.3, 5),
}
# método: (peso, probabilidad de rechazo)
METODOS = {
    "Tarjeta credito": (35, 0.12),
    "Tarjeta debito": (20, 0.07),
    "PSE": (25, 0.10),
    "Nequi": (12, 0.04),
    "Contraentrega": (8, 0.0),
}
COMENTARIOS = {
    1: ["Llegó defectuoso y el soporte no respondió.", "Muy mala calidad, no lo recomiendo.",
        "No corresponde a la descripción."],
    2: ["Se dañó a las pocas semanas.", "Calidad inferior a la esperada.", "Regular, esperaba más por el precio."],
    3: ["Cumple, pero nada especial.", "Aceptable para el precio.", "Funciona, aunque los materiales son básicos."],
    4: ["Buen producto, llegó a tiempo.", "Buena relación calidad-precio.", "Me gustó, lo volvería a comprar."],
    5: ["Excelente, superó mis expectativas.", "Perfecto, totalmente recomendado.",
        "Calidad excelente y entrega rápida."],
}


# ---------------------------------------------------------------- utilidades
def ascii(texto: str) -> str:
    return unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode().lower().replace(" ", "")


def precio_en(rango) -> int:
    """Precio comercial terminado en 900 (múltiplo de 100 para evitar centavos)."""
    lo, hi = rango
    valor = int(random.triangular(lo, hi, lo + (hi - lo) * 0.25))
    return max(lo, (valor // 1000) * 1000 + 900)


def fecha_aleatoria(desde: datetime, hasta: datetime) -> datetime:
    segundos = int((hasta - desde).total_seconds())
    return (desde + timedelta(seconds=random.randint(0, segundos))).replace(microsecond=0)


def sql_valor(v) -> str:
    if v is None:
        return "NULL"
    if isinstance(v, bool):
        return "1" if v else "0"
    if isinstance(v, (int, float)):
        return str(v)
    if isinstance(v, datetime):
        return f"'{v:%Y-%m-%dT%H:%M:%S}'"
    if isinstance(v, date):
        return f"'{v:%Y-%m-%d}'"
    return "N'" + str(v).replace("'", "''") + "'"


# ---------------------------------------------------------------- generación
def generar():
    datos = {}

    # 1. Categorías
    datos["Categorias"] = [
        {"CategoriaID": i, "Nombre": n, "Descripcion": d} for i, (n, d, _, _) in enumerate(CATEGORIAS, 1)
    ]

    # 2. Proveedores
    combinaciones = [(p, n) for p in PROV_PREFIJOS for n in PROV_NOMBRES]
    random.shuffle(combinaciones)
    proveedores = []
    for i, (pre, nom) in enumerate(combinaciones[:25], 1):
        ciudad, pais = random.choice(PROV_UBICACION)
        razon = f"{pre} {nom} S.A.S."
        proveedores.append({
            "ProveedorID": i, "RazonSocial": razon,
            "NIT": f"{900000000 + i * 37171}-{i % 10}",
            "Email": f"ventas@{ascii(pre + nom)}.com.co",
            "Telefono": f"60{random.randint(1, 8)}{random.randint(1000000, 9999999)}",
            "Ciudad": ciudad, "Pais": pais,
        })
    datos["Proveedores"] = proveedores

    # 3. Productos (cada categoría trabaja con 3 proveedores)
    productos, pid = [], 0
    for cat_id, (cat_nombre, _, tipos, rango) in enumerate(CATEGORIAS, 1):
        proveedores_cat = random.sample(range(1, 26), 3)
        for k in range(PRODUCTOS_POR_CATEGORIA):
            pid += 1
            tipo = tipos[k % len(tipos)]
            marca = random.choice(MARCAS)
            precio = precio_en(rango)
            bajo_stock = random.random() < 0.12
            productos.append({
                "ProductoID": pid,
                "SKU": f"{ascii(cat_nombre)[:3].upper()}-{pid:05d}",
                "Nombre": f"{tipo} {marca} {random.choice(VARIANTES)}",
                "Descripcion": f"{tipo} marca {marca}, categoría {cat_nombre.lower()}.",
                "Precio": precio,
                "Costo": int(precio * random.uniform(0.45, 0.75)) // 100 * 100,
                "Stock": random.randint(0, 20) if bajo_stock else random.randint(21, 400),
                "Activo": random.random() > 0.05,
                "FechaCreacion": (INICIO - timedelta(days=random.randint(30, 700))).date(),
                "CategoriaID": cat_id,
                "ProveedorID": random.choice(proveedores_cat),
                # atributos internos (no se insertan): popularidad y calidad percibida
                "_popularidad": random.paretovariate(1.3),
                "_calidad": random.gauss(2.3, 0.4) if random.random() < 0.08 else random.gauss(4.1, 0.45),
            })
    datos["Productos"] = productos

    # 4. Clientes y 5. Direcciones
    clientes, direcciones, dir_por_cliente = [], [], {}
    usados = set()
    did = 0
    pesos_ciudad = [c[3] for c in CIUDADES]
    for cid in range(1, N_CLIENTES + 1):
        nombre = random.choice(NOMBRES)
        apellido1, apellido2 = random.sample(APELLIDOS, 2)
        email = f"{ascii(nombre)}.{ascii(apellido1)}{cid}@{random.choice(DOMINIOS)}"
        usados.add(email)
        clientes.append({
            "ClienteID": cid, "Nombres": nombre, "Apellidos": f"{apellido1} {apellido2}",
            "Email": email, "Telefono": f"3{random.randint(0, 2)}{random.randint(10000000, 99999999)}",
            "FechaNacimiento": date(random.randint(1960, 2006), random.randint(1, 12), random.randint(1, 28)),
            "FechaRegistro": fecha_aleatoria(datetime(2023, 1, 1), datetime(2026, 6, 30)),
            "Segmento": random.choices(["Estandar", "Plata", "Oro"], [65, 25, 10])[0],
            "_actividad": random.lognormvariate(0, 0.9),
        })
        ciudad_base = random.choices(CIUDADES, pesos_ciudad)[0]
        n_dir = random.choices([1, 2, 3], [60, 30, 10])[0]
        alias_disp = random.sample(["Casa", "Oficina", "Apartamento", "Casa de mis padres"], n_dir)
        dir_por_cliente[cid] = []
        for j in range(n_dir):
            did += 1
            ciudad = ciudad_base if (j == 0 or random.random() < 0.7) else random.choices(CIUDADES, pesos_ciudad)[0]
            via = random.choice(["Calle", "Carrera", "Avenida", "Transversal", "Diagonal"])
            linea = f"{via} {random.randint(1, 180)} # {random.randint(1, 120)}-{random.randint(1, 99)}"
            if random.random() < 0.5:
                linea += f" Apto {random.randint(101, 1504)}"
            direcciones.append({
                "DireccionID": did, "ClienteID": cid, "Alias": alias_disp[j], "Linea": linea,
                "Ciudad": ciudad[0], "Departamento": ciudad[1],
                "CodigoPostal": f"{ciudad[2]}{random.randint(1, 999):03d}", "EsPrincipal": j == 0,
            })
            dir_por_cliente[cid].append(did)
    datos["Clientes"], datos["Direcciones"] = clientes, direcciones

    # 6-9. Pedidos, DetallePedido, Pagos, Envios
    pedidos, detalles, pagos, envios = [], [], [], []
    det_id = pago_id = envio_id = 0
    pesos_cliente = [c["_actividad"] for c in clientes]
    pesos_producto = [p["_popularidad"] for p in productos]
    nombres_transp = list(TRANSPORTADORAS)
    pesos_transp = [t[4] for t in TRANSPORTADORAS.values()]
    metodos = list(METODOS)
    pesos_metodo = [m[0] for m in METODOS.values()]
    entregados = []  # (cliente, producto, fecha_entrega) para generar reseñas

    fechas = []
    for _ in range(N_PEDIDOS):
        cliente = random.choices(clientes, pesos_cliente)[0]
        desde = max(cliente["FechaRegistro"], INICIO)
        fechas.append((fecha_aleatoria(desde, FIN), cliente))
    fechas.sort(key=lambda x: x[0])  # IDs de pedido crecientes en el tiempo

    for ped_id, (fecha, cliente) in enumerate(fechas, 1):
        cid = cliente["ClienteID"]
        dirs = dir_por_cliente[cid]
        direccion = dirs[0] if random.random() < 0.8 else random.choice(dirs)

        # líneas del pedido
        n_items = random.choices([1, 2, 3, 4, 5], [35, 30, 20, 10, 5])[0]
        elegidos = set()
        while len(elegidos) < n_items:
            elegidos.add(random.choices(productos, pesos_producto)[0]["ProductoID"])
        subtotal = 0
        lineas = []
        for prod_id in sorted(elegidos):
            prod = productos[prod_id - 1]
            cantidad = random.choices([1, 2, 3, 4], [70, 20, 7, 3])[0]
            descuento = random.choices([0, 5, 10, 15], [70, 12, 12, 6])[0]
            sub_linea = cantidad * prod["Precio"] * (100 - descuento) // 100
            subtotal += sub_linea
            det_id += 1
            lineas.append({"DetalleID": det_id, "PedidoID": ped_id, "ProductoID": prod_id,
                           "Cantidad": cantidad, "PrecioUnitario": prod["Precio"], "Descuento": descuento})
        detalles.extend(lineas)
        costo_envio = 0 if subtotal >= 150000 else 9900
        total = subtotal + costo_envio

        # ciclo de vida del pedido
        horas_al_cierre = (FIN - fecha).total_seconds() / 3600
        if random.random() < 0.06:
            estado = "Cancelado"
        elif horas_al_cierre < 72 and random.random() < 0.5:
            estado = "Pendiente"
        else:
            estado = "Pagado"  # puede avanzar a Enviado / Entregado según fechas

        envio = None
        if estado == "Pagado":
            despacho = fecha + timedelta(hours=random.randint(12, 60))
            if despacho <= FIN:
                transp = random.choices(nombres_transp, pesos_transp)[0]
                prefijo, dias_est, media, desv, _ = TRANSPORTADORAS[transp]
                dias_reales = max(1, round(random.gauss(media, desv)))
                entrega = despacho + timedelta(days=dias_reales, hours=random.randint(-4, 6))
                envio_id += 1
                envio = {
                    "EnvioID": envio_id, "PedidoID": ped_id, "Transportadora": transp,
                    "NumeroGuia": f"{prefijo}{envio_id * 104729 % 10**9:09d}",
                    "FechaDespacho": despacho,
                    "FechaEntregaEstimada": despacho + timedelta(days=dias_est),
                    "FechaEntrega": entrega if entrega <= FIN else None,
                    "Estado": "Entregado" if entrega <= FIN else "En transito",
                }
                estado = "Entregado" if envio["FechaEntrega"] else "Enviado"
                envios.append(envio)

        # pagos
        def nuevo_pago(metodo, estado_pago, momento):
            nonlocal pago_id
            pago_id += 1
            pagos.append({"PagoID": pago_id, "PedidoID": ped_id, "Metodo": metodo, "Estado": estado_pago,
                          "Monto": total, "FechaPago": momento, "Referencia": f"PAY-{pago_id:07d}"})

        if estado == "Cancelado":
            r = random.random()
            metodo = random.choices(metodos[:-1], pesos_metodo[:-1])[0]
            if r < 0.5:
                nuevo_pago(metodo, "Rechazado", fecha + timedelta(minutes=random.randint(1, 30)))
            elif r < 0.8:
                nuevo_pago(metodo, "Reembolsado", fecha + timedelta(minutes=random.randint(1, 30)))
        elif estado == "Pendiente":
            if random.random() < 0.4:
                metodo = random.choices(metodos[:-1], pesos_metodo[:-1])[0]
                nuevo_pago(metodo, "Rechazado", fecha + timedelta(minutes=random.randint(1, 30)))
        else:
            # Contraentrega solo aplica a pedidos ya entregados (se paga al recibir)
            candidatos = metodos if estado == "Entregado" else metodos[:-1]
            pesos = pesos_metodo if estado == "Entregado" else pesos_metodo[:-1]
            metodo = random.choices(candidatos, pesos)[0]
            momento = fecha + timedelta(minutes=random.randint(1, 30))
            if random.random() < METODOS[metodo][1]:
                nuevo_pago(metodo, "Rechazado", momento)
                momento += timedelta(minutes=random.randint(2, 40))
                if random.random() < 0.5:
                    metodo = random.choices(metodos[:-1], pesos_metodo[:-1])[0]
            nuevo_pago(metodo, "Aprobado", envio["FechaEntrega"] if metodo == "Contraentrega" else momento)

        if estado == "Entregado":
            for linea in lineas:
                entregados.append((cid, linea["ProductoID"], envio["FechaEntrega"]))

        pedidos.append({"PedidoID": ped_id, "ClienteID": cid, "DireccionID": direccion, "FechaPedido": fecha,
                        "Estado": estado, "Subtotal": subtotal, "CostoEnvio": costo_envio, "Total": total})

    datos["Pedidos"], datos["DetallePedido"] = pedidos, detalles
    datos["Pagos"], datos["Envios"] = pagos, envios

    # 10. Reseñas: un cliente reseña un producto una sola vez, después de recibirlo
    resenas, vistos = [], set()
    for cid, prod_id, entrega in entregados:
        if (prod_id, cid) in vistos or random.random() > 0.35:
            continue
        momento = entrega + timedelta(days=random.randint(1, 20), hours=random.randint(0, 12))
        if momento > FIN:
            continue
        vistos.add((prod_id, cid))
        calidad = productos[prod_id - 1]["_calidad"]
        nota = min(5, max(1, round(random.gauss(calidad, 0.8))))
        resenas.append({"ResenaID": len(resenas) + 1, "ProductoID": prod_id, "ClienteID": cid,
                        "Calificacion": nota,
                        "Comentario": random.choice(COMENTARIOS[nota]) if random.random() < 0.85 else None,
                        "Fecha": momento})
    datos["Resenas"] = resenas
    return datos


ORDEN = ["Categorias", "Proveedores", "Productos", "Clientes", "Direcciones",
         "Pedidos", "DetallePedido", "Pagos", "Envios", "Resenas"]


def escribir(datos):
    lineas = [
        "/* =====================================================================",
        "   Taller 3 - Bases de Datos II  |  Script 02: carga de datos",
        "   ARCHIVO GENERADO por sql/generar_datos.py (semilla fija 2026).",
        "   Ejecutar con:  sqlcmd -S .\\SQLEXPRESS -E -C -f 65001 -i sql\\02_carga_datos.sql",
        "   ===================================================================== */",
        "USE TiendaOnline;", "SET NOCOUNT ON;",
        "SET ANSI_NULLS ON;", "SET QUOTED_IDENTIFIER ON;  -- requerido por la columna calculada Subtotal",
        "GO", "",
        "-- Limpieza para que el script sea re-ejecutable (orden inverso a las FK)",
    ]
    lineas += [f"DELETE FROM dbo.{t};" for t in reversed(ORDEN)]
    lineas.append("GO")
    total = 0
    for tabla in ORDEN:
        filas = datos[tabla]
        total += len(filas)
        columnas = [c for c in filas[0] if not c.startswith("_")]
        lineas += ["", f"-- {tabla}: {len(filas)} registros", f"SET IDENTITY_INSERT dbo.{tabla} ON;"]
        for i in range(0, len(filas), 500):
            lote = filas[i:i + 500]
            lineas.append(f"INSERT INTO dbo.{tabla} ({', '.join(columnas)}) VALUES")
            valores = ["(" + ", ".join(sql_valor(f[c]) for c in columnas) + ")" for f in lote]
            lineas.append(",\n".join(valores) + ";")
        lineas += [f"SET IDENTITY_INSERT dbo.{tabla} OFF;", "GO"]
    lineas += ["", f"PRINT 'Carga completa: {total} registros en 10 tablas.';", ""]
    SALIDA.write_text("\n".join(lineas), encoding="utf-8")
    return total


if __name__ == "__main__":
    datos = generar()
    total = escribir(datos)
    for t in ORDEN:
        print(f"{t:<15}{len(datos[t]):>7}")
    print(f"{'TOTAL':<15}{total:>7}")
    print(f"Script escrito en {SALIDA}")
