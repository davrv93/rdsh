// modulos: /frontend/static/formatos.js, /frontend/static/charts.js, /frontend/static/app.js
//
// Render de la interfaz a partir de respuestas reales de la API, capturadas en
// tests/unit-web/fixtures. Si el backend cambia el contrato, estas pruebas lo
// detectan sin levantar el navegador completo ni el servidor.

const RANKING = cargarFixture('respuesta-ranking.json');
const SERIE = cargarFixture('respuesta-serie.json');
const COMPARACION = cargarFixture('respuesta-comparacion.json');

describe('utilidades de texto', () => {
  it('escapa el HTML que venga en los datos', () => {
    expect(escapar('<img src=x onerror=alert(1)>')).toBe(
      '&lt;img src=x onerror=alert(1)&gt;'
    );
  });

  it('convierte las negritas del resumen', () => {
    expect(marcado('Lidera **Trujillo**')).toBe('Lidera <strong>Trujillo</strong>');
  });

  it('escapa antes de aplicar el marcado, no después', () => {
    expect(marcado('**<b>x</b>**')).toBe('<strong>&lt;b&gt;x&lt;/b&gt;</strong>');
  });

  it('convierte los saltos de línea en <br/>', () => {
    expect(marcado('a\nb')).toBe('a<br/>b');
  });
});

describe('bloque de resultados · ranking', () => {
  let bloque;
  beforeEach(() => {
    estado.experto = false;
    OptimizaFormatos.setMoneda(RANKING.metricas.moneda);
    bloque = construirResultado(RANKING);
  });

  it('titula con el nombre de negocio que envía el backend', () => {
    expect(bloque.querySelector('.resultado-encabezado h2').textContent).toBe(RANKING.titulo);
  });

  it('muestra la etiqueta de intención en palabras', () => {
    expect(bloque.querySelector('.etiqueta-intencion').textContent).toBe(
      RANKING.intencion.etiqueta
    );
  });

  it('arma una tarjeta por indicador', () => {
    expect(bloque.querySelectorAll('.kpis .kpi')).toHaveLength(RANKING.tarjetas_kpi.length);
  });

  it('formatea el indicador principal como moneda abreviada', () => {
    expect(bloque.querySelector('.kpi .valor').textContent).toMatch(/^S\/ [\d.,]+ M$/);
  });

  it('incluye la vista gráfica y la tabla', () => {
    const encabezados = [...bloque.querySelectorAll('.card > header strong')].map((e) => e.textContent);
    expect(encabezados).toContain('Vista gráfica');
    expect(encabezados).toContain('Detalle');
  });

  it('usa las etiquetas legibles de columnas_meta en la tabla', () => {
    const encabezados = [...bloque.querySelectorAll('table.datos thead th')].map((e) => e.textContent);
    expect(encabezados).toContain('Región');
    expect(encabezados).toContain('Ingreso');
    expect(encabezados).notToContain('participacion_acumulada');
  });

  it('dibuja una fila por registro', () => {
    expect(bloque.querySelectorAll('table.datos tbody tr')).toHaveLength(RANKING.filas.length);
  });

  it('ofrece la descarga del resultado', () => {
    expect(bloque.querySelector('.boton-descarga').getAttribute('href')).toMatch(/\.csv$/);
  });

  it('avisa cuando hay datos personales protegidos', () => {
    const conPii = JSON.parse(JSON.stringify(RANKING));
    conPii.pii_enmascarada = ['cliente'];
    expect(construirResultado(conPii).textContent).toContain('datos personales protegidos');
  });
});

