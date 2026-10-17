# Mesa de Pedidos — Desafío 1

Sistema que procesa los mensajes de clientes de Ferretería Industrial Andina con un grafo de
LangGraph. Hace cuatro cosas:
- clasifica cada mensaje;
- responde las consultas con las políticas, citando documento y página;
- valida los pedidos contra el catálogo y la cuenta corriente;
- frena para pedir aprobación a Gerencia cuando la decisión no le corresponde.

- Informe: [INFORME.md](INFORME.md) (se entrega en PDF).
- Definiciones y decisiones: [BITACORA.md](BITACORA.md).

---

## 1. Requisitos

- Python 3.11 o superior.
- Una clave de API del proveedor de LLM: **Groq** (por defecto, tiene plan gratuito) u **OpenAI**.
- Para los embeddings, una de dos:
  - **Locales** (por defecto): `BAAI/bge-m3` corre en tu máquina. No necesita clave. La primera
    vez descarga el modelo (~2,3 GB) y en CPU indexar tarda alrededor de un minuto.
  - **Por API**: `text-embedding-3-small` de OpenAI. Necesita `OPENAI_API_KEY` y es pago,
    pero indexar cuesta menos de un centavo de dólar.

## 2. Instalación

```
python -m venv .venv
.venv\Scripts\activate              # Windows (en Linux/Mac: source .venv/bin/activate)
pip install -r requirements.txt
copy .env.example .env              # en Linux/Mac: cp .env.example .env
```

`requirements.txt` instala todo. Si sólo vas a usar embeddings por API, podés comentar el bloque
"Embeddings locales" (`langchain-huggingface`, `sentence-transformers`, `torch`, `hf_xet`)
antes de instalar. Ese bloque es el más pesado.

## 3. Configuración (`.env`)

Elegí una de estas combinaciones y completá sólo la clave del proveedor que uses.

| Combinación | Variables |
|---|---|
| **Groq + embeddings locales** (por defecto) | `PROVEEDOR_LLM=groq` · `MODELO=openai/gpt-oss-120b` · `PROVEEDOR_EMBEDDINGS=huggingface` · `MODELO_EMBEDDINGS=BAAI/bge-m3` · `GROQ_API_KEY=...` |
| Groq + embeddings por API | lo anterior, con `PROVEEDOR_EMBEDDINGS=openai` · `MODELO_EMBEDDINGS=text-embedding-3-small` · `OPENAI_API_KEY=...` |
| Todo OpenAI | `PROVEEDOR_LLM=openai` · `MODELO=gpt-4o-mini` · `PROVEEDOR_EMBEDDINGS=openai` · `MODELO_EMBEDDINGS=text-embedding-3-small` · `OPENAI_API_KEY=...` |

- Con embeddings locales, `DISPOSITIVO_EMBEDDINGS=cuda` usa la GPU si la hay. El valor por
  defecto es `cpu`.
- Cada modelo de embeddings tiene su propio índice, en `artifacts/indice_faiss/<proveedor>_<modelo>`.
  Al cambiar de modelo se construye uno nuevo la primera vez, y los índices de dos modelos nunca
  se mezclan.
- Groq cambia su catálogo de modelos cada tanto: https://console.groq.com/docs/models

## 4. Probar el grafo

Todos los comandos se corren desde la raíz del repo, con el entorno activado.

**El grafo completo.** Los checkpoints se guardan en `artifacts/checkpoints.sqlite`, con un
thread por mensaje:

```
python -m scripts.probar_grafo                      # los 20 mensajes de la bandeja
python -m scripts.probar_grafo MSG-009 MSG-013      # sólo esos
python -m scripts.probar_grafo --dibujar            # el grafo en mermaid
python -m scripts.probar_grafo --borrar MSG-013     # borra los checkpoints y corre de cero
```

**Frenar, aprobar y retomar:**

```
python -m scripts.probar_grafo --borrar MSG-013     # se frena: muestra el payload para Gerencia
#   ... se puede cerrar la terminal ...
python -m scripts.probar_grafo MSG-013 --retomar si # Gerencia aprueba → confirmar_pedido
python -m scripts.probar_grafo MSG-015 --retomar no # Gerencia rechaza → rechazar_pedido
```

Cuando un mensaje ya tiene thread, el script no lo vuelve a correr: muestra lo que quedó
guardado. Para correrlo de nuevo, usá `--borrar`.

Los mensajes que pasan por Gerencia son MSG-013, MSG-014 y MSG-015.

**Piezas sueltas:**

```
python -m scripts.probar_rag "cuánto sale el flete a Neuquén"   # una consulta al RAG
python -m scripts.probar_rag "..." --reindexar                  # reconstruye el índice (si cambian los PDF)
python -m scripts.probar_clasificar [MSG-004 ...]               # sólo la clasificación
```

La primera consulta construye el índice y las siguientes lo reutilizan.

> Pendiente: `correr.py` (procesar un mensaje y manejar la aprobación) y `evaluar.py`
> (los 20 casos contra el golden set, con salida en `evaluacion.json`).

## 5. Estructura

```
mesa_pedidos/   config, modelos, rag, datos, tools, estado, nodos, grafo
scripts/        pruebas manuales (probar_rag, probar_clasificar, probar_grafo)
data/           políticas (PDF), catálogo, clientes y bandeja
consigna/       consigna y golden set
artifacts/      índice FAISS y checkpoints (no se versiona: se regenera)
```

## 6. El grafo

```mermaid
graph TD;
	__start__([__start__]):::first
	cargar_cliente(cargar_cliente)
	clasificar(clasificar)
	responder_consulta(responder_consulta)
	extraer_pedido(extraer_pedido)
	validar_pedido(validar_pedido)
	aprobacion_humana(aprobacion_humana)
	confirmar_pedido(confirmar_pedido)
	rechazar_pedido(rechazar_pedido)
	derivar_humano(derivar_humano)
	__end__([__end__]):::last
	__start__ --> cargar_cliente;
	aprobacion_humana -. &nbsp;True&nbsp; .-> confirmar_pedido;
	aprobacion_humana -. &nbsp;False&nbsp; .-> rechazar_pedido;
	cargar_cliente --> clasificar;
	clasificar -. &nbsp;derivar&nbsp; .-> derivar_humano;
	clasificar -. &nbsp;pedido&nbsp; .-> extraer_pedido;
	clasificar -. &nbsp;consulta&nbsp; .-> responder_consulta;
	extraer_pedido --> validar_pedido;
	validar_pedido -. &nbsp;humano&nbsp; .-> aprobacion_humana;
	validar_pedido -. &nbsp;confirmar&nbsp; .-> confirmar_pedido;
	validar_pedido -. &nbsp;derivar&nbsp; .-> derivar_humano;
	validar_pedido -. &nbsp;rechazar&nbsp; .-> rechazar_pedido;
	confirmar_pedido --> __end__;
	derivar_humano --> __end__;
	rechazar_pedido --> __end__;
	responder_consulta --> __end__;
	classDef default fill:#f2f0ff,line-height:1.2
	classDef first fill-opacity:0
	classDef last fill:#bfb6fc
```
