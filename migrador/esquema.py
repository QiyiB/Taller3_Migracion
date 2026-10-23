"""Lectura del esquema de una base de SQL Server desde las vistas de sistema."""
from __future__ import annotations

from dataclasses import dataclass, field

import pyodbc

from .nombres import corchetes

TIPOS_NUMERICOS = {"decimal", "numeric", "money", "smallmoney", "int", "bigint", "smallint", "tinyint",
                   "float", "real"}


@dataclass
class Columna:
    nombre: str
    tipo: str
    nula: bool
    identidad: bool
    calculada: bool


@dataclass
class LlaveForanea:
    nombre: str
    hija: str                    # clave de la tabla hija ("dbo.DetallePedido")
    columnas_hija: list[str]
    padre: str                   # clave de la tabla padre ("dbo.Pedidos")
    columnas_padre: list[str]
    unica: bool = False          # las columnas de la hija forman una llave única -> relación 1:1
    max_hijos: int = 0           # máximo de filas hijas por fila padre (medido en los datos)
    prom_hijos: float = 0.0
    sin_padre: int = 0           # filas hijas con la llave foránea en NULL

    @property
    def autorreferencia(self) -> bool:
        return self.hija == self.padre


@dataclass
class Tabla:
    esquema: str
    nombre: str
    columnas: list[Columna] = field(default_factory=list)
    pk: list[str] = field(default_factory=list)
    unicos: list[list[str]] = field(default_factory=list)
    filas: int = 0

    @property
    def clave(self) -> str:
        return f"{self.esquema}.{self.nombre}"

    @property
    def sql(self) -> str:
        return corchetes(self.esquema, self.nombre)

    def columna(self, nombre: str) -> Columna:
        return next(c for c in self.columnas if c.nombre == nombre)


@dataclass
class Esquema:
    base: str
    tablas: dict[str, Tabla] = field(default_factory=dict)
    fks: list[LlaveForanea] = field(default_factory=list)

    def salientes(self, tabla: str) -> list[LlaveForanea]:
        """FKs en las que la tabla es la hija (apunta a otra)."""
        return [f for f in self.fks if f.hija == tabla and not f.autorreferencia]

    def entrantes(self, tabla: str) -> list[LlaveForanea]:
        """FKs de otras tablas que apuntan a esta tabla."""
        return [f for f in self.fks if f.padre == tabla and not f.autorreferencia]

    def fk(self, nombre: str) -> LlaveForanea:
        return next(f for f in self.fks if f.nombre == nombre)

    @property
    def total_filas(self) -> int:
        return sum(t.filas for t in self.tablas.values())


# ---------------------------------------------------------------- conexión
def drivers_sql_server() -> list[str]:
    """Drivers ODBC de SQL Server instalados, el más reciente primero (ODBC Driver 18, 17, ...)."""
    candidatos = [d for d in pyodbc.drivers() if "SQL Server" in d]
    return sorted(candidatos, key=lambda d: ("ODBC Driver" in d, d), reverse=True)


def cadena_conexion(servidor: str, base: str = "master", driver: str = "ODBC Driver 18 for SQL Server",
                    windows: bool = True, usuario: str = "", clave: str = "", confiar_certificado: bool = True) -> str:
    partes = [f"DRIVER={{{driver}}}", f"SERVER={servidor}", f"DATABASE={base}"]
    if windows:
        partes.append("Trusted_Connection=yes")
    else:
        partes += [f"UID={usuario}", f"PWD={{{clave.replace('}', '}}')}}}"]
    if confiar_certificado:
        partes.append("TrustServerCertificate=yes")
    return ";".join(partes) + ";"


def conectar(cadena: str) -> pyodbc.Connection:
    con = pyodbc.connect(cadena, autocommit=True, timeout=10)
    # DATETIMEOFFSET (tipo -155) no lo soporta pyodbc de forma nativa: se lee como texto ISO
    con.add_output_converter(-155, lambda v: v.decode("utf-16-le") if isinstance(v, bytes) else v)
    return con


def listar_bases(con: pyodbc.Connection) -> list[str]:
    cur = con.cursor()
    cur.execute("SELECT name FROM sys.databases WHERE database_id > 4 AND state_desc = 'ONLINE' ORDER BY name")
    return [r[0] for r in cur.fetchall()]


