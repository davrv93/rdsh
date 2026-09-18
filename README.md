# Optimiza Conversacional

Demo funcional de una arquitectura conversacional sobre Redshift: el usuario pregunta en
español, un agente clasifica la intención en el borde, recupera contexto semántico con
embeddings, genera SQL, lo valida, lo ejecuta en **Redshift read-only** o en **DuckDB**
(modo demo), transforma el resultado con DuckDB y devuelve tabla, KPIs, gráfico,
explicación y el tiempo de cada paso.

## Arranque con Docker

```bash
cp .env.example .env
docker compose up --build
```

Ese único comando levanta las tres piezas:

1. **`warehouse`** — el almacén analítico con los datos cargados en tablas reales
   (40 000 ventas, 25 000 sesiones web, 5 000 tickets…). Es PostgreSQL, compatible con el
   protocolo de Redshift.
2. **`warehouse-loader`** — proceso de carga: crea el esquema `analytics`, las tablas con sus
   tipos, los índices, carga los datos con `COPY` y otorga **solo `SELECT`** al usuario de la
   aplicación. Corre una vez y termina.
3. **`app`** — la aplicación. Arranca en modo `redshift`, se conecta con `psycopg2` y usuario
   de solo lectura, y **materializa el almacén en DuckDB** en segundo plano.

Abrir http://localhost:8000 (chat) y http://localhost:8000/admin (configuración).

Para correr sin almacén, solo con datos de demostración en DuckDB:

```bash
docker compose --profile demo up app-demo
```

Comandos útiles:

```bash
docker compose logs -f app                         # logs de la aplicación
docker compose logs warehouse-loader               # qué se cargó en el almacén
docker compose --profile test run --rm tests       # pruebas dentro de Docker
docker compose --profile qdrant up                 # levanta también Qdrant como vector DB
docker compose exec warehouse psql -U optimiza_ro -d analytics   # consultar el almacén a mano
docker compose down -v                             # detiene y borra los volúmenes
```

Puerto distinto: `OPTIMIZA_PORT=8080 docker compose up`. El almacén queda expuesto en el
`5439` de tu máquina (`WAREHOUSE_PORT_HOST`), así que también puedes conectar Power BI o DBeaver.

## Redshift real

El código no distingue entre el almacén local y un cluster: mismo driver, mismo usuario de
solo lectura, mismo `search_path` y `statement_timeout`. Para apuntar a Redshift de verdad
basta con cambiar las variables:

```bash
OPTIMIZA_SOURCE_MODE=redshift
REDSHIFT_HOST=mi-workgroup.123456789012.us-east-1.redshift-serverless.amazonaws.com
REDSHIFT_PORT=5439
REDSHIFT_DB=analytics
REDSHIFT_USER=optimiza_ro
REDSHIFT_PASSWORD=...
REDSHIFT_SCHEMA=analytics
```

```bash
docker compose up -d app     # sin el almacén local
```

Si no existe el cluster, [infra/](infra/) trae el Terraform para crear un Redshift Serverless
y el script que carga los datos y crea el usuario de solo lectura. Ver [infra/README.md](infra/README.md).

Con un cluster ya existente no hace falta cargar nada: apunta el `.env` a tu esquema y usa
**Configuración → Releer catálogo del almacén** para generar la metadata desde
`information_schema`.

## Arranque local sin Docker

```bash
./run.sh          # crea el venv, instala, genera los datos demo y levanta uvicorn
```

## Interfaz

Una sola columna centrada, tema claro y compacto, estilo chat: escribes abajo y cada respuesta
aparece en la conversación con su bloque de resultados (indicadores, gráfico, tabla y paneles
plegables). No hay panel lateral ni ventanas separadas.

La interfaz arranca en **vista ejecutiva**, pensada para quien no es ingeniero:

- La respuesta se redacta en lenguaje de negocio: *"Ingreso total del periodo: S/ 121.8 millones.
  El mejor mes fue jun 2025 con S/ 8.8 millones."* Sin SQL ni nombres de columnas.
- Las tarjetas y la tabla muestran moneda, porcentajes y fechas con formato local
  (`S/ 8 825 051`, `48.1 %`, `jun 2025`) y encabezados legibles (`Variación %`, `Periodo`).
- El paso a paso se cuenta en frases simples: *"Entendí tu pregunta"*, *"Revisé que fuera segura"*,
  *"Protegí los datos personales"*, cada uno con su tiempo.
