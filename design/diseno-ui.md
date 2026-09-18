# Guía de diseño — Optimiza Conversacional

Para quien diseñe o modifique la interfaz. No es una carta de estilo genérica: son las
decisiones tomadas en este producto, con el porqué, para que los cambios siguientes sumen en
la misma dirección en lugar de deshacerse entre sí.

---

## 1. Para quién es esto

| Perfil | Qué necesita | Qué le estorba |
|---|---|---|
| **Gerente comercial** (usuario principal) | El número, la comparación y el gráfico. Confiar en que el dato es de hoy | SQL, nombres de tablas, milisegundos, "DuckDB", "embeddings" |
| **Analista de negocio** | Lo anterior más el detalle y la descarga para seguir trabajando | Tener que pedirle la consulta al equipo de datos |
| **Equipo de datos** | El SQL generado, los tiempos por etapa, la validación, el motor que respondió | Que la herramienta le oculte lo que necesita para depurar |

Los tres usan la misma pantalla. La diferencia la hace el interruptor **Experto**, no una
aplicación distinta: el usuario de negocio ve una interfaz limpia y el equipo de datos activa
el detalle cuando lo necesita. Esa es la decisión de diseño de la que cuelgan casi todas las
demás.

---

## 2. Principios

**1. Responde primero, explica después.**
La primera línea que lee el usuario es la respuesta en palabras, no un gráfico ni una tabla:
*"Ingreso total del periodo: S/ 121.8 millones. El mejor mes fue jun 2025."* Todo lo demás
—indicadores, gráfico, detalle, pasos— está debajo, en ese orden, y se puede ignorar.

**2. Nada de jerga en la superficie.**
Si una palabra no la diría un gerente en una reunión, no va en la vista ejecutiva. Existe un
lugar para cada término técnico: el modo experto. Ver el glosario de la sección 4.

**3. Cada afirmación trae su respaldo a un clic.**
El usuario puede desconfiar del número: para eso está "Cómo obtuve esta respuesta", abierto a
un clic, en lenguaje llano. La confianza se construye mostrando el trabajo, no pidiendo fe.

**4. Compacto, no apretado.**
Densidad alta en información, generosa en aire vertical entre bloques. Texto base de 14 px,
tarjetas de 10–12 px de relleno, 8–10 px entre elementos del mismo grupo, 18 px entre grupos.
Una pantalla de 900 px de alto debe mostrar la respuesta, los indicadores y el gráfico sin
hacer scroll.

**5. Un solo acento.**
Azul `#2563eb` para lo accionable e interactivo. Verde solo para "está bien" (copia vigente,
datos protegidos), ámbar para "ojo" (demo, copia vencida), rojo solo para caídas y errores.
El color nunca es la única señal: siempre hay texto que dice lo mismo.

**6. El estado del sistema siempre visible, nunca ruidoso.**
De dónde salen los datos y de cuándo son: una insignia discreta arriba a la derecha. No una
alerta, no un banner. Si el usuario quiere el detalle, el `title` lo tiene.

**7. Si el sistema no está seguro, lo dice.**
No inventar joins, no adivinar la métrica, no rellenar con un promedio. Pedir contexto es una
respuesta válida y así está diseñada: mensaje ámbar, con opciones concretas, sin ejecutar nada.

---

## 3. Sistema visual

Todo vive en [`frontend/static/styles.css`](../frontend/static/styles.css) como variables CSS.
**No introducir valores sueltos**: si hace falta un color o un tamaño nuevo, primero se agrega
como token y se justifica aquí.

### Color

