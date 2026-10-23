# Taller Evaluativo 3: migración de SQL Server a MongoDB

**Bases de Datos II** · Profesor: Juan Carlos Gómez
**Caso de estudio:** *TiendaOnline*, un e-commerce colombiano con catálogo, clientes, pedidos, pagos, envíos y reseñas.

Partimos de una base relacional en SQL Server (10 tablas, 14.027 registros) y la migramos con Python a un modelo documental en MongoDB (6 colecciones). Comprobamos que la información se conserva (79 controles) y respondemos 7 preguntas de negocio con Aggregation Pipelines.

## Estructura del repositorio

```
├── sql/
│   ├── 01_esquema.sql              # creación de la BD y de las 10 tablas (PK, FK, CHECK, UNIQUE, índices)
│   ├── 02_carga_datos.sql          # carga de los 14.027 registros (generado)
│   ├── 03_verificacion_sql.sql     # conteos y controles de coherencia en SQL Server
│   └── generar_datos.py            # generador reproducible del script 02 (semilla fija)
├── migracion/
│   ├── migrar.py                   # extracción, transformación y carga a MongoDB
│   └── verificar.py                # verificación SQL Server vs MongoDB (79 controles)
├── consultas/
│   └── consultas.js                # 7 Aggregation Pipelines de negocio (mongosh)
├── docs/
│   ├── Documentacion_Taller3.docx  # documentación completa en Word (APA 7)
│   ├── generar_documentacion.py    # genera el .docx (python-docx)
│   ├── modelo_relacional.md        # diagrama ER, entidades, volumen y reglas
│   ├── modelo_documental.md        # colecciones, Embedding vs Referencing, proceso de migración
│   └── consultas.md                # justificación de negocio y explicación de cada pipeline
├── evidencias/
│   ├── 01_verificacion_sql_server.txt
│   ├── 02_log_migracion.txt
│   ├── 03_verificacion_migracion.md
│   ├── 04_resultados_consultas.txt
│   └── ejemplos/                   # un documento real de cada colección
├── presentacion/
│   └── Exposicion_Taller3.pptx     # presentación de la sustentación (23 diapositivas)
├── migrador/                       # aplicación genérica: cualquier base de SQL Server → MongoDB
│   ├── esquema.py                  # lee tablas, llaves y estadísticas desde las vistas de sistema
│   ├── propuesta.py                # reglas que proponen Embedding / Referencing (con justificación)
│   ├── motor.py                    # transformación y carga en MongoDB
│   ├── verificacion.py             # controles SQL Server vs MongoDB y reporte
│   └── gui.py                      # interfaz de escritorio (PySide6)
├── migrador_app.py                 # abre la aplicación de escritorio
├── tests/test_migrador.py          # pruebas de las reglas y de la migración completa
├── config.py                       # cadenas de conexión (se pueden cambiar con variables de entorno)
└── requirements.txt
```

## Requisitos

- SQL Server (probado con SQL Server 2025 Express, instancia `.\SQLEXPRESS`) y `sqlcmd`
- ODBC Driver 18 for SQL Server
- MongoDB (probado con 9.0) y `mongosh`
- Python 3.10 o superior

Si tu instancia o URI son distintas, define estas variables de entorno: `SQLSERVER_CONN`, `MONGO_URI` y `MONGO_DB` (ver `config.py`).

## Cómo ejecutarlo

```bash
pip install -r requirements.txt
```

1. Crear y poblar la base relacional:

```bash
sqlcmd -S .\SQLEXPRESS -E -C -f 65001 -i sql\01_esquema.sql
```

```bash
sqlcmd -S .\SQLEXPRESS -E -C -f 65001 -i sql\02_carga_datos.sql
```

```bash
sqlcmd -S .\SQLEXPRESS -E -C -f 65001 -W -i sql\03_verificacion_sql.sql
```

2. Migrar a MongoDB:

```bash
python migracion/migrar.py
```

3. Verificar la migración (genera `evidencias/03_verificacion_migracion.md`):

```bash
python migracion/verificar.py
```

4. Ejecutar las consultas:

```bash
mongosh tienda_online --quiet consultas/consultas.js
```

`02_carga_datos.sql` ya viene generado. Para regenerarlo: `python sql/generar_datos.py`.

## Resumen

### Modelo relacional: 10 entidades, 14.027 registros

| Categorias | Proveedores | Productos | Clientes | Direcciones | Pedidos | DetallePedido | Pagos | Envios | Resenas |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 12 | 25 | 300 | 800 | 1.185 | 2.000 | 4.317 | 2.144 | 1.866 | 1.378 |

