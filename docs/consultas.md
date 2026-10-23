# Consultas de negocio en MongoDB

El código está en [`consultas/consultas.js`](../consultas/consultas.js) y los resultados completos en [`evidencias/04_resultados_consultas.txt`](../evidencias/04_resultados_consultas.txt).

```bash
mongosh tienda_online --quiet consultas/consultas.js                    # todas
mongosh tienda_online --quiet --eval "var SOLO=3" consultas/consultas.js  # solo la C3
```

| # | Pregunta de negocio | Colección base | `$lookup` | Otros operadores |
|---|---|---|:-:|---|
| C1 | ¿Qué productos generan más ingresos y margen este año? | pedidos | 3 | `$match` `$unwind` `$group` `$sort` `$limit` `$project` |
| C2 | ¿Qué categorías son más rentables? | pedidos | 2 (uno con sub-pipeline) | `$match` `$unwind` `$group` `$addToSet` `$size` `$project` `$sort` |
| C3 | ¿Qué clientes merecen subir de segmento? | pedidos | 1 | `$match` `$group` `$max` `$sort` `$limit` `$indexOfArray` `$arrayElemAt` |
| C4 | ¿Qué transportadora cumple mejor? | pedidos | — | `$match` `$dateDiff` `$cond` `$group` `$avg` `$sort` |
| C5 | ¿Qué productos están mal calificados y de qué proveedor son? | resenas | 4 (uno con `let`+pipeline) | `$group` `$match` `$unwind` `$project` `$sort` |
| C6 | ¿Qué productos se van a agotar pronto? | productos | 2 (uno con `let`+pipeline) | `$match` `$unwind` `$group` `$project` `$sort` `$limit` |
| C7 | ¿Qué medio de pago pierde más ventas por rechazos? | pedidos | — | `$unwind` `$group` `$cond` `$project` `$sort` |

---

## C1. Top 10 productos por ingresos en 2026, con su margen

**Qué busca.** Los 10 productos que más dinero facturaron en 2026, con su categoría, su proveedor, las unidades vendidas, el margen bruto (ingreso − costo) y el stock actual.

**Pipeline, etapa por etapa.**
1. `$match`: deja solo los pedidos con pago aprobado (*Pagado, Enviado, Entregado*) de 2026.
2. `$unwind: "$items"`: convierte cada línea del array embebido en un documento.
3. `$group` por `items.producto_id`: suma unidades e ingresos y cuenta pedidos.
4. `$sort` + `$limit 10`: se ordena y se recorta **antes** de los `$lookup`, para que solo se busquen 10 productos y no 300.
5. Tres `$lookup` encadenados: `productos` → con `producto.categoria_id` a `categorias` → con `producto.proveedor_id` a `proveedores`.
6. `$project`: nombres legibles y cálculo del margen `ingresos − unidades × costo`.

**Por qué importa.** Muestra qué productos sostienen la facturación y si además dejan margen. Un producto puede vender mucho con poco margen.

**Decisiones que apoya.** Asegurar inventario de los productos estrella y negociar volumen con su proveedor. Destacarlos en la portada y en las campañas.

**Hallazgo.** El *Smartwatch Zenit Plus* es el producto que más factura (≈ $44 M, con 47 % de margen), pero **solo le quedan 9 unidades**. Coincide con la alerta de la C6.

**Impacto.** Evita perder ventas en los productos que más dinero dejan.

---

## C2. Rentabilidad por categoría

**Qué busca.** Por categoría: pedidos, unidades, ingresos, margen bruto en pesos y % de margen.

**Pipeline.**
1. `$match` de pedidos con pago aprobado y `$unwind` de `items`.
2. `$lookup` con `localField` **y** `pipeline: [{$project: {categoria_id, costo}}]`. Del producto solo se traen los dos campos necesarios, lo que reduce memoria.
3. `$group` por categoría. El costo se calcula como `cantidad × costo`, y `$addToSet` junta los `_id` de pedido para contar **pedidos distintos**, porque un pedido puede tener varios productos de la misma categoría.
4. `$lookup` a `categorias` para el nombre, `$project` con `$size` y el % de margen, y `$sort` por margen.