| Token | Valor | Uso |
|---|---|---|
| `--bg` | `#ffffff` | Fondo de la aplicación |
| `--bg-soft` | `#f7f8fa` | Fondos secundarios, chips, bloques de código |
| `--border` | `#e6e8ec` | Bordes de tarjetas y controles |
| `--border-soft` | `#f0f1f4` | Separadores internos de tablas y listas |
| `--text` | `#16191f` | Texto principal y cifras |
| `--text-2` | `#3d434e` | Texto de párrafo y celdas |
| `--muted` | `#767d8a` | Etiquetas, metadatos, texto de apoyo |
| `--accent` | `#2563eb` | Acciones, enlaces, foco, series de datos |
| `--accent-soft` | `#eff4ff` | Fondo de elementos activos y burbuja del usuario |
| `--ok` | `#0f8a5f` | Confirmaciones: copia vigente, PII protegida |
| `--warn` | `#b45309` | Advertencias: modo demo, copia vencida, truncado |
| `--danger` | `#d33b3b` | Caídas en los datos y errores del sistema |

Contraste verificado sobre fondo blanco: `--muted` 4.8:1, `--text-2` 10.2:1, `--accent` 6.3:1.
Todos por encima del mínimo AA para texto normal.

### Tipografía

Inter (Google Fonts) con respaldo del sistema. Una sola familia; la variación es de peso y
tamaño, nunca de fuente.

| Uso | Tamaño | Peso |
|---|---|---|
| Cifra de indicador | 18 px | 600 |
| Título de resultado | 15 px | 600 |
| Texto de conversación y campo de entrada | 14 px | 400 |
| Tabla, paneles, botones | 12.5 px | 400–550 |
| Metadatos, chips, etiquetas | 11–11.5 px | 400 |

Los números llevan `font-variant-numeric: tabular-nums` para que las columnas se alineen.

### Forma y movimiento

Radios: 7 px (controles), 10 px (tarjetas), 12 px (barra de escritura), 999 px (chips).
Sombra: una sola, mínima, en la barra de escritura. Las tarjetas se separan con borde, no con
sombra.

Movimiento: transiciones de 120–150 ms en color y borde. Nada rebota, nada se desliza. El único
elemento animado permanente es el indicador de carga. Respetar `prefers-reduced-motion`.

---

## 4. Lenguaje

El texto es la interfaz principal de este producto. Un buen mensaje evita un rediseño.

### Glosario

| No escribir | Escribir |
|---|---|
| Ejecutando query / SQL | Consultando los datos |
| DuckDB / caché materializada | La copia local |
| Redshift / warehouse | El almacén |
| Clasificador de intención | Entendí tu pregunta |
| Embeddings / retriever / RAG | Busqué en el catálogo |
| Enmascaramiento de PII | Protegí los datos personales |
| Full scan / LIMIT | (no se menciona: se resume como "revisé que fuera segura") |
| Exportar CSV | Descargar para Excel |
| Registros afectados / rows | Registros |
| Latencia | Respuesta en 20 ms |

### Reglas de redacción

- **Segunda persona y voz activa**: "Preparé tu archivo", no "El archivo ha sido generado".
- **La cifra antes que el método**: "S/ 121.8 millones en el periodo", no "Se calculó la suma
  del ingreso".
- **Números redondeados en el texto, exactos en la tabla**: "S/ 121.8 millones" en la
  respuesta, `S/ 121,847,302` en la celda.
- **Sin signos de admiración, sin emojis, sin felicitaciones.** La herramienta informa, no
  celebra.
- **Los errores dicen qué pasó, qué se puede hacer y a quién acudir**, sin trazas técnicas:
  > No pude obtener los datos en este momento. La fuente de información no respondió y no hay
  > una copia local disponible. Vuelve a intentarlo en unos minutos o avisa al equipo de datos.

  El detalle técnico va en `respuesta_tecnica`, visible solo en modo experto.

---

## 5. Estructura

Una sola columna centrada, máximo 860 px. Sin barras laterales, sin ventanas modales, sin
pestañas. La conversación es el hilo y los resultados viven dentro de ella.

