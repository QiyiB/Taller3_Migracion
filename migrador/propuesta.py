"""
Propuesta automática del modelo documental.

Cada tabla recibe una de tres decisiones:
  * coleccion     -> colección propia; sus llaves foráneas quedan como referencias.
  * array         -> se embebe como array de documentos dentro de su tabla padre.
  * subdocumento  -> se embebe como un único subdocumento (relación 1:1).

Reglas (en orden), las mismas que justificamos al diseñar TiendaOnline a mano:
  1. Sin llaves foráneas salientes -> entidad independiente o catálogo: colección.
  2. Otras tablas la referencian -> tiene vida propia: colección.
  3. Hoja con un padre "dueño" claro y pocos hijos por padre -> se embebe en ese padre
     (subdocumento si la relación es 1:1, array si es 1:N).
     El dueño se elige por: FK que forma parte de la PK (relación identificadora),
     nombre de la tabla que contiene el del padre (DetallePedido -> Pedidos),
     o ser la única FK.
  4. Hoja que relaciona varias entidades sin dueño claro (por ejemplo Reseñas entre
     Producto y Cliente) -> colección con referencias.
  5. Más de LIMITE_ARRAY hijos por padre -> no se embebe: el documento crecería sin
     límite (máximo 16 MB por documento).
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field

from .esquema import Esquema, LlaveForanea
from .nombres import raiz, singular, snake

COLECCION, ARRAY, SUBDOCUMENTO = "coleccion", "array", "subdocumento"
LIMITE_ARRAY = 500
ETIQUETAS = {COLECCION: "Colección propia", ARRAY: "Array embebido", SUBDOCUMENTO: "Subdocumento embebido"}


@dataclass
class Decision:
    tabla: str
    modo: str
    fk: str | None          # FK hacia el padre que la contiene (solo si se embebe)
    nombre: str             # nombre de la colección o del campo embebido
    razon: str
    manual: bool = False    # True si el usuario la cambió
    nombre_manual: bool = False  # True si el usuario escribió el nombre


@dataclass
class Plan:
    decisiones: dict[str, Decision] = field(default_factory=dict)
    snake_case: bool = True
    omitir_nulos: bool = True
    reemplazar: bool = True

    # ------------------------------------------------ navegación del árbol de documentos
    def padre(self, esquema: Esquema, tabla: str) -> str | None:
        d = self.decisiones[tabla]
        return esquema.fk(d.fk).padre if d.modo != COLECCION else None

    def raiz(self, esquema: Esquema, tabla: str) -> str:
        visitadas = set()
        while self.decisiones[tabla].modo != COLECCION:
            if tabla in visitadas:
                raise ValueError(f"Ciclo de embebido en {tabla}")
            visitadas.add(tabla)
            tabla = self.padre(esquema, tabla)
        return tabla

    def ruta(self, esquema: Esquema, tabla: str) -> list[tuple[str, bool]]:
        """Camino de campos desde el documento raíz: [("items", True)] = items es un array."""
        camino = []
        while self.decisiones[tabla].modo != COLECCION:
            d = self.decisiones[tabla]
            camino.append((d.nombre, d.modo == ARRAY))
            tabla = self.padre(esquema, tabla)
        return list(reversed(camino))

    def hijos(self, esquema: Esquema, tabla: str) -> list[str]:
        return [t for t, d in self.decisiones.items()
                if d.modo != COLECCION and esquema.fk(d.fk).padre == tabla]

    def colecciones(self) -> list[str]:
        return [t for t, d in self.decisiones.items() if d.modo == COLECCION]

    def campo(self, columna: str) -> str:
        return snake(columna) if self.snake_case else columna

    # ------------------------------------------------ validación
    def errores(self, esquema: Esquema) -> list[str]:
        errores = []
        for tabla, d in self.decisiones.items():
            if d.modo == COLECCION:
                continue
            try:
                self.raiz(esquema, tabla)
            except ValueError:
                errores.append(f"{tabla}: forma un ciclo de embebido (A dentro de B y B dentro de A).")
                continue
            fk = esquema.fk(d.fk)
            if d.modo == SUBDOCUMENTO and not (fk.unica or fk.max_hijos <= 1):
                errores.append(f"{tabla}: no puede ser subdocumento, hay hasta {fk.max_hijos} filas por "
                               f"cada {fk.padre}. Use array.")
        nombres_col = [d.nombre for d in self.decisiones.values() if d.modo == COLECCION]
        for n in {n for n in nombres_col if nombres_col.count(n) > 1}:
            errores.append(f"Hay dos colecciones llamadas '{n}'.")
        return errores

    # ------------------------------------------------ persistencia
    def a_json(self) -> str:
        return json.dumps({"snake_case": self.snake_case, "omitir_nulos": self.omitir_nulos,
                           "reemplazar": self.reemplazar,
                           "decisiones": [asdict(d) for d in self.decisiones.values()]},
                          indent=2, ensure_ascii=False)

    @classmethod
    def desde_json(cls, texto: str) -> Plan:
        datos = json.loads(texto)
        plan = cls(snake_case=datos["snake_case"], omitir_nulos=datos["omitir_nulos"],
                   reemplazar=datos["reemplazar"])
        for d in datos["decisiones"]:
            plan.decisiones[d["tabla"]] = Decision(**d)
        return plan


# ---------------------------------------------------------------- reglas
def _nombre_coleccion(esquema: Esquema, tabla: str, snake_case: bool) -> str:
    t = esquema.tablas[tabla]
    base = t.nombre if t.esquema == "dbo" else f"{t.esquema}_{t.nombre}"
    return snake(base) if snake_case else base


def _nombre_campo(esquema: Esquema, tabla: str, modo: str, snake_case: bool) -> str:
    n = snake(esquema.tablas[tabla].nombre) if snake_case else esquema.tablas[tabla].nombre
    return singular(n) if modo == SUBDOCUMENTO else n


def _embebible(fk: LlaveForanea) -> bool:
    return fk.max_hijos <= LIMITE_ARRAY


def _puntaje_dueno(esquema: Esquema, fk: LlaveForanea) -> tuple[int, list[str]]:
    hija, padre = esquema.tablas[fk.hija], esquema.tablas[fk.padre]
    puntos, motivos = 0, []
    if fk.columnas_hija and set(fk.columnas_hija) <= set(hija.pk):
        puntos += 3
        motivos.append("la llave foránea forma parte de su llave primaria (relación identificadora)")
    r = raiz(padre.nombre)
    if len(r) >= 4 and r in hija.nombre.lower() and hija.nombre.lower() != padre.nombre.lower():
        puntos += 3
        motivos.append(f"su nombre indica que es parte de {padre.nombre}")
    if fk.unica:
        puntos += 2
        motivos.append("la relación es 1:1")
    return puntos, motivos


def opciones(esquema: Esquema, tabla: str) -> list[tuple[str, str | None]]:
    """Decisiones posibles para una tabla: (modo, fk)."""
    resultado = [(COLECCION, None)]
    for fk in esquema.salientes(tabla):
        if len(fk.columnas_hija) != len(fk.columnas_padre):
            continue
        resultado.append((ARRAY, fk.nombre))
        if fk.unica or fk.max_hijos <= 1:
            resultado.append((SUBDOCUMENTO, fk.nombre))
    return resultado


def decidir(esquema: Esquema, tabla: str, snake_case: bool = True) -> Decision:
    t = esquema.tablas[tabla]
    salientes = esquema.salientes(tabla)
    entrantes = esquema.entrantes(tabla)
    col = lambda razon: Decision(tabla, COLECCION, None, _nombre_coleccion(esquema, tabla, snake_case), razon)

    if not salientes:
        return col("No depende de ninguna otra tabla: es una entidad independiente o un catálogo, "
                   "por eso tiene colección propia.")
    if entrantes:
        quienes = ", ".join(sorted({esquema.tablas[f.hija].nombre for f in entrantes}))
        return col(f"Otras tablas la referencian ({quienes}): tiene vida propia y se usa desde varias "
                   f"partes, así que se mantiene como colección y se referencia.")

    candidatas = [f for f in salientes if len(f.columnas_hija) == len(f.columnas_padre)]
    puntuadas = sorted(((*_puntaje_dueno(esquema, f), f) for f in candidatas), key=lambda x: -x[0])
    if puntuadas and puntuadas[0][0] >= 3 and (len(puntuadas) == 1 or puntuadas[0][0] > puntuadas[1][0]):
        puntos, motivos, fk = puntuadas[0]
    elif len(candidatas) == 1:
        fk, motivos = candidatas[0], ["es su única llave foránea"]
    else:
        padres = ", ".join(esquema.tablas[f.padre].nombre for f in salientes)
        return col(f"Relaciona varias entidades ({padres}) sin un dueño claro: se deja como colección "
                   f"con referencias para poder consultarla desde cualquiera de ellas.")

    padre = esquema.tablas[fk.padre].nombre
    if not _embebible(fk):
        cantidad = f"{fk.max_hijos:,}".replace(",", ".")
        return col(f"Podría embeberse en {padre}, pero hay hasta {cantidad} filas por cada {padre}: "
                   f"el documento crecería sin límite (máximo 16 MB). Se referencia.")
    modo = SUBDOCUMENTO if (fk.unica or (fk.max_hijos <= 1 and t.filas > 0)) else ARRAY
    detalle = "relación 1:1" if modo == SUBDOCUMENTO else f"máximo {fk.max_hijos} por cada {padre}"
    razon = (f"Ninguna otra tabla la referencia y pertenece a {padre} ({'; '.join(motivos)}). "
             f"Se embebe como {ETIQUETAS[modo].lower()} ({detalle}): se lee junto con {padre} "
             f"y se escribe de forma atómica en un solo documento.")
    if fk.sin_padre:
        razon += f" Atención: {fk.sin_padre} filas no tienen {padre}; irán a una colección aparte."
    return Decision(tabla, modo, fk.nombre, _nombre_campo(esquema, tabla, modo, snake_case), razon)


def proponer(esquema: Esquema, snake_case: bool = True) -> Plan:
    plan = Plan(snake_case=snake_case)
    for tabla in esquema.tablas:
        plan.decisiones[tabla] = decidir(esquema, tabla, snake_case)
    # Si algo quedó embebido dentro de una tabla que a su vez se embebe, la ruta es anidada:
    # es válido (por ejemplo pedido.items[].personalizaciones[]) siempre que no haya ciclos.
    return plan


def cambiar(plan: Plan, esquema: Esquema, tabla: str, modo: str, fk: str | None) -> None:
    """Aplica la elección manual del usuario sobre una tabla."""
    if modo == COLECCION:
        nombre = _nombre_coleccion(esquema, tabla, plan.snake_case)
        razon = "Elegido manualmente: colección propia; sus llaves foráneas quedan como referencias."
    else:
        nombre = _nombre_campo(esquema, tabla, modo, plan.snake_case)
        padre = esquema.tablas[esquema.fk(fk).padre].nombre
        razon = f"Elegido manualmente: {ETIQUETAS[modo].lower()} dentro de {padre}."
    plan.decisiones[tabla] = Decision(tabla, modo, fk, nombre, razon, manual=True)


def renombrar(plan: Plan, esquema: Esquema) -> None:
    """Recalcula los nombres (p. ej. al activar/desactivar snake_case), salvo los editados a mano."""
    for tabla, d in plan.decisiones.items():
        if d.nombre_manual:
            continue
        d.nombre = (_nombre_coleccion(esquema, tabla, plan.snake_case) if d.modo == COLECCION
                    else _nombre_campo(esquema, tabla, d.modo, plan.snake_case))


def describir(plan: Plan, esquema: Esquema) -> str:
    n_col = len(plan.colecciones())
    n_emb = len(plan.decisiones) - n_col
    return f"{len(plan.decisiones)} tablas → {n_col} colecciones ({n_emb} tablas embebidas)"
