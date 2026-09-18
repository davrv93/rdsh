# Arquitectura — Optimiza Conversacional

Diagramas en Mermaid, que GitHub renderiza directamente. Para presentaciones existe la versión
en [`arquitectura.svg`](arquitectura.svg).

---

## 1. Vista general

```mermaid
flowchart LR
    subgraph NAV["Navegador"]
        UI["Chat de una columna<br/>vista ejecutiva / modo experto"]
        ADM["Configuración<br/>metadata, relaciones, sync"]
    end

    subgraph APP["Aplicación · FastAPI"]
        direction TB
        ORQ["Orquestador<br/>pasos cronometrados"]

        subgraph AG["Agente"]
            direction LR
            CLS["1 · Clasificador edge ES<br/>CPU · sin red · ~0.1 ms"]
            RAG["2 · Retriever vectorial<br/>128 documentos"]
            GEN["3 · Generador SQL<br/>determinista + LLM opcional"]
            VAL["4 · Validador<br/>solo lectura · LIMIT · escaneo"]
        end

        RUT{"5 · Ruteo<br/>¿dónde ejecuto?"}

        subgraph POST["Post-proceso"]
            direction LR
            TRF["6 · Transformación DuckDB<br/>window functions"]
            PII["7 · Enmascarado de PII"]
            VIZ["8 · Gráfico + indicadores"]
            PRE["9 · Lenguaje de negocio"]
        end
    end

    subgraph DAT["Datos"]
        direction TB
        RS[("Almacén analítico<br/>Redshift / PostgreSQL<br/>usuario de solo lectura")]
        DD[("DuckDB embebido<br/>esquema cache + Parquet")]
    end

    SYNC["Materialización incremental<br/>marca de agua por tabla"]
    LOAD["Carga del almacén<br/>DDL · COPY · GRANT SELECT"]

    UI --> ORQ
    ADM --> ORQ
    ORQ --> CLS --> RAG --> GEN --> VAL --> RUT
    RUT -->|copia vigente| DD
    RUT -->|copia vencida o ausente| RS
    RS -.->|respaldo si falla| DD
    DD --> TRF
    RS --> TRF
    TRF --> PII --> VIZ --> PRE --> UI

    RS ==>|extracción por bloques| SYNC ==>|INSERT / REPLACE| DD
    LOAD ==> RS

    classDef agente fill:#eff4ff,stroke:#2563eb,color:#16191f
    classDef datos fill:#e9f7f1,stroke:#0f8a5f,color:#16191f
    classDef proceso fill:#fdf4e7,stroke:#b45309,color:#16191f
    class CLS,RAG,GEN,VAL,ORQ,TRF,PII,VIZ,PRE agente
    class RS,DD datos
    class SYNC,LOAD proceso
```

---

## 2. Una pregunta, paso a paso

Tiempos reales medidos contra el almacén local, con la copia materializada vigente.

```mermaid
sequenceDiagram
    autonumber
    actor U as Usuario
    participant UI as Chat
    participant O as Orquestador
    participant C as Clasificador edge
    participant R as Retriever vectorial
    participant P as Planificador SQL
    participant V as Validador
    participant D as DuckDB / Almacén
    participant PR as Presentación

    U->>UI: "¿cuánto vendimos por región?"
    UI->>O: POST /api/preguntar
    O->>C: clasificar intención
    C-->>O: KPI · confianza 0.64 · 0.2 ms
    O->>R: recuperar contexto
    R-->>O: 12 fragmentos de 128 · 1 ms
    O->>P: armar plan y SQL portable
    P-->>O: SELECT ... GROUP BY region · 0 ms
    O->>V: validar
    V-->>O: OK · LIMIT 5000 · riesgo bajo · 0.3 ms
    O->>D: ejecutar por la ruta elegida
    D-->>O: 7 filas · 5 ms copia / 20 ms almacén
    O->>D: transformar: ranking, participación, acumulado
    D-->>O: 7 filas · 5 columnas · 4 ms
    O->>PR: etiquetas, formatos y resumen
    PR-->>O: "Lidera Trujillo con S/ 21.4 millones…"
    O-->>UI: respuesta, tabla, gráfico y 8 pasos con tiempos
    UI-->>U: ~20 ms en total
```

