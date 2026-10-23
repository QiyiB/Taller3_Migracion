/* =====================================================================
   Taller 3 - Bases de Datos II
   Caso de estudio: Tienda en línea (e-commerce) "TiendaOnline"
   Script 01: creación de la base de datos y de las 10 entidades
   Ejecutar con:  sqlcmd -S .\SQLEXPRESS -E -C -f 65001 -i sql\01_esquema.sql
   ===================================================================== */
SET ANSI_NULLS ON;
SET QUOTED_IDENTIFIER ON;  -- requerido por la columna calculada persistida DetallePedido.Subtotal
GO
USE master;
GO

IF DB_ID(N'TiendaOnline') IS NOT NULL
BEGIN
    ALTER DATABASE TiendaOnline SET SINGLE_USER WITH ROLLBACK IMMEDIATE;
    DROP DATABASE TiendaOnline;
END
GO

CREATE DATABASE TiendaOnline;
GO

USE TiendaOnline;
GO

/* ---------- 1. Categorias: clasificación del catálogo ---------- */
CREATE TABLE dbo.Categorias (
    CategoriaID   INT IDENTITY(1,1) CONSTRAINT PK_Categorias PRIMARY KEY,
    Nombre        NVARCHAR(80)  NOT NULL CONSTRAINT UQ_Categorias_Nombre UNIQUE,
    Descripcion   NVARCHAR(200) NULL
);

/* ---------- 2. Proveedores: quienes abastecen los productos ---------- */
CREATE TABLE dbo.Proveedores (
    ProveedorID   INT IDENTITY(1,1) CONSTRAINT PK_Proveedores PRIMARY KEY,
    RazonSocial   NVARCHAR(120) NOT NULL,
    NIT           VARCHAR(15)   NOT NULL CONSTRAINT UQ_Proveedores_NIT UNIQUE,
    Email         VARCHAR(120)  NOT NULL,
    Telefono      VARCHAR(20)   NULL,
    Ciudad        NVARCHAR(60)  NOT NULL,
    Pais          NVARCHAR(60)  NOT NULL
);

/* ---------- 3. Productos: catálogo vendible ---------- */
CREATE TABLE dbo.Productos (
    ProductoID    INT IDENTITY(1,1) CONSTRAINT PK_Productos PRIMARY KEY,
    SKU           VARCHAR(20)    NOT NULL CONSTRAINT UQ_Productos_SKU UNIQUE,
    Nombre        NVARCHAR(150)  NOT NULL,
    Descripcion   NVARCHAR(300)  NULL,
    Precio        DECIMAL(14,2)  NOT NULL CONSTRAINT CK_Productos_Precio CHECK (Precio > 0),
    Costo         DECIMAL(14,2)  NOT NULL CONSTRAINT CK_Productos_Costo  CHECK (Costo  > 0),
    Stock         INT            NOT NULL CONSTRAINT CK_Productos_Stock  CHECK (Stock >= 0),
    Activo        BIT            NOT NULL CONSTRAINT DF_Productos_Activo DEFAULT (1),
    FechaCreacion DATE           NOT NULL,
    CategoriaID   INT            NOT NULL CONSTRAINT FK_Productos_Categorias  REFERENCES dbo.Categorias(CategoriaID),
    ProveedorID   INT            NOT NULL CONSTRAINT FK_Productos_Proveedores REFERENCES dbo.Proveedores(ProveedorID)
);

/* ---------- 4. Clientes ---------- */
CREATE TABLE dbo.Clientes (
    ClienteID       INT IDENTITY(1,1) CONSTRAINT PK_Clientes PRIMARY KEY,
    Nombres         NVARCHAR(80)  NOT NULL,
    Apellidos       NVARCHAR(80)  NOT NULL,
    Email           VARCHAR(120)  NOT NULL CONSTRAINT UQ_Clientes_Email UNIQUE,
    Telefono        VARCHAR(20)   NULL,
    FechaNacimiento DATE          NULL,
    FechaRegistro   DATETIME2(0)  NOT NULL,
    Segmento        VARCHAR(10)   NOT NULL
        CONSTRAINT CK_Clientes_Segmento CHECK (Segmento IN ('Estandar','Plata','Oro'))
);

/* ---------- 5. Direcciones: un cliente puede tener varias ---------- */
CREATE TABLE dbo.Direcciones (
    DireccionID   INT IDENTITY(1,1) CONSTRAINT PK_Direcciones PRIMARY KEY,
    ClienteID     INT           NOT NULL CONSTRAINT FK_Direcciones_Clientes REFERENCES dbo.Clientes(ClienteID),
    Alias         NVARCHAR(40)  NOT NULL,
    Linea         NVARCHAR(150) NOT NULL,
    Ciudad        NVARCHAR(60)  NOT NULL,
    Departamento  NVARCHAR(60)  NOT NULL,
    CodigoPostal  VARCHAR(10)   NULL,
    EsPrincipal   BIT           NOT NULL CONSTRAINT DF_Direcciones_EsPrincipal DEFAULT (0)
);

/* ---------- 6. Pedidos: encabezado de la compra ---------- */
CREATE TABLE dbo.Pedidos (
    PedidoID      INT IDENTITY(1,1) CONSTRAINT PK_Pedidos PRIMARY KEY,
    ClienteID     INT           NOT NULL CONSTRAINT FK_Pedidos_Clientes    REFERENCES dbo.Clientes(ClienteID),
    DireccionID   INT           NOT NULL CONSTRAINT FK_Pedidos_Direcciones REFERENCES dbo.Direcciones(DireccionID),
    FechaPedido   DATETIME2(0)  NOT NULL,
    Estado        VARCHAR(12)   NOT NULL
        CONSTRAINT CK_Pedidos_Estado CHECK (Estado IN ('Pendiente','Pagado','Enviado','Entregado','Cancelado')),
    Subtotal      DECIMAL(14,2) NOT NULL,
    CostoEnvio    DECIMAL(14,2) NOT NULL,
    Total         DECIMAL(14,2) NOT NULL,
    CONSTRAINT CK_Pedidos_Total CHECK (Total = Subtotal + CostoEnvio)
);

