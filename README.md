# desafio-mesa-pedidos-curso-ia

## Instalación

```
python -m venv .venv
.venv\Scripts\activate              # Windows (en Linux/Mac: source .venv/bin/activate)
pip install -r requirements.txt
copy .env.example .env              # y completar la clave del proveedor
```

Por defecto usa **Groq** para el LLM (`GROQ_API_KEY`) y embeddings **locales** (sin clave).
Para usar OpenAI, cambiar `PROVEEDOR_LLM` / `PROVEEDOR_EMBEDDINGS` en el `.env`.

## Probar

Desde la raíz del repo, con el entorno activado:

```
python -m scripts.probar_rag "cuánto sale el flete a Neuquén"     # consulta a las políticas
python -m scripts.probar_clasificar                               # clasifica la bandeja
python -m scripts.probar_clasificar MSG-004 MSG-017               # sólo esos mensajes
```

La primera consulta al RAG construye el índice (tarda un poco); las siguientes lo reutilizan.
Si cambian los PDF, agregar `--reindexar`.
