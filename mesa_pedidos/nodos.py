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
from mesa_pedidos.tools import CLIENTES, consultar_producto, verificar_credito

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


# =============================================================================
# validar_pedido
# =============================================================================

# Valores de condiciones_comerciales_2026.pdf. Si cambia el PDF, se cambian acá.
PEDIDO_MINIMO_AB = 250_000            # art. 3: categorías A y B, neto sin IVA
PEDIDO_MINIMO_C = 120_000             # art. 3: categoría C y monotributistas
ESCALA_VOLUMEN = [                    # art. 4: (neto desde, % de descuento), de mayor a menor
    (6_000_000, 12),
    (3_000_000, 8),
    (1_000_000, 5),
]
TOPE_DESCUENTO = 20                   # art. 5: descuento total sin consultar a Gerencia
TOPE_DESCUENTO_MARCAS = 15            # art. 5: herramienta eléctrica de estas marcas
MARCAS_TOPE_REDUCIDO = ["Dewalt", "Makita", "Bosch"]
RUBRO_TOPE_REDUCIDO = "Herramienta electrica"
MORA_GERENCIA = 30                    # art. 7: de 30 a 60 días, cada pedido va a Gerencia
MORA_MAXIMA = 60                      # art. 7: más de 60, nada en cuenta corriente

# Si fallan varias reglas, gana la peor: la que está más arriba en esta lista.
PRIORIDAD_ACCIONES = ["rechazar", "derivar", "humano"]


def calcular_neto(productos: list[dict]) -> float:
    """Neto del pedido: precio de lista x cantidad, sin IVA y antes de descuentos.

    Es la lectura de "monto neto" acordada en el Paso 2 (la que usa el art. 4 para elegir el
    descuento por volumen). Recibe los productos ya consultados en el catálogo.
    Ejemplo: [{"precio_lista": 3250.0, "cantidad": 200}] -> 650000.0
    """
    neto = 0.0
    for producto in productos:
        neto += producto["precio_lista"] * producto["cantidad"]
    return neto


def descuento_por_volumen(neto: float) -> int:
    """Porcentaje de descuento por volumen según la escala del art. 4.

    Ejemplo: 1_200_000 -> 5 ; 800_000 -> 0
    """
    for desde, porcentaje in ESCALA_VOLUMEN:
        if neto >= desde:
            return porcentaje
    return 0


def elegir_accion(acciones: list[str]) -> str:
    """De las salidas que dispararon las reglas, devuelve la peor; si no hay ninguna, confirmar.

    Ejemplo: ["humano", "derivar", "humano"] -> "derivar"
    """
    for accion in PRIORIDAD_ACCIONES:
        if accion in acciones:
            return accion
    return "confirmar"


def completar_faltantes(pedido: Pedido, cliente: dict, credito: dict) -> dict:
    """Completa lo que el mensaje no dijo con los datos habituales del cliente.

    - destino: la localidad del cliente.
    - forma de pago: con plazo acordado (dias_plazo > 0), cuenta corriente; si no, contado
      contra entrega.
    - plazo (si paga en cuenta corriente): el plazo acordado.
    Lo que el mensaje sí dijo no se toca. Cada dato completado deja una línea de log, para
    distinguir lo que pidió el cliente de lo que se supuso.

    Ejemplo (MSG-012: destino dicho, pago no dicho, dias_plazo 30):
        {"destino": "Santa Rosa", "forma_pago": "cuenta_corriente", "plazo_dias": 30,
         "completados": ["forma_pago", "plazo_dias"], "log": [...dos líneas...]}
    """
    completados = []
    log = []

    destino = pedido["destino"]
    if destino is None:
        destino = cliente["localidad"]
        completados.append("destino")
        log.append(f"validar_pedido: destino completado con la localidad del cliente ({destino})")

    forma_pago = pedido["forma_pago"]
    plazo_dias = pedido["plazo_dias"]
    if forma_pago is None:
        # El plazo acordado dice cómo compra habitualmente: con plazo, a cuenta corriente.
        if credito["dias_plazo"] > 0:
            forma_pago = "cuenta_corriente"
        else:
            forma_pago = "contado_contra_entrega"
        completados.append("forma_pago")
        log.append(f"validar_pedido: forma de pago completada con la habitual ({forma_pago})")
    if forma_pago == "cuenta_corriente" and plazo_dias is None:
        plazo_dias = credito["dias_plazo"]
        completados.append("plazo_dias")
        log.append(f"validar_pedido: plazo completado con el habitual ({plazo_dias} días)")

    return {
        "destino": destino,
        "forma_pago": forma_pago,
        "plazo_dias": plazo_dias,
        "completados": completados,
        "log": log,
    }


