"""
Motor de migración: lee las tablas, arma los documentos según el Plan y los carga en MongoDB.

Pasos:
  1. Leer cada tabla completa (SELECT *), ordenada por su llave primaria.
  2. Convertir cada fila en un documento (tipos de SQL Server -> tipos BSON).
  3. Embeber: cada fila hija se agrega al documento de su padre (array o subdocumento),
     usando un índice en memoria por la llave referenciada. Los embebidos pueden anidarse.
  4. Insertar las colecciones raíz en lotes y crear índices sobre las referencias.

Las filas hijas cuya llave foránea es NULL no tienen padre donde embeberse: se guardan
en una colección "<tabla>_sin_padre" para no perder información.
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, time as dtime
from decimal import Decimal

from bson import Binary
from bson.decimal128 import Decimal128
from pymongo import ASCENDING
from pymongo.errors import DocumentTooLarge

from .esquema import Esquema
from .nombres import snake
from .propuesta import ARRAY, COLECCION, Plan

LOTE = 1000


class MigracionCancelada(Exception):
    pass


@dataclass
class Resultado:
    documentos: dict[str, int] = field(default_factory=dict)       # colección -> documentos insertados
    embebidos: dict[str, int] = field(default_factory=dict)        # tabla -> filas embebidas
    sin_padre: dict[str, tuple[str, int]] = field(default_factory=dict)  # tabla -> (colección, filas)
    indices: dict[str, list[str]] = field(default_factory=dict)
    advertencias: list[str] = field(default_factory=list)
    segundos: float = 0.0


# ---------------------------------------------------------------- conversión de tipos
def convertir(v):
    if v is None or isinstance(v, (bool, int, float, str, datetime)):
        return v
    if isinstance(v, Decimal):
        return Decimal128(v)            # precisión exacta para dinero y DECIMAL
    if isinstance(v, date):
        return datetime(v.year, v.month, v.day)   # MongoDB no tiene tipo solo-fecha
    if isinstance(v, dtime):
        return v.isoformat()
    if isinstance(v, (bytes, bytearray, memoryview)):
        return Binary(bytes(v))
    if isinstance(v, uuid.UUID):
        return str(v)
    return str(v)


def llave(valores) -> tuple:
    """Llave de emparejamiento: SQL Server compara textos sin mayúsculas ni espacios finales."""
    return tuple(v.rstrip().casefold() if isinstance(v, str) else v for v in valores)


# ---------------------------------------------------------------- rutas dentro de los documentos
def ruta_campo(esquema: Esquema, plan: Plan, tabla: str, columna: str):
    """(colección raíz, ruta con puntos al campo, segmentos [(campo, es_array)] hasta la tabla)."""
    raiz = plan.raiz(esquema, tabla)
    segmentos = plan.ruta(esquema, tabla)
    t, d = esquema.tablas[tabla], plan.decisiones[tabla]
    if d.modo == COLECCION and columna in t.pk:
        final = "_id" if len(t.pk) == 1 else "_id." + plan.campo(columna)
    else:
        final = plan.campo(columna)
    prefijo = ".".join(c for c, _ in segmentos)
    return plan.decisiones[raiz].nombre, (prefijo + "." if prefijo else "") + final, segmentos


def desenrollar(segmentos) -> list[dict]:
    """Etapas para llegar a los elementos de una tabla embebida ($unwind por cada array)."""
    etapas, prefijo = [], ""
    for campo, es_array in segmentos:
        completo = prefijo + campo
        etapas.append({"$unwind": "$" + completo} if es_array else {"$match": {completo: {"$exists": True}}})
        prefijo = completo + "."
    return etapas


def columnas_omitidas(esquema: Esquema, plan: Plan, tabla: str) -> set[str]:
    """Columnas que no se copian: la FK hacia el padre que la contiene (queda implícita)."""
    d = plan.decisiones[tabla]
    return set(esquema.fk(d.fk).columnas_hija) if d.modo != COLECCION else set()


def esqueleto_documento(esquema: Esquema, plan: Plan, tabla: str) -> dict:
    """Estructura de un documento (campos y tipos) para la vista previa del modelo."""
    t, d = esquema.tablas[tabla], plan.decisiones[tabla]
    omitir = columnas_omitidas(esquema, plan, tabla)
    referencias = {fk.columnas_hija[0]: esquema.tablas[fk.padre].nombre
                   for fk in esquema.fks if fk.hija == tabla and len(fk.columnas_hija) == 1}
    doc = {}
    if d.modo == COLECCION and t.pk:
        tipos = {c: t.columna(c).tipo for c in t.pk}
        doc["_id"] = tipos[t.pk[0]] if len(t.pk) == 1 else {plan.campo(c): tipos[c] for c in t.pk}
        omitir = omitir | set(t.pk)
    for c in t.columnas:
        if c.nombre in omitir:
            continue
        valor = c.tipo + (" | null" if c.nula else "")
        if c.nombre in referencias:
            valor += f"  → referencia a {referencias[c.nombre]}"
        doc[plan.campo(c.nombre)] = valor
    for hija in plan.hijos(esquema, tabla):
        dh = plan.decisiones[hija]
        sub = esqueleto_documento(esquema, plan, hija)
        doc[dh.nombre] = [sub] if dh.modo == ARRAY else sub
    return doc


def nombre_sin_padre(plan: Plan, esquema: Esquema, tabla: str) -> str:
    t = esquema.tablas[tabla]
    base = snake(t.nombre) if plan.snake_case else t.nombre
    return f"{base}_sin_padre"


# ---------------------------------------------------------------- migrador
class Migrador:
    def __init__(self, con, db, esquema: Esquema, plan: Plan, progreso=None, cancelado=None):
        self.con, self.db, self.esquema, self.plan = con, db, esquema, plan
        self.progreso = progreso or (lambda msg, pct: None)
        self.cancelado = cancelado or (lambda: False)

    def _avisar(self, msg, pct):
        if self.cancelado():
            raise MigracionCancelada("Migración cancelada por el usuario.")
        self.progreso(msg, pct)

    def _documento(self, tabla: str, columnas: list[str], fila, completa: bool = False) -> dict:
        t, d, plan = self.esquema.tablas[tabla], self.plan.decisiones[tabla], self.plan
        omitir = set() if completa else columnas_omitidas(self.esquema, plan, tabla)
        doc = {}
        if d.modo == COLECCION and t.pk and not completa:
            if len(t.pk) == 1:
                doc["_id"] = convertir(fila[columnas.index(t.pk[0])])
            else:
                doc["_id"] = {plan.campo(c): convertir(fila[columnas.index(c)]) for c in t.pk}
            omitir |= set(t.pk)
        for i, c in enumerate(columnas):
            if c in omitir:
                continue
            v = convertir(fila[i])
            if v is None and plan.omitir_nulos:
                continue
            doc[plan.campo(c)] = v
        return doc

    def ejecutar(self) -> Resultado:
        inicio = time.perf_counter()
        errores = self.plan.errores(self.esquema)
        if errores:
            raise ValueError("El plan tiene errores:\n" + "\n".join(errores))
        res = Resultado()
        cur = self.con.cursor()
        tablas = list(self.esquema.tablas.values())

        if not self.plan.reemplazar:
            existentes = set(self.db.list_collection_names())
            choques = [self.plan.decisiones[t].nombre for t in self.plan.colecciones()
                       if self.plan.decisiones[t].nombre in existentes]
            if choques:
                raise ValueError(f"Ya existen las colecciones {', '.join(choques)} en '{self.db.name}'. "
                                 f"Active 'Reemplazar colecciones existentes' o elija otra base destino.")

        # 1-2. leer y convertir
        filas, docs = {}, {}
        for i, t in enumerate(tablas, 1):
            self._avisar(f"Leyendo {t.clave} ({t.filas:,} filas)".replace(",", "."), int(i / len(tablas) * 40))
            orden = " ORDER BY " + ", ".join(f"[{c}]" for c in t.pk) if t.pk else ""
            cur.execute(f"SELECT * FROM {t.sql}{orden}")
            columnas = [c[0] for c in cur.description]
            datos = cur.fetchall()
            filas[t.clave] = (columnas, datos)
            docs[t.clave] = [self._documento(t.clave, columnas, f) for f in datos]

        # 3. embeber cada tabla hija dentro de su padre
        self._avisar("Embebiendo tablas hijas en sus documentos padre", 42)
        indices_padre = {}
        for tabla, d in self.plan.decisiones.items():
            if d.modo == COLECCION:
                continue
            fk = self.esquema.fk(d.fk)
            col_p, datos_p = filas[fk.padre]
            clave_idx = (fk.padre, tuple(fk.columnas_padre))
            if clave_idx not in indices_padre:
                pos = [col_p.index(c) for c in fk.columnas_padre]
                indices_padre[clave_idx] = {llave(f[p] for p in pos): doc
                                            for f, doc in zip(datos_p, docs[fk.padre])}
            indice = indices_padre[clave_idx]
            if d.modo == ARRAY:
                for doc_p in docs[fk.padre]:
                    doc_p.setdefault(d.nombre, [])
            col_h, datos_h = filas[tabla]
            pos_h = [col_h.index(c) for c in fk.columnas_hija]
            huerfanas = []
            for f, doc in zip(datos_h, docs[tabla]):
                valores = [f[p] for p in pos_h]
                padre = None if any(v is None for v in valores) else indice.get(llave(valores))
                if padre is None:
                    huerfanas.append(self._documento(tabla, col_h, f, completa=True))
                elif d.modo == ARRAY:
                    padre[d.nombre].append(doc)
                else:
                    if d.nombre in padre:
                        raise ValueError(f"{tabla} se configuró como subdocumento, pero un mismo "
                                         f"{fk.padre} tiene más de una fila. Use array.")
                    padre[d.nombre] = doc
            res.embebidos[tabla] = len(datos_h) - len(huerfanas)
            if huerfanas:
                nombre = nombre_sin_padre(self.plan, self.esquema, tabla)
                res.sin_padre[tabla] = (nombre, len(huerfanas))
                docs[f"__sin_padre__{tabla}"] = huerfanas
                res.advertencias.append(f"{len(huerfanas)} filas de {tabla} no tienen padre; se guardaron "
                                        f"en la colección '{nombre}'.")

        # 4. insertar colecciones raíz (y las de filas sin padre)
        destinos = [(self.plan.decisiones[t].nombre, docs[t]) for t in self.plan.colecciones()]
        destinos += [(nombre, docs[f"__sin_padre__{t}"]) for t, (nombre, _) in res.sin_padre.items()]
        total_docs = max(1, sum(len(lista) for _, lista in destinos))
        hechos = 0
        for nombre, lista in destinos:
            if self.plan.reemplazar:
                self.db.drop_collection(nombre)
            self.db.create_collection(nombre)
            for i in range(0, len(lista), LOTE):
                self._avisar(f"Insertando en {nombre}", 45 + int(hechos / total_docs * 45))
                try:
                    self.db[nombre].insert_many(lista[i:i + LOTE], ordered=True)
                except DocumentTooLarge as e:
                    raise ValueError(f"Un documento de '{nombre}' supera 16 MB. Cambie alguna tabla embebida "
                                     f"en '{nombre}' a colección propia (referencing).") from e
                hechos += len(lista[i:i + LOTE])
            res.documentos[nombre] = len(lista)

        # 5. índices sobre referencias, llaves únicas y elementos embebidos referenciados
        self._avisar("Creando índices", 92)
        self._crear_indices(res)
        res.segundos = time.perf_counter() - inicio
        self._avisar(f"Migración terminada en {res.segundos:.1f} s", 100)
        return res

    def _crear_indices(self, res: Resultado):
        e, plan = self.esquema, self.plan

        def crear(coleccion, campos, unico=False, parcial=None):
            if campos == ["_id"]:
                return
            opciones = {"unique": True} if unico else {}
            if parcial:
                opciones["partialFilterExpression"] = parcial
            nombre = self.db[coleccion].create_index([(c, ASCENDING) for c in campos], **opciones)
            res.indices.setdefault(coleccion, [])
            if nombre not in res.indices[coleccion]:
                res.indices[coleccion].append(nombre)

        for tabla, d in plan.decisiones.items():
            t = e.tablas[tabla]
            omitidas = columnas_omitidas(e, plan, tabla)
            # referencias que salen de esta tabla
            for fk in e.fks:
                if fk.hija != tabla or set(fk.columnas_hija) & omitidas:
                    continue
                rutas = [ruta_campo(e, plan, tabla, c) for c in fk.columnas_hija]
                crear(rutas[0][0], [r[1] for r in rutas])
            if d.modo == COLECCION:
                for cols in t.unicos:
                    if cols == t.pk:
                        continue
                    rutas = [ruta_campo(e, plan, tabla, c)[1] for c in cols]
                    nulas = any(t.columna(c).nula for c in cols)
                    if nulas and not plan.omitir_nulos:
                        crear(d.nombre, rutas)
                    else:
                        crear(d.nombre, rutas, unico=True,
                              parcial={r: {"$exists": True} for r in rutas} if nulas else None)
            else:
                # si otra tabla referencia a esta tabla embebida, se indexa la llave referenciada
                for fk in e.entrantes(tabla):
                    if len(fk.columnas_padre) == 1 and not set(fk.columnas_padre) & omitidas:
                        col, ruta, _ = ruta_campo(e, plan, tabla, fk.columnas_padre[0])
                        crear(col, [ruta])