- La pantalla inicial propone seis preguntas redactadas como las haría un gerente
  (*"¿Quiénes son mis 10 mejores clientes?"*) y, después de la primera respuesta, quedan tres
  sugerencias sobre la barra de escritura.

El interruptor **Modo experto** (arriba a la derecha) agrega, sin cambiar nada del backend:
SQL generado, resultado de la validación, transformación DuckDB, contexto semántico recuperado,
tokens, costo y nombres técnicos de cada etapa. La preferencia queda guardada en el navegador.

El símbolo de moneda se configura con `CURRENCY_SYMBOL` (por defecto `S/`).

## Qué se puede preguntar

En la vista ejecutiva las preguntas aparecen reformuladas en lenguaje de negocio; el texto que
se envía al agente es el de la columna "Pregunta".

| Pregunta | Intención | Qué demuestra |
|---|---|---|
| Ventas por mes | KPI | Serie temporal + window functions en DuckDB |
| Top 10 clientes por ingreso | KPI | Ranking, participación, PII enmascarada |
| Compara campañas por ROI | comparacion | CTE + LEFT JOIN + KPI compuesto |
| ¿Qué productos cayeron este trimestre? | comparacion | Agregación condicional por periodo |
| ¿Qué tablas no relacionadas puedo combinar? | exploracion | Perfilado de claves candidatas |
| Hazme un gráfico de ingreso por región | grafico | Capa de visualización |
| Exporta el resultado a csv | exportacion | Reutiliza el resultado en caché |
| Dame el detalle de ventas de julio | detalle | Filas crudas, sin gráfico |
| ayúdame | aclaracion | Pide contexto y **no ejecuta SQL** |

## Arquitectura en una línea

```
pregunta → clasificador edge (ES, CPU) → retriever vectorial → generación SQL
        → validador read-only → ruteo: Redshift o copia en DuckDB
        → transformación DuckDB → gráfico + KPIs + pasos y tiempos
```

Y en paralelo, el proceso que reemplaza al ETL nocturno:

```
Redshift (solo lectura) → extracción incremental por marca de agua
                        → DuckDB (esquema cache) + Parquet
                        → consultas siguientes resueltas en local
```

## Dónde se ejecuta cada consulta

`QUERY_ROUTING` decide, y el motivo se muestra en el panel de pasos:

| Valor | Comportamiento |
|---|---|
| `auto` (por defecto) | Usa la copia local si todas las tablas están materializadas y dentro de `CACHE_MAX_AGE_MIN`; si no, consulta el almacén |
| `redshift` | Siempre el almacén |
| `cache` | Siempre la copia local; si falta una tabla, cae al almacén |

Se cambia en caliente desde **Configuración**, sin reiniciar.

Medido en esta demo, sobre el almacén local: ~16–24 ms por consulta contra el almacén,
~5 ms contra la copia en DuckDB. Contra un Redshift remoto la diferencia es mucho mayor,
porque desaparecen la red y la cola del cluster.

## Materialización Redshift → DuckDB

El proceso vive en [sync.py](backend/app/pipeline/sync.py) y se puede disparar de tres formas:

```bash
# al arrancar la aplicación (SYNC_ON_START=true, por defecto)
docker compose exec app python -m backend.app.pipeline.sync              # incremental
docker compose exec app python -m backend.app.pipeline.sync --completa   # recarga total
curl -X POST localhost:8000/api/admin/sync -H 'Content-Type: application/json' -d '{"incremental":true}'
```

Qué hace:

- Extrae con un cursor de servidor por bloques de 50 000 filas, sin traer todo a memoria.
- **Incremental por marca de agua**: usa la columna de fecha declarada en la metadata
  (`ventas.fecha`, `clientes.fecha_alta`, …) y solo pide `WHERE fecha > última marca`.
- Materializa en el esquema `cache` de DuckDB y exporta cada tabla a Parquet en
  `data/cache/`, inspeccionable con cualquier herramienta.
- Guarda el estado en `data/sync_state.json`: filas, marca, modo y duración por tabla.
- Deja auditoría del evento `sincronizacion`.

En **Configuración** se ve tabla por tabla cuántas filas hay, de cuándo es la copia y si está
vigente, con botones *Traer novedades* y *Recargar todo*.

