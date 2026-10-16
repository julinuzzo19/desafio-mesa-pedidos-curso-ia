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


class Cliente(TypedDict):
    """Los datos del cliente que usan los nodos, como estaban al llegar el mensaje.

    Las condiciones financieras (límite, saldo, mora, plazo, descuento) no van acá: las lee
    validar_pedido con verificar_credito, así cada dato tiene un solo origen.
    """
    cuit: str
    razon_social: str
    provincia: str
    localidad: str
    condicion_iva: str
    categoria: str


class ProductoPedido(TypedDict):
    """Un producto del pedido, tal como lo escribió el cliente."""
    sku: str
    cantidad: int


class Pedido(TypedDict):
    """Lo que extraer_pedido sacó del mensaje. Tiene siempre las mismas claves.

    Si la extracción falló, extraido es False, motivo dice por qué y los datos quedan vacíos;
    validar_pedido lo manda a derivar. Un dato en None es un dato que el mensaje no dice.
    """
    extraido: bool
    motivo: str | None  # por qué falló la extracción; None si salió bien
    productos: list[ProductoPedido]
    destino: str | None
    forma_pago: Literal["cuenta_corriente", "contado_contra_entrega", "anticipado_transferencia"] | None
    plazo_dias: int | None
    descuento_pedido: float | None  # porcentaje, ej. 25


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
    cliente: Cliente | None

    # Lo escribe clasificar.
    clasificacion: Clasificacion | None

    # Lo escribe responder_consulta: texto, citas (documento + página) y alcanza.
    respuesta: RespuestaRAG | None

    # Lo escribe extraer_pedido: sólo lo que dice el mensaje.
    pedido: Pedido | None

    # Lo escribe validar_pedido: acción + motivo + alertas + el escenario con que decidió
    # (crédito leído, neto). Van juntos para que Gerencia vea los mismos números que
    # produjeron la decisión. Su forma se define en ese sub-paso.
    decision: dict | None

    # Lo escriben todos los nodos, una línea cada uno. Sin el reducer add, cada nodo
    # pisaría la lista del anterior y quedaría sólo la línea del último.
    log: Annotated[list[str], add]
