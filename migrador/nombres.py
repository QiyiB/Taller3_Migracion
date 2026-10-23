"""Utilidades para convertir nombres de SQL Server en nombres de campos de MongoDB."""
import re


def snake(nombre: str) -> str:
    """FechaPedido -> fecha_pedido, ClienteID -> cliente_id, SKU -> sku."""
    s = re.sub(r"[\s\-\.]+", "_", nombre.strip())
    s = re.sub(r"([a-z0-9áéíóúñ])([A-ZÁÉÍÓÚÑ])", r"\1_\2", s)
    s = re.sub(r"([A-ZÁÉÍÓÚÑ]+)([A-ZÁÉÍÓÚÑ][a-záéíóúñ])", r"\1_\2", s)
    return re.sub(r"_+", "_", s).strip("_").lower()


def raiz(nombre: str) -> str:
    """Raíz aproximada para comparar nombres: Pedidos -> pedido, Direcciones -> direccion."""
    n = nombre.lower()
    if n.endswith("es") and len(n) > 5:
        return n[:-2]
    if n.endswith("s") and len(n) > 4:
        return n[:-1]
    return n


def singular(nombre: str) -> str:
    """Singular aproximado (español/inglés) para nombrar subdocumentos: envios -> envio."""
    n = nombre
    if n.endswith("iones"):
        return n[:-2]
    if n.endswith("ces") and len(n) > 4:
        return n[:-3] + "z"
    if n.endswith(("sses", "shes", "ches")):
        return n[:-2]
    if n.endswith("ies") and len(n) > 4:
        return n[:-3] + "y"
    if n.endswith("s") and not n.endswith("ss") and len(n) > 3:
        return n[:-1]
    return n


def corchetes(*partes: str) -> str:
    """Identificador de SQL Server entre corchetes: [dbo].[Mi Tabla]."""
    return ".".join("[" + p.replace("]", "]]") + "]" for p in partes)
