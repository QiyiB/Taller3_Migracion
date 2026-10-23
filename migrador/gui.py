"""
Aplicación de escritorio (PySide6) del migrador SQL Server -> MongoDB.

Cuatro pasos:
  1. Conexión     origen (SQL Server) y destino (MongoDB).
  2. Modelo       propuesta automática de Embedding/Referencing, editable tabla por tabla.
  3. Migración    progreso y registro de la carga.
  4. Verificación controles SQL Server vs MongoDB y reporte exportable.

Las tareas largas corren en un QThread para que la ventana no se congele.
"""
from __future__ import annotations

import json
import sys
import traceback
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QThread, Signal, Slot
from PySide6.QtGui import QBrush, QColor, QFont
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QFileDialog, QFormLayout, QFrame, QGroupBox,
                               QHBoxLayout, QHeaderView, QLabel, QLineEdit, QListWidget, QListWidgetItem,
                               QMainWindow, QMessageBox, QPlainTextEdit, QProgressBar, QPushButton, QSplitter,
                               QStackedWidget, QTableWidget, QTableWidgetItem, QTreeWidget, QTreeWidgetItem,
                               QVBoxLayout, QWidget)

from . import __version__
from .esquema import Esquema, cadena_conexion, conectar, drivers_sql_server, leer_esquema, listar_bases
from .motor import Migrador, Resultado, esqueleto_documento
from .nombres import snake
from .propuesta import (ARRAY, COLECCION, ETIQUETAS, SUBDOCUMENTO, Plan, cambiar, describir, opciones,
                        proponer, renombrar)
from .verificacion import Control, reporte_markdown, resumen, verificar

VERDE, OSCURO, MENTA, AMBAR, PIZARRA, ROJO = "#1F8A5B", "#0E2A23", "#E6F4EC", "#C97A0C", "#3A4A57", "#B3261E"

ESTILO = f"""
QWidget {{ font-family: 'Segoe UI'; font-size: 10pt; color: #1E2A2E; }}
QMainWindow, QStackedWidget > QWidget {{ background: #FFFFFF; }}
QListWidget#pasos {{ background: {OSCURO}; border: none; padding-top: 8px; }}
QListWidget#pasos::item {{ color: #9AA8B0; padding: 12px 18px; border: none; }}
QListWidget#pasos::item:selected {{ color: white; background: #173D33; border-left: 4px solid {VERDE}; }}
QListWidget#pasos::item:disabled {{ color: #4E615B; }}
QLabel#marca {{ background: {OSCURO}; color: white; font-size: 13pt; font-weight: 600; padding: 18px; }}
QLabel#titulo {{ font-size: 18pt; font-weight: 600; }}
QLabel#subtitulo {{ color: #5F6B70; }}
QLabel#resultado {{ font-size: 30pt; font-weight: 600; color: {VERDE}; }}
QGroupBox {{ font-weight: 600; border: 1px solid #D5DEE3; border-radius: 8px; margin-top: 12px; padding: 12px; }}
QGroupBox::title {{ subcontrol-origin: margin; left: 12px; padding: 0 4px; }}
QPushButton {{ padding: 7px 14px; border: 1px solid #C3CDD3; border-radius: 6px; background: #F7F9FA; }}
QPushButton:hover {{ background: #EEF2F4; }}
QPushButton#primario {{ background: {VERDE}; color: white; border: none; font-weight: 600; }}
QPushButton#primario:hover {{ background: #18744C; }}
QPushButton:disabled {{ color: #9AA8B0; background: #F0F2F3; }}
QLineEdit, QComboBox {{ padding: 5px; border: 1px solid #C3CDD3; border-radius: 5px; }}
QTreeWidget, QTableWidget, QPlainTextEdit {{ border: 1px solid #D5DEE3; border-radius: 6px; }}
QPlainTextEdit#codigo {{ font-family: Consolas; font-size: 9.5pt; background: #FBFCFC; }}
QFrame#razon {{ background: {MENTA}; border-radius: 8px; }}
QProgressBar {{ border: 1px solid #D5DEE3; border-radius: 5px; text-align: center; height: 18px; }}
QProgressBar::chunk {{ background: {VERDE}; border-radius: 4px; }}
"""


# ---------------------------------------------------------------- tareas en segundo plano
class Tarea(QObject):
    progreso = Signal(str, int)
    terminado = Signal(object)
    fallo = Signal(str, str)

    def __init__(self, funcion):
        super().__init__()
        self.funcion = funcion
        self.cancelar = False

    @Slot()
    def ejecutar(self):
        try:
            self.terminado.emit(self.funcion(self.progreso.emit, lambda: self.cancelar))
        except Exception as e:  # noqa: BLE001 - cualquier error se muestra al usuario
            self.fallo.emit(str(e), traceback.format_exc())