---

## 3. Dónde se ejecuta cada consulta

El validador extrae las tablas del SQL; con esa lista el orquestador decide y deja el motivo
escrito en el panel de pasos.

```mermaid
flowchart TD
    A["Tablas de la consulta"] --> B{"¿Hay almacén<br/>configurado?"}
    B -->|no| DEMO["DuckDB · datos de demostración"]
    B -->|sí| C{"QUERY_ROUTING"}

    C -->|redshift| RS["Almacén<br/>16–24 ms"]
    C -->|cache| D{"¿Todas las tablas<br/>materializadas?"}
    C -->|auto| E{"¿Todas las tablas<br/>materializadas?"}

    D -->|sí| CA["DuckDB · copia local<br/>~5 ms"]
    D -->|no| RS

    E -->|no| RS
    E -->|sí| F{"¿Copia dentro de<br/>CACHE_MAX_AGE_MIN?"}
    F -->|sí| CA
    F -->|no| RS

    RS -.->|falla y existe copia| CA

    classDef rapido fill:#e9f7f1,stroke:#0f8a5f,color:#16191f
    classDef lento fill:#fdf4e7,stroke:#b45309,color:#16191f
    class CA,DEMO rapido
    class RS lento
```

---

## 4. Materialización Redshift → DuckDB

Reemplaza al proceso nocturno: en vez de mover todo de madrugada, trae solo lo nuevo, cuando
hace falta.

```mermaid
flowchart LR
    subgraph ALM["Almacén"]
        T1[("ventas<br/>40 000 filas")]
        T2[("clientes")]
        T3[("6 tablas más")]
    end

    subgraph PROC["pipeline/sync.py"]
        direction TB
        W["Lee la marca de agua<br/>data/sync_state.json"]
        Q["SELECT * FROM tabla<br/>WHERE fecha > marca"]
        S["Cursor de servidor<br/>bloques de 50 000 filas"]
        M["CREATE OR REPLACE / INSERT<br/>en el esquema cache"]
        X["COPY a Parquet<br/>data/cache/*.parquet"]
        E["Actualiza el estado:<br/>filas, marca, modo, duración"]
    end

    subgraph LOC["DuckDB"]
        C1[("cache.ventas")]
        C2[("cache.clientes")]
        VW["Vistas con el nombre de negocio"]
    end

    AUD["Auditoría · evento sincronizacion"]

    T1 --> W
    T2 --> W
    T3 --> W
    W --> Q --> S --> M --> X --> E --> AUD
    M --> C1 --> VW
    M --> C2 --> VW

    classDef datos fill:#e9f7f1,stroke:#0f8a5f,color:#16191f
    class T1,T2,T3,C1,C2 datos
```

Primera corrida completa medida: **71 482 filas en 458 ms**. Las siguientes son incrementales.

---

## 5. Despliegue con Docker

```mermaid
flowchart TB
    NAV["Navegador<br/>localhost:8000"]
    BI["Power BI / DBeaver<br/>localhost:5439"]

    subgraph HOST["docker compose up --build"]
        direction TB
        LD["warehouse-loader<br/>DDL · COPY · índices · GRANT<br/>corre una vez y termina"]
        WH["warehouse<br/>PostgreSQL 16<br/>esquema analytics<br/>rol optimiza_ro, solo SELECT"]
        AP["app<br/>FastAPI + frontend estático<br/>agente + pipeline + DuckDB"]
        QD["qdrant<br/>perfil opcional"]
        V1[("volumen warehouse-data")]
        V2[("volumen optimiza-data<br/>DuckDB + Parquet + estado")]
    end

    NAV --> AP
    BI --> WH
    LD -->|carga inicial| WH
    AP -->|SELECT de solo lectura| WH
    WH --- V1
    AP --- V2
    AP -.->|VECTOR_BACKEND=qdrant| QD

    classDef infra fill:#eff4ff,stroke:#2563eb,color:#16191f
    class WH,LD,AP,QD infra
```

