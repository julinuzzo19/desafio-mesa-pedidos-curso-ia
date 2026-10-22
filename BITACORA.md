# Bitácora — Mesa de Pedidos

Definiciones, decisiones técnicas y conceptuales del sistema, y lo que quedó fuera de alcance.
Cada decisión lleva su porqué y, cuando las hubo, las alternativas descartadas.

## 1. Definiciones (lectura de la política)

| Término                                | Definición                                                                                                                                           | Fuente / argumento                                                                                                                                                 |
| --------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Monto neto                              | Precio de lista × cantidad, sin IVA, antes de descuentos                                                                                             | El art. 4 elige el descuento por volumen con el neto, así que es anterior al descuento; se usa igual en el art. 7 (crédito). El documento no lo define del todo. |
| Descuento total                         | Habitual + volumen + lo que pide el cliente                                                                                                           | Lectura del art. 5. En MSG-016 ("25% total") no cambia el veredicto (va a Gerencia por el descuento, el crédito y el stock).                                      |
| Tope de descuento                       | 20%; 15% si hay herramienta eléctrica Dewalt/Makita/Bosch                                                                                            | Art. 5                                                                                                                                                             |
| Pedido mínimo                          | 250.000 (A/B); 120.000 (C o monotributo)                                                                                                              | Art. 3: no se rechaza, queda en espera                                                                                                                             |
| "A 30 días"                            | Cuenta corriente con plazo de 30 días                                                                                                                | Comprar a crédito; los días van en otro campo                                                                                                                    |
| Pago no dicho                           | `dias_plazo` > 0 → cuenta corriente a esos días; 0 → contado contra entrega                                                                      | Un dato faltante no es una excepción: lo completa el código. No por categoría: hay clientes C con plazo 15.                                                     |
| Destino no dicho                        | Localidad del cliente                                                                                                                                 | Lo completa el código y lo anota en el log                                                                                                                        |
| `consulta`                            | Quiere información del negocio que está en los PDF (incluye datos específicos de productos, no recomendaciones)                                    | Por intención, no por palabras (MSG-007 y 018 mencionan productos y no son pedidos)                                                                               |
| `pedido`                              | Quiere comprar productos, con o sin condiciones (destino, plazo, pago, descuento)                                                                     | Las condiciones las juzga `validar_pedido`, no el LLM                                                                                                            |
| `derivar`                             | Todo lo demás: reclamos, proveedores, pedido de comunicación directa (sólo si la pide explícitamente), pedido + reclamo                           | Si una parte necesita a una persona, gana `derivar`                                                                                                              |
| `humano` vs `derivar`               | `humano`: pedido claro con una excepción que Gerencia aprueba o rechaza. `derivar`: no se puede evaluar como pedido; una persona lo toma de cero | —                                                                                                                                                                 |
| `rechazar` vs `humano`              | Depende de si la política deja margen: mora > 60 en cuenta corriente es "sin excepción"                                                             | Art. 7                                                                                                                                                             |
| Dato del cliente vs dato de la pregunta | Pertenencia del cliente (domicilio fiscal, IVA, categoría) → manda el CSV. De la pregunta (un destino, un monto hipotético) → manda el texto      | Consultas MSG-001 y MSG-008                                                                                                                                        |

---

## 2. Arquitectura

```
correr.py: ¿el CUIT está en clientes.csv? ── no ──→ rechazo (el grafo no arranca)
   │ sí
 START → [cargar_cliente] → [clasificar]
                              ├── consulta → [responder_consulta] → END
                              ├── derivar ─→ [derivar_humano] → END
                              └── pedido ──→ [extraer_pedido] → [validar_pedido]
                                                 ├── confirmar → [confirmar_pedido] → END
                                                 ├── rechazar ─→ [rechazar_pedido] → END
                                                 ├── derivar ──→ [derivar_humano] → END
                                                 └── humano ───→ [aprobacion_humana] (interrupt)
                                                                    ├── aprueba → [confirmar_pedido]
                                                                    └── rechaza → [rechazar_pedido]
```

**Criterio de qué nodo lleva LLM:** la entrada. Texto libre a interpretar → LLM con structured
output (`clasificar`, `extraer_pedido`, `responder_consulta`). Datos estructurados y reglas →
código (`validar_pedido`, que hace el análisis más exigente, va sin LLM). El LLM convierte
lenguaje en datos; el código decide sobre datos.