class Receptor(QObject):
    """Vive en el hilo de la interfaz: las señales de la tarea llegan aquí encoladas (thread-safe)."""

    def __init__(self, padre, ok, error, progreso, fin_hilo):
        super().__init__(padre)
        self._ok, self._error, self._progreso, self._fin_hilo = ok, error, progreso, fin_hilo

    @Slot(object)
    def ok(self, r):
        self._ok(r)

    @Slot(str, str)
    def error(self, mensaje, detalle):
        self._error(mensaje, detalle)

    @Slot(str, int)
    def progreso(self, mensaje, pct):
        self._progreso(mensaje, pct)

    @Slot()
    def fin_hilo(self):
        self._fin_hilo()


def miles(n) -> str:
    return f"{n:,}".replace(",", ".")


def etiqueta(texto, nombre=None, envolver=False):
    l = QLabel(texto)
    if nombre:
        l.setObjectName(nombre)
    l.setWordWrap(envolver)
    return l


def boton(texto, primario=False):
    b = QPushButton(texto)
    if primario:
        b.setObjectName("primario")
    b.setCursor(Qt.PointingHandCursor)
    return b


# ---------------------------------------------------------------- 1. conexión
class PaginaConexion(QWidget):
    def __init__(self):
        super().__init__()
        self.destino_editado = False
        lay = QVBoxLayout(self)
        lay.setContentsMargins(32, 24, 32, 24)
        lay.addWidget(etiqueta("Conexiones", "titulo"))
        lay.addWidget(etiqueta("Elija la base relacional de origen y la base de MongoDB donde se creará el "
                               "modelo documental.", "subtitulo", True))

        sql = QGroupBox("Origen: SQL Server")
        f = QFormLayout(sql)
        self.driver = QComboBox()
        self.driver.addItems(drivers_sql_server() or ["ODBC Driver 18 for SQL Server"])
        self.servidor = QLineEdit(r".\SQLEXPRESS")
        self.auth = QComboBox()
        self.auth.addItems(["Autenticación de Windows", "Usuario de SQL Server"])
        self.usuario = QLineEdit()
        self.clave = QLineEdit()
        self.clave.setEchoMode(QLineEdit.Password)
        self.confiar = QCheckBox("Confiar en el certificado del servidor (TrustServerCertificate)")
        self.confiar.setChecked(True)
        self.base = QComboBox()
        self.base.setEditable(True)
        self.base.setMinimumWidth(260)
        self.listar = boton("Listar bases")
        fila = QHBoxLayout()
        fila.addWidget(self.base, 1)
        fila.addWidget(self.listar)
        f.addRow("Driver ODBC", self.driver)
        f.addRow("Servidor", self.servidor)
        f.addRow("Autenticación", self.auth)
        f.addRow("Usuario", self.usuario)
        f.addRow("Contraseña", self.clave)
        f.addRow("", self.confiar)
        f.addRow("Base de datos", fila)
        lay.addWidget(sql)

        mongo = QGroupBox("Destino: MongoDB")
        g = QFormLayout(mongo)
        self.uri = QLineEdit("mongodb://localhost:27017")
        self.destino = QLineEdit()
        self.destino.setPlaceholderText("nombre de la base en MongoDB")
        g.addRow("URI de conexión", self.uri)
        g.addRow("Base destino", self.destino)
        lay.addWidget(mongo)

        self.estado = etiqueta("", "subtitulo", True)
        self.barra = QProgressBar()
        self.barra.setVisible(False)
        lay.addWidget(self.estado)
        lay.addWidget(self.barra)
        lay.addStretch(1)
        botones = QHBoxLayout()
        self.probar = boton("Probar conexiones")
        self.analizar = boton("Analizar esquema  →", primario=True)
        botones.addStretch(1)
        botones.addWidget(self.probar)
        botones.addWidget(self.analizar)
        lay.addLayout(botones)

        self.auth.currentIndexChanged.connect(self._auth)
        self.base.currentTextChanged.connect(self._sugerir_destino)
        self.destino.textEdited.connect(lambda _: setattr(self, "destino_editado", True))
        self._auth()

    def _auth(self):
        windows = self.auth.currentIndex() == 0
        self.usuario.setEnabled(not windows)
        self.clave.setEnabled(not windows)

    def _sugerir_destino(self, base):
        if not self.destino_editado and base:
            self.destino.setText(snake(base) + "_migrada")

    def cadena(self, base=None) -> str:
        return cadena_conexion(self.servidor.text().strip(), base or self.base.currentText().strip() or "master",
                               self.driver.currentText(), self.auth.currentIndex() == 0,
                               self.usuario.text(), self.clave.text(), self.confiar.isChecked())

    def validar(self) -> str | None:
        if not self.servidor.text().strip():
            return "Escriba el servidor de SQL Server."
        if not self.base.currentText().strip():
            return "Elija la base de datos de origen (use «Listar bases»)."
        if not self.destino.text().strip():
            return "Escriba el nombre de la base destino en MongoDB."
        if self.auth.currentIndex() == 1 and not self.usuario.text():
            return "Escriba el usuario de SQL Server."
        return None


