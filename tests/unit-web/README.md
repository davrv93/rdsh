# Motor de pruebas unitarias del frontend

Ejecuta los módulos de `frontend/static/` dentro de un navegador real, pero sin motor
gráfico: [Lightpanda](https://lightpanda.io). Arranca en milisegundos y consume una fracción
de la memoria de Chromium, así que cada archivo de pruebas corre en una página nueva y
aislada sin penalización.

```bash
npm run lightpanda:install     # descarga el binario en ./bin (una sola vez)
npm run test:unit              # 64 casos en ~60 ms
npm run test:unit formatos     # solo los specs cuyo nombre contenga "formatos"
npm run test:unit:chromium     # el mismo suite contra Chromium, para contrastar
npm run test:unit:json         # salida JSON para CI
```

Sin instalar nada localmente:

```bash
docker compose --profile test up -d lightpanda
docker compose --profile test run --rm unit-web
```

## Qué cubre

| Spec | Cubre |
|---|---|
| `formatos.spec.js` | Moneda, porcentajes, enteros, fechas y duraciones tal como los ve el usuario |
| `charts.spec.js` | El renderizador SVG de respaldo: barras, líneas, dona, dispersión y casos sin datos |
| `app-render.spec.js` | El render completo del bloque de resultados a partir de respuestas reales de la API |

Los fixtures de `fixtures/` son respuestas capturadas de `/api/preguntar`. Si el backend
cambia el contrato (nombres de campos, `columnas_meta`, pasos), estas pruebas lo detectan sin
levantar el navegador completo ni el servidor.

## Cómo está armado

```
runner.mjs      orquesta: levanta el servidor, abre una página por spec y reporta
navegador.mjs   capa de navegador: Lightpanda por CDP, Chromium como respaldo
servidor.mjs    sirve el repositorio y genera fixtures.js al vuelo
harness.html    página de pruebas con el DOM mínimo que esperan los módulos
microtest.js    describe / it / expect, corriendo dentro del navegador
dobles.js       fetch simulado con respuestas de la API
```

Cada spec declara en su primera línea qué módulos cargar antes:

```js
// modulos: /frontend/static/formatos.js, /frontend/static/charts.js
```

## Escribir una prueba

```js
// modulos: /frontend/static/formatos.js

describe('formatos · moneda', () => {
  it('abrevia los millones', () => {
    expect(OptimizaFormatos.moneda(121847301.66)).toBe('S/ 121.8 M');
  });
});
```

Aserciones disponibles: `toBe`, `toEqual`, `toContain`, `notToContain`, `toMatch`,
`toBeCloseTo`, `toBeTruthy`, `toBeFalsy`, `toHaveLength`, `toThrow`. Hay `beforeEach` y
`afterEach` por suite.

Como los archivos del frontend son scripts clásicos, las funciones internas de `app.js`
(`escapar`, `construirResultado`, `pieDeMensaje`…) son visibles desde los specs sin exportarlas
ni modificar el código de producción.

## Variables de entorno

| Variable | Para qué |
|---|---|
| `LIGHTPANDA_BIN` | Ruta a un binario de Lightpanda fuera de `./bin` |
| `LIGHTPANDA_WS` | Conectarse a un servidor CDP ya levantado, por ejemplo `ws://127.0.0.1:9222` |
| `MOTOR_PRUEBAS` | `lightpanda`, `chromium` o `auto` (por defecto) |
| `TEST_BIND` / `TEST_HOST` | Interfaz donde escucha el servidor y dirección que se anuncia al navegador |
| `LIGHTPANDA_DEBUG` | Muestra el log del navegador |

## Límites conocidos

- Lightpanda no tiene motor gráfico: no hay capturas de pantalla ni medidas de layout
  (`clientWidth` devuelve 0). Las pruebas que dependen de píxeles van en Playwright.
- Es un proyecto en desarrollo activo: si una API del navegador falta, el mismo suite corre
  con `MOTOR_PRUEBAS=chromium` para descartar que el fallo sea del código propio.
- El runner usa un binario `nightly`; conviene fijar la versión cuando el proyecto publique
  releases estables.