**Nodo decide, router traduce:** cada nodo escribe un valor de negocio (tipo, acción,
aprobación); el router (`add_conditional_edges` con mapa) lo traduce al nodo siguiente y no
aplica reglas. Agregar un destino cambia una entrada del mapa, no el nodo. Un valor fuera del
mapa da `KeyError` (verificado). Los routers son `lambda` en la misma línea; no se puede pasar
el valor directo porque el grafo se arma antes de que llegue un mensaje.

**Sistema de solo lectura:** ninguna hoja modifica stock ni saldo; el resultado queda en el log.
Datos de negocio detrás de una interfaz (`Catalogo`, `Clientes`) con adaptador CSV.

**Un `thread_id` por mensaje:** los mensajes son independientes. El checkpointer retoma un
mensaje frenado, no recuerda entre mensajes.

---

## 3. Estado del grafo (`estado.py`)

| Campo             | Lo escribe             | Contenido                                                                                                                    |
| ----------------- | ---------------------- | ---------------------------------------------------------------------------------------------------------------------------- |
| `mensaje`       | `correr.py`          | id, canal, fecha, CUIT, remitente, texto                                                                                     |
| `cliente`       | `cargar_cliente`     | cuit, razón social, provincia, localidad, IVA, categoría (sin condiciones financieras)                                     |
| `clasificacion` | `clasificar`         | tipo + motivo si la salida fue inválida                                                                                     |
| `respuesta`     | `responder_consulta` | `RespuestaRAG`: respuesta, citas, alcanza                                                                                  |
| `pedido`        | `extraer_pedido`     | extraído, motivo, productos, destino, forma de pago, plazo, descuento pedido                                                |
| `decision`      | `validar_pedido`     | acción, motivo, alertas, escenario (neto, descuento y tope, crédito leído, pago/plazo/destino finales, datos completados) |
| `aprobacion`    | `aprobacion_humana`  | `{aprobar: bool}`                                                                                                          |
| `log`           | todos                  | reducer `add`, una línea por nodo                                                                                         |

- **`None` = "ese nodo no corrió".** El estado inicial trae todos los campos en `None`
  (`TypedDict` no controla nada en ejecución; sin la clave, `KeyError`). Descartados: un valor
  por defecto (una consulta parecería un pedido) y omitir el campo.
- **Reemplazar vs acumular:** los campos que reemplazan tienen un solo nodo que los escribe
  (convención propia, no de LangGraph); los que acumulan llevan reducer (`log`). Sin reducer
  un segundo nodo pisa el valor sin error ni aviso (verificado).
- **Veredicto y evidencia juntos:** el crédito leído va dentro de `decision`, para que Gerencia
  vea los mismos números que produjeron la alerta. Descartados: un campo propio de crédito
  (podría desfasarse) y reconsultar en `aprobacion_humana` (números distintos de los que
  motivaron la alerta).
- **Foto del cliente:** al retomar días después se ve el crédito del momento de la solicitud.
  Alcanza para un sistema de solo lectura; en uno real es una decisión (foto vs dato fresco).
- **De dónde vino un mensaje a una hoja:** se mira `decision` (`None` = vino de `clasificar`) y
  `aprobacion` (`None` = no pasó por Gerencia). Se descartó un campo "vengo de": duplica el dato.

---

## 4. Nodos

### `cargar_cliente` (sin LLM)

- Busca por CUIT y guarda sólo los datos que usan otros nodos; las condiciones financieras las
  lee `validar_pedido` con `verificar_credito` (un solo origen por dato).
- CUIT no encontrado → `ValueError`: es un bug, porque `correr.py` ya validó. Descartados: un
  router a `END` (le da un camino normal a un bug) y seguir con `cliente: None` (el error
  aparece tres nodos después, tras dos llamadas al LLM).

### `clasificar` (LLM + structured output)

- `ClasificacionLLM` (Pydantic con `Literal`), `with_structured_output(include_raw=True)`.
  Pydantic valida en ejecución y rechaza una etiqueta fuera de la lista; `TypedDict` la dejaría
  pasar y rompería el router.
- Salida ilegible (`parsing_error`) → `derivar` con motivo: con incertidumbre, al lado seguro.
  No a `consulta`: un pedido mal clasificado terminaría respondido por el RAG sin que nadie se
  entere. Una etiqueta válida pero equivocada no la detecta ningún fallback: se mide.