```
┌──────────────────────────────────────────────┐
│ Cabecera  fuente · intención · Experto · ⚙︎  │  52 px, fija
├──────────────────────────────────────────────┤
│                                              │
│                    Pregunta del usuario  ──► │  burbuja azul, derecha
│                                              │
│ Respuesta en una o dos frases                │  texto plano, sin burbuja
│ [respuesta en 20 ms]                         │
│                                              │
│ Título del resultado · 7 registros · fuente  │
│ ┌────────┐┌────────┐┌────────┐┌────────┐     │  indicadores
│ │  KPI   ││  KPI   ││  KPI   ││  KPI   │     │
│ └────────┘└────────┘└────────┘└────────┘     │
│ ┌──────────────────────────────────────┐     │
│ │ Vista gráfica                        │     │
│ └──────────────────────────────────────┘     │
│ ┌──────────────────────────────────────┐     │
│ │ Detalle              [Descargar]     │     │
│ └──────────────────────────────────────┘     │
│ › Cómo obtuve esta respuesta · 20 ms         │  plegado
│ › Detalle técnico          (solo experto)    │
│                                              │
├──────────────────────────────────────────────┤
│ [sugerencias]                                │  fija abajo
│ [ Escribe tu pregunta…          ] [Enviar]   │
│ Consultas de solo lectura · datos protegidos │
└──────────────────────────────────────────────┘
```

**El orden no se negocia**: respuesta → indicadores → gráfico → detalle → cómo lo hice →
técnico. Va de lo que todos necesitan a lo que necesita uno de cada diez.

Al enviar una pregunta, el turno nuevo se ancla **arriba**, no al fondo: el usuario empieza a
leer donde empieza la respuesta.

---

## 6. Componentes

### Mensaje del usuario
Burbuja `--accent-soft`, alineada a la derecha, esquina inferior derecha recta. Máximo 78 % del
ancho.

### Respuesta del agente
Texto plano, sin burbuja: es el contenido principal, no un mensaje más. Negritas solo en las
cifras y los nombres propios que se destacan. Debajo, chips de metadatos (en vista ejecutiva,
solo el tiempo de respuesta).

**Variantes:** normal (texto plano) · aclaración y confirmación (fondo ámbar, con botones de
opción) · error (texto rojo, sin fondo).

### Tarjeta de indicador
Etiqueta de 11 px en `--muted`, cifra de 18 px en `--text`, detalle opcional debajo (verde si
suma, rojo si resta). Máximo cuatro por respuesta: más tarjetas es menos jerarquía.

### Gráfico
Dentro de una tarjeta con cabecera "Vista gráfica". Alto entre 210 y 300 px según la cantidad
de series. Ejes en español, valores abreviados con moneda (`S/ 9M`), máximo cuatro marcas por
eje. El motivo de la elección del gráfico solo se muestra en modo experto.

### Tabla
Cabeceras con la etiqueta legible de `columnas_meta`, no el nombre de la columna (ese va en el
`title`). Números a la derecha con cifras tabulares, negativos en rojo. Alto máximo 290 px con
scroll interno. En vista ejecutiva se ocultan las columnas de trabajo
(`participacion_acumulada`, `media_movil_3`, `ranking_caida`).

### Panel plegable
Chevron que rota, título de una línea con el dato más relevante al lado
("Cómo obtuve esta respuesta · 20 ms"). Cerrado por omisión, salvo el primero de la respuesta.

### Barra de escritura
Fija abajo, centrada, sombra mínima, anillo de foco de 3 px. A su izquierda, hasta tres
sugerencias que aparecen **después** de la primera respuesta, nunca junto al estado inicial
(que ya propone ejemplos).

---

## 7. Estados

Todos los estados tienen texto definido. Si aparece uno nuevo, se escribe aquí antes de
implementarlo.

| Estado | Qué se ve |
|---|---|
| **Inicial** | Título "¿Qué quieres saber hoy?", una línea de contexto y seis preguntas de ejemplo en lenguaje de negocio. Centrado vertical. |
| **Procesando** | El mensaje "Buscando la respuesta…" con el indicador de carga, en el lugar donde aparecerá la respuesta. El botón Enviar queda deshabilitado. |
| **Sin resultados** | "La consulta se ejecutó pero no devolvió filas. Prueba ampliando el periodo o quitando filtros." Sin tabla ni gráfico vacíos. |
| **Ambigüedad** | Mensaje ámbar: "Necesito un poco más de contexto para consultar los datos. No ejecuté SQL todavía", con sugerencias concretas. |
| **Sin relación entre tablas** | Mensaje ámbar con la frase textual "No encontré una relación declarada; puedo mostrar los datos por separado o probar una relación sugerida", más dos botones. |
| **Error de datos** | Texto rojo, sin traza técnica, con qué hacer a continuación. |
| **Datos truncados** | Chip ámbar "primeros registros" en la cabecera de la tabla. |
| **PII protegida** | Chip verde "datos personales protegidos". Nunca una advertencia: es una garantía, no un problema. |
| **Modo demostración** | Insignia ámbar "Demo · al 30 sep 2025". |