# ---------------------------------------------------------------- 2. modelo
class PaginaModelo(QWidget):
    cambio = Signal()

    def __init__(self):
        super().__init__()
        self.esquema: Esquema | None = None
        self.plan: Plan | None = None
        self.original: str = ""
        self.tabla_actual: str | None = None

        lay = QVBoxLayout(self)
        lay.setContentsMargins(32, 24, 32, 24)
        lay.addWidget(etiqueta("Modelo documental propuesto", "titulo"))
        self.resumen = etiqueta("", "subtitulo", True)
        lay.addWidget(self.resumen)
        self.errores = etiqueta("", envolver=True)
        self.errores.setStyleSheet(f"color: {ROJO};")
        lay.addWidget(self.errores)

        division = QSplitter(Qt.Horizontal)
        self.arbol = QTreeWidget()
        self.arbol.setHeaderLabels(["Estructura en MongoDB", "Tabla SQL", "Tipo", "Filas"])
        self.arbol.header().setSectionResizeMode(0, QHeaderView.Stretch)
        for i in (1, 2, 3):
            self.arbol.header().setSectionResizeMode(i, QHeaderView.ResizeToContents)
        division.addWidget(self.arbol)

        panel = QWidget()
        p = QVBoxLayout(panel)
        p.setContentsMargins(16, 0, 0, 0)
        self.nombre_tabla = etiqueta("Seleccione una tabla", "titulo")
        self.nombre_tabla.setStyleSheet("font-size: 14pt;")
        self.info = etiqueta("", "subtitulo", True)
        self.decision = QComboBox()
        self.campo = QLineEdit()
        formulario = QFormLayout()
        formulario.addRow("Decisión", self.decision)
        formulario.addRow("Nombre", self.campo)
        marco = QFrame()
        marco.setObjectName("razon")
        m = QVBoxLayout(marco)
        m.addWidget(etiqueta("<b>Justificación</b>"))
        self.razon = etiqueta("", envolver=True)
        m.addWidget(self.razon)
        self.vista = QPlainTextEdit()
        self.vista.setObjectName("codigo")
        self.vista.setReadOnly(True)
        p.addWidget(self.nombre_tabla)
        p.addWidget(self.info)
        p.addLayout(formulario)
        p.addWidget(marco)
        p.addWidget(etiqueta("<b>Vista previa del documento raíz</b>"))
        p.addWidget(self.vista, 1)
        division.addWidget(panel)
        division.setSizes([540, 480])
        lay.addWidget(division, 1)

        opciones_lay = QHBoxLayout()
        self.snake = QCheckBox("Nombres en snake_case")
        self.nulos = QCheckBox("Omitir campos NULL")
        self.reemplazar = QCheckBox("Reemplazar colecciones existentes")
        for c in (self.snake, self.nulos, self.reemplazar):
            c.setChecked(True)
            opciones_lay.addWidget(c)
        opciones_lay.addStretch(1)
        lay.addLayout(opciones_lay)

        botones = QHBoxLayout()
        self.restaurar = boton("Restaurar propuesta")
        self.guardar = boton("Guardar plan…")
        self.cargar = boton("Cargar plan…")
        self.continuar = boton("Continuar  →", primario=True)
        for b in (self.restaurar, self.guardar, self.cargar):
            botones.addWidget(b)
        botones.addStretch(1)
        botones.addWidget(self.continuar)
        lay.addLayout(botones)

        self.arbol.currentItemChanged.connect(lambda item, _: self._seleccionar(item))
        self.decision.activated.connect(self._cambiar_decision)
        self.campo.editingFinished.connect(self._cambiar_nombre)
        self.snake.toggled.connect(self._opciones)
        self.nulos.toggled.connect(self._opciones)
        self.reemplazar.toggled.connect(self._opciones)
        self.restaurar.clicked.connect(self._restaurar)

    # ------------------------------------------------ datos
    def cargar_datos(self, esquema: Esquema, plan: Plan):
        self.esquema, self.plan = esquema, plan
        self.original = plan.a_json()
        for c, v in ((self.snake, plan.snake_case), (self.nulos, plan.omitir_nulos),
                     (self.reemplazar, plan.reemplazar)):
            c.blockSignals(True)
            c.setChecked(v)
            c.blockSignals(False)
        self.tabla_actual = None
        self.refrescar()

    def refrescar(self):
        e, plan = self.esquema, self.plan
        self.resumen.setText(f"Base <b>{e.base}</b>: {miles(e.total_filas)} filas. Propuesta: <b>{describir(plan, e)}</b>. "
                             f"Seleccione una tabla para ver por qué se decidió así o para cambiarla.")
        errores = plan.errores(e)
        self.errores.setText("\n".join("⚠ " + x for x in errores))
        self.errores.setVisible(bool(errores))
        self.continuar.setEnabled(not errores)

        self.arbol.blockSignals(True)
        self.arbol.clear()
        seleccion = None
        for tabla in sorted(plan.colecciones(), key=lambda t: plan.decisiones[t].nombre):
            item = self._item(self.arbol, tabla)
            seleccion = seleccion or (item if tabla == self.tabla_actual else None)
            seleccion = self._agregar_hijos(item, tabla) or seleccion
        self.arbol.expandAll()
        self.arbol.blockSignals(False)
        if seleccion is None and self.arbol.topLevelItemCount():
            seleccion = self.arbol.topLevelItem(0)
        if seleccion:
            self.arbol.setCurrentItem(seleccion)
            self._seleccionar(seleccion)

    def _item(self, padre, tabla) -> QTreeWidgetItem:
        d, t = self.plan.decisiones[tabla], self.esquema.tablas[tabla]
        sufijo = {COLECCION: "", ARRAY: "[ ]", SUBDOCUMENTO: "{ }"}[d.modo]
        tipo = {COLECCION: "colección", ARRAY: "array embebido", SUBDOCUMENTO: "subdocumento"}[d.modo]
        item = QTreeWidgetItem(padre, [f"{d.nombre} {sufijo}".strip(), t.nombre, tipo, miles(t.filas)])
        item.setData(0, Qt.UserRole, tabla)
        item.setToolTip(0, d.razon)
        item.setForeground(1, QBrush(QColor(PIZARRA)))
        item.setForeground(2, QBrush(QColor(VERDE if d.modo == COLECCION else AMBAR)))
        if d.modo == COLECCION:
            fuente = QFont()
            fuente.setBold(True)
            item.setFont(0, fuente)
        if d.manual:
            item.setText(2, tipo + " ✎")
        return item

    def _agregar_hijos(self, item, tabla):
        encontrado = None
        for hija in sorted(self.plan.hijos(self.esquema, tabla)):
            sub = self._item(item, hija)
            if hija == self.tabla_actual:
                encontrado = sub
            encontrado = self._agregar_hijos(sub, hija) or encontrado
        return encontrado

    # ------------------------------------------------ panel de detalle
    def _seleccionar(self, item):
        if item is None:
            return
        e, plan = self.esquema, self.plan
        tabla = item.data(0, Qt.UserRole)
        self.tabla_actual = tabla
        t, d = e.tablas[tabla], plan.decisiones[tabla]
        self.nombre_tabla.setText(t.clave)
        refs = [f"{', '.join(f.columnas_hija)} → {e.tablas[f.padre].nombre} "
                f"(máx. {f.max_hijos} por {e.tablas[f.padre].nombre})" for f in e.salientes(tabla)]
        entran = sorted({e.tablas[f.hija].nombre for f in e.entrantes(tabla)})
        self.info.setText(f"{miles(t.filas)} filas · PK: {', '.join(t.pk) or '—'}" +
                          (f"<br>Referencia a: {'; '.join(refs)}" if refs else "") +
                          (f"<br>La referencian: {', '.join(entran)}" if entran else ""))
        self.decision.blockSignals(True)
        self.decision.clear()
        for modo, fk in opciones(e, tabla):
            if modo == COLECCION:
                texto = "Colección propia (referencing)"
            else:
                f = e.fk(fk)
                texto = f"{ETIQUETAS[modo]} en {e.tablas[f.padre].nombre}  (vía {', '.join(f.columnas_hija)})"
            self.decision.addItem(texto, (modo, fk))
            if modo == d.modo and fk == d.fk:
                self.decision.setCurrentIndex(self.decision.count() - 1)
        self.decision.blockSignals(False)
        self.campo.setText(d.nombre)
        self.razon.setText(d.razon)
        raiz = plan.raiz(e, tabla) if not plan.errores(e) else tabla
        self.vista.setPlainText(json.dumps(esqueleto_documento(e, plan, raiz), indent=2, ensure_ascii=False))

    def _cambiar_decision(self):
        modo, fk = self.decision.currentData()
        cambiar(self.plan, self.esquema, self.tabla_actual, modo, fk)
        self.refrescar()

    def _cambiar_nombre(self):
        nombre = self.campo.text().strip()
        d = self.plan.decisiones.get(self.tabla_actual) if self.tabla_actual else None
        if d and nombre and nombre != d.nombre:
            d.nombre, d.nombre_manual = nombre, True
            self.refrescar()

    def _opciones(self):
        self.plan.omitir_nulos = self.nulos.isChecked()
        self.plan.reemplazar = self.reemplazar.isChecked()
        if self.plan.snake_case != self.snake.isChecked():
            self.plan.snake_case = self.snake.isChecked()
            renombrar(self.plan, self.esquema)
        self.refrescar()

    def _restaurar(self):
        self.cargar_datos(self.esquema, proponer(self.esquema, self.snake.isChecked()))