- Proveedor caído: reintenta (`max_retries=2`) y la excepción sube. Una caída de red no es una
  decisión de negocio; mandarla a derivar ensucia la medición.
- Prompt: criterio de la sección 1 + few-shot con ejemplos **inventados** (usar mensajes de la
  bandeja contamina la medición; uno casi copia de MSG-018 se reemplazó).
- Lección de las pruebas: las correcciones fueron **acotar** frases que le delegaban un juicio
  al LLM ("asesorar sobre productos", "necesita a una persona").

### `responder_consulta` (LLM + RAG)

- Lee `mensaje.texto`, `mensaje.fecha` y `cliente`. La búsqueda usa sólo la pregunta; fecha y
  cliente van sólo al LLM (datos del cliente en la búsqueda traen chunks que confunden).
- Fecha del mensaje, no la de hoy: la respuesta depende de cuándo preguntó, y con la de hoy la
  evaluación daría distinto según el día.
- No necesita mora, saldo ni límite (verificado en las 8 consultas).
- "No alcanza" lo decide el LLM (el retriever siempre devuelve k fragmentos, sirvan o no) y va
  en un campo; termina en `END` diciéndolo. Se descartó rutearlo a `derivar_humano`.
- El índice se carga la primera vez que se usa, no al importar.

### `extraer_pedido` (LLM + structured output)

- Extrae sólo lo que dice el mensaje; lo no dicho queda en `None`. Si lo completara el LLM no
  se distinguiría lo pedido de lo supuesto.
- SKU tal como está escrito; producto sin SKU lo decide `validar_pedido`.
- Salida inválida → `extraido: False` + motivo, y `validar_pedido` deriva (mismo patrón que
  `encontrado` en las tools). Se descartó un router nuevo.

### `validar_pedido` (sin LLM, con las dos tools)

Reglas por código con `if`; los valores de la política en constantes con nombre y artículo.
Leer las reglas con el RAG exigiría un LLM y daría veredictos no deterministas.

| # | Regla                                                         | Salida   | Fuente                                             |
| - | ------------------------------------------------------------- | -------- | -------------------------------------------------- |
| 1 | `extraido: False`                                           | derivar  | —                                                 |
| 2 | SKU inexistente                                               | derivar  | catálogo                                          |
| 3 | Stock insuficiente                                            | humano   | art. 9 (Gerencia decide parcial/sustitución/baja) |
| 4 | Neto < mínimo                                                | derivar  | art. 3 ("no se rechazan")                          |
| 5 | Mora > 60 y cuenta corriente                                  | rechazar | art. 7 ("sin excepción")                          |
| 6 | Mora 30-60                                                    | humano   | art. 7                                             |
| 7 | Cuenta corriente y saldo + neto > límite                     | humano   | art. 7                                             |
| 8 | Cuenta corriente sin plazo acordado, o plazo > `dias_plazo` | humano   | art. 6                                             |
| 9 | Pidió descuento y total > tope                               | humano   | art. 5                                             |

- Se evalúan todas y gana la peor: rechazar > derivar > humano > confirmar. `derivar` queda para
  lo que no se puede evaluar como pedido (extracción fallida, SKU inexistente, bajo el mínimo).
- **Cambio en la medición:** el stock insuficiente iba a `derivar` (con prioridad sobre `humano`,
  porque un pedido sin stock no debía confirmarse). El golden set espera `aprobacion_humana` en
  MSG-016 (stock + crédito + descuento). Se adoptó esa lectura: la falta de stock es una alerta
  más para Gerencia, que ya está mirando el pedido y decide la entrega parcial o la sustitución
  (art. 9). Si aprueba, el log de `confirmar_pedido` lleva la alerta de stock.
- Regla 9 sólo si el cliente pidió descueGHnto: si no, Mesa aplica hasta el tope sin consultar
  (MSG-010: 23% con tope 15% → confirmar).
- Antes de las reglas completa destino, forma de pago y plazo, con una línea de log cada uno.
- Mora > 60 con pago anticipado no rechaza: no usa crédito.

### `aprobacion_humana` (`interrupt()`)

- Payload: id, fecha y texto del mensaje · razón social, CUIT, categoría · productos · neto,
  pago, plazo, destino, descuento y tope · crédito (foto) · **todas las alertas** · la pregunta.
  Con una sola alerta, Gerencia aprobaría MSG-015 viendo el crédito y no la mora.
