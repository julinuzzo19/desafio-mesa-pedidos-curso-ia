"""
rag.py — Buscar en los PDF de políticas y responder citando documento y página.

Dos fases:
  INDEXAR (una vez):     PDF -> páginas con metadata -> chunks -> vectores -> FAISS -> disco
  CONSULTAR (cada vez):  pregunta -> vector -> top k chunks -> LLM -> respuesta + citas + alcanza

Para probarlo desde la terminal: scripts/probar_rag.py.
"""

import shutil

from langchain_community.document_loaders import PyPDFLoader
from langchain_community.vectorstores import FAISS
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter
from pydantic import BaseModel, Field

from mesa_pedidos import config
from mesa_pedidos.modelos import crear_embeddings, crear_llm


# =============================================================================
# Formas de los datos (Pydantic)
# =============================================================================

class RespuestaLLM(BaseModel):
    """Lo que el LLM está obligado a devolver (structured output).

    El LLM elige QUÉ fragmentos usó (eso es comprensión). Documento y página
    no los escribe él: los pone el código después, desde la metadata.
    """

    # Las descripciones (Field) son instrucciones: el LLM las lee para saber qué poner.
    respuesta: str = Field(description="Respuesta al cliente, sólo con lo que dicen los fragmentos.")
    fragmentos_usados: list[int] = Field(
        description="Números de los fragmentos usados para responder, ej. [1, 3]. Vacía si no alcanza."
    )
    alcanza: bool = Field(
        description="True si los fragmentos responden la pregunta; False si falta información."
    )


class Cita(BaseModel):
    """Una fuente verificable: qué PDF y qué página."""
    documento: str
    pagina: int


class RespuestaRAG(BaseModel):
    """Lo que devuelve el RAG: el texto del LLM más las citas que arma el código."""
    respuesta: str
    citas: list[Cita]
    alcanza: bool


# =============================================================================
# Fase 1: indexar (una vez)
# =============================================================================

def cargar_paginas() -> list[Document]:
    """Lee los 4 PDF y devuelve una lista con un Document por página."""
    archivos = sorted(config.CARPETA_POLITICAS.glob("*.pdf"))  # sorted: siempre el mismo orden
    if not archivos:
        raise FileNotFoundError(f"No hay PDF en {config.CARPETA_POLITICAS}")

    paginas = []
    for archivo in archivos:
        for pagina in PyPDFLoader(str(archivo)).load():
            # Acá nace la cita: documento y página quedan pegados a la página como metadata,
            # y viajan con ella hasta la respuesta. pypdf numera desde 0; la cita, desde 1.
            pagina.metadata = {
                "documento": archivo.name,
                "pagina": pagina.metadata["page"] + 1,
            }
            paginas.append(pagina)
    return paginas


def construir_indice() -> FAISS:
    """PDF -> chunks -> vectores -> FAISS, y lo guarda en disco para no repetirlo."""
    paginas = cargar_paginas()

    # Corta cada página en chunks de ~1000 caracteres, prefiriendo cortar entre líneas.
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=config.TAMANO_CHUNK,
        chunk_overlap=config.SOLAPAMIENTO_CHUNK,  # cada chunk repite el final del anterior
    )
    # Cada chunk hereda la metadata (documento, página) de la página de la que salió.
    chunks = splitter.split_documents(paginas)
    print(f"  Indexando {len(paginas)} páginas en {len(chunks)} chunks "
          f"con {config.PROVEEDOR_EMBEDDINGS}: {config.MODELO_EMBEDDINGS}...")

    # Calcula el vector de cada chunk y arma el índice (el paso caro).
    indice = FAISS.from_documents(chunks, crear_embeddings())

    config.CARPETA_INDICE.mkdir(parents=True, exist_ok=True)
    indice.save_local(str(config.CARPETA_INDICE))  # index.faiss (vectores) + index.pkl (textos)
    return indice


