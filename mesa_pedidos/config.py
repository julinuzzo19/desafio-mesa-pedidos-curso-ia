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
RUTA_BANDEJA = RAIZ / "data" / "bandeja.jsonl"

# --- Modelos (el proveedor se elige en el .env; la clave de cada uno también va ahí) ---
PROVEEDOR_LLM = os.getenv("PROVEEDOR_LLM", "groq")  # groq | openai
MODELO = os.getenv("MODELO", "openai/gpt-oss-120b")
PROVEEDOR_EMBEDDINGS = os.getenv("PROVEEDOR_EMBEDDINGS", "huggingface")  # huggingface (local) | openai
MODELO_EMBEDDINGS = os.getenv("MODELO_EMBEDDINGS", "BAAI/bge-m3")
DISPOSITIVO_EMBEDDINGS = os.getenv("DISPOSITIVO_EMBEDDINGS", "cpu")  # sólo para huggingface

# Un índice por modelo de embeddings: un índice sólo sirve con el modelo que lo generó.
# Así, cambiar de modelo en el .env usa (o construye) su propio índice, en vez de mezclar
# vectores de dos modelos. Ej.: artifacts/indice_faiss/huggingface_BAAI-bge-m3
_nombre_indice = f"{PROVEEDOR_EMBEDDINGS}_{MODELO_EMBEDDINGS}".replace("/", "-")
CARPETA_INDICE = RAIZ / "artifacts" / "indice_faiss" / _nombre_indice  # no se versiona: se regenera

# Checkpoints del grafo: el estado de cada mensaje (un thread por mensaje), para poder retomar
# uno frenado en aprobacion_humana. No se versiona: es el estado de una corrida.
RUTA_CHECKPOINTS = RAIZ / "artifacts" / "checkpoints.sqlite"

# --- RAG (Paso 1: punto de partida, se ajusta con pruebas propias, nunca con el golden set) ---
TAMANO_CHUNK = 1000
SOLAPAMIENTO_CHUNK = 150  # 15% del chunk
TOP_K = 5
