"""
datos.py — De dónde salen los datos de negocio (catálogo y clientes).

Las tools no leen archivos: piden los datos a una interfaz. Hoy la implementa un adaptador
que lee CSV; si mañana los datos vienen de una base, se escribe otro adaptador y las tools
no cambian.
"""

import csv
from pathlib import Path
from typing import Protocol


def normalizar_sku(sku: str) -> str:
    """Deja el código en un formato único para comparar: sin espacios y en mayúsculas.

    Ejemplo: " ab-1020 " -> "AB-1020"
    """
    return sku.strip().upper()


class Catalogo(Protocol):
    """La interfaz: lo único que las tools saben del catálogo.

    Protocol declara qué métodos tiene que tener una clase, sin decir cómo se implementan.
    Cualquier clase con un método buscar(sku) sirve como catálogo.
    """

    def buscar(self, sku: str) -> dict | None:
        """Devuelve el producto con ese SKU, o None si no existe."""
        ...


class CatalogoCSV:
    """El adaptador: implementa Catalogo leyendo catalogo.csv."""

    def __init__(self, ruta: Path):
        # Se lee el archivo una sola vez, al crear el catálogo, y queda en memoria.
        self._productos = {}
        with open(ruta, encoding="utf-8-sig") as archivo:  # utf-8-sig: tolera el BOM si lo hay
            for fila in csv.DictReader(archivo):  # cada fila llega como dict de textos
                producto = {
                    "sku": fila["sku"],
                    "nombre": fila["nombre"],
                    "rubro": fila["rubro"],
                    "marca": fila["marca"],
                    "unidad": fila["unidad"],
                    # En el CSV todo es texto: se convierte acá para que quien lo use
                    # pueda calcular y comparar ("1840" > "200" como texto da mal).
                    "precio_lista": float(fila["precio_lista"]),
                    "alicuota_iva": float(fila["alicuota_iva"]),
                    "stock": int(fila["stock"]),
                    "deposito": fila["deposito"],
                }
                # La clave es el SKU normalizado, para que la búsqueda también lo sea.
                self._productos[normalizar_sku(fila["sku"])] = producto

    def buscar(self, sku: str) -> dict | None:
        # .get devuelve None si la clave no existe, en vez de fallar.
        return self._productos.get(normalizar_sku(sku))


# --- Clientes ---

def normalizar_cuit(cuit: str) -> str:
    """Deja sólo los dígitos, para comparar sin importar guiones ni espacios.

    Ejemplo: "30-71455982-2" -> "30714559822"
    """
    return "".join(caracter for caracter in cuit if caracter.isdigit())


class Clientes(Protocol):
    """La interfaz: lo único que las tools saben de los clientes."""

    def buscar(self, cuit: str) -> dict | None:
        """Devuelve el cliente con ese CUIT, o None si no existe."""
        ...


class ClientesCSV:
    """El adaptador: implementa Clientes leyendo clientes.csv."""

    def __init__(self, ruta: Path):
        self._clientes = {}
        with open(ruta, encoding="utf-8-sig") as archivo:
            for fila in csv.DictReader(archivo):
                cliente = {
                    "cuit": fila["cuit"],
                    "razon_social": fila["razon_social"],
                    "provincia": fila["provincia"],
                    "localidad": fila["localidad"],
                    "condicion_iva": fila["condicion_iva"],
                    "categoria": fila["categoria"],
                    "limite_credito": float(fila["limite_credito"]),
                    "saldo_actual": float(fila["saldo_actual"]),
                    "dias_plazo": int(fila["dias_plazo"]),
                    "descuento_habitual": float(fila["descuento_habitual"]),
                    "estado": fila["estado"],
                    "mora_dias": int(fila["mora_dias"]),
                }
                self._clientes[normalizar_cuit(fila["cuit"])] = cliente

    def buscar(self, cuit: str) -> dict | None:
        return self._clientes.get(normalizar_cuit(cuit))
