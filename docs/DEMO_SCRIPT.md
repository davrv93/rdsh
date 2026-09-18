# Guion de demo — 5 minutos

**Antes de empezar:** `docker compose up --build` y abrir http://localhost:8000.
Tener a la vista también http://localhost:8000/admin en otra pestaña.
La pantalla es un chat de una sola columna: se escribe abajo y la respuesta, con sus
indicadores, gráfico y tabla, aparece dentro de la conversación.

---

## Antes del minuto 0 — Qué se levantó

Un solo `docker compose up --build` dejó corriendo tres piezas: el **almacén** con los datos
en tablas reales, el **proceso de carga** que creó el esquema y otorgó solo `SELECT`, y la
**aplicación**, que al arrancar materializó las 71 482 filas del almacén en DuckDB en menos
de medio segundo. Vale la pena mostrar `docker compose ps` antes de empezar.

## Minuto 0:00–0:40 — El problema actual

> "Hoy Optimiza lee vistas de Redshift de noche, inserta en otra base, transforma, crea
> stores y genera tablas finales para Power BI. Son unas tres horas de proceso y el dato
> llega con medio día de rezago. Cada pregunta nueva del negocio es un cambio de ETL."

Abrir el panel **Comparativa** (al final de la columna de resultados, después de la primera
pregunta) y mostrar los 165 minutos del pipeline nocturno.

## Minuto 0:40–1:40 — Primera pregunta: KPI + serie temporal

Escribir: **"Muéstrame las ventas por mes"**

Señalar, en este orden:

1. La respuesta está escrita para negocio: *"Ingreso total del periodo: S/ 121.8 millones.
   El mejor mes fue jun 2025…"*. Ningún usuario necesita leer SQL.
2. Las tarjetas de indicadores y el gráfico de línea elegido automáticamente, con moneda y
   meses en español.
3. El panel **Cómo obtuve esta respuesta**: ocho etapas contadas en lenguaje simple
   ("Entendí tu pregunta", "Revisé que fuera segura"), con su tiempo. Total ~25 ms.
4. Activar **Modo experto** (arriba a la derecha) y mostrar el SQL generado: legible, portable
   entre Redshift y DuckDB, con `LIMIT` inyectado por el validador.
5. En el mismo panel, la **transformación DuckDB**: `LAG`, `SUM OVER`, media móvil.
   DuckDB no es solo caché: hizo una transformación real sobre el resultado.
6. Volver a apagar **Modo experto** para seguir la demo con la vista del usuario final.

## Minuto 1:40–2:30 — Ranking y explicación

Escribir: **"Top 10 clientes por ingreso"**

- El planificador entendió el `top 10` y la dimensión cliente, y usó la relación declarada
  `ventas.cliente_id = clientes.cliente_id`.
- La transformación DuckDB añadió `ranking`, `participacion` y `participacion_acumulada`.
- Los nombres de cliente aparecen **enmascarados**: la política de PII se aplica antes de
  devolver los datos, y al LLM solo viajan metadatos.

## Minuto 2:30–3:20 — Comparación real de periodos

Escribir: **"¿Qué productos cayeron este trimestre?"**

- Intención detectada: `comparacion`.
- El SQL usa agregación condicional en una sola pasada: periodo actual contra el anterior.
- La tabla muestra `variacion_pct` y el gráfico de barras divergente marca las caídas en rojo.
- Comentar: "El dato es de este instante, no de la corrida de anoche."

## Minuto 3:20–4:10 — Tablas sin relación: el agente no inventa

Escribir: **"¿Qué tablas no relacionadas puedo combinar?"**

- El agente perfila claves candidatas **con DuckDB**: cobertura de valores y cardinalidad.
- `tickets_soporte.documento_cliente ↔ clientes.documento`: cobertura 100 %, `many_to_one`,
  candidata confiable.
- `web_sessions.utm_campaign` contra el catálogo de productos: 0 valores comunes, descartada.
- Frase clave: **"No encontré una relación declarada; puedo mostrar los datos por separado o
  probar una relación sugerida."** Nunca ejecuta el join por su cuenta.
- Ir al panel admin y declarar la relación virtual `tickets_soporte.documento_cliente =
  clientes.documento`. El catálogo se reindexa al instante.

## Minuto 4:00–4:30 — Dónde se ejecuta cada consulta

En **Configuración**, panel *Materialización del almacén*: tabla por tabla, cuántas filas hay
en la copia local, la marca de agua y hace cuánto se actualizó.

- Cambiar el ruteo a **redshift · siempre el almacén** y repetir "ventas por mes": el paso dice
  *"Consulté el almacén"*, ~20 ms.
- Volver a **auto**: el paso dice *"Consulté la copia local"*, ~5 ms, con el motivo
  *"copia local vigente"*.
- Pulsar **Traer novedades**: el proceso incremental solo pide `WHERE fecha > última marca`.

> "Esto es el ETL nocturno, pero incremental, a demanda y en milisegundos. Y si la copia no
> está fresca o falta una tabla, la pregunta se resuelve igual contra el almacén."

## Minuto 4:30–4:45 — Exportación y panel admin

Escribir: **"Exporta el resultado a csv"**

- Intención `exportacion`: reutiliza el último resultado en caché, **no vuelve a consultar
  la base**, y entrega el CSV.
- En **Configuración** (`/admin`): fuentes conectadas, evaluación del clasificador edge
  (precisión y latencia por caso), embeddings indexados con vista previa del vector, y el log
  de auditoría. Esta pantalla es para el equipo de datos, no para el usuario final.

## Minuto 4:45–5:00 — Cierre

> "Mismo resultado que el tablero de Power BI, pero en milisegundos, sobre el dato vigente,
> sin materializar tablas intermedias y sin escribir ETL para cada pregunta nueva.
> El clasificador y los embeddings corren en CPU local, así que el costo por pregunta es
> cero cuando no se llama al LLM; con LLM, el costo aparece medido en el panel de pasos.
> Redshift se toca en modo lectura, con validación de SQL, límite de filas y timeout."

---

## Preguntas de respaldo (si sobra tiempo o falla alguna)

| Pregunta | Qué demuestra |
|---|---|
| "Compara campañas por ROI" | CTE + LEFT JOIN + KPI compuesto con inversión |
| "Margen por categoría en 2025" | Filtro temporal detectado en español |
| "Dame el detalle de ventas de julio" | Intención `detalle`, sin gráfico, tabla cruda |
| "Hazme un gráfico de ingreso por región" | Intención `grafico`, capa de visualización forzada |
| "ayúdame" | Intención `aclaracion`: pide contexto y **no ejecuta SQL** |

## Si algo falla

- El backend no responde → `docker compose logs -f app`.
- Sin internet, Vega-Lite no carga desde el CDN: el frontend dibuja el gráfico con su
  renderizador SVG propio. La demo sigue funcionando.
- El almacén no conecta → si hay copia local, el agente responde igual y lo dice en los pasos;
  si no la hay, se puede levantar el modo demo con `docker compose --profile demo up app-demo`.
