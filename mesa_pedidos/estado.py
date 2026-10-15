"""
estado.py — El estado que viaja por el grafo: lo único que un nodo puede leer de otro.

Cada campo que reemplaza su valor tiene un solo nodo que lo escribe; así, si un valor está
mal, se sabe qué nodo mirar. La excepción es log: lo escriben todos y acumula (reducer add).

Un campo en None significa "el nodo que lo escribe no corrió para este mensaje"
(ej.: una consulta termina sin pedido ni decisión). Quien lo lea tiene que contemplarlo.
"""

from operator import add
from typing import Annotated, Literal, TypedDict

from mesa_pedidos.rag import RespuestaRAG


class Mensaje(TypedDict):
    """Un renglón de bandeja.jsonl, tal como llega."""
    id: str
    canal: str
    fecha: str  # fecha del mensaje (no la de hoy): las reglas con plazos se miden contra esta
    cuit: str
    remitente: str
    texto: str


class Clasificacion(TypedDict):
    """Qué tipo de mensaje es. El nodo escribe el tipo; el router lo traduce a un nodo."""
    tipo: Literal["consulta", "pedido", "derivar"]
    motivo: str | None  # por qué se derivó cuando la clasificación falló; None si salió bien


class EstadoMesa(TypedDict):
    """El estado completo de un mensaje (un thread por mensaje).

    Ejemplo al arrancar (lo arma correr.py):
        {"mensaje": {...}, "cliente": None, "clasificacion": None, "respuesta": None,
         "pedido": None, "decision": None, "log": []}
    """

    # Lo escribe correr.py en el estado inicial.
    mensaje: Mensaje

    # Lo escribe cargar_cliente: datos del cliente + categoría, como estaban al llegar el mensaje.
    # Las condiciones financieras no van acá: las lee validar_pedido con verificar_credito.
    cliente: dict | None

    # Lo escribe clasificar.
    clasificacion: Clasificacion | None

    # Lo escribe responder_consulta: texto, citas (documento + página) y alcanza.
    respuesta: RespuestaRAG | None

    # Lo escribe extraer_pedido: sólo lo que dice el mensaje. Su forma se define en ese sub-paso.
    pedido: dict | None

    # Lo escribe validar_pedido: acción + motivo + alertas + el escenario con que decidió
    # (crédito leído, neto). Van juntos para que Gerencia vea los mismos números que
    # produjeron la decisión. Su forma se define en ese sub-paso.
    decision: dict | None

    # Lo escriben todos los nodos, una línea cada uno. Sin el reducer add, cada nodo
    # pisaría la lista del anterior y quedaría sólo la línea del último.
    log: Annotated[list[str], add]
