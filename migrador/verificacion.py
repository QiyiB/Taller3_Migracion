"""
Verificación genérica: compara SQL Server con MongoDB después de migrar.

  1. Conteos: cada tabla contra su colección o contra sus elementos embebidos ($unwind).
  2. Sumas de control: columnas numéricas (no llaves) deben sumar lo mismo en ambos motores.
  3. Integridad referencial: cada referencia que quedó como campo se resuelve con $lookup.
  4. Muestra: filas al azar comparadas campo a campo (o localizadas, si están embebidas).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from bson.decimal128 import Decimal128

from .esquema import TIPOS_NUMERICOS, Esquema
from .motor import Resultado, columnas_omitidas, convertir, desenrollar, ruta_campo
from .nombres import corchetes
from .propuesta import COLECCION, Plan

MUESTRA = 3
MAX_SUMAS_POR_TABLA = 3


@dataclass
class Control:
    categoria: str
    descripcion: str
    esperado: object
    obtenido: object
    ok: bool | None      # None = no verificable (se informa, no cuenta como falla)


def _num(v) -> Decimal:
    if v is None:
        return Decimal(0)
    if isinstance(v, Decimal128):
        return v.to_decimal()
    return Decimal(str(v))


def _normalizar(v):
    """Valor comparable: Decimal128 -> Decimal y fechas a milisegundos (precisión de MongoDB)."""
    if isinstance(v, Decimal128):
        return v.to_decimal()
    if isinstance(v, datetime):
        return v.replace(microsecond=v.microsecond // 1000 * 1000, tzinfo=None)
    return v


def _contar(db, coleccion, segmentos) -> int:
    if not segmentos:
        return db[coleccion].count_documents({})
    r = list(db[coleccion].aggregate(desenrollar(segmentos) + [{"$count": "n"}]))
    return r[0]["n"] if r else 0


def verificar(con, db, esquema: Esquema, plan: Plan, resultado: Resultado | None = None,
              progreso=None) -> list[Control]:
    avisar = progreso or (lambda msg, pct: None)
    cur = con.cursor()
    controles: list[Control] = []
    sin_padre = resultado.sin_padre if resultado else {}
    tablas = list(esquema.tablas)

    # 1. conteos
    for i, tabla in enumerate(tablas, 1):
        avisar(f"Conteo de {tabla}", int(i / len(tablas) * 25))
        t, d = esquema.tablas[tabla], plan.decisiones[tabla]
        coleccion, _, segmentos = ruta_campo(esquema, plan, tabla, t.columnas[0].nombre)
        huerfanas = sin_padre.get(tabla, (None, 0))[1]
        destino = coleccion if d.modo == COLECCION else f"{coleccion}.{'.'.join(s for s, _ in segmentos)}"
        controles.append(Control("Conteos", f"{t.nombre} → {destino}", t.filas - huerfanas,
                                 _contar(db, coleccion, segmentos), None))
        if huerfanas:
            nombre = sin_padre[tabla][0]
            controles.append(Control("Conteos", f"{t.nombre} sin padre → {nombre}", huerfanas,
                                     db[nombre].count_documents({}), None))
    for c in controles:
        c.ok = c.esperado == c.obtenido

    # 2. sumas de control
    for i, tabla in enumerate(tablas, 1):
        avisar(f"Sumas de control de {tabla}", 25 + int(i / len(tablas) * 25))
        t = esquema.tablas[tabla]
        llaves = set(t.pk) | {c for fk in esquema.fks if fk.hija == tabla for c in fk.columnas_hija}
        numericas = [c for c in t.columnas if c.tipo in TIPOS_NUMERICOS and c.nombre not in llaves
                     and not c.identidad][:MAX_SUMAS_POR_TABLA]
        for c in numericas:
            aproximado = c.tipo in ("float", "real")
            cast = "FLOAT" if aproximado else "DECIMAL(38, 6)"
            cur.execute(f"SELECT SUM(CAST({corchetes(c.nombre)} AS {cast})) FROM {t.sql}")
            esperado = _num(cur.fetchone()[0])
            coleccion, ruta, segmentos = ruta_campo(esquema, plan, tabla, c.nombre)
            r = list(db[coleccion].aggregate(desenrollar(segmentos) +
                                              [{"$group": {"_id": None, "s": {"$sum": "$" + ruta}}}]))
            obtenido = _num(r[0]["s"]) if r else Decimal(0)
            if tabla in sin_padre:
                r = list(db[sin_padre[tabla][0]].aggregate(
                    [{"$group": {"_id": None, "s": {"$sum": "$" + plan.campo(c.nombre)}}}]))
                obtenido += _num(r[0]["s"]) if r else Decimal(0)
            ok = (abs(esperado - obtenido) <= Decimal("1e-6") * max(Decimal(1), abs(esperado))
                  if aproximado else esperado == obtenido)
            controles.append(Control("Sumas de control", f"Σ {t.nombre}.{c.nombre}", esperado, obtenido, ok))

    # 3. integridad referencial de las referencias que quedaron como campos
    referencias = [fk for fk in esquema.fks if plan.decisiones[fk.hija].fk != fk.nombre]
    for i, fk in enumerate(referencias, 1):
        avisar(f"Referencia {fk.nombre}", 50 + int(i / max(1, len(referencias)) * 30))
        hija, padre = esquema.tablas[fk.hija], esquema.tablas[fk.padre]
        desc = f"{hija.nombre}.{', '.join(fk.columnas_hija)} → {padre.nombre}"
        if len(fk.columnas_hija) != 1:
            controles.append(Control("Integridad referencial", desc + " (llave compuesta)", "—", "—", None))
            continue
        if fk.columnas_padre[0] in columnas_omitidas(esquema, plan, fk.padre):
            controles.append(Control("Integridad referencial", desc + " (llave implícita en el padre)",
                                     "—", "—", None))
            continue
        col_h, ruta_h, seg_h = ruta_campo(esquema, plan, fk.hija, fk.columnas_hija[0])
        col_p, ruta_p, _ = ruta_campo(esquema, plan, fk.padre, fk.columnas_padre[0])
        pipeline = desenrollar(seg_h) + [
            {"$match": {ruta_h: {"$exists": True, "$ne": None}}},
            {"$lookup": {"from": col_p, "localField": ruta_h, "foreignField": ruta_p, "as": "_ref",
                         "pipeline": [{"$project": {"_id": 1}}, {"$limit": 1}]}},
            {"$match": {"_ref": {"$size": 0}}},
            {"$count": "n"}]
        r = list(db[col_h].aggregate(pipeline))
        huerfanas = r[0]["n"] if r else 0
        controles.append(Control("Integridad referencial", desc + " (referencias sin destino)", 0, huerfanas,
                                 huerfanas == 0))

    # 4. muestra al azar
    for i, tabla in enumerate(tablas, 1):
        avisar(f"Muestra de {tabla}", 80 + int(i / len(tablas) * 20))
        t, d = esquema.tablas[tabla], plan.decisiones[tabla]
        if len(t.pk) != 1 or t.filas == 0:
            continue
        pk = t.pk[0]
        if d.modo == COLECCION:
            cur.execute(f"SELECT TOP {MUESTRA} * FROM {t.sql} ORDER BY NEWID()")
            columnas = [c[0] for c in cur.description]
            iguales = total = 0
            for fila in cur.fetchall():
                doc = db[d.nombre].find_one({"_id": convertir(fila[columnas.index(pk)])}) or {}
                for j, c in enumerate(columnas):
                    if c == pk:
                        continue
                    total += 1
                    esperado = convertir(fila[j])
                    obtenido = doc.get(plan.campo(c))
                    if _normalizar(esperado) == _normalizar(obtenido):
                        iguales += 1
            controles.append(Control("Muestra al azar", f"{t.nombre}: {MUESTRA} filas campo a campo",
                                     total, iguales, iguales == total))
        elif pk not in columnas_omitidas(esquema, plan, tabla):
            coleccion, ruta, _ = ruta_campo(esquema, plan, tabla, pk)
            cur.execute(f"SELECT TOP {MUESTRA} {corchetes(pk)} FROM {t.sql} ORDER BY NEWID()")
            valores = [convertir(r[0]) for r in cur.fetchall()]
            halladas = sum(1 for v in valores if db[coleccion].count_documents({ruta: v}, limit=1))
            controles.append(Control("Muestra al azar", f"{t.nombre}: filas localizadas en {coleccion}.{ruta}",
                                     len(valores), halladas, halladas == len(valores)))
    avisar("Verificación terminada", 100)
    return controles


def resumen(controles: list[Control]) -> tuple[int, int]:
    evaluados = [c for c in controles if c.ok is not None]
    return sum(1 for c in evaluados if c.ok), len(evaluados)


def _fmt(v) -> str:
    """Formato colombiano: punto de miles y coma decimal (1.426.165.610,50)."""
    if isinstance(v, (Decimal, int)) and not isinstance(v, bool):
        texto = f"{Decimal(v).normalize():,f}" if isinstance(v, Decimal) else f"{v:,}"
        return texto.replace(",", "§").replace(".", ",").replace("§", ".")
    return str(v)


def reporte_markdown(controles: list[Control], esquema: Esquema, plan: Plan, destino: str,
                     resultado: Resultado | None = None) -> str:
    ok, total = resumen(controles)
    lineas = [f"# Verificación de la migración {esquema.base} → {destino}", "",
              f"**Resultado: {ok}/{total} controles correctos.**", "", "## Modelo aplicado", "",
              "| Tabla | Decisión | Destino | Justificación |", "|---|---|---|---|"]
    for tabla, d in plan.decisiones.items():
        destino_t = d.nombre if d.modo == COLECCION else \
            f"{plan.decisiones[plan.raiz(esquema, tabla)].nombre}." + ".".join(s for s, _ in plan.ruta(esquema, tabla))
        lineas.append(f"| {tabla} | {d.modo} | `{destino_t}` | {d.razon} |")
    if resultado:
        lineas += ["", f"Migración en {resultado.segundos:.1f} s."]
        lineas += [f"- {a}" for a in resultado.advertencias]
    categoria = None
    for c in controles:
        if c.categoria != categoria:
            categoria = c.categoria
            lineas += ["", f"## {categoria}", "", "| Control | SQL Server / esperado | MongoDB | OK |",
                       "|---|---:|---:|:-:|"]
        marca = "✅" if c.ok else ("➖" if c.ok is None else "❌")
        lineas.append(f"| {c.descripcion} | {_fmt(c.esperado)} | {_fmt(c.obtenido)} | {marca} |")
    return "\n".join(lineas) + "\n"