# ---------------------------------------------------------------- 3. migración
class PaginaMigracion(QWidget):
    def __init__(self):
        super().__init__()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(32, 24, 32, 24)
        lay.addWidget(etiqueta("Migración", "titulo"))
        self.resumen = etiqueta("", envolver=True)
        self.resumen.setTextFormat(Qt.RichText)
        lay.addWidget(self.resumen)
        self.aviso = etiqueta("", envolver=True)
        self.aviso.setStyleSheet(f"color: {AMBAR};")
        lay.addWidget(self.aviso)
        self.barra = QProgressBar()
        self.barra.setValue(0)
        lay.addWidget(self.barra)
        self.log = QPlainTextEdit()
        self.log.setObjectName("codigo")
        self.log.setReadOnly(True)
        lay.addWidget(self.log, 1)
        botones = QHBoxLayout()
        self.volver = boton("←  Volver al modelo")
        self.cancelar = boton("Cancelar")
        self.cancelar.setEnabled(False)
        self.iniciar = boton("Iniciar migración", primario=True)
        botones.addWidget(self.volver)
        botones.addStretch(1)
        botones.addWidget(self.cancelar)
        botones.addWidget(self.iniciar)
        lay.addLayout(botones)

    def preparar(self, esquema: Esquema, plan: Plan, destino: str, existentes: list[str]):
        filas = []
        for tabla in sorted(plan.colecciones(), key=lambda t: plan.decisiones[t].nombre):
            d = plan.decisiones[tabla]
            dentro = [f"{plan.decisiones[h].nombre}" for h in self._descendientes(esquema, plan, tabla)]
            extra = f" <span style='color:{AMBAR}'>+ embebe {', '.join(dentro)}</span>" if dentro else ""
            filas.append(f"<li><b>{d.nombre}</b> ← {esquema.tablas[tabla].nombre}{extra}</li>")
        self.resumen.setText(f"Origen <b>{esquema.base}</b> → destino MongoDB <b>{destino}</b>. "
                             f"Se crearán {len(plan.colecciones())} colecciones:<ul>{''.join(filas)}</ul>")
        nombres = {plan.decisiones[t].nombre for t in plan.colecciones()}
        choques = sorted(nombres & set(existentes))
        sobrantes = sorted(set(existentes) - nombres)
        avisos = []
        if choques:
            accion = "se reemplazarán" if plan.reemplazar else "ya existen y la migración se detendrá"
            avisos.append(f"⚠ Las colecciones {', '.join(choques)} {accion}.")
        if sobrantes:
            avisos.append(f"La base destino ya tiene otras colecciones que no se tocarán: {', '.join(sobrantes)}.")
        self.aviso.setText(" ".join(avisos))
        self.barra.setValue(0)
        self.log.clear()

    @staticmethod
    def _descendientes(esquema, plan, tabla):
        for h in plan.hijos(esquema, tabla):
            yield h
            yield from PaginaMigracion._descendientes(esquema, plan, h)

    def registrar(self, mensaje, pct):
        self.barra.setValue(pct)
        ultima = self.log.toPlainText().splitlines()[-1:] or [""]
        if ultima[0] != mensaje:
            self.log.appendPlainText(mensaje)


