"""
nodos.py — Los nodos del grafo.

Cada nodo recibe el estado completo y devuelve sólo los campos que cambia; LangGraph los
mezcla con el resto. Cada uno deja una línea en log: qué nodo actuó y qué decidió o encontró.
"""

from typing import Literal

from pydantic import BaseModel, Field

from mesa_pedidos.estado import EstadoMesa, Pedido
from mesa_pedidos import rag
from mesa_pedidos.modelos import crear_llm
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
  comerciales, descuentos, envíos, garantías, devoluciones, formas de pago, fichas técnicas).
  Las políticas cubren información específica de los productos (características, qué incluye,
  compatibilidades), pero no recomendaciones: pedir que le aconsejen qué producto le conviene
  NO es una consulta.
- pedido: quiere comprar productos. Si además pide condiciones (destino, plazo, forma de pago,
  un descuento), sigue siendo pedido: esas condiciones se evalúan después.
- derivar: todo lo demás. Reclamos, mensajes de proveedores, pedidos de hablar con una persona.

Si una parte del mensaje pide comunicación directa con una persona, es derivar aunque el resto
sea una consulta o un pedido. Cuenta sólo si el cliente lo pide de forma explícita: que lo
llamen, que lo visiten, hablar con alguien. Lo mismo si el mensaje trae un reclamo.

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

    # El cliente del proveedor reintenta solo ante fallas de red. Si después de eso el
    # proveedor sigue sin responder, la excepción sube a propósito: una caída de red no es una
    # decisión de negocio, y si se mandara a derivar ensuciaría la medición.
    llm = crear_llm()

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


# =============================================================================
# responder_consulta
# =============================================================================

# El índice se carga la primera vez que se responde una consulta y queda en memoria para las
# siguientes. No se carga al importar este archivo: tarda (carga el modelo de embeddings) y
# muchos usos de nodos.py no lo necesitan (ej. probar sólo clasificar).
_indice = None


def obtener_indice():
    """Devuelve el índice, cargándolo sólo la primera vez."""
    global _indice  # global: se modifica la variable del archivo, no una local
    if _indice is None:
        _indice = rag.obtener_indice()
    return _indice


def responder_consulta(estado: EstadoMesa) -> dict:
    """Responde la consulta con los PDF de políticas, citando documento y página.

    Le pasa al RAG la fecha del mensaje (los plazos se miden contra ella, no contra hoy) y los
    datos del cliente del registro (las reglas que dependen de quién es salen de ahí, no del texto).
    Ejemplo de lo que devuelve:
        {"respuesta": RespuestaRAG(respuesta="...", citas=[...], alcanza=True),
         "log": ["responder_consulta: alcanza sí, 1 cita"]}
    """
    mensaje = estado["mensaje"]

    # Si el proveedor no responde, la excepción sube: igual que en clasificar.
    respuesta, _chunks = rag.responder(
        mensaje["texto"],
        obtener_indice(),
        fecha=mensaje["fecha"],
        cliente=estado["cliente"],
    )

    alcanza = "sí" if respuesta.alcanza else "no"
    linea = f"responder_consulta: alcanza {alcanza}, {len(respuesta.citas)} cita(s)"
    return {"respuesta": respuesta, "log": [linea]}


# =============================================================================
# extraer_pedido
# =============================================================================

class Producto(BaseModel):
    """Un producto del pedido: código y cantidad, tal como los escribió el cliente."""
    sku: str = Field(description="Código del producto tal como figura en el mensaje, ej. AB-1020.")
    cantidad: int = Field(gt=0, description="Cantidad pedida de ese producto.")  # gt=0: mayor a cero


