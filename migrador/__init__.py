"""
Migrador SQL Server -> MongoDB.

Lee el esquema de cualquier base de SQL Server, propone un modelo documental
(Embedding / Referencing) con su justificación, migra los datos y verifica
que la información se conservó.

  esquema.py       lectura de tablas, columnas, llaves y estadísticas
  propuesta.py     reglas que proponen el modelo documental
  motor.py         transformación y carga en MongoDB
  verificacion.py  controles SQL Server vs MongoDB
  gui.py           aplicación de escritorio (PySide6)
"""
__version__ = "1.0.0"
