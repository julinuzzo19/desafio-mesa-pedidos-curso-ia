"""
tools.py — Las consultas a los datos de negocio que usa validar_pedido.

Las llama un nodo del grafo, siempre y en un orden fijo; no las elige un LLM.
Se usan con .invoke(), ej.: consultar_producto.invoke({"sku": "AB-1020"})
"""

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from mesa_pedidos import config
from mesa_pedidos.datos import Catalogo, CatalogoCSV, Clientes, ClientesCSV

# El catálogo se carga una vez, cuando se importa este archivo. Las tools sólo conocen la
# interfaz (Catalogo): para cambiar de dónde salen los datos, se cambia esta línea.
CATALOGO: Catalogo = CatalogoCSV(config.RUTA_CATALOGO)


class ConsultarProductoInput(BaseModel):
    """Lo que recibe consultar_producto (args_schema): valida que llegue un SKU de texto."""
    sku: str = Field(description="Código del producto, ej. AB-1020.")


# @tool convierte la función en una tool: el nombre sale de la función, la descripción del
# docstring y los parámetros del args_schema.
@tool(args_schema=ConsultarProductoInput)
def consultar_producto(sku: str) -> dict:
    """
    Consultar producto en la base de datos segun codigo.

    Devuelve siempre un dict, nunca una excepción:
      - si existe:    {"encontrado": True, "sku": ..., "precio_lista": ..., "stock": ..., ...}
      - si no existe: {"encontrado": False, "sku": <el código recibido>}
    """
    producto = CATALOGO.buscar(sku)

    if producto is None:
        # Se devuelve el código tal como llegó: el log y la persona que reciba el pedido
        # necesitan saber cuál fue el renglón que falló.
        return {"encontrado": False, "sku": sku}

    # ** copia todas las claves del producto dentro del dict nuevo.
    return {"encontrado": True, **producto}



# Igual que el catálogo: se carga una vez y la tool sólo conoce la interfaz.
CLIENTES: Clientes = ClientesCSV(config.RUTA_CLIENTES)


class VerificarCreditoInput(BaseModel):
    """Lo que recibe verificar_credito (args_schema): valida que llegue un CUIT de texto."""
    cuit: str = Field(description="CUIT del cliente, con o sin guiones, ej. 30-71455982-2.")


@tool(args_schema=VerificarCreditoInput)
def verificar_credito(cuit: str) -> dict:
    """
    Consultar la situación de crédito de un cliente según su CUIT.

    Devuelve datos, no un veredicto: decidir si el pedido entra es trabajo de validar_pedido,
    que cruza el crédito con la mora, el estado y la forma de pago.
    Devuelve siempre un dict, nunca una excepción:
      - si existe:    {"encontrado": True, "limite_credito": ..., "saldo_actual": ...,
                       "disponible": ..., "mora_dias": ..., "estado": ..., ...}
      - si no existe: {"encontrado": False, "cuit": <el CUIT recibido>}
    """
    cliente = CLIENTES.buscar(cuit)

    if cliente is None:
        return {"encontrado": False, "cuit": cuit}

    # El disponible es un dato derivado, no una decisión: se calcula acá para que la resta
    # viva en un solo lugar. Puede dar negativo si el saldo ya supera el límite.
    disponible = cliente["limite_credito"] - cliente["saldo_actual"]
    return {"encontrado": True, **cliente, "disponible": disponible}