- Afuera: `log`, `clasificacion`, `respuesta`, datos completados (auditoría).
- Gerencia decide en bloque: `Command(resume={"aprobar": bool})`. Aprobar por alerta exigiría
  una regla para combinar respuestas que la política no da.
- Nada con efectos antes del `interrupt()`: al retomar el nodo corre desde el principio (un
  mail se mandaría dos veces). La línea de log va después y sale una sola vez.
- Respuesta sin booleano → `ValueError`.
- El `thread_id` es la identidad: retomar con otro id aplica la respuesta a otro pedido frenado,
  sin error. Se retoma con el `mensaje.id` del payload.
- Checkpointer: `SqliteSaver` en `artifacts/checkpoints.sqlite` (puerto y adaptador, igual que
  los CSV). Al retomar no corren los nodos anteriores ni el LLM (verificado).

### Hojas

| Hoja                 | Log                                                                                      |
| -------------------- | ---------------------------------------------------------------------------------------- |
| `derivar_humano`   | id + origen (clasificar / validar_pedido) + motivo + las demás alertas                  |
| `rechazar_pedido`  | id + motivo (+ "rechazado por Gerencia")                                                 |
| `confirmar_pedido` | id + productos + neto + pago y plazo + destino (+ "aprobado por Gerencia" y las alertas) |

Una consulta que llega a `confirmar_pedido` rompe en `decision` (`None`): es un bug de ruteo y
debe verse.

---

## 5. Tools

- Las llama `validar_pedido` en orden fijo, no un LLM. El `args_schema` valida que el código las
  llame bien (campo mal nombrado → `ValidationError`).
- `consultar_producto`: SKU normalizado (sin espacios, mayúsculas); devuelve `encontrado` + la
  fila con tipos reales. Nunca lanza.
- `verificar_credito`: CUIT normalizado a dígitos; devuelve límite, saldo, disponible (límite −
  saldo, puede ser negativo), mora, estado, plazo, descuento habitual. No da veredicto: las
  reglas viven juntas en `validar_pedido`. La llama `validar_pedido`, no `cargar_cliente`.
- Las tools traen datos; los cálculos (`calcular_neto`) son funciones junto a las reglas.

---

## 6. RAG

| Parámetro   | Valor                                                                                                             | Por qué                                          |
| ------------ | ----------------------------------------------------------------------------------------------------------------- | ------------------------------------------------- |
| Loader       | `PyPDFLoader`, metadata `{documento, pagina}` (página desde 1)                                               | La cita necesita documento y página              |
| Chunking     | Por sección: `\n\n` antes de cada título (`ART. N -`, `N. TÍTULO`, rubro en mayúsculas), máx. 1000/150 | Ver pruebas abajo                                 |
| Embeddings   | Configurables (`bge-m3` local u OpenAI); un índice por modelo                                                  | Mezclar vectores de dos modelos falla en silencio |
| Vector store | FAISS persistido en `artifacts/`; reindexación manual (`--reindexar`)                                        | Se versiona la fuente, no lo derivado             |
| Top k        | 5                                                                                                                 | —                                                |
| Citas        | El LLM devuelve qué fragmentos usó (`[1]`); el código traduce a documento y página                          | El LLM no puede inventar una página              |

**Pruebas de chunking** (lección: el tamaño es un tradeoff; lo que resolvió fue respetar la
estructura del documento):

- 1000/150 por tamaño: MSG-001 falló por **recuperación** (la tabla de zonas quedó partida).
- 1500/225: arregló MSG-001 y rompió MSG-005 (regla diluida en un chunk largo; ganó un pie de
  página corto por cercanía de significado).
- Por sección, 1000/150: 27 chunks, los tres casos bien.
- Descartado sumar la provincia a la búsqueda: no arregla el corte y rompe MSG-002.
- Descartados: Parent Document Retriever, Markdown + `MarkdownHeaderTextSplitter`, validar
  "alcanza = sí ⇒ al menos una cita" (no lo pide la consigna; riesgo aceptado).

**Recuperación vs generación:** se depuran por separado. La bonificación del 50% en zona 5
estaba en el primer chunk y la respuesta no la mencionó: problema de generación.

---

## 7. Proyecto