# ---------------------------------------------------------------- lectura del esquema
def leer_esquema(con: pyodbc.Connection, estadisticas: bool = True, progreso=None) -> Esquema:
    cur = con.cursor()
    cur.execute("SELECT DB_NAME()")
    esquema = Esquema(base=cur.fetchone()[0])
    avisar = progreso or (lambda *_: None)

    cur.execute("""
        SELECT t.object_id, s.name, t.name
        FROM sys.tables t JOIN sys.schemas s ON s.schema_id = t.schema_id
        WHERE t.is_ms_shipped = 0 AND t.name <> 'sysdiagrams'
        ORDER BY s.name, t.name""")
    por_id = {}
    for oid, sch, nom in cur.fetchall():
        t = Tabla(sch, nom)
        esquema.tablas[t.clave] = t
        por_id[oid] = t

    cur.execute("""
        SELECT c.object_id, c.name, ty.name, c.is_nullable, c.is_identity, c.is_computed
        FROM sys.columns c JOIN sys.types ty ON ty.user_type_id = c.user_type_id
        JOIN sys.tables t ON t.object_id = c.object_id
        ORDER BY c.object_id, c.column_id""")
    for oid, nom, tipo, nula, ident, calc in cur.fetchall():
        if oid in por_id:
            por_id[oid].columnas.append(Columna(nom, tipo.lower(), bool(nula), bool(ident), bool(calc)))

    cur.execute("""
        SELECT i.object_id, i.index_id, i.is_primary_key, c.name
        FROM sys.indexes i
        JOIN sys.index_columns ic ON ic.object_id = i.object_id AND ic.index_id = i.index_id
        JOIN sys.columns c ON c.object_id = ic.object_id AND c.column_id = ic.column_id
        JOIN sys.tables t ON t.object_id = i.object_id
        WHERE (i.is_primary_key = 1 OR i.is_unique = 1) AND ic.is_included_column = 0 AND i.has_filter = 0
        ORDER BY i.object_id, i.index_id, ic.key_ordinal""")
    indices: dict[tuple, tuple[bool, list[str]]] = {}
    for oid, iid, es_pk, col in cur.fetchall():
        indices.setdefault((oid, iid), (bool(es_pk), []))[1].append(col)
    for (oid, _), (es_pk, cols) in indices.items():
        if oid not in por_id:
            continue
        if es_pk:
            por_id[oid].pk = cols
        por_id[oid].unicos.append(cols)

    cur.execute("""
        SELECT fk.name, fk.parent_object_id, fk.referenced_object_id, ch.name, pa.name
        FROM sys.foreign_keys fk
        JOIN sys.foreign_key_columns fkc ON fkc.constraint_object_id = fk.object_id
        JOIN sys.columns ch ON ch.object_id = fkc.parent_object_id AND ch.column_id = fkc.parent_column_id
        JOIN sys.columns pa ON pa.object_id = fkc.referenced_object_id AND pa.column_id = fkc.referenced_column_id
        ORDER BY fk.object_id, fkc.constraint_column_id""")
    fks: dict[str, LlaveForanea] = {}
    for nom, hija, padre, col_h, col_p in cur.fetchall():
        if hija not in por_id or padre not in por_id:
            continue
        fk = fks.setdefault(nom, LlaveForanea(nom, por_id[hija].clave, [], por_id[padre].clave, []))
        fk.columnas_hija.append(col_h)
        fk.columnas_padre.append(col_p)
    esquema.fks = list(fks.values())
    for fk in esquema.fks:
        fk.unica = any(set(u) == set(fk.columnas_hija) for u in esquema.tablas[fk.hija].unicos)

    if estadisticas:
        total = len(esquema.tablas)
        for i, t in enumerate(esquema.tablas.values(), 1):
            avisar(f"Contando filas de {t.clave}", int(i / total * 50))
            cur.execute(f"SELECT COUNT_BIG(*) FROM {t.sql}")
            t.filas = int(cur.fetchone()[0])
        for i, fk in enumerate(esquema.fks, 1):
            avisar(f"Midiendo la relación {fk.nombre}", 50 + int(i / max(1, len(esquema.fks)) * 50))
            medir_relacion(cur, esquema, fk)
    return esquema


def medir_relacion(cur, esquema: Esquema, fk: LlaveForanea) -> None:
    """Cuántas filas hijas tiene cada padre: decide si un array embebido queda acotado."""
    hija = esquema.tablas[fk.hija]
    cols = ", ".join(corchetes(c) for c in fk.columnas_hija)
    no_nulos = " AND ".join(f"{corchetes(c)} IS NOT NULL" for c in fk.columnas_hija)
    algun_nulo = " OR ".join(f"{corchetes(c)} IS NULL" for c in fk.columnas_hija)
    cur.execute(f"""SELECT ISNULL(MAX(n), 0), ISNULL(AVG(CAST(n AS FLOAT)), 0)
                    FROM (SELECT COUNT(*) AS n FROM {hija.sql} WHERE {no_nulos} GROUP BY {cols}) x""")
    fk.max_hijos, fk.prom_hijos = cur.fetchone()
    fk.max_hijos = int(fk.max_hijos)
    cur.execute(f"SELECT COUNT_BIG(*) FROM {hija.sql} WHERE {algun_nulo}")
    fk.sin_padre = int(cur.fetchone()[0])
