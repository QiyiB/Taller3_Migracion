# Verificación de la migración SQL Server → MongoDB

Generado por `python migracion/verificar.py`.

**Resultado: 79/79 controles correctos.**


## 1. Conteos

| Control | SQL Server / esperado | MongoDB | OK |
|---|---:|---:|:-:|
| Categorias -> categorias | 12 | 12 | ✅ |
| Proveedores -> proveedores | 25 | 25 | ✅ |
| Productos -> productos | 300 | 300 | ✅ |
| Clientes -> clientes | 800 | 800 | ✅ |
| Pedidos -> pedidos | 2000 | 2000 | ✅ |
| Resenas -> resenas | 1378 | 1378 | ✅ |
| Direcciones -> clientes.direcciones[] | 1185 | 1185 | ✅ |
| DetallePedido -> pedidos.items[] | 4317 | 4317 | ✅ |
| Pagos -> pedidos.pagos[] | 2144 | 2144 | ✅ |
| Envios -> pedidos.envio | 1866 | 1866 | ✅ |
| Pedidos en estado Pendiente | 5 | 5 | ✅ |
| Pedidos en estado Pagado | 4 | 4 | ✅ |
| Pedidos en estado Enviado | 10 | 10 | ✅ |
| Pedidos en estado Entregado | 1856 | 1856 | ✅ |
| Pedidos en estado Cancelado | 125 | 125 | ✅ |

## 2. Sumas de control

| Control | SQL Server / esperado | MongoDB | OK |
|---|---:|---:|:-:|
| SUM(Pedidos.Total) = SUM(totales.total) | 1,426,165,610.00 | 1,426,165,610.00 | ✅ |
| SUM(DetallePedido.Subtotal) = SUM(items.subtotal) | 1,423,789,610.00 | 1,423,789,610.00 | ✅ |
| SUM(DetallePedido.Cantidad) = SUM(items.cantidad) | 6190 | 6190 | ✅ |
| SUM(Pagos.Monto) aprobados = SUM(pagos.monto) aprobados | 1,342,001,300.00 | 1,342,001,300.00 | ✅ |
| SUM(Productos.Stock) = SUM(stock) | 53446 | 53446 | ✅ |
| SUM(Resenas.Calificacion) = SUM(calificacion) | 5454 | 5454 | ✅ |

## 3. Integridad referencial (huérfanos)

| Control | SQL Server / esperado | MongoDB | OK |
|---|---:|---:|:-:|
| pedidos.cliente_id -> clientes | 0 | 0 | ✅ |
| pedidos.items.producto_id -> productos | 0 | 0 | ✅ |
| productos.categoria_id -> categorias | 0 | 0 | ✅ |
| productos.proveedor_id -> proveedores | 0 | 0 | ✅ |
| resenas.producto_id -> productos | 0 | 0 | ✅ |
| resenas.cliente_id -> clientes | 0 | 0 | ✅ |

## 4. Estructuras embebidas

| Control | SQL Server / esperado | MongoDB | OK |
|---|---:|---:|:-:|
| Pedidos con SUM(items.subtotal) <> totales.subtotal | 0 | 0 | ✅ |
| Pedidos con total <> subtotal + costo_envio | 0 | 0 | ✅ |
| Pedidos cuya dirección no pertenece al cliente | 0 | 0 | ✅ |
| Clientes con != 1 dirección principal | 0 | 0 | ✅ |
| Pedidos 'Entregado' sin envio.fecha_entrega | 0 | 0 | ✅ |
| productos.calificacion.total_resenas desactualizado | 0 | 0 | ✅ |
| Documentos de pedidos que no cumplen el $jsonSchema | 0 | 0 | ✅ |

## 5. Muestra de pedidos

