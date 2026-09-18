# AGENTS.md

Guía para agentes de codificación y personas que trabajen en este repositorio.
Léela completa antes de tocar código: varias de las reglas de abajo son invariantes del
producto, no preferencias de estilo.

## Qué es esto

Demo funcional de **Optimiza Conversacional**: el usuario pregunta en español, un agente
clasifica la intención localmente, recupera contexto semántico, genera SQL, lo valida,
lo ejecuta contra el almacén analítico (Redshift o su equivalente local) o contra la copia
materializada en DuckDB, transforma el resultado y devuelve tabla, gráfico, explicación y
los tiempos de cada etapa.

Aproximadamente 8 516 líneas entre backend, frontend y pruebas. Sin framework de frontend:
HTML, CSS y JavaScript sin dependencias de build.

## Comandos

```bash
# Levantar todo (almacén + carga + aplicación)
docker compose up --build

# Solo demo, sin almacén
docker compose --profile demo up app-demo

# Pruebas
.venv/bin/python -m pytest -q                      # 72 pruebas (4 de integración se saltan)
docker compose --profile test run --rm tests       # las mismas dentro de la imagen
npm run test:unit                                  # 64 unitarias del frontend sobre Lightpanda (~60 ms)
npm run test:unit:chromium                         # el mismo suite en Chromium, para contrastar
npx playwright test                                # 5 pruebas de interfaz (requiere la app arriba)

# Pruebas de integración contra el almacén levantado
docker compose up -d warehouse warehouse-loader
OPTIMIZA_SOURCE_MODE=redshift REDSHIFT_HOST=localhost REDSHIFT_PORT=5439 \
  REDSHIFT_USER=optimiza_ro REDSHIFT_PASSWORD=optimiza_ro_pwd REDSHIFT_SCHEMA=analytics \
  .venv/bin/python -m pytest tests/test_warehouse_integracion.py -v

# Procesos de datos
docker compose exec app python -m backend.app.pipeline.sync              # incremental
docker compose exec app python -m backend.app.pipeline.sync --completa   # recarga total
python -m backend.app.seed.generate_seed                                 # regenera los Parquet
python -m backend.app.pipeline.warehouse_loader                          # recarga el almacén
```

## Mapa del código

| Ruta | Responsabilidad |
|---|---|
| `backend/app/config.py` | Toda la configuración por variables de entorno. Nada se hardcodea. |
| `backend/app/agent/intent_classifier.py` | Fachada de clasificación. La lógica está en `agent/clasificacion/`. |
| `backend/app/agent/clasificacion/` | Cadena de motores con relevo: `base.py` (contrato), `motores.py` (edge, transformers, llm, reglas), `cadena.py` (orden, umbrales y traza). |
| `backend/app/canales/whatsapp.py` | Canal de WhatsApp sobre Evolution API: instancia, webhook, autorización y formato de texto plano. |
| `backend/app/agent/intent_data.py` | Frases de entrenamiento y set de evaluación del clasificador. |
| `backend/app/agent/planner.py` | Traduce la pregunta a un plan y a SQL portable. Detecta métrica, dimensión, grano temporal, filtros y ranking. |
| `backend/app/agent/validator.py` | Única puerta antes de ejecutar: solo lectura, tablas permitidas, `LIMIT`, riesgo de escaneo. |
| `backend/app/agent/orchestrator.py` | Flujo completo, ruteo de la consulta, pasos cronometrados, sesiones. |
| `backend/app/agent/chart.py` | Elige la visualización y arma la especificación Vega-Lite. |
| `backend/app/agent/presentacion.py` | Traduce el resultado técnico a lenguaje de negocio: etiquetas, formatos y resumen. |
| `backend/app/agent/llm.py` | Cliente Anthropic opcional. Solo recibe metadatos, nunca filas. |
| `backend/app/semantic/` | Embeddings locales, índice vectorial y catálogo (tablas, columnas, KPIs, relaciones, glosario). |
| `backend/app/engines/redshift_adapter.py` | Conexión de solo lectura, `search_path`, timeout, streaming por bloques, introspección. |
| `backend/app/engines/duckdb_engine.py` | Ejecución, transformación, caché materializada (`cache`), perfilado de claves. |
| `backend/app/pipeline/warehouse_loader.py` | Crea el esquema del almacén, carga los datos y otorga `SELECT` al usuario de la app. |
| `backend/app/pipeline/sync.py` | Materialización incremental Redshift → DuckDB con marca de agua. |
| `backend/app/security/` | Enmascaramiento de PII y auditoría JSONL. |
| `backend/app/api/` | Rutas de chat, administración y metainformación. |
| `frontend/static/` | Chat de una columna, formatos de negocio, gráficos y panel de configuración. |
| `tests/unit-web/` | Motor propio de pruebas unitarias del frontend sobre Lightpanda: runner, capa de navegador, harness y specs. |
| `docker/warehouse/01-init.sql` | Esquema, rol de solo lectura y revocación de permisos de escritura. |
| `infra/` | Terraform para Redshift Serverless y script de bootstrap. |