Los diagramas están en [design/arquitectura.md](design/arquitectura.md) (Mermaid, se renderizan
en GitHub) y en [design/arquitectura.svg](design/arquitectura.svg) para presentaciones. El
detalle escrito está en [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md). El guion de la presentación
está en [docs/DEMO_SCRIPT.md](docs/DEMO_SCRIPT.md).

## Clasificador edge en español

Corre **antes** que el agente, en CPU, sin GPU y sin red. Devuelve una de siete intenciones:
`KPI`, `exploracion`, `comparacion`, `detalle`, `grafico`, `exportacion`, `aclaracion`.

- Backend `edge` (por defecto): regresión logística softmax sobre features hasheadas
  (palabras, bigramas, n-gramas de carácter). Se entrena al arrancar en ~20 ms, ocupa ~14 k
  parámetros y clasifica en **~0.1 ms**.
- Backend `transformers`: usa un modelo HuggingFace local; por ejemplo
  `luigicfilho/intento-v1-edge`, `prudant/es_intent_classification` o
  `balidea-ai-lab/Micro-GuardBertMTL`. Se configura con `EDGE_CLASSIFIER_BACKEND=transformers`
  y `EDGE_MODEL_NAME=...`; si el modelo no está disponible localmente, degrada al backend
  `edge` sin interrumpir la demo.
- Fallback por reglas (`EDGE_CLASSIFIER_BACKEND=rules`), siempre disponible.

Efecto de la intención en el flujo:

| Intención | Comportamiento |
|---|---|
| `aclaracion` | Pide más contexto. **No genera ni ejecuta SQL.** |
| `grafico` | Fuerza la capa de visualización |
| `exportacion` | Prepara el CSV reutilizando el último resultado de la sesión |
| `KPI`, `comparacion` | Retriever vectorial + generación de SQL |
| `exploracion` | Responde desde el catálogo y perfila claves candidatas |
| `detalle` | Devuelve filas, sin gráfico |

La latencia medida aparece en la insignia superior y en el panel de pasos. La evaluación
completa (precisión y latencia por caso) está en `/admin` y en `GET /api/admin/clasificador`.

## DuckDB: para qué se usa

1. **Simulador de Redshift** en modo demo: vistas sobre Parquet.
2. **Motor de transformación**: el resultado siempre pasa por una segunda consulta DuckDB con
   window functions (`LAG`, `SUM OVER`, `ROW_NUMBER`, medias móviles, participaciones).
   Esto ocurre también cuando el origen fue Redshift.
3. **Perfilado de claves** entre tablas sin relación declarada: cobertura de valores y
   cardinalidad reales antes de proponer un join.
4. **Caché y materialización** de resultados (`materialize`).

## Tablas sin relación declarada

El agente **no inventa joins**. Cuando la pregunta necesita cruzar tablas sin relación:

1. Busca una relación declarada o virtual en el catálogo.
2. Si no existe, perfila claves candidatas con DuckDB (cobertura y cardinalidad).
3. Responde: *"No encontré una relación declarada; puedo mostrar los datos por separado o
   probar una relación sugerida"*, con botones para elegir.
4. El admin puede declarar la relación virtual, que se persiste y se reindexa al instante.

En los datos demo, `tickets_soporte` y `web_sessions` no tienen relación declarada:
la primera tiene una clave compatible (`documento_cliente` ↔ `clientes.documento`, cobertura
100 %) y la segunda no tiene ninguna clave confiable contra el modelo de ventas.

## Modos de fuente

| Modo | Configuración | Comportamiento |
|---|---|---|
| Redshift (por defecto en Docker) | `OPTIMIZA_SOURCE_MODE=redshift` + credenciales | Consulta el almacén en solo lectura, lo materializa en DuckDB y rutea según `QUERY_ROUTING`. Si el almacén falla, usa la copia local. |
| Demo | `OPTIMIZA_SOURCE_MODE=demo` | DuckDB + Parquet generados, sin almacén. |

Para Redshift hace falta `psycopg2` (ya incluido en la imagen Docker; en local:
`pip install -r requirements-redshift.txt`) y un usuario de solo lectura.

## LLM (opcional)

Con `LLM_PROVIDER=anthropic` y `ANTHROPIC_API_KEY`, la generación de SQL pasa por el modelo
y el planificador determinista queda como respaldo. Al LLM solo se le envían **metadatos**
(tablas, columnas, descripciones, KPIs, relaciones y valores categóricos no sensibles);
nunca filas de datos ni columnas marcadas como PII. El costo estimado por pregunta aparece
en el panel de pasos.