class PedidoLLM(BaseModel):
    """Lo que el LLM está obligado a devolver (structured output).

    Sólo lo que dice el mensaje: lo que no menciona queda en None. Completar con los datos
    habituales del cliente es trabajo de validar_pedido, así se distingue lo que pidió el
    cliente de lo que se supuso.
    """
    productos: list[Producto] = Field(description="Los productos pedidos, uno por código.")
    destino: str | None = Field(
        default=None, description="Lugar de entrega si el mensaje lo dice; si no, null."
    )
    forma_pago: Literal["cuenta_corriente", "contado_contra_entrega", "anticipado_transferencia"] | None = Field(
        default=None,
        description=(
            "cuenta_corriente si pide pagar a N días o cargarlo a la cuenta; "
            "contado_contra_entrega si paga al recibir; "
            "anticipado_transferencia si paga por transferencia antes del envío; "
            "null si no lo dice."
        ),
    )
    plazo_dias: int | None = Field(
        default=None, description="Días de plazo de pago si los dice (ej. 'a 30 días' -> 30); si no, null."
    )
    descuento_pedido: float | None = Field(
        default=None, description="Porcentaje de descuento que pide el cliente (ej. 15); si no pide, null."
    )


PROMPT_EXTRAER = """Sos el asistente de la Mesa de Pedidos de una distribuidora.
Extraé del mensaje del cliente los datos del pedido.

Reglas:
- Extraé SÓLO lo que el mensaje dice. Si un dato no aparece, dejalo en null: no lo completes,
  no lo supongas. "Como siempre" sin más detalle no es un dato: dejalo en null.
- Copiá cada código de producto tal como está escrito, con su cantidad.
- "A N días" o "cargarlo a la cuenta" es cuenta_corriente; los N días van en plazo_dias.

Ejemplos:
- "Mandame 12 rollos C-25 y 3 mechas M-8 a Rafaela, a 15 días." ->
  productos [C-25 x 12, M-8 x 3], destino Rafaela, forma_pago cuenta_corriente, plazo_dias 15
- "Quiero 40 tornillos T-100, pago con transferencia antes de que salga. Si me hacen un 8%..." ->
  productos [T-100 x 40], forma_pago anticipado_transferencia, descuento_pedido 8
- "Lo de siempre: 5 baldes P-20." -> productos [P-20 x 5], todo lo demás null"""


def extraer_pedido(estado: EstadoMesa) -> dict:
    """Convierte el texto del pedido en datos: productos, destino, forma de pago, plazo, descuento.

    Si la salida del LLM no se puede leer, no lanza: escribe extraido=False con el motivo, y
    validar_pedido lo manda a derivar (después de este nodo no hay router).
    Ejemplo de lo que devuelve:
        {"pedido": {"extraido": True, "productos": [{"sku": "AB-1020", "cantidad": 200}], ...},
         "log": ["extraer_pedido: 1 producto(s), pago sin indicar"]}
    """
    texto = estado["mensaje"]["texto"]

    # Igual que en clasificar: si el proveedor no responde, la excepción sube.
    llm_estructurado = crear_llm().with_structured_output(PedidoLLM, include_raw=True)
    resultado = llm_estructurado.invoke([
        ("system", PROMPT_EXTRAER),
        ("human", texto),
    ])

    salida = resultado["parsed"]
    if salida is None:
        # Mismas claves que un pedido extraído, con los datos vacíos: quien lo lea encuentra
        # siempre la misma forma (ver Pedido en estado.py).
        pedido_fallido: Pedido = {
            "extraido": False,
            "motivo": f"salida inválida del LLM: {resultado['parsing_error']}",
            "productos": [],
            "destino": None,
            "forma_pago": None,
            "plazo_dias": None,
            "descuento_pedido": None,
        }
        return {
            "pedido": pedido_fallido,
            "log": ["extraer_pedido: no se pudo extraer (salida inválida)"],
        }

    # model_dump convierte el objeto Pydantic en un dict común, que es lo que guarda el estado.
    pedido: Pedido = {"extraido": True, "motivo": None, **salida.model_dump()}

    pago = salida.forma_pago if salida.forma_pago is not None else "sin indicar"
    linea = f"extraer_pedido: {len(salida.productos)} producto(s), pago {pago}"
    return {"pedido": pedido, "log": [linea]}