def validar_pedido(estado: EstadoMesa) -> dict:
    """Aplica las reglas comerciales al pedido y decide: confirmar, humano, rechazar o derivar.

    Sin LLM: sólo datos estructurados (pedido, cliente, catálogo, crédito) y reglas por código.
    Evalúa TODAS las reglas y junta las alertas; la salida es la peor de las que dispararon.
    Antes completa lo que el mensaje no dijo (destino, forma de pago, plazo) con los datos
    habituales del cliente, y lo deja anotado en el log.
    """
    pedido = estado["pedido"]
    cliente = estado["cliente"]
    log = []

    # Cada regla que falla agrega su salida y un texto. Al final se elige la peor salida.
    acciones = []
    alertas = []

    # --- Regla 1: la extracción falló. No hay pedido que evaluar. ---
    if not pedido["extraido"]:
        decision = {
            "accion": "derivar",
            "motivo": f"no se pudo extraer el pedido: {pedido['motivo']}",
            "alertas": [],
            "escenario": None,
        }
        return {"decision": decision, "log": ["validar_pedido: derivar (pedido no extraído)"]}

    # --- Datos de las tools: crédito del cliente y cada producto del catálogo. ---
    credito = verificar_credito.invoke({"cuit": cliente["cuit"]})
    if not credito["encontrado"]:
        # cargar_cliente ya encontró a este cliente: si ahora no está, es un bug, no negocio.
        raise ValueError(f"CUIT {cliente['cuit']} no está en clientes al validar el pedido")

    productos_encontrados = []  # los del catálogo, con la cantidad pedida
    for item in pedido["productos"]:
        producto = consultar_producto.invoke({"sku": item["sku"]})

        # Regla 2: el SKU no existe en el catálogo.
        if not producto["encontrado"]:
            acciones.append("derivar")
            alertas.append(f"SKU {item['sku']} no existe en el catálogo")
            continue  # sin precio ni stock no hay nada más que revisar de este producto

        # Regla 3: no hay stock suficiente (art. 9: nunca se confirma stock que no existe).
        if item["cantidad"] > producto["stock"]:
            acciones.append("derivar")
            alertas.append(
                f"stock insuficiente de {producto['sku']}: pide {item['cantidad']}, hay {producto['stock']}"
            )

        productos_encontrados.append({**producto, "cantidad": item["cantidad"]})

    # --- Completar lo que el mensaje no dijo, con los datos habituales del cliente. ---
    completo = completar_faltantes(pedido, cliente, credito)
    destino = completo["destino"]
    forma_pago = completo["forma_pago"]
    plazo_dias = completo["plazo_dias"]
    completados = completo["completados"]
    log.extend(completo["log"])  # extend: agrega cada línea de la lista, no la lista entera

    en_cuenta_corriente = forma_pago == "cuenta_corriente"

    # --- Cálculos ---
    neto = calcular_neto(productos_encontrados)
    volumen = descuento_por_volumen(neto)
    descuento_pedido = pedido["descuento_pedido"]
    descuento_total = credito["descuento_habitual"] + volumen
    if descuento_pedido is not None:
        # Lectura acordada: lo que pide el cliente se suma al habitual y al de volumen.
        descuento_total += descuento_pedido

    # El tope es más bajo si hay herramienta eléctrica de ciertas marcas (art. 5).
    tope = TOPE_DESCUENTO
    for producto in productos_encontrados:
        if producto["rubro"] == RUBRO_TOPE_REDUCIDO and producto["marca"] in MARCAS_TOPE_REDUCIDO:
            tope = TOPE_DESCUENTO_MARCAS

    # --- Regla 4: pedido mínimo según categoría (art. 3: no se rechaza, queda en espera). ---
    if cliente["categoria"] == "C" or cliente["condicion_iva"] == "Monotributo":
        minimo = PEDIDO_MINIMO_C
    else:
        minimo = PEDIDO_MINIMO_AB
    if neto < minimo:
        acciones.append("derivar")
        alertas.append(f"neto ${neto:,.0f} por debajo del pedido mínimo ${minimo:,.0f}")

    # --- Reglas 5 y 6: mora (art. 7). ---
    mora = credito["mora_dias"]
    if mora > MORA_MAXIMA and en_cuenta_corriente:
        acciones.append("rechazar")
        alertas.append(f"mora de {mora} días: no se toman pedidos en cuenta corriente, sin excepción")
    elif MORA_GERENCIA <= mora <= MORA_MAXIMA:
        acciones.append("humano")
        alertas.append(f"mora de {mora} días: todo pedido requiere autorización de Gerencia")

    # --- Regla 7: crédito (art. 7). Sólo si usa crédito, es decir, cuenta corriente. ---
    if en_cuenta_corriente and credito["saldo_actual"] + neto > credito["limite_credito"]:
        acciones.append("humano")
        alertas.append(
            f"supera el límite de crédito: neto ${neto:,.0f}, disponible ${credito['disponible']:,.0f}"
        )

    # --- Regla 8: plazo (art. 6). Cuenta corriente sin plazo acordado, o más días que el acordado. ---
    if en_cuenta_corriente and credito["dias_plazo"] == 0:
        acciones.append("humano")
        alertas.append("pide cuenta corriente y no tiene plazo acordado")
    elif en_cuenta_corriente and plazo_dias > credito["dias_plazo"]:
        acciones.append("humano")
        alertas.append(f"pide {plazo_dias} días de plazo y tiene acordados {credito['dias_plazo']}")

    # --- Regla 9: descuento pedido por encima del tope (art. 5). ---
    # Sin pedido de descuento no hace falta Gerencia: Mesa aplica hasta el tope sin consultar.
    if descuento_pedido is not None and descuento_total > tope:
        acciones.append("humano")
        alertas.append(f"descuento total {descuento_total:g}% supera el tope de {tope}%")

    # --- Decisión: la peor salida; el motivo es la primera alerta de esa salida. ---
    accion = elegir_accion(acciones)
    motivo = None
    for numero in range(len(acciones)):
        if acciones[numero] == accion:
            # Setea motivo de la peor accion posible
            motivo = alertas[numero]
            break

    decision = {
        "accion": accion,
        "motivo": motivo,
        "alertas": alertas,
        # El escenario con que se decidió: Gerencia ve los mismos números (decisión del 3.1).
        "escenario": {
            "neto": neto,
            "descuento_total": descuento_total,
            "tope_descuento": tope,
            "credito": {
                "limite_credito": credito["limite_credito"],
                "saldo_actual": credito["saldo_actual"],
                "disponible": credito["disponible"],
                "mora_dias": credito["mora_dias"],
                "estado": credito["estado"],
            },
            "forma_pago": forma_pago,
            "plazo_dias": plazo_dias,
            "destino": destino,
            "completados": completados,
        },
    }

    log.append(f"validar_pedido: {accion} ({len(alertas)} alerta(s))")
    return {"decision": decision, "log": log}
