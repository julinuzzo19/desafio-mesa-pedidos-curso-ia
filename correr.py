"""
correr.py — Procesa mensajes de la bandeja desde un menú y maneja la aprobación de Gerencia.

Cada mensaje es un thread (thread_id = id del mensaje) guardado en artifacts/checkpoints.sqlite:
un pedido frenado en aprobacion_humana se puede retomar después, aunque se cierre la terminal.

Antes de invocar el grafo se valida que el CUIT del mensaje esté en clientes.csv. Si no está,
el mensaje se rechaza acá y el grafo no arranca.

Uso (desde la raíz del repo, con el entorno activado):
  python correr.py
"""

import json
import sqlite3
import sys

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command

from mesa_pedidos import config
from mesa_pedidos.grafo import construir_grafo, estado_inicial
from mesa_pedidos.tools import CLIENTES


def leer_bandeja() -> list[dict]:
    """Los mensajes de bandeja.jsonl, en orden."""
    mensajes = []
    with open(config.RUTA_BANDEJA, encoding="utf-8") as archivo:
        for linea in archivo:
            mensajes.append(json.loads(linea))
    return mensajes


def situacion(grafo, id_mensaje: str) -> str:
    """Cómo está el thread del mensaje: sin correr, frenado o terminado."""
    guardado = grafo.get_state({"configurable": {"thread_id": id_mensaje}})
    if not guardado.values:
        return ""
    if guardado.next:
        # Tiene un nodo pendiente: quedó frenado en aprobacion_humana.
        return "[FRENADO]"
    return "[terminado]"


def mostrar_menu(grafo, mensajes: list[dict]) -> None:
    """Lista los mensajes con un número, el comienzo del texto y su situación."""
    print("\n=== Mesa de Pedidos ===")
    for numero, mensaje in enumerate(mensajes, start=1):
        texto = mensaje["texto"].replace("\n", " ")
        if len(texto) > 60:
            texto = texto[:60] + "..."
        estado = situacion(grafo, mensaje["id"])
        print(f"{numero:>3}. {mensaje['id']}  {texto}  {estado}")
    print("  b. borrar todos los checkpoints   q. salir")


def mostrar_resultado(grafo, configuracion: dict) -> None:
    """Imprime el log, la respuesta con sus citas y, si está frenado, el payload para Gerencia."""
    guardado = grafo.get_state(configuracion)
    for paso in guardado.values["log"]:
        print(f"  {paso}")

    respuesta = guardado.values.get("respuesta")
    if respuesta is not None:
        print(f"\n  respuesta: {respuesta.respuesta}")
        for cita in respuesta.citas:
            print(f"  cita: {cita.documento}, p. {cita.pagina}")

    for tarea in guardado.tasks:
        for pendiente in tarea.interrupts:
            print("\n  FRENADO, esperando a Gerencia. Lo que ve Gerencia:")
            print(json.dumps(pendiente.value, ensure_ascii=False, indent=4))


def preguntar_gerencia() -> bool | None:
    """Pide la decisión de Gerencia. None si se deja para después."""
    while True:
        opcion = input("\n¿Gerencia aprueba? (s = sí / n = no / Enter = dejar pendiente): ")
        opcion = opcion.strip().lower()
        if opcion == "s":
            return True
        if opcion == "n":
            return False
        if opcion == "":
            return None
        print("  Respuesta no válida.")


def procesar(grafo, mensaje: dict) -> None:
    """Corre un mensaje, o lo retoma si está frenado, o muestra lo guardado si ya terminó."""
    configuracion = {"configurable": {"thread_id": mensaje["id"]}}
    print(f"\n===== {mensaje['id']} ({mensaje['remitente']})")
    print(f"  texto: {mensaje['texto']}\n")

    guardado = grafo.get_state(configuracion)
    if not guardado.values:
        # Mensaje nuevo: primero se valida el CUIT, fuera del grafo.
        if CLIENTES.buscar(mensaje["cuit"]) is None:
            print(f"  RECHAZADO: el CUIT {mensaje['cuit']} no está en clientes.csv. El grafo no arranca.")
            return
        grafo.invoke(estado_inicial(mensaje), configuracion)
    else:
        # Ya tiene thread: no se vuelve a correr (el log se duplicaría); se muestra lo guardado.
        print("  (ya procesado: se muestra lo guardado)")

    mostrar_resultado(grafo, configuracion)

    # Si quedó frenado, Gerencia decide ahora o lo deja para después.
    if grafo.get_state(configuracion).next:
        aprobar = preguntar_gerencia()
        if aprobar is None:
            print("  Queda pendiente. Se puede retomar más tarde, aunque se cierre la terminal.")
            return
        grafo.invoke(Command(resume={"aprobar": aprobar}), configuracion)
        print("\n  Después de la decisión de Gerencia:")
        mostrar_resultado(grafo, configuracion)


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")  # para que se vean los acentos en Windows

    config.RUTA_CHECKPOINTS.parent.mkdir(parents=True, exist_ok=True)
    # check_same_thread=False: LangGraph puede usar la conexión desde otro hilo.
    conexion = sqlite3.connect(config.RUTA_CHECKPOINTS, check_same_thread=False)
    grafo = construir_grafo(checkpointer=SqliteSaver(conexion))
    mensajes = leer_bandeja()

    while True:
        mostrar_menu(grafo, mensajes)
        opcion = input("\nElegí un número: ").strip().lower()

        if opcion == "q":
            break
        if opcion == "b":
            # Borra todos los threads: la próxima vez cada mensaje corre de cero.
            conexion.close()
            config.RUTA_CHECKPOINTS.unlink(missing_ok=True)
            conexion = sqlite3.connect(config.RUTA_CHECKPOINTS, check_same_thread=False)
            grafo = construir_grafo(checkpointer=SqliteSaver(conexion))
            print("  Checkpoints borrados.")
            continue
        if not opcion.isdigit() or not 1 <= int(opcion) <= len(mensajes):
            print("  Opción no válida.")
            continue

        procesar(grafo, mensajes[int(opcion) - 1])
        input("\n(Enter para volver al menú)")

    conexion.close()


if __name__ == "__main__":
    main()