---

## 8. Accesibilidad

Requisitos, no recomendaciones:

- **Contraste** mínimo 4.5:1 en texto y 3:1 en bordes de controles. Los tokens de la sección 3
  ya cumplen; cualquier color nuevo se verifica antes.
- **Foco visible** en todo elemento interactivo: anillo de 3 px con `--accent` al 10 %. No
  eliminar `outline` sin reemplazo.
- **Todo accesible por teclado**: Tab recorre en orden lógico; Enter envía; los paneles
  plegables son `<details>` nativos, que ya responden a teclado.
- **La respuesta se anuncia**: la zona de conversación es `aria-live="polite"` para que un
  lector de pantalla lea la respuesta nueva sin perder el foco.
- **El color nunca solo**: una caída se ve en rojo *y* lleva el signo menos; la copia vigente
  es verde *y* dice "copia vigente".
- **Áreas táctiles** de 32 px como mínimo en móvil.
- **Etiquetas reales**: cada control tiene `<label>`, `aria-label` o texto visible. El campo de
  la pregunta no depende solo del `placeholder`.
- **`prefers-reduced-motion`**: sin transiciones ni animación del indicador de carga.

---

## 9. Antes de dar por terminado un cambio de interfaz

1. ¿La primera línea que lee el usuario es la respuesta, no un dato del sistema?
2. ¿Aparece alguna palabra del glosario prohibido en la vista ejecutiva?
3. ¿Los números usan el formato de negocio (`S/ 121.8 M`, `48.1 %`, `jun 2025`)?
4. ¿Funciona a 1280, 768 y 375 px de ancho?
5. ¿Se puede completar la tarea solo con el teclado, y se ve dónde está el foco?
6. ¿Los colores nuevos son tokens existentes?
7. ¿El estado de error y el de vacío tienen texto definido en la sección 7?
8. ¿Pasan `npm run test:unit` y `npx playwright test`?

---

## 10. Qué no hacer

- Ventanas modales. Interrumpen la conversación; todo cabe en el hilo.
- Barras laterales de navegación. Hay una sola pantalla y una de configuración.
- Pestañas dentro del resultado. El orden vertical ya es la jerarquía.
- Un segundo color de acento "para destacar". Si todo destaca, nada destaca.
- Iconografía decorativa junto al texto. El único icono permanente es el chevron de los
  paneles.
- Porcentajes con cuatro decimales, fechas ISO o identificadores internos en la vista
  ejecutiva.
- Mostrar un gráfico cuando el usuario pidió una tabla, o al revés.

---

## 11. Pendientes de diseño

| Tema | Estado |
|---|---|
| **WhatsApp** | La conversación por WhatsApp no tiene tarjetas ni paneles: hay que definir el equivalente en texto plano y decidir qué se envía como imagen o archivo. Base en [docs/WHATSAPP.md](../docs/WHATSAPP.md), sección "Formato de la respuesta". |
| **Historial de conversaciones** | Hoy la sesión vive en memoria. Cuando persista, definir cómo se lista y se retoma sin agregar una barra lateral. |
| **Preguntas de seguimiento** | "¿y sin el canal web?" sobre el resultado anterior: falta decidir cómo se muestra el contexto heredado. |
| **Modo oscuro** | No existe. Si se agrega, los tokens ya están centralizados; falta verificar contraste y el tema de los gráficos. |
| **Densidad alternativa** | Un modo compacto para analistas que miran tablas largas, sin tocar la vista por defecto. |