- LLM y embeddings por `.env` (`init_chat_model` / `init_embeddings`): Groq u OpenAI. Que el
  sistema no dependa de una sola API.
- Datos en `data/`; `golden_set.json` en `consigna/` (no es entrada del sistema).
- `artifacts/` (índice, checkpoints) no se versiona.
- CUIT desconocido se valida en `correr.py` antes del grafo. Costo aceptado: ese rechazo no
  queda en el estado ni en el checkpoint. Todos los CUIT de la bandeja existen.

## 8. Ejecución y medición

**`correr.py` (menú):** lista los 20 mensajes con su situación leída de los checkpoints (sin
correr / frenado / terminado). Valida el CUIT antes de invocar el grafo. Si un pedido se frena,
Gerencia aprueba, rechaza o lo deja pendiente para retomarlo después (aunque se cierre la
terminal). Un mensaje terminado no se vuelve a correr: el reducer duplicaría el log.

**`evaluar.py`:**

| Decisión                                                                                              | Por qué                                                                                                                                           |
| ------------------------------------------------------------------------------------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------- |
| Checkpoints propios (`checkpoints_eval.sqlite`), borrados al arrancar; threads `eval-MSG-0XX`      | Cada medición parte de cero y no pisa lo de `correr.py`                                                                                         |
| Un pedido frenado cuenta como `aprobacion_humana`; no se retoma                                      | El golden set usa esa rama como resultado esperado; retomar exigiría inventar la decisión de Gerencia                                            |
| Ruta = nodo pendiente si está frenado; si no, el nodo de la última línea del log                    | Cada nodo escribe su log empezando por su nombre                                                                                                   |
| Dato clave: tienen que estar **todos** los `debe_contener`                                     | Una respuesta a medias no le sirve al cliente                                                                                                      |
| Comparación normalizada: minúsculas, sin tildes, sin `$` y sin **ningún** espacio en blanco | Mide si el dato está, no cómo lo formateó el modelo. No interpreta números (`1,5 millones` ≠ `1.500.000`): eso volvería la métrica laxa |
| Si un mensaje lanza una excepción, se registra y la evaluación sigue                                 | Un fallo de red no corta las otras 19 mediciones                                                                                                   |
| Extra: si la respuesta cita el `documento` esperado                                                  | Se informa aparte; no entra en los dos números                                                                                                    |
| `evaluacion.json` se escribe al final y se versiona                                                  | Es entregable; una corrida cancelada no deja un archivo a medias                                                                                   |

**Resultados y qué cambió con la medición:**

- **MSG-016:** el golden set espera `aprobacion_humana`; el sistema lo derivaba por falta de
  stock. Se cambió la regla 3 a `humano` (ver `validar_pedido`).
- **MSG-001, dato clave:** la primera corrida dio 7/8. La respuesta era correcta, pero el modelo
  escribió `5 %` (espacio fino, se ve igual que un espacio) y la normalización sólo sacaba el
  espacio común. Era un error del **evaluador**, no del sistema; se corrigió para sacar cualquier
  espacio. El PDF dice `5%`: el espacio lo agrega la generación.
- Resultado: 20/20 rama correcta, 8/8 dato clave, las 8 consultas citan el documento esperado.
- Una sola corrida: el LLM no es del todo determinista, otra corrida podría variar.

---

## 9. Conceptos aplicados

Cada concepto con el razonamiento propio que lo sostiene, en limpio.

**Structured output (clases 2-3)**

- El LLM traduce texto libre a un objeto con forma fija (Pydantic); el código decide sobre ese
  objeto. Pydantic valida en ejecución: una etiqueta inexistente se convierte en `parsing_error`
  y cae en el fallback, en vez de romper el router más adelante.
- El LLM extrae el "25%" de MSG-016 pero no decide si se acepta: su trabajo es identificar el
  dato; la regla del art. 5 la aplica el código, que da siempre el mismo resultado.G

**RAG (clases 4-5)**

- Indexar es un proceso aparte del flujo; la segunda corrida se ahorra la indexación (`.faiss` y
  `.pkl`), pero sigue cargando el modelo de embeddings, porque la pregunta también se embebe.
- El retriever mide distancia (parecido), no relevancia: siempre devuelve k fragmentos. Por eso
  "no alcanza" lo tiene que decidir el LLM.
