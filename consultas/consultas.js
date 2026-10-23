

const ESTADOS_VENTA = ["Pagado", "Enviado", "Entregado"];   // pedidos con pago aprobado
const redondear = (expr, dec = 0) => ({ $round: [{ $toDouble: expr }, dec] });

const consultas = [


  {
    titulo: "C1. Top 10 productos por ingresos en 2026 (con categoría, proveedor y margen)",
    coleccion: "pedidos",
    pipeline: [
      { $match: { estado: { $in: ESTADOS_VENTA },
                  fecha: { $gte: ISODate("2026-01-01"), $lt: ISODate("2027-01-01") } } },
      { $unwind: "$items" },
      { $group: { _id: "$items.producto_id",
                  unidades: { $sum: "$items.cantidad" },
                  ingresos: { $sum: "$items.subtotal" },
                  pedidos:  { $sum: 1 } } },
      { $sort: { ingresos: -1 } },
      { $limit: 10 },
      { $lookup: { from: "productos", localField: "_id", foreignField: "_id", as: "producto" } },
      { $unwind: "$producto" },
      { $lookup: { from: "categorias", localField: "producto.categoria_id", foreignField: "_id", as: "categoria" } },
      { $unwind: "$categoria" },
      { $lookup: { from: "proveedores", localField: "producto.proveedor_id", foreignField: "_id", as: "proveedor" } },
      { $unwind: "$proveedor" },
      { $project: {
          _id: 0,
          sku: "$producto.sku",
          producto: "$producto.nombre",
          categoria: "$categoria.nombre",
          proveedor: "$proveedor.razon_social",
          pedidos: 1,
          unidades: 1,
          ingresos: redondear("$ingresos"),
          margen_bruto: redondear({ $subtract: ["$ingresos", { $multiply: ["$unidades", "$producto.costo"] }] }),
          stock_actual: "$producto.stock" } }
    ]
  },


  {
    titulo: "C2. Ingresos, margen bruto y % de margen por categoría",
    coleccion: "pedidos",
    pipeline: [
      { $match: { estado: { $in: ESTADOS_VENTA } } },
      { $unwind: "$items" },
      { $lookup: { from: "productos", localField: "items.producto_id", foreignField: "_id", as: "p",
                   pipeline: [{ $project: { categoria_id: 1, costo: 1 } }] } },
      { $unwind: "$p" },
      { $group: { _id: "$p.categoria_id",
                  unidades: { $sum: "$items.cantidad" },
                  ingresos: { $sum: "$items.subtotal" },
                  costo:    { $sum: { $multiply: ["$items.cantidad", "$p.costo"] } },
                  pedidos:  { $addToSet: "$_id" } } },
      { $lookup: { from: "categorias", localField: "_id", foreignField: "_id", as: "categoria" } },
      { $unwind: "$categoria" },
      { $project: {
          _id: 0,
          categoria: "$categoria.nombre",
          pedidos: { $size: "$pedidos" },
          unidades: 1,
          ingresos: redondear("$ingresos"),
          margen_bruto: redondear({ $subtract: ["$ingresos", "$costo"] }),
          margen_pct: redondear({ $multiply: [{ $divide: [{ $subtract: ["$ingresos", "$costo"] }, "$ingresos"] }, 100] }, 1) } },
      { $sort: { margen_bruto: -1 } }
    ]
  },


  {
    titulo: "C3. Top 15 clientes no-Oro por valor comprado (candidatos a upgrade de segmento)",
    coleccion: "pedidos",
    pipeline: [
      { $match: { estado: "Entregado" } },
      { $group: { _id: "$cliente_id",
                  total_comprado: { $sum: "$totales.total" },
                  pedidos: { $sum: 1 },
                  ultima_compra: { $max: "$fecha" } } },
      { $lookup: { from: "clientes", localField: "_id", foreignField: "_id", as: "cliente" } },
      { $unwind: "$cliente" },
      { $match: { "cliente.segmento": { $ne: "Oro" } } },
      { $sort: { total_comprado: -1 } },
      { $limit: 15 },
      { $project: {
          _id: 0,
          cliente_id: "$_id",
          nombre: { $concat: ["$cliente.nombres", " ", "$cliente.apellidos"] },
          email: "$cliente.email",
          segmento_actual: "$cliente.segmento",
          ciudad: { $arrayElemAt: ["$cliente.direcciones.ciudad",
                                   { $indexOfArray: ["$cliente.direcciones.es_principal", true] }] },
          pedidos: 1,
          total_comprado: redondear("$total_comprado"),
          ticket_promedio: redondear({ $divide: ["$total_comprado", "$pedidos"] }),
          ultima_compra: { $dateToString: { format: "%Y-%m-%d", date: "$ultima_compra" } } } }
    ]
  },


  {
    titulo: "C4. Desempeño de transportadoras: días promedio de entrega y % de entregas tarde",
    coleccion: "pedidos",
    pipeline: [
      { $match: { "envio.estado": "Entregado" } },
      { $project: {
          transportadora: "$envio.transportadora",
          dias: { $divide: [{ $dateDiff: { startDate: "$envio.fecha_despacho",
                                           endDate: "$envio.fecha_entrega", unit: "hour" } }, 24] },
          // tarde = llegó en un día calendario posterior al prometido
          tarde: { $cond: [{ $gt: [{ $dateDiff: { startDate: "$envio.fecha_entrega_estimada",
                                                  endDate: "$envio.fecha_entrega", unit: "day" } }, 0] }, 1, 0] },
          valor: "$totales.total" } },
      { $group: { _id: "$transportadora",
                  envios: { $sum: 1 },
                  dias_promedio: { $avg: "$dias" },
                  dias_maximo: { $max: "$dias" },
                  entregas_tarde: { $sum: "$tarde" },
                  valor_transportado: { $sum: "$valor" } } },
      { $project: {
          _id: 0,
          transportadora: "$_id",
          envios: 1,
          dias_promedio: { $round: ["$dias_promedio", 1] },
          dias_maximo: { $round: ["$dias_maximo", 1] },
          entregas_tarde: 1,
          pct_tarde: { $round: [{ $multiply: [{ $divide: ["$entregas_tarde", "$envios"] }, 100] }, 1] },
          valor_transportado: redondear("$valor_transportado") } },
      { $sort: { pct_tarde: -1 } }
    ]
  },

  {
    titulo: "C5. Productos mal calificados (promedio < 3 con al menos 3 reseñas) y su proveedor",
    coleccion: "resenas",
    pipeline: [
      { $group: { _id: "$producto_id",
                  promedio: { $avg: "$calificacion" },
                  resenas: { $sum: 1 },
                  negativas: { $sum: { $cond: [{ $lte: ["$calificacion", 2] }, 1, 0] } } } },
      { $match: { resenas: { $gte: 3 }, promedio: { $lt: 3 } } },
      { $lookup: { from: "productos", localField: "_id", foreignField: "_id", as: "producto" } },
      { $unwind: "$producto" },
      { $lookup: { from: "categorias", localField: "producto.categoria_id", foreignField: "_id", as: "categoria" } },
      { $unwind: "$categoria" },
      { $lookup: { from: "proveedores", localField: "producto.proveedor_id", foreignField: "_id", as: "proveedor" } },
      { $unwind: "$proveedor" },
      { $lookup: { from: "resenas", let: { pid: "$_id" }, as: "quejas_recientes",
                   pipeline: [
                     { $match: { $expr: { $eq: ["$producto_id", "$$pid"] },
                                 calificacion: { $lte: 2 }, comentario: { $exists: true } } },
                     { $sort: { fecha: -1 } },
                     { $limit: 2 },
                     { $project: { _id: 0, calificacion: 1, comentario: 1 } } ] } },
      { $project: {
          _id: 0,
          sku: "$producto.sku",
          producto: "$producto.nombre",
          categoria: "$categoria.nombre",
          proveedor: "$proveedor.razon_social",
          contacto_proveedor: "$proveedor.contacto.email",
          promedio: { $round: ["$promedio", 2] },
          resenas: 1,
          pct_negativas: { $round: [{ $multiply: [{ $divide: ["$negativas", "$resenas"] }, 100] }, 0] },
          quejas_recientes: 1 } },
      { $sort: { promedio: 1, resenas: -1 } }
    ]
  },


  {
    titulo: "C6. Riesgo de quiebre de stock: días de inventario restantes según ventas de los últimos 90 días",
    coleccion: "productos",
    pipeline: [
      { $match: { activo: true, stock: { $lte: 20 } } },
      { $lookup: { from: "pedidos", let: { pid: "$_id" }, as: "ventas",
                   pipeline: [
                     { $match: { fecha: { $gte: ISODate("2026-07-02") }, estado: { $ne: "Cancelado" },
                                 $expr: { $in: ["$$pid", "$items.producto_id"] } } },
                     { $unwind: "$items" },
                     { $match: { $expr: { $eq: ["$items.producto_id", "$$pid"] } } },
                     { $group: { _id: null, unidades: { $sum: "$items.cantidad" }, pedidos: { $sum: 1 } } } ] } },
      { $unwind: "$ventas" },      // descarta productos sin ventas recientes: no hay urgencia
      { $lookup: { from: "proveedores", localField: "proveedor_id", foreignField: "_id", as: "proveedor" } },
      { $unwind: "$proveedor" },
      { $project: {
          _id: 0,
          sku: 1,
          producto: "$nombre",
          stock: 1,
          vendidas_90d: "$ventas.unidades",
          venta_diaria: { $round: [{ $divide: ["$ventas.unidades", 90] }, 2] },
          dias_de_inventario: { $round: [{ $divide: ["$stock", { $divide: ["$ventas.unidades", 90] }] }, 0] },
          proveedor: "$proveedor.razon_social",
          contacto_proveedor: "$proveedor.contacto.email" } },
      { $sort: { dias_de_inventario: 1, vendidas_90d: -1 } },
      { $limit: 15 }
    ]
  },

 
  {
    titulo: "C7. Tasa de rechazo por método de pago y monto rechazado",
    coleccion: "pedidos",
    pipeline: [
      { $unwind: "$pagos" },
      { $group: { _id: "$pagos.metodo",
                  intentos: { $sum: 1 },
                  aprobados: { $sum: { $cond: [{ $eq: ["$pagos.estado", "Aprobado"] }, 1, 0] } },
                  rechazados: { $sum: { $cond: [{ $eq: ["$pagos.estado", "Rechazado"] }, 1, 0] } },
                  monto_aprobado: { $sum: { $cond: [{ $eq: ["$pagos.estado", "Aprobado"] }, "$pagos.monto", 0] } },
                  monto_rechazado: { $sum: { $cond: [{ $eq: ["$pagos.estado", "Rechazado"] }, "$pagos.monto", 0] } } } },
      { $project: {
          _id: 0,
          metodo: "$_id",
          intentos: 1,
          aprobados: 1,
          rechazados: 1,
          tasa_rechazo_pct: { $round: [{ $multiply: [{ $divide: ["$rechazados", "$intentos"] }, 100] }, 1] },
          monto_aprobado: redondear("$monto_aprobado"),
          monto_rechazado: redondear("$monto_rechazado") } },
      { $sort: { tasa_rechazo_pct: -1 } }
    ]
  }
];


consultas.forEach((c, i) => {
  if (typeof SOLO !== "undefined" && SOLO !== i + 1) return;
  print("\n" + "=".repeat(100));
  print(c.titulo);
  print("Colección: " + c.coleccion);
  print("=".repeat(100));
  const resultado = db.getCollection(c.coleccion).aggregate(c.pipeline).toArray();
  resultado.forEach(doc => printjson(doc));
  print(`(${resultado.length} documentos)`);
});
