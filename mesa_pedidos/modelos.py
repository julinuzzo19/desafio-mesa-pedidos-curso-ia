"""
modelos.py — Crea el LLM y el modelo de embeddings según el .env.

El resto del sistema no sabe qué proveedor se usa: pide un LLM o unos embeddings acá.
Para cambiar de proveedor se cambia el .env (y se instala su paquete), no el código.
"""

from langchain.chat_models import init_chat_model
from langchain.embeddings import init_embeddings
from langchain_core.embeddings import Embeddings
from langchain_core.language_models import BaseChatModel

from mesa_pedidos import config


def crear_llm() -> BaseChatModel:
    """El LLM del proveedor configurado (ej. groq u openai).

    temperature=0: la misma entrada da siempre la misma salida.
    El cliente de cada proveedor reintenta solo ante fallas de red (max_retries=2 por defecto).
    """
    return init_chat_model(
        config.MODELO,
        model_provider=config.PROVEEDOR_LLM,
        temperature=0,
    )


def crear_embeddings() -> Embeddings:
    """El modelo que convierte texto en vectores: local (huggingface) o por API (ej. openai).

    Se usa al indexar y al consultar: tiene que ser el mismo, si no los vectores no se comparan.
    """
    opciones = {}
    if config.PROVEEDOR_EMBEDDINGS == "huggingface":
        # Sólo el modelo local necesita saber dónde corre y que normalice los vectores
        # (largo 1: la similitud se mide sólo por dirección). Los de API ya vienen normalizados.
        opciones["model_kwargs"] = {"device": config.DISPOSITIVO_EMBEDDINGS}
        opciones["encode_kwargs"] = {"normalize_embeddings": True}

    return init_embeddings(
        config.MODELO_EMBEDDINGS,
        provider=config.PROVEEDOR_EMBEDDINGS,
        **opciones,  # ** pasa cada clave del dict como un parámetro con nombre
    )
