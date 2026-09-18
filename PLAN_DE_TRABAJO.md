# Plan de trabajo — Optimiza Conversacional

**Fecha:** 18 de septiembre de 2026
**Estado:** Fase 0 (demo funcional) completada. Pendiente la decisión de avanzar a piloto.

---

## 1. Objetivo

Validar y llevar a producción una forma distinta de entregar analítica en Optimiza: en lugar
de un proceso nocturno que mueve datos de Redshift a otra base, los transforma y publica
tablas para Power BI, el usuario de negocio pregunta en español y obtiene la respuesta —número,
gráfico y detalle— sobre el dato vigente, en segundos.

La hipótesis técnica a validar: **una capa semántica vectorial, un clasificador de intención
local y un motor analítico embebido (DuckDB) permiten responder las mismas preguntas que hoy
resuelve el pipeline nocturno, más rápido, con menos infraestructura intermedia y sin escribir
un ETL nuevo por cada pregunta.**

## 2. Alcance

**Dentro:** preguntas analíticas sobre el dominio comercial (ventas, clientes, productos,
campañas, regiones, soporte y web); generación y validación de SQL; ejecución de solo lectura;
materialización incremental hacia DuckDB; visualización automática; exportación; panel de
administración de metadata y relaciones.

**Fuera, por ahora:** escritura sobre el almacén; pronósticos y modelos predictivos; reemplazo
de los tableros existentes de Power BI; ingesta de fuentes nuevas que hoy no estén en Redshift;
aplicación móvil nativa.

## 3. Estado actual — Fase 0 completada

La demo está construida, corre con un solo comando y tiene evidencia medida:

| Entregable | Estado | Evidencia |
|---|---|---|
| Chat en español con respuesta, tabla y gráfico | Completo | 5 pruebas de interfaz automatizadas |
| Clasificador de intención local, 7 intenciones | Completo | 100 % de acierto en el set de evaluación, 0.06–0.2 ms por pregunta, CPU, sin red |
| Capa semántica vectorial sobre metadata | Completo | 128 documentos indexados: tablas, columnas, KPIs, relaciones, valores y glosario |
| Generación y validación de SQL | Completo | Generador determinista sin costo, LLM opcional; validador que rechaza escritura, tablas fuera de catálogo y escaneos completos |
| Ejecución contra el almacén en solo lectura | Completo | Pruebas de integración: el almacén rechaza `DELETE` y `CREATE TABLE` del usuario de la aplicación |
| Materialización Redshift → DuckDB | Completo | 71 482 filas en 458 ms al arrancar; incremental por marca de agua |
| Ruteo entre almacén y copia local | Completo | 16–24 ms contra el almacén, ~5 ms contra la copia local |
| Guardia de tablas sin relación declarada | Completo | Perfila claves candidatas y pide confirmación; nunca cruza por su cuenta |
| Enmascaramiento de PII y auditoría | Completo | Correos, documentos y nombres enmascarados antes de responder; bitácora JSONL |
| Interfaz para usuarios no técnicos | Completo | Vista ejecutiva por defecto, modo experto para el equipo de datos |
| Infraestructura reproducible | Completo | `docker compose up --build` levanta almacén, carga y aplicación; Terraform para Redshift Serverless real |
| Pruebas | Completo | 68 pruebas automatizadas (64 unitarias y de API, 4 de integración) |

**Lo que la Fase 0 todavía no prueba:** el comportamiento con el volumen, la latencia de red y
el modelo de datos reales de Optimiza; la calidad de las respuestas frente a las preguntas que
el negocio hace de verdad; y la operación sostenida con usuarios concurrentes.

---

## 4. Fases

### Fase 1 — Piloto con datos reales (3 a 4 semanas)

**Objetivo:** conectar la solución al Redshift de Optimiza, con un dominio acotado y un grupo
pequeño de usuarios, y medir si responde bien a las preguntas reales.

**Tareas**

1. Crear el usuario de solo lectura en el Redshift de Optimiza y acordar el esquema del piloto
   (propuesta: el dominio comercial que ya alimenta el tablero principal).
2. Generar la metadata inicial con la introspección automática del catálogo
   (`POST /api/admin/metadata/introspectar`) y completarla con el equipo de datos:
   descripciones, sinónimos, KPIs oficiales, relaciones declaradas y marcado de PII.
3. Recolectar entre 60 y 100 preguntas reales de usuarios de negocio (entrevistas y revisión de
   los pedidos que hoy llegan al equipo de datos) y convertirlas en un set de evaluación.
4. Medir la tasa de respuesta correcta sobre ese set y ajustar el planificador determinista;
   decidir con datos si el LLM es necesario para cerrar la brecha.
5. Configurar la frecuencia de materialización según la frescura que pida cada tabla.
6. Habilitar el piloto para 5 a 10 usuarios y acompañarlos durante dos semanas.

