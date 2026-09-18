// modulos: /frontend/static/formatos.js
//
// Formatos que ve el usuario de negocio: moneda, porcentajes, fechas y tiempos.

describe('formatos · moneda', () => {
  beforeEach(() => OptimizaFormatos.setMoneda('S/'));

  it('abrevia los millones', () => {
    expect(OptimizaFormatos.moneda(121847301.66)).toBe('S/ 121.8 M');
  });

  it('abrevia los miles de millones', () => {
    expect(OptimizaFormatos.moneda(2400000000)).toBe('S/ 2.4 mil M');
  });

  it('usa separador de miles sin decimales entre mil y un millón', () => {
    expect(OptimizaFormatos.moneda(8825050.55, false)).toBe('S/ 8,825,051');
  });

  it('mantiene dos decimales por debajo de mil', () => {
    expect(OptimizaFormatos.moneda(12.5)).toBe('S/ 12.50');
  });

  it('respeta el símbolo configurado por el backend', () => {
    OptimizaFormatos.setMoneda('$');
    expect(OptimizaFormatos.moneda(1500000)).toBe('$ 1.5 M');
  });

  it('devuelve un guion ante un valor no numérico', () => {
    expect(OptimizaFormatos.moneda('sin dato')).toBe('—');
  });
});

describe('formatos · porcentajes y razones', () => {
  it('convierte la proporción a porcentaje con un decimal', () => {
    expect(OptimizaFormatos.porcentaje(0.1751)).toBe('17.5 %');
  });

  it('conserva el signo en las caídas', () => {
    expect(OptimizaFormatos.porcentaje(-0.834)).toBe('-83.4 %');
  });

  it('formatea las razones con la x al final', () => {
    expect(OptimizaFormatos.valor(301.5057, 'ratio')).toBe('301.51x');
  });
});

describe('formatos · enteros y decimales', () => {
  it('separa los miles de los enteros', () => {
    expect(OptimizaFormatos.entero(40000)).toBe('40,000');
  });

  it('abrevia los decimales grandes', () => {
    expect(OptimizaFormatos.decimal(2725251.31)).toBe('2.7 M');
  });

  it('no abrevia por debajo de mil', () => {
    expect(OptimizaFormatos.decimal(12.345)).toBe('12.35');
  });
});

describe('formatos · fechas', () => {
  it('muestra mes y año cuando el día es el primero', () => {
    expect(OptimizaFormatos.fecha('2025-06-01')).toBe('jun 2025');
  });

  it('muestra el día cuando no es el primero', () => {
    expect(OptimizaFormatos.fecha('2025-09-30')).toBe('30 sep 2025');
  });

  it('devuelve el texto original si no es una fecha', () => {
    expect(OptimizaFormatos.fecha('Trujillo')).toBe('Trujillo');
  });

  it('tolera valores nulos', () => {
    expect(OptimizaFormatos.fecha(null)).toBe('—');
  });
});

describe('formatos · tiempos', () => {
  it('llama instantáneo a lo que baja de una décima de milisegundo', () => {
    expect(OptimizaFormatos.duracion(0.02)).toBe('instantáneo');
  });

  it('usa dos decimales por debajo del milisegundo', () => {
    expect(OptimizaFormatos.duracion(0.23)).toBe('0.23 ms');
  });

  it('redondea los milisegundos', () => {
    expect(OptimizaFormatos.duracion(21.7)).toBe('22 ms');
  });

  it('pasa a segundos por encima de mil milisegundos', () => {
    expect(OptimizaFormatos.duracion(2500)).toBe('2.50 s');
  });

  it('describe en palabras los tiempos muy cortos', () => {
    expect(OptimizaFormatos.segundos(5)).toBe('menos de una centésima de segundo');
  });
});

describe('formatos · despacho por tipo semántico', () => {
  beforeEach(() => OptimizaFormatos.setMoneda('S/'));

  it('aplica el formato que declara el backend en columnas_meta', () => {
    expect(OptimizaFormatos.valor(1500000, 'moneda')).toBe('S/ 1.5 M');
    expect(OptimizaFormatos.valor(0.121, 'porcentaje')).toBe('12.1 %');
    expect(OptimizaFormatos.valor(3, 'entero')).toBe('3');
    expect(OptimizaFormatos.valor('2025-06-01', 'fecha')).toBe('jun 2025');
    expect(OptimizaFormatos.valor('Lima', 'texto')).toBe('Lima');
  });

  it('traduce los booleanos', () => {
    expect(OptimizaFormatos.valor(true, 'booleano')).toBe('Sí');
    expect(OptimizaFormatos.valor(false, 'booleano')).toBe('No');
  });

  it('muestra un guion ante valores ausentes, sea cual sea el tipo', () => {
    expect(OptimizaFormatos.valor(null, 'moneda')).toBe('—');
    expect(OptimizaFormatos.valor(undefined, 'porcentaje')).toBe('—');
    expect(OptimizaFormatos.valor('', 'texto')).toBe('—');
  });

  it('permite pedir el monto completo en las tablas', () => {
    expect(OptimizaFormatos.valor(3007587.4, 'moneda', { compacto: false })).toBe('S/ 3,007,587');
  });
});
