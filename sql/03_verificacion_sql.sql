/* =====================================================================
   Taller 3 - Bases de Datos II  |  Script 03: verificación del modelo relacional
   Conteo por tabla, total de registros y controles de coherencia.
   Ejecutar con:  sqlcmd -S .\SQLEXPRESS -E -C -f 65001 -i sql\03_verificacion_sql.sql
   ===================================================================== */
USE TiendaOnline;
SET NOCOUNT ON;
GO

PRINT '== Registros por tabla ==';
SELECT Tabla, Registros FROM (
    SELECT 'Categorias'    AS Tabla, COUNT(*) AS Registros, 1  AS Orden FROM dbo.Categorias    UNION ALL
    SELECT 'Proveedores',            COUNT(*),              2           FROM dbo.Proveedores   UNION ALL
    SELECT 'Productos',              COUNT(*),              3           FROM dbo.Productos     UNION ALL
    SELECT 'Clientes',               COUNT(*),              4           FROM dbo.Clientes      UNION ALL
    SELECT 'Direcciones',            COUNT(*),              5           FROM dbo.Direcciones   UNION ALL
    SELECT 'Pedidos',                COUNT(*),              6           FROM dbo.Pedidos       UNION ALL
    SELECT 'DetallePedido',          COUNT(*),              7           FROM dbo.DetallePedido UNION ALL
    SELECT 'Pagos',                  COUNT(*),              8           FROM dbo.Pagos         UNION ALL
    SELECT 'Envios',                 COUNT(*),              9           FROM dbo.Envios        UNION ALL
    SELECT 'Resenas',                COUNT(*),              10          FROM dbo.Resenas
) t ORDER BY Orden;

SELECT SUM(n) AS TotalRegistros FROM (
    SELECT COUNT(*) n FROM dbo.Categorias UNION ALL SELECT COUNT(*) FROM dbo.Proveedores UNION ALL
    SELECT COUNT(*)   FROM dbo.Productos  UNION ALL SELECT COUNT(*) FROM dbo.Clientes    UNION ALL
    SELECT COUNT(*)   FROM dbo.Direcciones UNION ALL SELECT COUNT(*) FROM dbo.Pedidos    UNION ALL
    SELECT COUNT(*)   FROM dbo.DetallePedido UNION ALL SELECT COUNT(*) FROM dbo.Pagos    UNION ALL
    SELECT COUNT(*)   FROM dbo.Envios     UNION ALL SELECT COUNT(*) FROM dbo.Resenas) x;

PRINT '== Controles de coherencia (todos deben ser 0) ==';
SELECT 'Pedidos cuyo subtotal no cuadra con el detalle' AS Control, COUNT(*) AS Casos
FROM dbo.Pedidos p
WHERE p.Subtotal <> (SELECT SUM(d.Subtotal) FROM dbo.DetallePedido d WHERE d.PedidoID = p.PedidoID)
UNION ALL
SELECT 'Pedidos con direccion de otro cliente', COUNT(*)
FROM dbo.Pedidos p JOIN dbo.Direcciones d ON d.DireccionID = p.DireccionID
WHERE d.ClienteID <> p.ClienteID
UNION ALL
SELECT 'Pedidos Entregados sin envio entregado', COUNT(*)
FROM dbo.Pedidos p LEFT JOIN dbo.Envios e ON e.PedidoID = p.PedidoID AND e.Estado = 'Entregado'
WHERE p.Estado = 'Entregado' AND e.EnvioID IS NULL
UNION ALL
SELECT 'Pedidos Pagado/Enviado/Entregado sin pago aprobado', COUNT(*)
FROM dbo.Pedidos p
WHERE p.Estado IN ('Pagado','Enviado','Entregado')
  AND NOT EXISTS (SELECT 1 FROM dbo.Pagos g WHERE g.PedidoID = p.PedidoID AND g.Estado = 'Aprobado')
UNION ALL
SELECT 'Resenas de productos no recibidos por el cliente', COUNT(*)
FROM dbo.Resenas r
WHERE NOT EXISTS (SELECT 1 FROM dbo.Pedidos p JOIN dbo.DetallePedido d ON d.PedidoID = p.PedidoID
                  WHERE p.ClienteID = r.ClienteID AND d.ProductoID = r.ProductoID AND p.Estado = 'Entregado');

PRINT '== Distribucion de pedidos por estado ==';
SELECT Estado, COUNT(*) AS Pedidos, SUM(Total) AS Valor FROM dbo.Pedidos GROUP BY Estado ORDER BY Pedidos DESC;
GO