## Invariantes: no romper

1. **Solo lectura, siempre.** El validador (`validator.py`) rechaza cualquier sentencia que no
   sea `SELECT`/`WITH`, cualquier tabla fuera del catálogo y las funciones de acceso a
   archivos. La conexión al almacén se abre con `readonly=True`. El usuario de base de datos
   solo tiene `GRANT SELECT`. Los tres controles son independientes a propósito: no elimines
   uno porque "ya está cubierto por otro".
2. **Nunca inventar joins.** Si la pregunta necesita cruzar tablas sin relación declarada, el
   agente perfila las claves candidatas en DuckDB (cobertura y cardinalidad reales) y pide
   confirmación. No agregues heurísticas que ejecuten un join no declarado por su cuenta.
3. **Nada de datos al LLM.** Solo metadatos: nombres, descripciones, KPIs, relaciones y valores
   categóricos no sensibles. Las columnas marcadas `pii` nunca salen.
4. **PII enmascarada antes de responder.** Se aplica en `orchestrator._enmascarar`, sobre el
   resultado final, con `MASK_PII=true` por defecto.
5. **El clasificador corre en CPU, sin red y sin GPU**, y reporta su latencia medida en cada
   respuesta. El fallback por reglas siempre debe existir.
6. **SQL portable entre Redshift y DuckDB.** Usa `date_trunc`, `CAST`, CTEs y window functions
   estándar. Nada de `strftime`, `read_parquet` u otras funciones propias de un motor dentro
   del SQL generado por el agente (el motor de transformación sí puede usarlas).
7. **Los tiempos se miden, no se estiman.** Cada etapa reporta milisegundos reales.
8. **La vista ejecutiva no muestra jerga.** El texto de `respuesta` no debe contener SQL,
   nombres de columnas técnicos ni nombres de motores. Ese detalle vive en
   `respuesta_tecnica`, `sql` y los paneles del modo experto. Hay pruebas que lo verifican.
9. **La cadena de clasificación siempre termina en `reglas`.** Es la garantía de que el
   sistema responde aunque fallen los demás motores; `cadena.py` la agrega si no está.
10. **WhatsApp solo responde a números autorizados.** Sin lista, el canal calla. No agregues un
   modo "abierto a todos".
11. **Todo en español**: interfaz, mensajes, docstrings, nombres de dominio, commits y
   documentación. Los identificadores de librerías y los términos técnicos establecidos
   quedan en su idioma original.

## Convenciones

- Python 3.12 en la imagen, 3.13 en local. Tipado con `from __future__ import annotations`.
- Los módulos de dominio usan nombres en español (`presentacion.py`, `planner.py`,
  `resumen_ejecutivo`). Mantén la coherencia: no mezcles `get_summary` con `resumen`.
- Docstrings que expliquen **por qué**, no qué hace la línea siguiente.
- Sin dependencias nuevas salvo necesidad real. El camino por defecto debe funcionar sin red:
  embeddings por hashing, clasificador entrenado en proceso, generador SQL determinista.
- El frontend no tiene build. Nada de npm en producción: `package.json` existe solo para las
  pruebas (Playwright y `puppeteer-core`, que habla CDP con Lightpanda).
- Las respuestas de la API son diccionarios planos serializables. Si agregas un campo,
  agrégalo también a la prueba correspondiente en `tests/test_api.py`.

## Cómo agregar cosas

**Un KPI nuevo**: declararlo en `backend/app/seed/metadata.json` (`kpis`) y, si el planificador
determinista debe saber calcularlo, agregarlo a `METRICAS` y a `PALABRAS_METRICA` en
`planner.py`. Añadir una prueba en `tests/test_planner.py`.

**Una dimensión nueva**: agregar el patrón a `DIMENSIONES_TEXTO` en `planner.py` y la etiqueta
legible a `ETIQUETAS` en `presentacion.py`.

