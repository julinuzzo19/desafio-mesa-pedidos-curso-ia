"""
probar_rag.py — Prueba manual del RAG desde la terminal, sin grafo.

No es parte del sistema: sirve para probar preguntas sueltas y ver qué chunks se recuperan.

Uso:
  python -m scripts.probar_rag "cuánto sale el flete a Neuquén"      (desde la raíz del repo)
  python -m scripts.probar_rag "..." --reindexar     (borra el índice y lo reconstruye)
"""

import argparse
import sys

from mesa_pedidos import config
from mesa_pedidos.rag import obtener_indice, responder


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")  # para que se vean los acentos en Windows

    # Lee lo que se escribió en la terminal: la pregunta y, opcionalmente, --reindexar.
    parser = argparse.ArgumentParser(description="Consulta las políticas con RAG.")
    parser.add_argument("pregunta")
    parser.add_argument("--reindexar", action="store_true", help="Borra y reconstruye el índice.")
    args = parser.parse_args()

    indice = obtener_indice(args.reindexar)
    respuesta, chunks = responder(args.pregunta, indice)

    # Se muestran los chunks recuperados: permite ver si un error es de recuperación
    # (el dato no llegó) o de generación (llegó y el LLM no lo usó).
    print(f"\nChunks recuperados (top {config.TOP_K}):")
    numero = 1
    for chunk in chunks:
        inicio = chunk.page_content[:90].replace("\n", " ")
        print(f"  [{numero}] {chunk.metadata['documento']}, p. {chunk.metadata['pagina']} | {inicio}...")
        numero += 1

    print(f"\nRespuesta: {respuesta.respuesta}")
    print(f"Alcanza:   {'sí' if respuesta.alcanza else 'no'}")
    print("Citas:")
    for cita in respuesta.citas:
        print(f"  - {cita.documento}, p. {cita.pagina}")


# Sólo corre main() si se ejecuta este archivo directamente.
if __name__ == "__main__":
    main()