def obtener_indice(reindexar: bool = False) -> FAISS:
    """Carga el índice de disco si existe; si no, lo construye."""
    if reindexar and config.CARPETA_INDICE.exists():
        shutil.rmtree(config.CARPETA_INDICE)  # borra la carpeta entera para forzar la reconstrucción

    if (config.CARPETA_INDICE / "index.faiss").exists():
        print(f"  Cargando índice de {config.CARPETA_INDICE}")
        return FAISS.load_local(
            str(config.CARPETA_INDICE),
            crear_embeddings(),  # hace falta igual: la pregunta también se convierte en vector
            allow_dangerous_deserialization=True,  # seguro sólo porque el índice lo generamos nosotros
        )

    return construir_indice()


# =============================================================================
# Fase 2: consultar (con cada pregunta)
# =============================================================================

PROMPT_SISTEMA = """Sos el asistente de la Mesa de Pedidos de una distribuidora.
Respondé la pregunta del cliente usando SÓLO los fragmentos de las políticas que te paso.
Cada fragmento empieza con su número y su fuente: [1] documento, p. N.

Reglas:
- No uses conocimiento propio ni completes con suposiciones.
- En fragmentos_usados, poné el número de cada fragmento que usaste para responder.
- Si los fragmentos no alcanzan para responder, decilo en la respuesta, marcá alcanza = false
  y no inventes."""


def formatear_contexto(chunks: list[Document]) -> str:
    """Arma el texto que ve el LLM: cada chunk con su número y su fuente arriba.

    Ejemplo de un fragmento:
        [1] logistica_fletes_2026.pdf, p. 1
        Zona 5 - Patagonia (Neuquen, ...): flete $175.000 por envio...
    """
    bloques = []
    numero = 1
    for chunk in chunks:
        encabezado = f"[{numero}] {chunk.metadata['documento']}, p. {chunk.metadata['pagina']}"
        bloques.append(f"{encabezado}\n{chunk.page_content}")
        numero += 1
    return "\n\n".join(bloques)  # una línea en blanco entre fragmentos


def armar_citas(fragmentos_usados: list[int], chunks: list[Document]) -> list[Cita]:
    """Traduce los números que eligió el LLM a documento y página reales.

    Ejemplo: el LLM devuelve [1] -> es chunks[0] -> su metadata dice logistica_fletes_2026.pdf, p. 1.
    """
    citas = []
    for numero in fragmentos_usados:
        # El LLM sólo puede elegir entre los fragmentos que recibió (del 1 al k).
        if numero < 1 or numero > len(chunks):
            raise ValueError(f"El LLM citó el fragmento {numero}, pero sólo recibió {len(chunks)}")

        chunk = chunks[numero - 1]  # el fragmento [1] es la posición 0 de la lista
        cita = Cita(documento=chunk.metadata["documento"], pagina=chunk.metadata["pagina"])

        if cita not in citas:  # dos chunks de la misma página son una sola cita
            citas.append(cita)
    return citas


def responder(pregunta: str, indice: FAISS) -> tuple[RespuestaRAG, list[Document]]:
    """Responde una pregunta con los PDF de políticas. Devuelve la respuesta y los chunks usados."""
    # 1. Recuperación: FAISS convierte la pregunta en vector y trae los k chunks más parecidos.
    #    Siempre trae k, aunque ninguno sirva: decidir si alcanzan es trabajo del LLM.
    chunks = indice.similarity_search(pregunta, k=config.TOP_K)

    # 2. El LLM, obligado a responder con la forma de RespuestaLLM.
    #    El proveedor y el modelo salen del .env (ver modelos.py).
    llm_estructurado = crear_llm().with_structured_output(RespuestaLLM)

    # 3. Generación: las reglas van como mensaje de sistema; los fragmentos y la pregunta, como
    #    mensaje del usuario. Si la salida no cumple RespuestaLLM, falla acá de forma visible.
    mensaje_usuario = f"Fragmentos:\n\n{formatear_contexto(chunks)}\n\nPregunta: {pregunta}"
    salida = llm_estructurado.invoke([
        ("system", PROMPT_SISTEMA),
        ("human", mensaje_usuario),
    ])

    # 4. Se arma la respuesta final: texto y "alcanza" del LLM, citas del código.
    respuesta = RespuestaRAG(
        respuesta=salida.respuesta,
        citas=armar_citas(salida.fragmentos_usados, chunks),
        alcanza=salida.alcanza,
    )
    return respuesta, chunks