/* ---------- 7. DetallePedido: líneas de cada pedido ---------- */
CREATE TABLE dbo.DetallePedido (
    DetalleID      INT IDENTITY(1,1) CONSTRAINT PK_DetallePedido PRIMARY KEY,
    PedidoID       INT           NOT NULL CONSTRAINT FK_Detalle_Pedidos   REFERENCES dbo.Pedidos(PedidoID),
    ProductoID     INT           NOT NULL CONSTRAINT FK_Detalle_Productos REFERENCES dbo.Productos(ProductoID),
    Cantidad       INT           NOT NULL CONSTRAINT CK_Detalle_Cantidad  CHECK (Cantidad > 0),
    PrecioUnitario DECIMAL(14,2) NOT NULL,
    Descuento      DECIMAL(5,2)  NOT NULL CONSTRAINT DF_Detalle_Descuento DEFAULT (0)
        CONSTRAINT CK_Detalle_Descuento CHECK (Descuento BETWEEN 0 AND 100),
    Subtotal       AS CAST(Cantidad * PrecioUnitario * (100 - Descuento) / 100 AS DECIMAL(14,2)) PERSISTED,
    CONSTRAINT UQ_Detalle_Pedido_Producto UNIQUE (PedidoID, ProductoID)
);

/* ---------- 8. Pagos: intentos de pago de un pedido (1:N) ---------- */
CREATE TABLE dbo.Pagos (
    PagoID      INT IDENTITY(1,1) CONSTRAINT PK_Pagos PRIMARY KEY,
    PedidoID    INT           NOT NULL CONSTRAINT FK_Pagos_Pedidos REFERENCES dbo.Pedidos(PedidoID),
    Metodo      VARCHAR(20)   NOT NULL
        CONSTRAINT CK_Pagos_Metodo CHECK (Metodo IN ('Tarjeta credito','Tarjeta debito','PSE','Nequi','Contraentrega')),
    Estado      VARCHAR(12)   NOT NULL
        CONSTRAINT CK_Pagos_Estado CHECK (Estado IN ('Aprobado','Rechazado','Reembolsado')),
    Monto       DECIMAL(14,2) NOT NULL CONSTRAINT CK_Pagos_Monto CHECK (Monto > 0),
    FechaPago   DATETIME2(0)  NOT NULL,
    Referencia  VARCHAR(30)   NOT NULL CONSTRAINT UQ_Pagos_Referencia UNIQUE
);

/* ---------- 9. Envios: despacho del pedido (1:0..1) ---------- */
CREATE TABLE dbo.Envios (
    EnvioID              INT IDENTITY(1,1) CONSTRAINT PK_Envios PRIMARY KEY,
    PedidoID             INT           NOT NULL CONSTRAINT FK_Envios_Pedidos REFERENCES dbo.Pedidos(PedidoID)
                                       CONSTRAINT UQ_Envios_Pedido UNIQUE,
    Transportadora       NVARCHAR(40)  NOT NULL,
    NumeroGuia           VARCHAR(30)   NOT NULL CONSTRAINT UQ_Envios_Guia UNIQUE,
    FechaDespacho        DATETIME2(0)  NOT NULL,
    FechaEntregaEstimada DATETIME2(0)  NOT NULL,
    FechaEntrega         DATETIME2(0)  NULL,
    Estado               VARCHAR(12)   NOT NULL
        CONSTRAINT CK_Envios_Estado CHECK (Estado IN ('En transito','Entregado','Devuelto'))
);

/* ---------- 10. Resenas: opinión de un cliente sobre un producto ---------- */
CREATE TABLE dbo.Resenas (
    ResenaID      INT IDENTITY(1,1) CONSTRAINT PK_Resenas PRIMARY KEY,
    ProductoID    INT           NOT NULL CONSTRAINT FK_Resenas_Productos REFERENCES dbo.Productos(ProductoID),
    ClienteID     INT           NOT NULL CONSTRAINT FK_Resenas_Clientes  REFERENCES dbo.Clientes(ClienteID),
    Calificacion  TINYINT       NOT NULL CONSTRAINT CK_Resenas_Calificacion CHECK (Calificacion BETWEEN 1 AND 5),
    Comentario    NVARCHAR(400) NULL,
    Fecha         DATETIME2(0)  NOT NULL,
    CONSTRAINT UQ_Resenas_Producto_Cliente UNIQUE (ProductoID, ClienteID)
);
GO

/* Índices sobre llaves foráneas (SQL Server no los crea automáticamente) */
CREATE INDEX IX_Productos_Categoria   ON dbo.Productos(CategoriaID);
CREATE INDEX IX_Productos_Proveedor   ON dbo.Productos(ProveedorID);
CREATE INDEX IX_Direcciones_Cliente   ON dbo.Direcciones(ClienteID);
CREATE INDEX IX_Pedidos_Cliente       ON dbo.Pedidos(ClienteID);
CREATE INDEX IX_Pedidos_Fecha         ON dbo.Pedidos(FechaPedido);
CREATE INDEX IX_Detalle_Producto      ON dbo.DetallePedido(ProductoID);
CREATE INDEX IX_Pagos_Pedido          ON dbo.Pagos(PedidoID);
CREATE INDEX IX_Resenas_Cliente       ON dbo.Resenas(ClienteID);
GO

PRINT 'Esquema TiendaOnline creado correctamente (10 tablas).';