**Por qué importa.** Las categorías que más facturan no siempre son las más rentables.

**Decisiones que apoya.** Dónde invertir en publicidad y qué categorías ampliar en el catálogo.

**Hallazgo.** *Deportes* es la que más factura y más margen deja en pesos (≈ $102 M), pero su % de margen (38 %) está por debajo de *Tecnología* (42,8 %) y *Oficina* (42,4 %). *Calzado* tiene el % más bajo (35,5 %).

**Impacto.** El presupuesto de marketing se dirige a donde cada peso vendido deja más utilidad.

---

## C3. Clientes candidatos a subir de segmento

**Qué busca.** Los 15 clientes **que no son Oro** que más han comprado, con su ciudad principal, número de pedidos, ticket promedio y última compra.

**Pipeline.**
1. `$match` de pedidos entregados y `$group` por `cliente_id` (total, número de pedidos y fecha máxima).
2. `$lookup` a `clientes` y `$match` sobre un campo traído por el lookup (`cliente.segmento ≠ "Oro"`).
3. `$sort` + `$limit 15`.
4. `$project`. La ciudad principal sale del **array embebido** `direcciones`: `$indexOfArray` encuentra la posición de `es_principal: true` y `$arrayElemAt` toma la ciudad de esa posición.

**Por qué importa.** Si la segmentación está desactualizada, los mejores clientes no reciben los beneficios que les corresponden y se pueden ir a la competencia.

**Decisiones que apoya.** Reclasificar a estos clientes y dirigirles campañas de fidelización.

**Hallazgo.** Hay clientes "Estándar" con más de 20 pedidos y más de $18 M comprados (los clientes 45 y 286). Están claramente mal segmentados.

**Impacto.** Más retención de los clientes de mayor valor.

---

## C4. Desempeño de las transportadoras

**Qué busca.** Por transportadora: envíos entregados, días promedio y máximo de entrega, número y % de entregas tarde, y valor transportado.

**Pipeline.**
1. `$match` sobre un campo del **subdocumento embebido** `envio.estado`. No hay `$lookup`, porque el envío vive dentro del pedido. Así se aprovecha el modelo.
2. `$project`:
   - `$dateDiff` en horas ÷ 24 da los días reales de entrega.
   - `$dateDiff` en días entre la fecha estimada y la real, más `$cond`, marca la entrega como tarde (1) si llegó un día después del prometido.
3. `$group` por transportadora (`$avg`, `$max`, `$sum`) y `$sort` por % de entregas tarde.

**Por qué importa.** La entrega tarde es la principal causa de reclamos en el e-commerce y afecta la recompra.

**Decisiones que apoya.** A qué transportadora asignar más volumen, a cuál exigirle mejoras o penalizar, y qué promesa de entrega mostrar al cliente.

**Hallazgo.** *Deprisa* promete 2 días y llega tarde en el **61,5 %** de los casos. *Interrapidísimo* es la más lenta (4,4 días) y llega tarde en el 52 %. *Servientrega* mueve el mayor valor y es la más cumplida (28,5 % tarde).

**Impacto.** Menos reclamos y mejor experiencia de compra.

---

## C5. Productos mal calificados y su proveedor

**Qué busca.** Los productos con promedio menor a 3 y al menos 3 reseñas, con el % de reseñas negativas, el proveedor y su email, y las dos quejas más recientes.

**Pipeline.**
1. `$group` sobre `resenas` por producto (promedio, total y negativas con `$cond`).
2. `$match` posterior al group: `resenas ≥ 3` (para descartar casos poco representativos) y `promedio < 3`.
3. **Cuatro `$lookup`**: `productos`, `categorias`, `proveedores` y un `$lookup` con `let: {pid}` + `pipeline` sobre la misma colección `resenas`, que filtra las de calificación ≤ 2 con comentario, ordena por fecha y toma 2.
4. `$project` y `$sort` por promedio ascendente.

**Por qué importa.** Un producto mal calificado genera devoluciones, reclamos y daña la reputación de la tienda.

**Decisiones que apoya.** Retirar o pausar productos, abrir un reclamo de calidad con el proveedor o cambiar de proveedor.