Sin API key, la demo funciona igual con el planificador determinista y costo cero.

## Seguridad

- Redshift siempre en solo lectura: usuario read-only, sesión `READ ONLY` y
  `statement_timeout`.
- Credenciales solo por variables de entorno (`.env`, nunca en el código).
- Validación del SQL antes de ejecutar: solo `SELECT`/`WITH`, tablas del catálogo, sin
  funciones de acceso a archivos, `LIMIT` obligatorio y aviso de riesgo de full scan.
- Límite de filas (`MAX_ROWS`) y timeout (`QUERY_TIMEOUT_S`) en ambos motores.
- Enmascaramiento de PII antes de devolver datos y antes de cualquier envío al LLM.
- Log de auditoría append-only en `data/audit.jsonl`, visible en `/admin`.

## API

| Endpoint | Descripción |
|---|---|
| `POST /api/preguntar` | Pregunta en lenguaje natural; devuelve respuesta, SQL, filas, gráfico, pasos y métricas |
| `POST /api/relacion/confirmar` | Acepta o rechaza una relación sugerida |
| `GET /api/export/{session_id}.csv` | Descarga el último resultado de la sesión |
| `GET /api/historial/{session_id}` | Historial de la conversación |
| `GET /api/salud` | Estado: fuente activa, clasificador, capa semántica, límites |
| `GET /api/ejemplos` | Preguntas de ejemplo, con su título en lenguaje de negocio |
| `GET /api/comparativa` | Pipeline nocturno vs flujo conversacional (con latencias medidas) |
| `GET /api/intencion?texto=...` | Clasificador edge aislado |
| `GET/POST /api/admin/metadata` | Ver y cargar el catálogo semántico |
| `GET /api/admin/embeddings` | Documentos indexados con vista previa del vector |
| `POST /api/admin/buscar` | Búsqueda semántica sobre la metadata |
| `GET/POST/DELETE /api/admin/relaciones` | Relaciones declaradas, virtuales y candidatas |
| `GET /api/admin/fuentes`, `POST /api/admin/fuentes/probar` | Estado y prueba de conexiones |
| `GET /api/admin/clasificador` | Evaluación del clasificador edge |
| `GET /api/admin/auditoria` | Últimos eventos auditados |
| `GET /api/admin/sync` | Estado de la copia materializada, tabla por tabla |
| `POST /api/admin/sync` | Ejecuta la materialización (completa o incremental) |
| `POST /api/admin/routing` | Cambia en caliente dónde se ejecutan las consultas |
| `POST /api/admin/metadata/introspectar` | Genera la metadata desde el catálogo real del almacén |

Documentación interactiva: http://localhost:8000/docs

## Datos

`backend/app/seed/generate_seed.py` genera ocho tablas que `warehouse-loader` carga en el
almacén como tablas reales (y que en modo demo se leen como Parquet):

| Tabla | Filas | Relación declarada |
|---|---|---|
| ventas | 40 000 | sí (clientes, productos, campanias, regiones, dim_fechas) |
| clientes | 600 | sí |
| productos | 120 | sí |
| campanias | 24 | sí |
| regiones | 7 | sí |
| dim_fechas | 731 | sí |
| tickets_soporte | 5 000 | **no** (clave compatible sin declarar) |
| web_sessions | 25 000 | **no** (sin clave confiable) |

Los datos incluyen estacionalidad, tendencia y una caída deliberada de la categoría *Moda*
en el tercer trimestre de 2025, para que la pregunta "¿qué productos cayeron este trimestre?"
tenga una respuesta real. Regenerar: `python -m backend.app.seed.generate_seed`.

## Pruebas

Tres niveles, del más rápido al más completo:

```bash
# 1. Backend: 72 pruebas de unidad, API e integración
.venv/bin/python -m pytest -q
docker compose --profile test run --rm tests        # las mismas dentro de la imagen

# 2. Frontend: 64 pruebas unitarias en un navegador real, en ~60 ms
npm run lightpanda:install                          # una sola vez
npm run test:unit
docker compose --profile test up -d lightpanda      # o sin instalar nada:
docker compose --profile test run --rm unit-web

# 3. Interfaz de punta a punta (requiere la app corriendo)
npm install && npx playwright install chromium
npx playwright test
```

