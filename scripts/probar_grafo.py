"""
probar_grafo.py — Corre mensajes de la bandeja por el grafo real y muestra su log.

No es parte del sistema: es una prueba manual. Usa el checkpointer (SQLite en artifacts/),
con un thread por mensaje (thread_id = id del mensaje). Un mensaje que ya tiene thread no se
vuelve a correr: se muestra lo guardado (si no, el log acumularía las líneas dos veces).

Uso (desde la raíz del repo):
  python -m scripts.probar_grafo                         (los 20 mensajes)
  python -m scripts.probar_grafo MSG-013 MSG-015         (sólo esos)
  python -m scripts.probar_grafo MSG-013 --retomar si    (Gerencia aprueba el frenado)
  python -m scripts.probar_grafo MSG-013 --retomar no    (Gerencia rechaza)
  python -m scripts.probar_grafo --borrar                (borra los checkpoints y corre de cero)
  python -m scripts.probar_grafo --dibujar               (imprime el grafo en formato mermaid)
"""

import argparse
import json
import sqlite3
import sys

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command

from mesa_pedidos import config
from mesa_pedidos.grafo import construir_grafo, estado_inicial


def mostrar(id_mensaje: str, grafo, configuracion: dict) -> None:
    """Imprime el log guardado del thread y, si está frenado, lo que ve Gerencia."""
    guardado = grafo.get_state(configuracion)
    print(f"===== {id_mensaje}")
    for paso in guardado.values["log"]:
        print(f"  {paso}")
    if guardado.values.get("respuesta") is not None:
        print(f"  respuesta: {guardado.values['respuesta'].respuesta}")

    # Un thread frenado tiene un nodo pendiente (next) y el payload del interrupt en sus tareas.
    if guardado.next:
        for tarea in guardado.tasks:
            for pendiente in tarea.interrupts:
                print("  FRENADO, esperando a Gerencia. Payload:")
                print(json.dumps(pendiente.value, ensure_ascii=False, indent=4))


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")  # para que se vean los acentos en Windows

    parser = argparse.ArgumentParser(description="Corre mensajes por el grafo.")
    parser.add_argument("ids", nargs="*", help="Ids de mensajes, ej. MSG-013. Sin ids: todos.")
    parser.add_argument("--retomar", choices=["si", "no"], help="Respuesta de Gerencia.")
    parser.add_argument("--borrar", action="store_true", help="Borra los checkpoints antes.")
    parser.add_argument("--dibujar", action="store_true", help="Imprime el grafo en mermaid.")
    args = parser.parse_args()

    if args.borrar and config.RUTA_CHECKPOINTS.exists():
        config.RUTA_CHECKPOINTS.unlink()
    config.RUTA_CHECKPOINTS.parent.mkdir(parents=True, exist_ok=True)

    # check_same_thread=False: LangGraph puede usar la conexión desde otro hilo.
    conexion = sqlite3.connect(config.RUTA_CHECKPOINTS, check_same_thread=False)
    grafo = construir_grafo(checkpointer=SqliteSaver(conexion))

    if args.dibujar:
        # Se pega en https://mermaid.live para verlo como diagrama.
        print(grafo.get_graph().draw_mermaid())
        return

    with open(config.RUTA_BANDEJA, encoding="utf-8") as archivo:
        for linea in archivo:
            mensaje = json.loads(linea)
            if args.ids and mensaje["id"] not in args.ids:
                continue

            configuracion = {"configurable": {"thread_id": mensaje["id"]}}
            ya_existe = bool(grafo.get_state(configuracion).values)

            if args.retomar:
                # Retomar: el mismo thread, con la respuesta de Gerencia en vez de un estado nuevo.
                if not grafo.get_state(configuracion).next:
                    print(f"===== {mensaje['id']}: no está frenado, no hay nada que retomar")
                    continue
                grafo.invoke(Command(resume={"aprobar": args.retomar == "si"}), configuracion)
            elif not ya_existe:
                grafo.invoke(estado_inicial(mensaje), configuracion)

            mostrar(mensaje["id"], grafo, configuracion)

    conexion.close()


if __name__ == "__main__":
    main()
