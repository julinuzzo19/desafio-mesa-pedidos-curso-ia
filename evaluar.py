"""
evaluar.py — Corre los 20 mensajes de la bandeja contra el golden set y saca dos números:
  1. cuántos salieron por la rama correcta (de 20);
  2. en cuántas de las 8 consultas aparece el dato clave (de 8).

Cada mensaje corre de cero, en un archivo de checkpoints propio de la evaluación, así no pisa
lo que haya quedado de correr.py. Los pedidos que se frenan en aprobacion_humana no se retoman:
el golden set marca esa rama como el resultado esperado, y retomarlos exigiría inventar la
decisión de Gerencia.

El detalle queda en evaluacion.json (raíz del repo).

Uso (desde la raíz del repo, con el entorno activado):
  python evaluar.py
"""

import json
import sqlite3
import sys
import unicodedata
from datetime import datetime

from langgraph.checkpoint.sqlite import SqliteSaver

from mesa_pedidos import config
from mesa_pedidos.grafo import construir_grafo, estado_inicial

RUTA_GOLDEN = config.RAIZ / "consigna" / "golden_set.json"
RUTA_CHECKPOINTS_EVAL = config.RAIZ / "artifacts" / "checkpoints_eval.sqlite"
RUTA_SALIDA = config.RAIZ / "evaluacion.json"


def normalizar(texto: str) -> str:
    """Deja el texto comparable: minúsculas, sin tildes, sin espacios ni signo $.

    Así "5 %" y "5%" o "$ 68.000" y "68.000" cuentan igual, pero el número tiene que estar.
    Ejemplo: "Un 5 % de Garantía: $1.500.000" -> "un5%degarantia:1.500.000"
    """
    texto = texto.lower()
    # Separa cada letra de su tilde y descarta las tildes.
    sin_tildes = ""
    for caracter in unicodedata.normalize("NFD", texto):
        if unicodedata.category(caracter) != "Mn":
            sin_tildes += caracter
    # Saca todo espacio en blanco, no sólo el común: el modelo a veces escribe "5 %"
    # (espacio fino), que se ve igual pero es otro carácter.
    resultado = ""
    for caracter in sin_tildes:
        if not caracter.isspace() and caracter != "$":
            resultado += caracter
    return resultado


def ruta_obtenida(guardado) -> str:
    """El nodo donde terminó el mensaje.

    Si quedó frenado esperando a Gerencia, es aprobacion_humana. Si no, el nodo de la última
    línea del log: cada nodo escribe sus líneas empezando por su nombre ("confirmar_pedido: ...").
    """
    if guardado.next:
        return guardado.next[0]
    ultima_linea = guardado.values["log"][-1]
    return ultima_linea.split(":")[0]


def evaluar_consulta(caso: dict, respuesta) -> dict:
    """Para una consulta: qué datos clave aparecen en la respuesta y si cita el documento esperado."""
    if respuesta is None:
        return {"dato_clave": False, "faltan": caso["debe_contener"], "documento_citado": False}

    texto = normalizar(respuesta.respuesta)
    faltan = []
    for dato in caso["debe_contener"]:
        if normalizar(dato) not in texto:
            faltan.append(dato)

    documentos_citados = []
    for cita in respuesta.citas:
        documentos_citados.append(cita.documento)

    return {
        # Cuenta como acierto sólo si están todos los datos clave.
        "dato_clave": len(faltan) == 0,
        "faltan": faltan,
        "documento_citado": caso.get("documento") in documentos_citados,
        "respuesta": respuesta.respuesta,
        "citas": documentos_citados,
    }


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")  # para que se vean los acentos en Windows

    with open(RUTA_GOLDEN, encoding="utf-8") as archivo:
        casos = json.load(archivo)["casos"]
    mensajes = {}
    with open(config.RUTA_BANDEJA, encoding="utf-8") as archivo:
        for linea in archivo:
            mensaje = json.loads(linea)
            mensajes[mensaje["id"]] = mensaje

    # Cada evaluación parte de cero: se borran los checkpoints de la corrida anterior.
    RUTA_CHECKPOINTS_EVAL.parent.mkdir(parents=True, exist_ok=True)
    RUTA_CHECKPOINTS_EVAL.unlink(missing_ok=True)
    conexion = sqlite3.connect(RUTA_CHECKPOINTS_EVAL, check_same_thread=False)
    grafo = construir_grafo(checkpointer=SqliteSaver(conexion))

    resultados = []
    rutas_correctas = 0
    consultas = 0
    consultas_con_dato = 0

    for caso in casos:
        id_mensaje = caso["id"]
        configuracion = {"configurable": {"thread_id": f"eval-{id_mensaje}"}}
        resultado = {"id": id_mensaje, "ruta_esperada": caso["ruta"]}

        try:
            grafo.invoke(estado_inicial(mensajes[id_mensaje]), configuracion)
            guardado = grafo.get_state(configuracion)
            resultado["ruta_obtenida"] = ruta_obtenida(guardado)
            resultado["log"] = guardado.values["log"]
        except Exception as error:
            # Un mensaje que falla (ej. el proveedor no responde) no corta la evaluación.
            guardado = None
            resultado["ruta_obtenida"] = None
            resultado["error"] = f"{type(error).__name__}: {error}"

        resultado["ruta_ok"] = resultado["ruta_obtenida"] == caso["ruta"]
        if resultado["ruta_ok"]:
            rutas_correctas += 1

        marca = "✔" if resultado["ruta_ok"] else "✘"
        linea = f"{marca} {id_mensaje}  esperada {caso['ruta']:<20} obtenida {resultado['ruta_obtenida']}"

        # Las consultas tienen además el dato clave.
        if "debe_contener" in caso:
            consultas += 1
            respuesta = None
            if guardado is not None:
                respuesta = guardado.values.get("respuesta")
            resultado.update(evaluar_consulta(caso, respuesta))
            if resultado["dato_clave"]:
                consultas_con_dato += 1
                linea += "  | dato clave ✔"
            else:
                linea += f"  | dato clave ✘ (falta: {', '.join(resultado['faltan'])})"

        if "error" in resultado:
            linea += f"  | ERROR {resultado['error']}"
        print(linea)
        resultados.append(resultado)

    conexion.close()

    print(f"\nRama correcta: {rutas_correctas}/{len(casos)}")
    print(f"Consultas con el dato clave: {consultas_con_dato}/{consultas}")

    salida = {
        "fecha": datetime.now().isoformat(timespec="seconds"),
        "modelo": f"{config.PROVEEDOR_LLM}/{config.MODELO}",
        "embeddings": f"{config.PROVEEDOR_EMBEDDINGS}/{config.MODELO_EMBEDDINGS}",
        "chunk": {"tamano": config.TAMANO_CHUNK, "solapamiento": config.SOLAPAMIENTO_CHUNK, "k": config.TOP_K},
        "resumen": {
            "rama_correcta": f"{rutas_correctas}/{len(casos)}",
            "dato_clave": f"{consultas_con_dato}/{consultas}",
        },
        "casos": resultados,
    }
    with open(RUTA_SALIDA, "w", encoding="utf-8") as archivo:
        json.dump(salida, archivo, ensure_ascii=False, indent=2)
    print(f"Detalle en {RUTA_SALIDA.name}")


if __name__ == "__main__":
    main()
