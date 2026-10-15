"""
nodos.py — Los nodos del grafo.

Cada nodo recibe el estado completo y devuelve sólo los campos que cambia; LangGraph los
mezcla con el resto. Cada uno deja una línea en log: qué nodo actuó y qué decidió o encontró.
"""

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