- Si los chunks llegan al LLM sin `[documento, p. N]`, no puede saber la página: o no cita o
  inventa una cita creíble. Por eso la fuente la pone el código.
- La búsqueda densa es cercanía de significado; la coincidencia de palabras es BM25. Un chunk
  corto (un pie de página) tiene un vector menos diluido y puede ganarle a uno largo.
- Un PDF sin títulos detectables se corta por tamaño (nunca entre documentos); se nota probando
  consultas de ese documento o en la evaluación.
- Cambiar el modelo de embeddings sin reindexar: si cambian las dimensiones, FAISS falla; si no,
  trae fragmentos sin relación y el sistema responde con seguridad algo incorrecto.

**Tools (clase 6)**

- Una tool trae datos; no decide. Si un agente ReAct eligiera `consultar_producto`, ante un SKU
  inexistente convendría un error accionable con los SKU más parecidos.
- El `args_schema` sirve aunque no haya LLM: valida que el código llame bien a la tool.

**Grafo, estado y routers (clase 7)**

- Un nodo devuelve sólo lo que cambia; LangGraph reemplaza el campo o lo combina con su reducer.
  `log` necesita `add` porque lo escriben varios nodos y se quiere la historia completa.
- El nodo decide (escribe tipo o acción); el router sólo traduce a un nodo. Un `if` dentro de un
  nodo que escribe estado es lógica del nodo; un `if` para elegir el nodo siguiente va en
  `add_conditional_edges`, porque el grafo tiene que conocer sus caminos para dibujarse,
  checkpointear e interrumpir.
- Sin el campo en el estado inicial, leerlo da `KeyError`: por eso todo arranca en `None`.

**Evaluación**

- Se mide con un set fijo y una métrica definida antes de mirar los resultados; la salida
  queda guardada para comparar corridas.
- El evaluador también es código y puede fallar: ante un número malo, primero ver si el dato
  estaba (MSG-001). Corregir la métrica es legítimo sólo si el dato estaba; si no, es trampa.
- Ante un fallo real, ubicar la pieza (clasificación, extracción, regla, recuperación o
  generación) antes de corregir. No ajustar el prompt caso por caso hasta 20/20: sobreajusta al
  golden set.

**Interrupt y checkpointer (clase 7)**

- El checkpointer guarda el estado después de cada nodo, bajo un `thread_id`. Al retomar sólo
  vuelve a correr el nodo frenado, con la respuesta de Gerencia; los anteriores no se repiten y
  no se vuelve a llamar al LLM.
- `interrupt()` corta el nodo; al retomar, el nodo corre desde la primera línea y esta vez
  `interrupt()` devuelve el valor de `Command(resume=...)`. Por eso nada con efectos antes: un
  mail antes del `interrupt()` se mandaría al frenar y otra vez al retomar.
- El dato que Gerencia necesita al retomar tiene que estar en el estado: una variable local se
  pierde, y `validar_pedido` no se vuelve a ejecutar.
- Gerencia ve, por defecto, la foto guardada en el payload; el crédito actual habría que
  reconsultarlo al mostrar.

---

## 10. Fuera de alcance

| Qué                                                               | Por qué                                                                                                |
| ------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------- |
| Acumulación de pedidos bajo el mínimo (30 días, art. 3)         | Exige memoria entre mensajes, escribir datos y un disparador por tiempo                                 |
| Ejecutar sustituciones y entregas parciales (art. 9)               | La falta de stock va a Gerencia, que decide; el sistema no arma el pedido parcial ni elige el sustituto |
| Precio final con descuentos                                        | No lo pide la consigna                                                                                  |
| Pedido + pregunta aparte en el mismo mensaje                       | No lo contempla la consigna ni lo trae la bandeja                                                       |
| Producto sin SKU                                                   | Ningún pedido de la bandeja lo trae                                                                    |
| Sugerir SKU parecidos ante uno inexistente (distancia de edición) | Sólo útil si un agente elige las tools                                                                |

**Mejoras anotadas, no implementadas:**

- Payload: mostrar descuento total y tope sólo cuando el cliente pidió descuento (en MSG-013
  aparece 23% vs 15% sin alerta y puede confundir).
- Payload: comentario libre de Gerencia; crédito actual junto a la foto.
- Prompt del RAG: mencionar bonificaciones (la medición dio 8/8; queda como mejora si aparece una omisión).
- Avisar al indexar si un PDF no tiene títulos detectados.
