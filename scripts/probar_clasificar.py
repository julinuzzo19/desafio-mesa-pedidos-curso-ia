"""
probar_clasificar.py — Prueba manual del nodo clasificar desde la terminal, sin grafo.

No es parte del sistema: sirve para ver cómo clasifica los mensajes de la bandeja después de
cambiar el prompt. Corre todos por defecto, porque un cambio puede arreglar un caso y romper otro.

Uso (desde la raíz del repo):
  python -m scripts.probar_clasificar                     (los 20 mensajes)
  python -m scripts.probar_clasificar MSG-004 MSG-017     (sólo esos)
"""

import argparse
import json
import sys

from mesa_pedidos import config
from mesa_pedidos.nodos import clasificar


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")  # para que se vean los acentos en Windows

    # Lee los ids que se escribieron en la terminal; si no hay ninguno, se corren todos.
    parser = argparse.ArgumentParser(description="Clasifica mensajes de la bandeja.")
    parser.add_argument("ids", nargs="*", help="Ids de mensajes, ej. MSG-004. Vacío = todos.")
    args = parser.parse_args()

    with open(config.RUTA_BANDEJA, encoding="utf-8") as archivo:
        for linea in archivo:
            mensaje = json.loads(linea)  # cada línea del .jsonl es un mensaje

            if args.ids and mensaje["id"] not in args.ids:
                continue

            # El nodo sólo lee el mensaje: alcanza con un estado armado a mano con ese campo.
            resultado = clasificar({"mensaje": mensaje})
            clasificacion = resultado["clasificacion"]

            inicio = mensaje["texto"][:70]
            print(f"{mensaje['id']}  {clasificacion['tipo']:<9} | {inicio}...")
            if clasificacion["motivo"]:
                print(f"           motivo: {clasificacion['motivo']}")


# Sólo corre main() si se ejecuta este archivo directamente.
if __name__ == "__main__":
    main()