**Entregables:** metadata del dominio piloto documentada; set de evaluación con su medición;
informe de brechas; instancia del piloto operando.

**Criterios de aceptación**
- 80 % o más de las preguntas del set se responden correctamente sin intervención técnica.
- Ninguna respuesta expone datos personales sin enmascarar.
- Ninguna consulta escribe en el almacén (verificado en la bitácora de auditoría).
- Latencia mediana por debajo de 3 segundos con datos reales.

**Equipo:** 1 ingeniero de datos (50 %), 1 desarrollador backend (100 %), 1 analista de negocio
(30 %), 1 responsable de seguridad para la revisión de accesos (10 %).

**Riesgo principal:** la metadata real es pobre o inconsistente. Es la tarea con más incertidumbre
y la que más condiciona la calidad de las respuestas.

---

### Fase 2 — Endurecimiento para uso interno (4 a 6 semanas)

**Objetivo:** convertir el piloto en un servicio que pueda usar cualquier persona autorizada de
la organización.

**Tareas**

1. **Autenticación y autorización.** Integración con el proveedor de identidad corporativo
   (SSO). Hoy no hay autenticación: es el bloqueante principal para abrir el acceso.
2. **Control de acceso por fila y columna.** Que cada usuario vea solo su territorio, su canal o
   su cartera. Requiere decidir si se resuelve en el almacén (vistas y roles) o en la aplicación.
3. **Sesiones persistentes.** Hoy viven en memoria del proceso; moverlas a almacenamiento
   externo para que sobrevivan a un reinicio y permitan más de una réplica.
4. **Vector store gestionado.** Pasar de índice en proceso a pgvector o Qdrant cuando la
   metadata supere unos pocos miles de columnas.
5. **Observabilidad.** Métricas de latencia por etapa, tasa de aclaraciones, consultas
   rechazadas por el validador, costo por pregunta y alertas de fallo de materialización.
6. **Programación de la materialización.** Orquestador (cron o Airflow) con reintentos y
   notificación; el proceso ya es incremental e idempotente.
7. **Endurecimiento de la imagen y despliegue.** Usuario sin privilegios, escaneo de
   vulnerabilidades, gestión de secretos fuera del `.env`, despliegue en la infraestructura
   estándar de Optimiza.

**Entregables:** servicio con SSO y control de acceso; tableros de observabilidad; materialización
programada; documento de operación (runbook).

**Criterios de aceptación**
- Un usuario no puede consultar datos fuera de su alcance autorizado, verificado con pruebas.
- El servicio sobrevive al reinicio de un contenedor sin perder conversaciones activas.
- Las alertas de fallo llegan al equipo responsable en menos de 5 minutos.
- Revisión de seguridad aprobada.

**Equipo:** 1 desarrollador backend (100 %), 1 ingeniero de plataforma (60 %), 1 ingeniero de
datos (30 %), seguridad (20 %).

---

### Fase 3 — Producción y adopción (4 a 6 semanas)

**Objetivo:** abrir el servicio al conjunto de usuarios objetivo y medir el impacto contra el
proceso actual.

**Tareas**

1. Ampliar el catálogo a los dominios que hoy cubre Power BI, uno por uno, con su metadata
   revisada por el dueño de cada dominio.
2. Definir qué tableros siguen existiendo y cuáles se reemplazan. La recomendación es convivir:
   el tablero para el seguimiento recurrente, la conversación para la pregunta nueva.
3. Capacitación y material de apoyo para usuarios de negocio.
4. Medir el uso real: preguntas por usuario, tasa de éxito, preguntas que quedan sin responder
   (fuente de trabajo para el equipo de datos).
5. Evaluar la reducción de trabajo en el pipeline nocturno: qué tablas intermedias dejan de ser
   necesarias y cuánto se ahorra en cómputo y mantenimiento.

**Entregables:** servicio en producción; informe de adopción e impacto; decisión documentada
sobre qué partes del pipeline nocturno se retiran.

**Criterios de aceptación**
- 70 % de los usuarios objetivo usa el servicio al menos una vez por semana durante un mes.
- Reducción medible del tiempo de espera para preguntas nuevas, comparado con la línea base
  actual (hoy: cambio de ETL y despliegue).
- Sin incidentes de seguridad ni de exposición de datos.

**Equipo:** 1 desarrollador backend (60 %), 1 ingeniero de datos (60 %), 1 analista de negocio
(50 %), gestión del cambio (30 %).

---

### Fase 4 — Evolución (continuo)

Candidatos, a priorizar con el uso real:

- **LLM para preguntas complejas**, manteniendo el generador determinista como respaldo y el
  validador como control obligatorio. Decisión basada en la brecha medida en la Fase 1.
- **Memoria conversacional**: preguntas de seguimiento sobre el resultado anterior
  ("¿y sin el canal web?").
