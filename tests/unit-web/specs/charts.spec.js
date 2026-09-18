// modulos: /frontend/static/formatos.js, /frontend/static/charts.js
//
// Renderizador de gráficos. En esta página no existe vegaEmbed, así que se
// ejercita el camino de respaldo: el renderizador SVG propio, que es el que
// mantiene la demo funcionando sin acceso al CDN.

const COLUMNAS_RANKING = [
  { nombre: 'region', etiqueta: 'Región', tipo: 'texto' },
  { nombre: 'ingreso', etiqueta: 'Ingreso', tipo: 'moneda' },
];

const FILAS_RANKING = [
  { region: 'Trujillo', ingreso: 21373334 },
  { region: 'Santiago', ingreso: 17997725 },
  { region: 'Bogotá', ingreso: 17133164 },
];

function contenedor() {
  const div = document.createElement('div');
  document.body.appendChild(div);
  return div;
}

describe('gráficos · barras', () => {
  let destino;
  beforeEach(() => {
    OptimizaFormatos.setMoneda('S/');
    destino = contenedor();
    OptimizaCharts.renderGrafico(destino, {
      tipo: 'barras',
      campos: { dimension: 'region', medida: 'ingreso', horizontal: true },
      spec: { mark: 'bar', encoding: {} },
    }, FILAS_RANKING, COLUMNAS_RANKING);
  });
  afterEach(() => destino.remove());

  it('dibuja un SVG', () => {
    expect(destino.querySelectorAll('svg')).toHaveLength(1);
  });

  it('dibuja una barra por fila', () => {
    expect(destino.querySelectorAll('rect')).toHaveLength(FILAS_RANKING.length);
  });

  it('rotula cada barra con su categoría', () => {
    expect(destino.innerHTML).toContain('Trujillo');
    expect(destino.innerHTML).toContain('Santiago');
  });

  it('formatea los valores como moneda, no como número crudo', () => {
    expect(destino.innerHTML).toContain('S/ 21.4 M');
    expect(destino.innerHTML).notToContain('21373334');
  });
});

describe('gráficos · serie temporal', () => {
  let destino;
  const columnas = [
    { nombre: 'periodo', etiqueta: 'Periodo', tipo: 'fecha' },
    { nombre: 'ingreso', etiqueta: 'Ingreso', tipo: 'moneda' },
  ];
  const filas = [
    { periodo: '2025-01-01', ingreso: 4035261 },
    { periodo: '2025-02-01', ingreso: 5721594 },
    { periodo: '2025-03-01', ingreso: 6677034 },
    { periodo: '2025-04-01', ingreso: 8072837 },
  ];

  beforeEach(() => {
    destino = contenedor();
    OptimizaCharts.renderGrafico(destino, {
      tipo: 'linea',
      campos: { x: 'periodo', y: 'ingreso', serie: null },
      spec: { mark: 'line', encoding: {} },
    }, filas, columnas);
  });
  afterEach(() => destino.remove());

  it('traza una polilínea con un punto por periodo', () => {
    const polilinea = destino.querySelector('polyline');
    expect(polilinea).toBeTruthy();
    expect(polilinea.getAttribute('points').trim().split(/\s+/)).toHaveLength(filas.length);
  });

  it('marca cada observación', () => {
    expect(destino.querySelectorAll('circle')).toHaveLength(filas.length);
  });

  it('rotula el eje temporal en español', () => {
    expect(destino.innerHTML).toContain('ene 2025');
  });
});

describe('gráficos · otras formas', () => {
  it('dibuja un arco por categoría en la dona', () => {
    const destino = contenedor();
    OptimizaCharts.renderGrafico(destino, {
      tipo: 'dona',
      campos: { dimension: 'region', medida: 'ingreso' },
      spec: { mark: 'arc', encoding: {} },
    }, FILAS_RANKING, COLUMNAS_RANKING);
    expect(destino.querySelectorAll('path')).toHaveLength(FILAS_RANKING.length);
    destino.remove();
  });

  it('dibuja un punto por observación en la dispersión', () => {
    const destino = contenedor();
    const filas = [{ inversion: 1000, ingreso: 5000 }, { inversion: 2000, ingreso: 9000 }];
    OptimizaCharts.renderGrafico(destino, {
      tipo: 'dispersion',
      campos: { x: 'inversion', y: 'ingreso', color: null },
      spec: { mark: 'point', encoding: {} },
    }, filas, []);
    expect(destino.querySelectorAll('circle')).toHaveLength(filas.length);
    destino.remove();
  });
});

describe('gráficos · casos sin datos', () => {
  it('explica por qué no hay gráfico cuando no hay filas', () => {
    const destino = contenedor();
    OptimizaCharts.renderGrafico(destino, {
      tipo: 'ninguno', motivo: 'El resultado no tiene filas.', spec: null,
    }, [], []);
    expect(destino.textContent).toContain('El resultado no tiene filas.');
    expect(destino.querySelectorAll('svg')).toHaveLength(0);
    destino.remove();
  });

  it('no falla si el visual viene vacío', () => {
    const destino = contenedor();
    OptimizaCharts.renderGrafico(destino, null, [], []);
    expect(destino.textContent).toContain('Sin gráfico');
    destino.remove();
  });
});

describe('gráficos · utilidades', () => {
  it('no agrega decimales a los enteros', () => {
    expect(OptimizaCharts.formatearNumero(7)).toBe('7');
  });

  it('abrevia las magnitudes grandes', () => {
    expect(OptimizaCharts.formatearNumero(2500000)).toBe('2.50 M');
  });

  it('expone una paleta legible sobre fondo claro', () => {
    expect(OptimizaCharts.PALETA.length).toBeCloseTo(7, 0);
    expect(OptimizaCharts.PALETA[0]).toBe('#2563eb');
  });
});