**Hallazgo.** *Importadora Global S.A.S.* aparece **3 veces** en la lista, entre ellas la *Licuadora Cumbre Plus* (promedio 1,69 en 13 reseñas). La *Licuadora* y la *Silla ergonómica Nova Prime* además están en el top 10 de ingresos (C1): se venden mucho, pero dejan clientes insatisfechos.

**Impacto.** Menos devoluciones y una base objetiva para negociar con los proveedores.

---

## C6. Riesgo de quiebre de stock

**Qué busca.** Los productos activos con stock ≤ 20 que sí se vendieron en los últimos 90 días, con cuántos días de inventario les quedan al ritmo actual y a qué proveedor pedirles.

**Pipeline.**
1. `$match` en `productos` (activos y con stock ≤ 20). Usa el índice de `stock`.
2. `$lookup` hacia `pedidos` con `let: {pid: "$_id"}` y un **sub-pipeline**: filtra los pedidos de los últimos 90 días que contienen el producto, aplica `$unwind` a los ítems, se queda solo con la línea de ese producto y suma las unidades.
3. `$unwind: "$ventas"`: descarta los productos sin ventas recientes, porque no son urgentes.
4. `$lookup` a `proveedores` para el contacto.
5. `$project`: `venta_diaria = unidades / 90` y `días de inventario = stock / venta_diaria`. Luego `$sort` ascendente y `$limit 15`.

**Por qué importa.** Un producto agotado es venta perdida, y si es un producto estrella la pérdida es grande.

**Decisiones que apoya.** Lista priorizada de órdenes de compra con el contacto del proveedor.

**Hallazgo.** Un libro ya está en **0 unidades** y se vende de forma constante. El *Smartwatch Zenit Plus* (n.º 1 en ingresos) tiene **22 días** de inventario.

**Impacto.** Menos ventas perdidas por falta de stock y compras planificadas con anticipación.

---

## C7. Tasa de rechazo por medio de pago

**Qué busca.** Por medio de pago: intentos, aprobados, rechazados, tasa de rechazo, monto aprobado y monto rechazado.

**Pipeline.**
1. `$unwind: "$pagos"` sobre el **array embebido** de intentos de pago.
2. `$group` por método con `$cond` para contar y sumar según el estado del intento.
3. `$project` con la tasa de rechazo y `$sort` descendente.

**Por qué importa.** Cada rechazo es un cliente que puede abandonar la compra. Saber qué medio rechaza más permite actuar.

**Decisiones que apoya.** Negociar con la pasarela de tarjeta de crédito, sugerir Nequi o PSE en el checkout cuando falla la tarjeta, y decidir si ampliar el pago contraentrega.

**Hallazgo.** La **tarjeta de crédito** rechaza el 14,3 % de los intentos (≈ $64 M rechazados). Nequi solo rechaza el 7 %.

**Impacto.** Mejor tasa de conversión del checkout y menos carritos abandonados.

---

## Modificaciones típicas para la sustentación

| Pedido del profesor | Cambio |
|---|---|
| "Top 5 en vez de 10" o "solo 2025" | C1: `$limit: 5` o `fecha: {$gte: ISODate("2025-01-01"), $lt: ISODate("2026-01-01")}` |
| "Solo una categoría" | C1: después del `$lookup` a categorías, `{ $match: { "categoria.nombre": "Tecnología" } }` |
| "Agregar la ciudad de envío" | C4: en `$project`, `departamento: "$direccion_envio.departamento"`, y agrupar por `{t: "$transportadora", d: "$departamento"}` |
| "Incluir clientes Oro" | C3: quitar el `$match` de segmento |
| "Umbral de stock 50" | C6: `stock: { $lte: 50 }` |
| "Solo pagos de 2026" | C7: antes del `$unwind`, `{ $match: { fecha: { $gte: ISODate("2026-01-01") } } }` |
| "Ver el pedido completo de un cliente con nombre de cliente" | `db.pedidos.aggregate([{ $match: { cliente_id: 45 } }, { $lookup: { from: "clientes", localField: "cliente_id", foreignField: "_id", as: "cliente" } }])` |