# ---------------------------------------------------------------- 4. verificación
class PaginaVerificacion(QWidget):
    def __init__(self):
        super().__init__()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(32, 24, 32, 24)
        lay.addWidget(etiqueta("Verificación", "titulo"))
        cabecera = QHBoxLayout()
        self.cifra = etiqueta("—", "resultado")
        self.detalle = etiqueta("", "subtitulo", True)
        cabecera.addWidget(self.cifra)
        cabecera.addSpacing(16)
        cabecera.addWidget(self.detalle, 1)
        lay.addLayout(cabecera)
        self.tabla = QTableWidget(0, 5)
        self.tabla.setHorizontalHeaderLabels(["Categoría", "Control", "SQL Server / esperado", "MongoDB", ""])
        h = self.tabla.horizontalHeader()
        h.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        h.setSectionResizeMode(1, QHeaderView.Stretch)
        for i in (2, 3, 4):
            h.setSectionResizeMode(i, QHeaderView.ResizeToContents)
        self.tabla.verticalHeader().setVisible(False)
        self.tabla.setEditTriggers(QTableWidget.NoEditTriggers)
        self.tabla.setAlternatingRowColors(True)
        lay.addWidget(self.tabla, 1)
        botones = QHBoxLayout()
        self.nueva = boton("Nueva migración")
        self.repetir = boton("Volver a verificar")
        self.exportar = boton("Exportar reporte…", primario=True)
        botones.addWidget(self.nueva)
        botones.addStretch(1)
        botones.addWidget(self.repetir)
        botones.addWidget(self.exportar)
        lay.addLayout(botones)

    def mostrar(self, controles: list[Control], resultado: Resultado | None):
        ok, total = resumen(controles)
        self.cifra.setText(f"{ok}/{total}")
        self.cifra.setStyleSheet(f"color: {VERDE if ok == total else ROJO};")
        texto = "controles correctos." if ok == total else "controles correctos. Revise las filas en rojo."
        if resultado:
            docs = sum(resultado.documentos.values())
            texto += (f"<br>{miles(docs)} documentos en {len(resultado.documentos)} colecciones, "
                      f"migrados en {resultado.segundos:.1f} s.")
            for a in resultado.advertencias:
                texto += f"<br>⚠ {a}"
        self.detalle.setText(texto)
        self.tabla.setRowCount(len(controles))
        from .verificacion import _fmt
        for i, c in enumerate(controles):
            marca = "✓" if c.ok else ("—" if c.ok is None else "✗")
            for j, v in enumerate([c.categoria, c.descripcion, _fmt(c.esperado), _fmt(c.obtenido), marca]):
                item = QTableWidgetItem(v)
                if j in (2, 3):
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                if j == 4:
                    item.setTextAlignment(Qt.AlignCenter)
                    item.setForeground(QBrush(QColor(VERDE if c.ok else (PIZARRA if c.ok is None else ROJO))))
                if c.ok is False:
                    item.setBackground(QBrush(QColor("#FBE9E7")))
                self.tabla.setItem(i, j, item)