Las pruebas unitarias del frontend corren sobre [Lightpanda](https://lightpanda.io), un
navegador headless sin motor gráfico: el suite completo tarda ~60 ms, contra ~430 ms del
mismo suite en Chromium. Ejecutan los módulos reales de `frontend/static/` contra respuestas
capturadas de la API, así que detectan un cambio de contrato del backend sin levantar el
servidor. El detalle está en [tests/unit-web/README.md](tests/unit-web/README.md); para
contrastar un resultado, `npm run test:unit:chromium` corre lo mismo en Chromium.

Las pruebas marcadas `integracion` corren contra el almacén levantado y se saltan solas si no
está disponible:

```bash
docker compose up -d warehouse warehouse-loader
OPTIMIZA_SOURCE_MODE=redshift REDSHIFT_HOST=localhost REDSHIFT_PORT=5439 \
  REDSHIFT_USER=optimiza_ro REDSHIFT_PASSWORD=optimiza_ro_pwd REDSHIFT_SCHEMA=analytics \
  .venv/bin/python -m pytest tests/test_warehouse_integracion.py -v
```

Verifican la conexión de solo lectura, que el almacén **rechaza** una escritura, una consulta
real sobre 40 000 filas y que el ruteo usa la copia local cuando está fresca.

Cobertura de las pruebas: capa de presentación (etiquetas, formatos y resumen sin jerga),
clasificador edge (precisión, cobertura de intenciones, latencia,
fallback), validador de SQL (escritura, tablas fuera de catálogo, límites, full scan),
DuckDB (transformación real con window functions, perfilado de claves), planificador
(sin joins inventados) y API de extremo a extremo (KPI, aclaración, exploración, exportación,
comparación, PII, relaciones virtuales).

## Variables de entorno

Ver [.env.example](.env.example). Las más relevantes:

| Variable | Por defecto | Descripción |
|---|---|---|
| `OPTIMIZA_SOURCE_MODE` | `demo` | `demo` o `redshift` |
| `MAX_ROWS` | `5000` | Límite de filas por consulta |
| `QUERY_TIMEOUT_S` | `15` | Timeout de ejecución |
| `MASK_PII` | `true` | Enmascaramiento de PII en las respuestas |
| `EDGE_CLASSIFIER_BACKEND` | `edge` | `edge`, `transformers` o `rules` |
| `EMBEDDING_BACKEND` | `hashing` | `hashing` o `st` (sentence-transformers) |
| `VECTOR_BACKEND` | `memory` | `memory` o `qdrant` |
| `LLM_PROVIDER` | `none` | `none` o `anthropic` |
| `QUERY_ROUTING` | `auto` | `auto`, `redshift` o `cache` |
| `CACHE_MAX_AGE_MIN` | `720` | Minutos que la copia local se considera vigente |
| `SYNC_ON_START` | `true` | Materializa al arrancar si la copia está vacía |
| `CURRENCY_SYMBOL` | `S/` | Símbolo de moneda que ve el usuario final |

## Estructura

```
backend/app/     config, agent/ (clasificador, planner, validador, gráficos, orquestador),
                 semantic/ (embeddings, vector store, catálogo), engines/ (DuckDB, Redshift),
                 pipeline/ (carga del almacén y materialización a DuckDB),
                 security/ (PII, auditoría), api/ (rutas), seed/ (datos y metadata)
docker/          init del almacén (esquema, usuario de solo lectura, permisos)
infra/           Terraform para Redshift Serverless y script de bootstrap
frontend/static/ chat, panel de resultados, formatos de negocio, gráficos y panel admin
tests/           pytest (unitarias, API e integración), unit-web/ (motor propio sobre
                 Lightpanda para el frontend) y e2e/ (Playwright)
scripts/         instalación de Lightpanda
docs/            ARCHITECTURE.md y DEMO_SCRIPT.md
```

## Limitaciones conocidas de la demo

- El almacén local es PostgreSQL, no Redshift: no hay nodos, ni claves de distribución u
  ordenamiento, ni `COPY` desde S3. El SQL generado es portable entre ambos y el camino de
  código es idéntico, pero los tiempos de un cluster real serán distintos.
- Las sesiones viven en memoria del proceso: reiniciar el contenedor las borra.
- El planificador determinista cubre el vocabulario analítico del catálogo demo; para
  preguntas más libres conviene activar el LLM.
- No hay autenticación ni control de acceso por usuario: es una demo local.
- La metadata se edita como JSON completo desde el panel admin, sin control de versiones.
