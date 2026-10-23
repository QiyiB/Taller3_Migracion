"""Parámetros de conexión. Se pueden sobrescribir con variables de entorno."""
import os

SQLSERVER_CONN = os.getenv(
    "SQLSERVER_CONN",
    "DRIVER={ODBC Driver 18 for SQL Server};SERVER=.\\SQLEXPRESS;DATABASE=TiendaOnline;"
    "Trusted_Connection=yes;TrustServerCertificate=yes;",
)
MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")
MONGO_DB = os.getenv("MONGO_DB", "tienda_online")