| Control | SQL Server / esperado | MongoDB | OK |
|---|---:|---:|:-:|
| Pedido 309 - cliente | 70 | 70 | ✅ |
| Pedido 309 - estado | Entregado | Entregado | ✅ |
| Pedido 309 - fecha | 2025-06-02 16:59:39 | 2025-06-02 16:59:39 | ✅ |
| Pedido 309 - total | 1,647,940.00 | 1,647,940.00 | ✅ |
| Pedido 309 - ciudad envío | Pereira | Pereira | ✅ |
| Pedido 309 - # líneas | 3 | 3 | ✅ |
| Pedido 309 - # pagos | 1 | 1 | ✅ |
| Pedido 309 - guía | INT030685597 | INT030685597 | ✅ |
| Pedido 309 - líneas idénticas | True | True | ✅ |
| Pedido 664 - cliente | 611 | 611 | ✅ |
| Pedido 664 - estado | Entregado | Entregado | ✅ |
| Pedido 664 - fecha | 2025-10-31 16:47:50 | 2025-10-31 16:47:50 | ✅ |
| Pedido 664 - total | 3,406,920.00 | 3,406,920.00 | ✅ |
| Pedido 664 - ciudad envío | Bogotá | Bogotá | ✅ |
| Pedido 664 - # líneas | 4 | 4 | ✅ |
| Pedido 664 - # pagos | 1 | 1 | ✅ |
| Pedido 664 - guía | COO065665083 | COO065665083 | ✅ |
| Pedido 664 - líneas idénticas | True | True | ✅ |
| Pedido 809 - cliente | 212 | 212 | ✅ |
| Pedido 809 - estado | Entregado | Entregado | ✅ |
| Pedido 809 - fecha | 2025-12-20 16:09:02 | 2025-12-20 16:09:02 | ✅ |
| Pedido 809 - total | 852,600.00 | 852,600.00 | ✅ |
| Pedido 809 - ciudad envío | Manizales | Manizales | ✅ |
| Pedido 809 - # líneas | 2 | 2 | ✅ |
| Pedido 809 - # pagos | 1 | 1 | ✅ |
| Pedido 809 - guía | ENV080117685 | ENV080117685 | ✅ |
| Pedido 809 - líneas idénticas | True | True | ✅ |
| Pedido 1334 - cliente | 11 | 11 | ✅ |
| Pedido 1334 - estado | Entregado | Entregado | ✅ |
| Pedido 1334 - fecha | 2026-05-11 16:31:52 | 2026-05-11 16:31:52 | ✅ |
| Pedido 1334 - total | 58,255.00 | 58,255.00 | ✅ |
| Pedido 1334 - ciudad envío | Cartagena | Cartagena | ✅ |
| Pedido 1334 - # líneas | 1 | 1 | ✅ |
| Pedido 1334 - # pagos | 2 | 2 | ✅ |
| Pedido 1334 - guía | DEP131958540 | DEP131958540 | ✅ |
| Pedido 1334 - líneas idénticas | True | True | ✅ |
| Pedido 1942 - cliente | 381 | 381 | ✅ |
| Pedido 1942 - estado | Cancelado | Cancelado | ✅ |
| Pedido 1942 - fecha | 2026-09-18 15:53:34 | 2026-09-18 15:53:34 | ✅ |
| Pedido 1942 - total | 168,900.00 | 168,900.00 | ✅ |
| Pedido 1942 - ciudad envío | Medellín | Medellín | ✅ |
| Pedido 1942 - # líneas | 1 | 1 | ✅ |
| Pedido 1942 - # pagos | 1 | 1 | ✅ |
| Pedido 1942 - guía |  |  | ✅ |
| Pedido 1942 - líneas idénticas | True | True | ✅ |

## Colecciones e índices en MongoDB

| Colección | Documentos | Índices |
|---|---:|---|
| categorias | 12 | _id_ |
| clientes | 800 | _id_, email_1 |
| pedidos | 2000 | _id_, cliente_id_1_fecha_-1, fecha_1, estado_1, items.producto_id_1, envio.transportadora_1 |
| productos | 300 | _id_, sku_1, categoria_id_1, proveedor_id_1, stock_1 |
| proveedores | 25 | _id_ |
| resenas | 1378 | _id_, producto_id_1_cliente_id_1, cliente_id_1 |

Documentos de ejemplo de cada colección: `evidencias/ejemplos/`. Pedidos comparados en la muestra: 309, 664, 809, 1334, 1942.
