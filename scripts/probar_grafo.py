"""
probar_grafo.py — Corre mensajes de la bandeja por el grafo real y muestra su log.

No es parte del sistema: es una prueba manual. Todavía sin checkpointer ni interrupt (Paso 5).

Uso (desde la raíz del repo):
  python -m scripts.probar_grafo                    (los 20 mensajes)
  python -m scripts.probar_grafo MSG-016 MSG-018    (sólo esos)
  python -m scripts.probar_grafo --dibujar          (imprime el grafo en formato mermaid)
"""

import argparse
import json
import sys

from mesa_pedidos import config
from mesa_pedidos.grafo import construir_grafo, estado_inicial


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")  # para que se vean los acentos en Windows

    parser = argparse.ArgumentParser(description="Corre mensajes por el grafo.")
    parser.add_argument("ids", nargs="*", help="Ids de mensajes, ej. MSG-016. Sin ids: todos.")
    parser.add_argument("--dibujar", action="store_true", help="Imprime el grafo en mermaid.")
    args = parser.parse_args()

    grafo = construir_grafo()

    if args.dibujar:
        # Se pega en https://mermaid.live para verlo como diagrama.
        print(grafo.get_graph().draw_mermaid())
        return

    with open(config.RUTA_BANDEJA, encoding="utf-8") as archivo:
        for linea in archivo:
            mensaje = json.loads(linea)
            if args.ids and mensaje["id"] not in args.ids:
                continue

            final = grafo.invoke(estado_inicial(mensaje))

            print(f"===== {mensaje['id']}")
            for paso in final["log"]:
                print(f"  {paso}")
            if final["respuesta"] is not None:
                print(f"  respuesta: {final['respuesta'].respuesta}")


if __name__ == "__main__":
    main()
