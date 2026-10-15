"""
nodos.py — Los nodos del grafo.

Cada nodo recibe el estado completo y devuelve sólo los campos que cambia; LangGraph los
mezcla con el resto. Cada uno deja una línea en log: qué nodo actuó y qué decidió o encontró.
"""

from typing import Literal

from langchain_groq import ChatGroq
from pydantic import BaseModel, Field

from mesa_pedidos import config
from mesa_pedidos.estado import EstadoMesa
from mesa_pedidos.tools import CLIENTES

# Lo que los demás nodos usan del cliente. Las condiciones financieras (límite, saldo, mora,
# plazo, descuento) quedan afuera a propósito: las lee validar_pedido con verificar_credito,
# así cada dato tiene un solo origen.
CAMPOS_CLIENTE = ["cuit", "razon_social", "provincia", "localidad", "condicion_iva", "categoria"]


def cargar_cliente(estado: EstadoMesa) -> dict:
    """Guarda en el estado los datos del cliente que mandó el mensaje, como están al llegar.

    Ejemplo de lo que devuelve:
        {"cliente": {"cuit": "30-71455982-2", "razon_social": "...", "categoria": "B", ...},
         "log": ["cargar_cliente: ... (categoría B)"]}
    """
    cuit = estado["mensaje"]["cuit"]
    fila = CLIENTES.buscar(cuit)

    if fila is None:
        # No es un caso de negocio: correr.py rechaza los CUIT desconocidos antes de invocar
        # el grafo. Si llegó hasta acá, algo se rompió; se corta en el lugar, no tres nodos después.
        raise ValueError(
            f"CUIT {cuit} no está en clientes: correr.py debería haberlo rechazado "
            f"antes de invocar el grafo"
        )

    # Se copian sólo los campos de CAMPOS_CLIENTE, uno por uno.
    cliente = {}
    for campo in CAMPOS_CLIENTE:
        cliente[campo] = fila[campo]

    linea = f"cargar_cliente: {cliente['razon_social']} (categoría {cliente['categoria']})"
    return {"cliente": cliente, "log": [linea]}  # log va en lista: el reducer add suma listas


# =============================================================================
# clasificar
# =============================================================================

class ClasificacionLLM(BaseModel):
    """Lo que el LLM está obligado a devolver (structured output).

    Literal hace que Pydantic rechace cualquier otro valor (ej. "reclamo"): una salida
    así no llega al estado como tipo válido, se trata como salida inválida.
    """
    tipo: Literal["consulta", "pedido", "derivar"] = Field(
        description="consulta, pedido o derivar, según la intención del cliente."
    )


PROMPT_CLASIFICAR = """Sos el clasificador de la Mesa de Pedidos de una distribuidora.
Leé el mensaje de un cliente y decidí su tipo según lo que el cliente QUIERE, no según las
palabras que usa (mencionar productos o cantidades no lo convierte en pedido).

- consulta: quiere información que está en las políticas de la empresa (condiciones
  comerciales, descuentos, envíos, garantías, devoluciones, formas de pago). Asesorar sobre qué
  producto le conviene NO es una consulta: las políticas no lo cubren.
- pedido: quiere comprar productos. Si además pide condiciones (destino, plazo, forma de pago,
  un descuento), sigue siendo pedido: esas condiciones se evalúan después.
- derivar: todo lo demás. Reclamos, mensajes de proveedores, pedidos de hablar con una persona.

Si una parte del mensaje necesita a una persona, es derivar aunque el resto sea una consulta o
un pedido: un pedido con un reclamo, o una pregunta con un pedido de que lo llamen o lo visiten.

No evalúes montos, stock ni crédito: eso se revisa después.

Ejemplos:
- "¿Cuál es el plazo para devolver un producto fallado?" -> consulta
- "Necesito 10 cajas de tornillos T-100 y 4 mechas M-8, entrega en el depósito." -> pedido
- "Mandame 20 rollos de cable C-25 a 60 días y con 15% de descuento." -> pedido
- "La factura de este mes nos cobró las pinzas a un precio distinto del acordado." -> derivar
- "Somos fabricantes de pinceles y queremos ofrecerles nuestro catálogo." -> derivar
- "Quiero 5 baldes de pintura P-20, y de paso: la entrega pasada llegó rota." -> derivar
- "¿Aceptan cheques? Igual prefiero que pase un vendedor por el local a explicarme." -> derivar"""


def clasificar(estado: EstadoMesa) -> dict:
    """Decide si el mensaje es consulta, pedido o derivar, y lo escribe en el estado.

    Escribe el tipo, no el nodo siguiente: eso lo traduce el router del grafo.
    Ejemplo de lo que devuelve:
        {"clasificacion": {"tipo": "pedido", "motivo": None}, "log": ["clasificar: pedido"]}
    """
    texto = estado["mensaje"]["texto"]

    # temperature=0: el mismo mensaje se clasifica siempre igual.
    # ChatGroq reintenta solo ante fallas de red (max_retries=2). Si después de eso Groq sigue
    # sin responder, la excepción sube a propósito: una caída de red no es una decisión de
    # negocio, y si se mandara a derivar ensuciaría la medición.
    llm = ChatGroq(model=config.MODELO, temperature=0)

    # include_raw=True: si la salida no cumple ClasificacionLLM, en vez de lanzar una excepción
    # devuelve {"raw": ..., "parsed": None, "parsing_error": <el error>}.
    llm_estructurado = llm.with_structured_output(ClasificacionLLM, include_raw=True)
    resultado = llm_estructurado.invoke([
        ("system", PROMPT_CLASIFICAR),
        ("human", texto),
    ])

    salida = resultado["parsed"]
    if salida is None:
        # La salida no se pudo leer (parsing_error), o el modelo no devolvió nada estructurado.
        # Con incertidumbre se va al lado seguro: derivar, con el motivo para quien lo revise.
        error = resultado["parsing_error"]
        motivo = f"salida inválida del LLM: {error}"
        return {
            "clasificacion": {"tipo": "derivar", "motivo": motivo},
            "log": ["clasificar: derivar (salida inválida)"],
        }

    return {
        "clasificacion": {"tipo": salida.tipo, "motivo": None},
        "log": [f"clasificar: {salida.tipo}"],
    }