# ---------------------------------------------------------------- ventana principal
class Ventana(QMainWindow):
    PASOS = ["1  Conexión", "2  Modelo", "3  Migración", "4  Verificación"]

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Migrador SQL Server → MongoDB")
        self.resize(1180, 780)
        self.esquema: Esquema | None = None
        self.plan: Plan | None = None
        self.resultado: Resultado | None = None
        self.controles: list[Control] = []
        self._hilos = []

        central = QWidget()
        raiz = QHBoxLayout(central)
        raiz.setContentsMargins(0, 0, 0, 0)
        raiz.setSpacing(0)
        barra_lateral = QWidget()
        barra_lateral.setFixedWidth(230)
        barra_lateral.setStyleSheet(f"background: {OSCURO};")
        lateral = QVBoxLayout(barra_lateral)
        lateral.setContentsMargins(0, 0, 0, 0)
        lateral.setSpacing(0)
        marca = etiqueta("Migrador\nSQL Server → MongoDB", "marca", True)
        lateral.addWidget(marca)
        self.pasos = QListWidget()
        self.pasos.setObjectName("pasos")
        self.pasos.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.pasos.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        for p in self.PASOS:
            self.pasos.addItem(QListWidgetItem(p))
        lateral.addWidget(self.pasos, 1)
        version = etiqueta(f"v{__version__}", "marca")
        version.setStyleSheet(f"background:{OSCURO}; color:#6F8580; font-size:9pt; padding:12px 18px;")
        lateral.addWidget(version)
        raiz.addWidget(barra_lateral)

        self.paginas = QStackedWidget()
        self.p_con, self.p_mod = PaginaConexion(), PaginaModelo()
        self.p_mig, self.p_ver = PaginaMigracion(), PaginaVerificacion()
        for p in (self.p_con, self.p_mod, self.p_mig, self.p_ver):
            self.paginas.addWidget(p)
        raiz.addWidget(self.paginas, 1)
        self.setCentralWidget(central)
        self.statusBar().showMessage("Listo")

        self.pasos.currentRowChanged.connect(self.paginas.setCurrentIndex)
        self.p_con.listar.clicked.connect(self.listar_bases)
        self.p_con.probar.clicked.connect(self.probar)
        self.p_con.analizar.clicked.connect(self.analizar)
        self.p_mod.continuar.clicked.connect(self.ir_a_migracion)
        self.p_mod.guardar.clicked.connect(self.guardar_plan)
        self.p_mod.cargar.clicked.connect(self.cargar_plan)
        self.p_mig.volver.clicked.connect(lambda: self.ir(1))
        self.p_mig.iniciar.clicked.connect(self.migrar)
        self.p_mig.cancelar.clicked.connect(self.cancelar_migracion)
        self.p_ver.exportar.clicked.connect(self.exportar)
        self.p_ver.repetir.clicked.connect(self.verificar)
        self.p_ver.nueva.clicked.connect(lambda: self.ir(0))
        self.habilitar(0)
        self.ir(0)

    # ------------------------------------------------ navegación
    def habilitar(self, hasta: int):
        for i in range(self.pasos.count()):
            item = self.pasos.item(i)
            flags = Qt.ItemIsSelectable | Qt.ItemIsEnabled if i <= hasta else Qt.NoItemFlags
            item.setFlags(flags)

    def ir(self, paso: int):
        self.pasos.setCurrentRow(paso)

    # ------------------------------------------------ tareas
    def lanzar(self, funcion, al_terminar, progreso=None, ocupado=(), al_fallar=None):
        """Ejecuta funcion(avisar, cancelado) en un QThread; los callbacks corren en el hilo de la interfaz."""
        hilo, tarea = QThread(self), Tarea(funcion)
        tarea.moveToThread(hilo)
        for w in ocupado:
            w.setEnabled(False)

        def fin():
            for w in ocupado:
                w.setEnabled(True)
            hilo.quit()

        def ok(r):
            fin()
            al_terminar(r)

        def error(msg, detalle):
            fin()
            if al_fallar:
                al_fallar()
            self.statusBar().showMessage("Error")
            caja = QMessageBox(QMessageBox.Critical, "Error", msg, parent=self)
            caja.setDetailedText(detalle)
            caja.exec()

        def avance(mensaje, pct):
            self.statusBar().showMessage(mensaje)
            if progreso:
                progreso(mensaje, pct)

        registro = []

        def liberar():
            self._hilos.remove(registro[0])

        receptor = Receptor(self, ok, error, avance, liberar)
        registro.append((hilo, tarea, receptor))
        hilo.started.connect(tarea.ejecutar)
        tarea.terminado.connect(receptor.ok)
        tarea.fallo.connect(receptor.error)
        tarea.progreso.connect(receptor.progreso)
        hilo.finished.connect(receptor.fin_hilo)
        self._hilos.append(registro[0])
        hilo.start()
        return tarea

    def _mongo(self):
        from pymongo import MongoClient
        return MongoClient(self.p_con.uri.text().strip(), serverSelectionTimeoutMS=5000)

    # ------------------------------------------------ paso 1
    def listar_bases(self):
        cadena = self.p_con.cadena("master")

        def trabajo(avisar, _):
            avisar("Conectando a SQL Server…", 0)
            return listar_bases(conectar(cadena))

        def listo(bases):
            actual = self.p_con.base.currentText()
            self.p_con.base.clear()
            self.p_con.base.addItems(bases)
            if actual in bases:
                self.p_con.base.setCurrentText(actual)
            self.statusBar().showMessage(f"{len(bases)} bases encontradas")

        self.lanzar(trabajo, listo, ocupado=[self.p_con.listar])

    def probar(self):
        cadena, mongo = self.p_con.cadena(), self._mongo()

        def trabajo(avisar, _):
            avisar("Probando SQL Server…", 0)
            conectar(cadena).cursor().execute("SELECT 1")
            avisar("Probando MongoDB…", 50)
            version = mongo.server_info()["version"]
            return version

        self.lanzar(trabajo, lambda v: self.p_con.estado.setText(
            f"✔ SQL Server conectado · ✔ MongoDB {v} conectado"), ocupado=[self.p_con.probar])

    def analizar(self):
        problema = self.p_con.validar()
        if problema:
            QMessageBox.warning(self, "Faltan datos", problema)
            return
        cadena, mongo = self.p_con.cadena(), self._mongo()
        barra = self.p_con.barra
        barra.setVisible(True)
        barra.setValue(0)

        def trabajo(avisar, _):
            avisar("Comprobando MongoDB…", 0)
            mongo.admin.command("ping")
            avisar("Leyendo el esquema de SQL Server…", 2)
            esquema = leer_esquema(conectar(cadena), progreso=avisar)
            if not esquema.tablas:
                raise ValueError("La base no tiene tablas de usuario.")
            return esquema, proponer(esquema)

        def listo(r):
            barra.setVisible(False)
            self.esquema, self.plan = r
            self.p_mod.cargar_datos(self.esquema, self.plan)
            self.p_con.estado.setText(f"✔ Esquema leído: {len(self.esquema.tablas)} tablas, "
                                      f"{len(self.esquema.fks)} relaciones.")
            self.statusBar().showMessage(f"Esquema de {self.esquema.base} analizado")
            self.habilitar(1)
            self.ir(1)

        self.lanzar(trabajo, listo, progreso=lambda m, p: (barra.setValue(p), self.p_con.estado.setText(m)),
                    ocupado=[self.p_con.analizar, self.p_con.probar])

    # ------------------------------------------------ paso 2
    def guardar_plan(self):
        ruta, _ = QFileDialog.getSaveFileName(self, "Guardar plan", f"plan_{self.esquema.base}.json", "JSON (*.json)")
        if ruta:
            Path(ruta).write_text(self.plan.a_json(), encoding="utf-8")
            self.statusBar().showMessage(f"Plan guardado en {ruta}")

    def cargar_plan(self):
        ruta, _ = QFileDialog.getOpenFileName(self, "Cargar plan", "", "JSON (*.json)")
        if not ruta:
            return
        try:
            plan = Plan.desde_json(Path(ruta).read_text(encoding="utf-8"))
            if set(plan.decisiones) != set(self.esquema.tablas):
                raise ValueError("El plan corresponde a otro esquema (las tablas no coinciden).")
            self.plan = plan
            self.p_mod.cargar_datos(self.esquema, plan)
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, "No se pudo cargar el plan", str(e))

    def ir_a_migracion(self):
        self.plan = self.p_mod.plan
        destino = self.p_con.destino.text().strip()
        try:
            existentes = self._mongo()[destino].list_collection_names()
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, "MongoDB no responde", str(e))
            return
        self.p_mig.preparar(self.esquema, self.plan, destino, existentes)
        self.habilitar(2)
        self.ir(2)

    # ------------------------------------------------ paso 3
    def migrar(self):
        cadena, mongo = self.p_con.cadena(), self._mongo()
        destino, esquema, plan = self.p_con.destino.text().strip(), self.esquema, self.plan
        self.p_mig.log.clear()

        def trabajo(avisar, cancelado):
            migrador = Migrador(conectar(cadena), mongo[destino], esquema, plan, avisar, cancelado)
            return migrador.ejecutar()

        def listo(resultado: Resultado):
            self.resultado = resultado
            self.p_mig.cancelar.setEnabled(False)
            for nombre, n in resultado.documentos.items():
                self.p_mig.log.appendPlainText(f"  {nombre:<28}{miles(n):>10} documentos")
            for a in resultado.advertencias:
                self.p_mig.log.appendPlainText(f"⚠ {a}")
            self.p_mig.log.appendPlainText("Verificando…")
            self.verificar()

        self.p_mig.cancelar.setEnabled(True)
        self.tarea_migracion = self.lanzar(trabajo, listo, progreso=self.p_mig.registrar,
                                           ocupado=[self.p_mig.iniciar, self.p_mig.volver],
                                           al_fallar=lambda: self.p_mig.cancelar.setEnabled(False))

    def cancelar_migracion(self):
        if getattr(self, "tarea_migracion", None):
            self.tarea_migracion.cancelar = True
            self.p_mig.cancelar.setEnabled(False)

    # ------------------------------------------------ paso 4
    def verificar(self):
        cadena, mongo = self.p_con.cadena(), self._mongo()
        destino, esquema, plan, resultado = self.p_con.destino.text().strip(), self.esquema, self.plan, self.resultado

        def trabajo(avisar, _):
            return verificar(conectar(cadena), mongo[destino], esquema, plan, resultado, avisar)

        def listo(controles):
            self.controles = controles
            self.p_ver.mostrar(controles, self.resultado)
            ok, total = resumen(controles)
            self.statusBar().showMessage(f"Verificación: {ok}/{total} controles correctos")
            self.habilitar(3)
            self.ir(3)

        progreso = self.p_mig.registrar if self.paginas.currentIndex() == 2 else None
        self.lanzar(trabajo, listo, progreso=progreso, ocupado=[self.p_ver.repetir])

    def exportar(self):
        destino = self.p_con.destino.text().strip()
        ruta, _ = QFileDialog.getSaveFileName(self, "Exportar reporte", f"verificacion_{destino}.md",
                                              "Markdown (*.md)")
        if ruta:
            Path(ruta).write_text(reporte_markdown(self.controles, self.esquema, self.plan, destino,
                                                   self.resultado), encoding="utf-8")
            self.statusBar().showMessage(f"Reporte guardado en {ruta}")


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Migrador SQL Server → MongoDB")
    app.setStyleSheet(ESTILO)
    ventana = Ventana()
    ventana.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
