"""
config.py — Rutas y parámetros del sistema, en un solo lugar.

Los valores sensibles o que cambian por máquina (API key, modelo, dispositivo) salen del .env.
Los parámetros de diseño (tamaño de chunk, k) están acá, con el porqué en la BITACORA.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

RAIZ = Path(__file__).resolve().parent.parent
load_dotenv(RAIZ / ".env")

# --- Rutas ---
CARPETA_POLITICAS = RAIZ / "data" / "politicas"
RUTA_CATALOGO = RAIZ / "data" / "catalogo.csv"
RUTA_CLIENTES = RAIZ / "data" / "clientes.csv"
CARPETA_INDICE = RAIZ / "artifacts" / "indice_faiss"  # no se versiona: se regenera

# --- Modelos ---
MODELO = os.getenv("MODELO", "openai/gpt-oss-120b")
MODELO_EMBEDDINGS = os.getenv("MODELO_EMBEDDINGS", "BAAI/bge-m3")
DISPOSITIVO_EMBEDDINGS = os.getenv("DISPOSITIVO_EMBEDDINGS", "cpu")

# --- RAG (Paso 1: punto de partida, se ajusta con pruebas propias, nunca con el golden set) ---
TAMANO_CHUNK = 1000
SOLAPAMIENTO_CHUNK = 150  # 15% del chunk
TOP_K = 5