Detalle en [docs/modelo_relacional.md](docs/modelo_relacional.md).

### Modelo documental: 6 colecciones

| Colección | Qué contiene | Embedding | Referencing |
|---|---|---|---|
| `pedidos` | Pedidos + DetallePedido + Pagos + Envios | `items[]`, `pagos[]`, `envio`, copia de `direccion_envio` | `cliente_id`, `items.producto_id` |
| `clientes` | Clientes + Direcciones | `direcciones[]` | — |
| `productos` | Productos (+ resumen de reseñas) | `calificacion` (calculado) | `categoria_id`, `proveedor_id` |
| `resenas` | Resenas | — | `producto_id`, `cliente_id` |
| `categorias`, `proveedores` | Catálogos compartidos | — | referenciados desde `productos` |

Justificación completa en [docs/modelo_documental.md](docs/modelo_documental.md).

### Verificación: 79/79 controles correctos

Conteos tabla↔colección (incluidos los arrays embebidos), sumas de control exactas de dinero y cantidades, cero referencias huérfanas, coherencia interna de los documentos y comparación campo a campo de 5 pedidos. Ver [evidencias/03_verificacion_migracion.md](evidencias/03_verificacion_migracion.md).

### Consultas

| # | Pregunta de negocio |
|---|---|
| C1 | Top 10 productos por ingresos y margen en 2026 (3 `$lookup`) |
| C2 | Rentabilidad y % de margen por categoría |
| C3 | Clientes que deberían subir de segmento |
| C4 | Cumplimiento de las transportadoras |
| C5 | Productos mal calificados y su proveedor (4 `$lookup`) |
| C6 | Riesgo de quiebre de stock según ventas de 90 días |
| C7 | Tasa de rechazo por medio de pago |

Explicación y valor para el negocio de cada una en [docs/consultas.md](docs/consultas.md).

## Aplicación de escritorio: Migrador SQL Server → MongoDB

Además de la migración hecha a mano para TiendaOnline, el repositorio incluye una aplicación que migra **cualquier** base de SQL Server:

1. **Conexión.** Origen (servidor, autenticación de Windows o de SQL Server, base) y destino (URI y base de MongoDB).
2. **Modelo.** Lee el esquema desde las vistas de sistema (tablas, PK, FK, UNIQUE) y mide cuántos hijos tiene cada padre. Con eso propone, para cada tabla, si va como colección propia, como array embebido o como subdocumento, y muestra la **justificación**. Cada decisión se puede cambiar, y la vista previa muestra cómo queda el documento.
3. **Migración.** Muestra el progreso y el registro de la carga, y crea índices sobre las referencias.
4. **Verificación.** Conteos, sumas de control, integridad referencial con `$lookup` y una muestra al azar. El reporte se puede exportar en Markdown.

Reglas de la propuesta (las mismas que justificamos al diseñar TiendaOnline):

| Patrón en SQL Server | Propuesta |
|---|---|
| No depende de nadie (catálogo) o la referencian otras tablas | Colección propia |
| Ninguna tabla la referencia y tiene un padre "dueño" (FK en la PK, nombre que lo contiene o FK única) | Embebida en ese padre |
| FK única (relación 1:1) | Subdocumento |
| Relaciona varias entidades sin dueño claro | Colección con referencias |
| Más de 500 hijos por padre | No se embebe: el documento crecería sin límite |

Con TiendaOnline propone 7 colecciones. Es casi el modelo que hicimos a mano; la única diferencia es que deja `Direcciones` como colección porque `Pedidos` la referencia. En la pantalla del modelo se puede cambiar a array dentro de `clientes`.

Para abrir la aplicación:

```bash
python migrador_app.py
```

Para generar el ejecutable de Windows (queda en `dist/MigradorSQLaMongo/`):

```bash
python -m PyInstaller --noconfirm --windowed --name MigradorSQLaMongo --distpath dist --workpath build --specpath build migrador_app.py
```

Para ejecutar las pruebas (reglas y migración completa de TiendaOnline):

```bash
python -m unittest discover -s tests -v
```

**Límites conocidos:** solo lee SQL Server. Carga cada tabla completa en memoria, lo que sirve para bases de hasta algunos millones de filas. Las copias históricas (como la dirección congelada en el pedido) y los campos calculados son decisiones de negocio y no se generan automáticamente. La integridad de llaves foráneas compuestas no se verifica.