describe('bloque de resultados · vista ejecutiva frente a modo experto', () => {
  afterEach(() => { estado.experto = false; });

  it('oculta las columnas técnicas al usuario de negocio', () => {
    estado.experto = false;
    const columnas = [...construirResultado(RANKING).querySelectorAll('table.datos thead th')]
      .map((e) => e.getAttribute('title'));
    expect(columnas).notToContain('participacion_acumulada');
  });

  it('las muestra en modo experto', () => {
    estado.experto = true;
    const columnas = [...construirResultado(RANKING).querySelectorAll('table.datos thead th')]
      .map((e) => e.getAttribute('title'));
    expect(columnas).toContain('participacion_acumulada');
  });

  it('solo agrega los paneles técnicos en modo experto', () => {
    estado.experto = false;
    const ejecutivo = [...construirResultado(RANKING).querySelectorAll('details.panel summary')]
      .map((e) => e.textContent).join(' | ');
    expect(ejecutivo).toContain('Cómo obtuve esta respuesta');
    expect(ejecutivo).notToContain('Detalle técnico');

    estado.experto = true;
    const experto = [...construirResultado(RANKING).querySelectorAll('details.panel summary')]
      .map((e) => e.textContent).join(' | ');
    expect(experto).toContain('Detalle técnico');
    expect(experto).toContain('Contexto semántico');
  });

  it('no filtra datos del motor en el pie del mensaje ejecutivo', () => {
    estado.experto = false;
    const pie = pieDeMensaje(RANKING);
    expect(pie).toContain('respuesta en');
    expect(pie).notToContain('costo IA');

    estado.experto = true;
    expect(pieDeMensaje(RANKING)).toContain('costo IA');
  });
});

describe('bloque de resultados · comparación', () => {
  let bloque;
  beforeEach(() => {
    estado.experto = false;
    bloque = construirResultado(COMPARACION);
  });

  it('marca en rojo los valores negativos de la tabla', () => {
    expect(bloque.querySelectorAll('td.negativo').length > 0).toBeTruthy();
  });

  it('formatea las variaciones como porcentaje', () => {
    const celdas = [...bloque.querySelectorAll('table.datos tbody td')].map((e) => e.textContent);
    expect(celdas.some((t) => /%$/.test(t))).toBeTruthy();
  });
});

describe('panel de pasos', () => {
  it('cuenta los pasos en lenguaje de negocio', () => {
    estado.experto = false;
    const panel = construirResultado(SERIE).querySelector('details.panel');
    expect(panel.textContent).toContain('Entendí tu pregunta');
    expect(panel.textContent).toContain('Consulté');
    expect(panel.textContent).notToContain('clasificador_edge');
  });

  it('usa los nombres técnicos en modo experto', () => {
    estado.experto = true;
    const panel = construirResultado(SERIE).querySelector('details.panel');
    expect(panel.textContent).toContain('Intención');
    estado.experto = false;
  });

  it('muestra un paso por etapa medida', () => {
    const panel = construirResultado(SERIE).querySelector('details.panel');
    expect(panel.querySelectorAll('ol.pasos li')).toHaveLength(SERIE.pasos.length);
  });
});

describe('mensajes del chat', () => {
  beforeEach(() => { document.getElementById('chat-log').innerHTML = ''; });

  it('agrega el mensaje del usuario al hilo', () => {
    agregarMensaje('¿cuánto vendimos?', 'user');
    const mensajes = document.querySelectorAll('#chat-log .msg.user');
    expect(mensajes).toHaveLength(1);
    expect(mensajes[0].textContent).toContain('¿cuánto vendimos?');
  });

  it('nunca inyecta HTML recibido como texto', () => {
    agregarMensaje('<script>window.__hackeado = true;</script>', 'bot');
    expect(window.__hackeado).toBeFalsy();
    expect(document.querySelectorAll('#chat-log script')).toHaveLength(0);
  });

  it('dibuja los botones de las opciones cuando el agente pide confirmación', () => {
    agregarMensaje('No encontré una relación declarada', 'bot warn', '', [
      { accion: 'separado', texto: 'Mostrar por separado' },
    ]);
    const botones = document.querySelectorAll('#chat-log .opciones button');
    expect(botones).toHaveLength(1);
    expect(botones[0].textContent).toBe('Mostrar por separado');
  });
});
