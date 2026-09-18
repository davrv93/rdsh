# Arquitectura — Optimiza Conversacional

## 1. Vista general

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                            NAVEGADOR (frontend estático)                     │
│  Chat (izquierda)            │  Panel de resultados (derecha)                │
│  - historial de sesión       │  - tarjetas KPI                               │
│  - intención detectada       │  - gráfico Vega-Lite (fallback SVG propio)    │
│  - sugerencias / opciones    │  - tabla + exportación CSV                    │
│                              │  - panel de SQL, pasos y tiempos              │
└───────────────┬──────────────────────────────────────────────────────────────┘
                │ HTTP JSON  (/api/preguntar, /api/admin/*, /api/comparativa)
┌───────────────▼──────────────────────────────────────────────────────────────┐
│                        BACKEND FastAPI — Orquestador del agente              │
│                                                                              │
│  1. Clasificador edge (ES)  ──► intención + latencia (CPU, sin GPU, sin red) │
│     backend `edge`: softmax sobre features hasheadas, entrenado al arrancar  │
│     backend `transformers`: modelo HF local     fallback: reglas regex       │
│                                                                              │
│  2. Retriever vectorial ──► tablas, columnas, KPIs, relaciones, glosario     │
│     embeddings locales (hashing) o sentence-transformers · store: memoria    │
│     o Qdrant · puntaje híbrido coseno + solape léxico                        │
│                                                                              │
│  3. Generación de SQL                                                        │
│     a) LLM opcional (Anthropic) — recibe SOLO metadata, nunca datos          │
│     b) Planificador determinista (por defecto): métrica + dimensión + grano  │
│        + filtros temporales + ranking, con CTEs y window functions           │
│                                                                              │
│  4. Guardia de relaciones ──► si no hay relación declarada, NO inventa join: │
│     perfila claves candidatas en DuckDB y pide confirmación                  │
│                                                                              │
│  5. Validador SQL ──► solo SELECT/WITH, catálogo permitido, LIMIT, timeout,  │
│     riesgo de full scan, sin funciones de acceso a archivos                  │
│                                                                              │
│  6. Ejecución ──► Redshift read-only (si hay credenciales) o DuckDB demo     │
│                                                                              │
│  7. Transformación DuckDB ──► siempre, sobre el resultado: window functions, │
│     participación, acumulados, variaciones, ranking                          │
│                                                                              │
│  8. PII + visualización + métricas ──► enmascarado, gráfico elegido, tiempos │
└───────────────┬──────────────────────────────┬───────────────────────────────┘
                │                              │
      ┌─────────▼─────────┐          ┌─────────▼──────────┐
      │  Redshift (RO)    │  sync →  │  DuckDB embebido   │
      │  usuario read-only│  ───────►│  esquema `cache`   │
      │  statement_timeout│          │  + Parquet         │
      │  search_path      │          │  transformaciones  │
      └───────────────────┘          └────────────────────┘
```

## 1b. Las tres capas en Docker

```
┌────────────────┐   COPY / DDL / GRANT SELECT   ┌──────────────────────────┐
│ warehouse-     │ ────────────────────────────► │ warehouse                │
│ loader         │   (una sola vez al arrancar)  │ almacén analítico        │
│ proceso de     │                               │ esquema `analytics`      │
│ carga          │                               │ usuario optimiza_ro (RO) │
└────────────────┘                               └────────────┬─────────────┘
                                                              │ SELECT (solo lectura)
                                              ┌───────────────▼──────────────┐
                                              │ app                          │
                                              │  ├─ agente conversacional    │
                                              │  ├─ pipeline/sync.py         │
                                              │  │   extracción incremental  │
                                              │  │   por marca de agua       │
                                              │  └─ DuckDB `cache` + Parquet │
                                              └──────────────────────────────┘
```

El proceso de materialización sustituye al ETL nocturno: en lugar de mover los datos de
madrugada a otra base y precalcular tablas para Power BI, trae solo las filas nuevas cuando
hacen falta y deja la copia lista para responder preguntas en milisegundos.

## 1c. Ruteo de cada consulta

```
tablas de la consulta (las extrae el validador del SQL)
        │
        ├─ ¿hay Redshift configurado?  no ──────────────► DuckDB con datos demo
        │                              sí
        ├─ QUERY_ROUTING=redshift ─────────────────────► Redshift
        ├─ QUERY_ROUTING=cache y todo materializado ───► DuckDB (copia local)
        └─ auto:
             ├─ falta alguna tabla en la copia ────────► Redshift
             ├─ copia más vieja que CACHE_MAX_AGE_MIN ─► Redshift
             └─ copia completa y vigente ──────────────► DuckDB (copia local)

Si Redshift falla en ejecución y existe copia local, se responde con la copia
y el paso queda registrado como "respaldo tras el fallo de Redshift".
```

## 2. Componentes y archivos

| Componente | Archivo | Rol |
|---|---|---|
| Configuración | `backend/app/config.py` | Variables de entorno, límites, modo demo/Redshift |
| Datos demo | `backend/app/seed/generate_seed.py` | 8 tablas Parquet, 2 sin relación declarada |
| Metadata semántica | `backend/app/seed/metadata.json` | Tablas, columnas, KPIs, relaciones, glosario, PII |
| Embeddings | `backend/app/semantic/embeddings.py` | Hashing local (CPU) o sentence-transformers |
| Vector store | `backend/app/semantic/vector_store.py` | Coseno en memoria + espejo opcional en Qdrant |
| Catálogo | `backend/app/semantic/catalog.py` | Indexado, relaciones virtuales, búsqueda de join path |
| Clasificador edge | `backend/app/agent/intent_classifier.py` | 7 intenciones, latencia medida, fallback por reglas |
| Planificador SQL | `backend/app/agent/planner.py` | NL → plan → SQL portable Redshift/DuckDB |
| LLM opcional | `backend/app/agent/llm.py` | Anthropic Messages API, solo metadata |
| Validador | `backend/app/agent/validator.py` | Read-only, catálogo, LIMIT, full scan |
| Gráficos | `backend/app/agent/chart.py` | Selección automática + spec Vega-Lite |
| Orquestador | `backend/app/agent/orchestrator.py` | Flujo completo, pasos, tiempos, sesiones |
| Motor DuckDB | `backend/app/engines/duckdb_engine.py` | Ejecución, transformación, perfilado de claves |
| Adaptador Redshift | `backend/app/engines/redshift_adapter.py` | Conexión read-only, timeout, `search_path`, streaming por bloques, introspección |
| Carga del almacén | `backend/app/pipeline/warehouse_loader.py` | DDL, `COPY`, índices y `GRANT SELECT` al usuario de la app |
| Materialización | `backend/app/pipeline/sync.py` | Extracción incremental por marca de agua hacia DuckDB + Parquet |
| Init del almacén | `docker/warehouse/01-init.sql` | Esquema, rol de solo lectura y revocación de permisos de escritura |
| Infraestructura | `infra/terraform/main.tf` | Redshift Serverless real (namespace, workgroup, security group) |
| Seguridad | `backend/app/security/` | Enmascaramiento de PII y auditoría JSONL |
| API | `backend/app/api/` | Rutas de chat, admin y meta |
| Frontend | `frontend/static/` | Chat, resultados, gráficos, panel admin |

## 3. Flujo de una pregunta

```
"Muéstrame las ventas por mes y top clientes"
  │
  ├─ clasificador_edge        0.1 ms   intención = grafico (confianza 0.78)
  ├─ retriever_vectorial      1.2 ms   12 fragmentos de 128 documentos
  ├─ generacion_sql           0.0 ms   plan: serie mensual + dimensión cliente
  ├─ validacion_sql           1.5 ms   OK · LIMIT 5000 · riesgo bajo
  ├─ ejecucion_duckdb        10.1 ms   21 filas
  ├─ transformacion_duckdb    8.4 ms   LAG, SUM OVER, media móvil 3
  ├─ enmascaramiento_pii      0.3 ms   columna cliente enmascarada
  └─ visualizacion            1.2 ms   línea (dimensión temporal)
Total: ~26 ms
```

## 4. Decisiones de diseño

1. **El camino por defecto no depende de la nube.** El clasificador, los embeddings y el
   generador SQL funcionan sin red. El LLM es una mejora opcional, no un requisito.
2. **DuckDB participa siempre**, incluso cuando el origen es Redshift: el resultado se
   transforma localmente. Eso reduce el trabajo del warehouse y permite pre-agregar y cachear.
3. **Nunca se inventan relaciones.** Sin relación declarada el agente perfila claves con
   DuckDB (cobertura y cardinalidad reales) y pide confirmación antes de cruzar.
4. **La seguridad se aplica en capas**: usuario read-only en Redshift, validador de SQL,
   límite de filas, timeout, enmascaramiento de PII y auditoría.
5. **Los tiempos se miden, no se estiman.** Cada etapa reporta milisegundos reales, incluida
   la latencia del clasificador edge.

## 5. Escalamiento a producción

- Cambiar `VECTOR_BACKEND=qdrant` (o pgvector) cuando la metadata crezca a miles de columnas.
- Sustituir el planificador determinista por el LLM en preguntas complejas, manteniendo el
  planificador como respaldo y el validador como control obligatorio.
- Introspección automática del catálogo de Redshift (`RedshiftAdapter.introspect`) para
  generar la metadata inicial y enriquecerla con descripciones del equipo de datos.
- Programar la materialización (cron o Airflow) según la frescura que pida el negocio; el
  proceso ya es incremental e idempotente.
- Materializar en DuckDB las agregaciones más consultadas (`materialize`) como caché caliente.
- Añadir autenticación y control de acceso por fila/columna antes de exponerlo a usuarios finales.
