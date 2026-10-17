"""
grafo.py — Conecta los nodos: qué nodo sigue a cuál.

Las aristas fijas van siempre al mismo nodo. Las condicionales las decide un router: una
función que lee lo que un nodo ya escribió en el estado (el tipo, la acción) y lo traduce al
nombre del nodo siguiente. El router no decide nada de negocio: eso ya lo hizo el nodo.
"""

from langgraph.graph import END, START, StateGraph

from mesa_pedidos import nodos
from mesa_pedidos.estado import EstadoMesa


# =============================================================================
# Armado
# =============================================================================

def construir_grafo(checkpointer=None):
    """Arma y compila el grafo.

    Con checkpointer, el estado de cada mensaje se guarda después de cada nodo (un thread por
    mensaje); es lo que permite frenar en aprobacion_humana y retomar más tarde. Sin
    checkpointer el grafo corre igual, pero un interrupt() no se puede retomar.
    """
    grafo = StateGraph(EstadoMesa)

    # Los nodos: el nombre con que se los conecta y la función que corre.
    grafo.add_node("cargar_cliente", nodos.cargar_cliente)
    grafo.add_node("clasificar", nodos.clasificar)
    grafo.add_node("responder_consulta", nodos.responder_consulta)
    grafo.add_node("extraer_pedido", nodos.extraer_pedido)
    grafo.add_node("validar_pedido", nodos.validar_pedido)
    grafo.add_node("aprobacion_humana", nodos.aprobacion_humana)
    grafo.add_node("confirmar_pedido", nodos.confirmar_pedido)
    grafo.add_node("rechazar_pedido", nodos.rechazar_pedido)
    grafo.add_node("derivar_humano", nodos.derivar_humano)

    # Aristas fijas.
    grafo.add_edge(START, "cargar_cliente")
    grafo.add_edge("cargar_cliente", "clasificar")
    grafo.add_edge("extraer_pedido", "validar_pedido")

    # Bifurcación 1: según el tipo de mensaje.
    # El router es la lambda: LangGraph la llama con el estado al salir de clasificar, y
    # devuelve el tipo que escribió ese nodo. El mapa lo traduce al nodo siguiente.
    grafo.add_conditional_edges(
        "clasificar",
        lambda estado: estado["clasificacion"]["tipo"],
        {
            "consulta": "responder_consulta",
            "pedido": "extraer_pedido",
            "derivar": "derivar_humano",
        },
    )

    # Bifurcación 2: según la acción que decidió validar_pedido.
    grafo.add_conditional_edges(
        "validar_pedido",
        lambda estado: estado["decision"]["accion"],
        {
            "confirmar": "confirmar_pedido",
            "humano": "aprobacion_humana",
            "rechazar": "rechazar_pedido",
            "derivar": "derivar_humano",
        },
    )

    # Bifurcación 3: según lo que respondió Gerencia al retomar.
    grafo.add_conditional_edges(
        "aprobacion_humana",
        lambda estado: estado["aprobacion"]["aprobar"],
        {True: "confirmar_pedido", False: "rechazar_pedido"},
    )

    # Donde termina cada camino.
    grafo.add_edge("responder_consulta", END)
    grafo.add_edge("confirmar_pedido", END)
    grafo.add_edge("rechazar_pedido", END)
    grafo.add_edge("derivar_humano", END)

    return grafo.compile(checkpointer=checkpointer)


def estado_inicial(mensaje: dict) -> EstadoMesa:
    """El estado con que arranca un mensaje: todo en None salvo el mensaje (contrato del 3.1)."""
    return {
        "mensaje": mensaje,
        "cliente": None,
        "clasificacion": None,
        "respuesta": None,
        "pedido": None,
        "decision": None,
        "aprobacion": None,
        "log": [],
    }