- **Alertas proactivas**: el sistema avisa cuando un indicador se sale de su rango.
- **Aprendizaje del glosario**: las aclaraciones que hace el usuario alimentan la capa semántica.
- **Más dominios**: finanzas, logística, recursos humanos.

---

## 5. Cronograma

| Fase | Duración | Inicio estimado | Fin estimado |
|---|---|---|---|
| 0 — Demo funcional | Completada | — | 18 sep 2026 |
| 1 — Piloto con datos reales | 3 a 4 semanas | 29 sep 2026 | 24 oct 2026 |
| 2 — Endurecimiento | 4 a 6 semanas | 27 oct 2026 | 5 dic 2026 |
| 3 — Producción y adopción | 4 a 6 semanas | 8 dic 2026 | 23 ene 2027 |
| 4 — Evolución | Continuo | — | — |

Las fechas suponen que la decisión de avanzar se toma en la semana del 22 de septiembre y que
los accesos al Redshift de Optimiza están disponibles en la primera semana de la Fase 1. El
retraso en esos accesos desplaza todo el cronograma.

---

## 6. Riesgos

| Riesgo | Impacto | Mitigación |
|---|---|---|
| La metadata real es pobre: tablas sin descripción, columnas ambiguas, sin relaciones declaradas | Alto. Es el insumo de la capa semántica; sin él, las respuestas fallan | Introspección automática como punto de partida y trabajo dirigido con los dueños de cada dominio. El sistema ya pide aclaración en vez de adivinar |
| El SQL generado responde algo plausible pero incorrecto | Alto. Erosiona la confianza del negocio | Set de evaluación con preguntas reales desde la Fase 1; el SQL y los pasos siempre visibles para el equipo de datos; el agente pide aclaración ante ambigüedad |
| Consultas pesadas afectan al cluster productivo | Medio | Usuario de solo lectura, `statement_timeout`, límite de filas, validador que detecta escaneos completos y ruteo preferente a la copia materializada |
| Exposición de datos personales | Alto | Enmascaramiento antes de responder, columnas marcadas como PII fuera del LLM, auditoría de cada consulta. Pendiente de Fase 2: control de acceso por usuario |
| Dependencia de un proveedor de LLM | Medio | El camino por defecto no usa LLM. Si se activa, es reemplazable y el validador no cambia |
| Adopción baja: los usuarios siguen pidiendo tableros | Medio | Piloto acompañado, capacitación, y convivencia con Power BI en lugar de reemplazo forzado |
| La copia materializada queda desactualizada sin que nadie lo note | Medio | Indicador de frescura por tabla en la interfaz, ruteo automático al almacén cuando la copia vence, alertas en Fase 2 |

---

## 7. Decisiones pendientes

Requieren definición antes o durante la Fase 1:

1. **Dominio del piloto.** ¿Cuál es el conjunto de tablas con el que se empieza?
2. **Frescura requerida por tabla.** ¿Cada cuánto debe actualizarse la copia local? De esto
   depende el costo de consulta sobre el cluster.
3. **Dónde vive el control de acceso.** ¿Vistas y roles en Redshift, o filtros en la aplicación?
4. **LLM sí o no.** Se decide con la medición de la Fase 1, no antes.
5. **Convivencia con Power BI.** ¿Qué tableros se mantienen y cuáles se retiran?
6. **Responsable del catálogo.** La metadata necesita un dueño permanente; sin eso se degrada.

---

## 8. Métricas de éxito

| Métrica | Línea base actual | Meta |
|---|---|---|
| Tiempo desde la pregunta hasta la respuesta | Horas o días si requiere cambio de ETL; 12 h de rezago del dato | Menos de 5 segundos, sobre el dato vigente |
| Preguntas nuevas atendidas sin desarrollo | 0 | 80 % de las preguntas del set de evaluación |
| Duración del proceso nocturno | ~165 minutos por corrida | Reducción de las etapas que dejan de ser necesarias |
| Carga de trabajo del equipo de datos en pedidos ad hoc | Por medir en la Fase 1 | Reducción del 50 % |
| Costo por pregunta | No aplica | Cero sin LLM; medido y visible si se activa |

---

## 9. Supuestos

- Existe un Redshift productivo con los datos del dominio comercial y es posible crear en él un
  usuario de solo lectura.
- El equipo de datos puede dedicar tiempo a describir la metadata: es la tarea que más condiciona
  el resultado y no se puede automatizar del todo.
- Las estimaciones de esfuerzo suponen dedicación efectiva de las personas indicadas, sin
  interrupciones por otros proyectos.
- La infraestructura de despliegue de Optimiza admite contenedores Docker.
- Las cifras de la Fase 0 se midieron contra un almacén local equivalente a Redshift, no contra
  el cluster productivo. Los tiempos con datos y red reales serán distintos y se medirán en la
  Fase 1.