Para un Redshift real, `warehouse` y `warehouse-loader` desaparecen: se cambian las variables
`REDSHIFT_*` y queda solo `app`. El Terraform de [`infra/`](../infra/) crea el cluster.

---

## 6. Capas de seguridad

Tres controles independientes. Ninguno sustituye a otro.

```mermaid
flowchart TB
    Q["SQL generado"] --> V["1 · Validador de la aplicación<br/>solo SELECT/WITH · catálogo permitido<br/>LIMIT obligatorio · riesgo de escaneo<br/>sin funciones de acceso a archivos"]
    V -->|rechaza| X["Error explicado<br/>sin ejecutar nada"]
    V -->|aprueba| S["2 · Sesión de solo lectura<br/>readonly=True · statement_timeout<br/>search_path acotado"]
    S --> P["3 · Permisos del motor<br/>GRANT SELECT únicamente<br/>sin CREATE ni escritura"]
    P --> R["Resultado"]
    R --> M["Enmascarado de PII<br/>correos, documentos, nombres"]
    M --> A["Auditoría JSONL<br/>pregunta, SQL, fuente, filas, tiempos"]
    A --> U["Usuario"]

    LLM["LLM opcional"] -.->|solo metadatos<br/>nunca filas ni columnas PII| Q

    classDef ctrl fill:#fdecec,stroke:#d33b3b,color:#16191f
    class V,S,P,M ctrl
```

Verificado con pruebas de integración: el usuario de la aplicación recibe
`permission denied for table ventas` al intentar `DELETE`, y
`permission denied for schema analytics` al intentar `CREATE TABLE`.

---

## 7. Comparación con el proceso actual

```mermaid
flowchart LR
    subgraph HOY["Hoy · proceso nocturno · ~165 min"]
        direction LR
        H1["SELECT sobre vistas<br/>45 min"] --> H2["INSERT en base intermedia<br/>35 min"] --> H3["Stored procedures<br/>40 min"] --> H4["Tablas finales<br/>25 min"] --> H5["Refresco de Power BI<br/>20 min"] --> H6["Dato con 12 h de rezago"]
    end

    subgraph AHORA["Ahora · por pregunta · ~20 ms"]
        direction LR
        A1["Intención<br/>0.2 ms"] --> A2["Contexto<br/>1 ms"] --> A3["SQL y validación<br/>1 ms"] --> A4["Ejecución<br/>5–20 ms"] --> A5["Transformación<br/>4 ms"] --> A6["Dato vigente"]
    end

    classDef lento fill:#fdf4e7,stroke:#b45309,color:#16191f
    classDef rapido fill:#e9f7f1,stroke:#0f8a5f,color:#16191f
    class H1,H2,H3,H4,H5,H6 lento
    class A1,A2,A3,A4,A5,A6 rapido
```

Una pregunta nueva, hoy, exige cambiar el ETL y desplegar. En el flujo conversacional no
requiere código: si la metadata la describe, el agente la responde.

---

## Referencias al código

| Bloque del diagrama | Archivo |
|---|---|
| Clasificador edge | [`backend/app/agent/intent_classifier.py`](../backend/app/agent/intent_classifier.py) |
| Retriever vectorial | [`backend/app/semantic/`](../backend/app/semantic/) |
| Generador SQL | [`backend/app/agent/planner.py`](../backend/app/agent/planner.py), [`llm.py`](../backend/app/agent/llm.py) |
| Validador | [`backend/app/agent/validator.py`](../backend/app/agent/validator.py) |
| Ruteo y pasos cronometrados | [`backend/app/agent/orchestrator.py`](../backend/app/agent/orchestrator.py) |
| Motores | [`backend/app/engines/`](../backend/app/engines/) |
| Carga y materialización | [`backend/app/pipeline/`](../backend/app/pipeline/) |
| Seguridad | [`backend/app/security/`](../backend/app/security/), [`docker/warehouse/01-init.sql`](../docker/warehouse/01-init.sql) |
| Presentación de negocio | [`backend/app/agent/presentacion.py`](../backend/app/agent/presentacion.py) |