**Una intención nueva**: agregar frases a `ENTRENAMIENTO` y casos a `EVALUACION` en
`intent_data.py`, la regla de respaldo en `REGLAS` de `clasificacion/motores.py`, la traducción
en `INTENCIONES_NEGOCIO` de `presentacion.py` y la rama correspondiente en
`orchestrator.preguntar`.

**Un motor de clasificación nuevo**: implementar `MotorBase` en `clasificacion/motores.py`
(`nombre`, `disponible()`, `clasificar()`, `info()`), registrarlo en `REGISTRO` y agregarlo a
`INTENT_ENGINES`. La cadena se encarga del relevo; no hace falta tocar el orquestador.

**Una tabla nueva del almacén**: describirla en `metadata.json` (incluyendo `role` de cada
columna y `pii` donde corresponda), agregar el DDL en `warehouse_loader.DDL` si forma parte
del entorno local, y verificar que `sync.columna_marca` encuentre su columna de fecha.

**Una función nueva del frontend**: agregar el caso en `tests/unit-web/specs/`. Si toca el
render de resultados, usar un fixture de `tests/unit-web/fixtures/` en vez de inventar el
payload; se capturan con `curl -X POST localhost:8000/api/preguntar`.

**Una etapa nueva del agente**: marcarla con `cronometro.marcar(...)` y traducirla en
`PASOS_NEGOCIO` de `presentacion.py`, o el usuario verá el nombre técnico.

## Trampas conocidas

Cosas que ya costaron un rato y conviene no repetir:

- **Tipos de numpy y pandas no son serializables.** La respuesta pasa por `_to_native` en
  `orchestrator.py`. Si construyes estructuras nuevas con valores de un DataFrame, conviértelas
  o pasarán por ahí; si te saltas ese camino, FastAPI falla con
  `Unable to serialize unknown type: <class 'numpy.bool'>`.
- **Cursor de servidor en psycopg2**: un cursor con nombre necesita transacción (`autocommit=False`)
  y su `description` recién existe **después del primer fetch**. Ambos detalles están resueltos
  en `RedshiftAdapter.execute_stream`.
- **`.env` alimenta la interpolación de docker compose.** Una variable en `.env` gana sobre el
  valor por defecto de `docker-compose.yml`. Si el contenedor arranca en un modo que no
  esperabas, mira ahí primero.
- **El frontend está montado como volumen; el backend no.** Cambios en `frontend/static/` se ven
  recargando el navegador. Cambios en `backend/` requieren `docker compose up -d --build app`.
- **JavaScript sin módulos comparte el ámbito global.** Dos archivos no pueden declarar el mismo
  identificador de nivel superior: `charts.js` está envuelto en una IIFE por eso.
- **CSS: los hijos de un contenedor flex con alto fijo se encogen.** Las tarjetas de resultados
  llevan `flex: 0 0 auto` para no colapsar a cero.
- **Acentos en las pruebas de Playwright**: usa texto sin acentos en las aserciones, o normaliza
  a NFC. Un `más` compuesto y otro precompuesto no coinciden.
- **Handshake CDP con nombre de host**: un servidor CDP responde `403` si el header `Host` no
  es una IP o `localhost` (defensa contra DNS rebinding). Entre contenedores hay que resolver
  el nombre a IP antes de conectar; está resuelto en `tests/unit-web/navegador.mjs`.
- **La imagen de Lightpanda usa tini como entrypoint**: el `command` del compose debe incluir
  la ruta del binario (`/bin/lightpanda serve …`), no solo `serve`.
- **Lightpanda no tiene layout**: `clientWidth` devuelve 0 y no hay capturas de pantalla. Lo
  que dependa de píxeles va en Playwright, no en el motor unitario.
- **Esperar al contenedor**: tras `docker compose up -d --build`, un bucle de `curl` sin pausa
  se agota antes de que el servicio levante. Consulta el estado con `docker compose ps`.

## Al terminar un cambio

1. `.venv/bin/python -m pytest -q` en verde.
2. Si tocaste backend: `docker compose up -d --build app` y las pruebas dentro de la imagen.
3. Si tocaste frontend: `npm run test:unit` (rápido, sin servidor) y `npx playwright test`
   con la aplicación levantada.
4. Si cambiaste comportamiento visible, actualiza `README.md` y, si aplica,
   `docs/ARCHITECTURE.md`, `docs/DEMO_SCRIPT.md` y `design/diseno-ui.md`.
5. Si tocaste la interfaz, revisa la lista de verificación de `design/diseno-ui.md`, sección 9.
5. Reporta lo que quedó fuera. No declares terminado lo que no verificaste.
