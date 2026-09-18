/**
 * Micro framework de pruebas que corre dentro del navegador.
 *
 * Se carga antes que los specs. Cada spec registra sus casos con describe/it y
 * el runner lee window.__resultado cuando la página termina de cargar.
 *
 * No usa módulos ES a propósito: los archivos del frontend son scripts clásicos
 * y así comparten el mismo ámbito global.
 */
(function () {
  const suites = [];
  let suiteActual = null;

  function describe(nombre, fn) {
    suiteActual = { nombre, casos: [], antes: [], despues: [] };
    suites.push(suiteActual);
    fn();
    suiteActual = null;
  }

  function it(nombre, fn) {
    if (!suiteActual) throw new Error(`it("${nombre}") fuera de un describe`);
    suiteActual.casos.push({ nombre, fn });
  }

  function beforeEach(fn) { suiteActual.antes.push(fn); }
  function afterEach(fn) { suiteActual.despues.push(fn); }

  function formatear(valor) {
    if (typeof valor === 'string') return JSON.stringify(valor);
    if (valor instanceof Element) return `<${valor.tagName.toLowerCase()}>`;
    try { return JSON.stringify(valor); } catch (e) { return String(valor); }
  }

  function expect(actual) {
    const fallo = (mensaje) => { throw new Error(mensaje); };
    return {
      toBe(esperado) {
        if (actual !== esperado) fallo(`esperaba ${formatear(esperado)} y recibí ${formatear(actual)}`);
      },
      toEqual(esperado) {
        const a = JSON.stringify(actual), b = JSON.stringify(esperado);
        if (a !== b) fallo(`esperaba ${b} y recibí ${a}`);
      },
      toContain(fragmento) {
        const contiene = typeof actual === 'string'
          ? actual.includes(fragmento)
          : Array.prototype.includes.call(actual || [], fragmento);
        if (!contiene) fallo(`${formatear(actual)} no contiene ${formatear(fragmento)}`);
      },
      notToContain(fragmento) {
        if (String(actual).includes(fragmento)) fallo(`${formatear(actual)} no debía contener ${formatear(fragmento)}`);
      },
      toMatch(expresion) {
        if (!expresion.test(String(actual))) fallo(`${formatear(actual)} no coincide con ${expresion}`);
      },
      toBeCloseTo(esperado, tolerancia = 0.001) {
        if (Math.abs(Number(actual) - Number(esperado)) > tolerancia) {
          fallo(`esperaba ~${esperado} y recibí ${actual}`);
        }
      },
      toBeTruthy() { if (!actual) fallo(`esperaba un valor verdadero y recibí ${formatear(actual)}`); },
      toBeFalsy() { if (actual) fallo(`esperaba un valor falso y recibí ${formatear(actual)}`); },
      toHaveLength(n) {
        const largo = actual ? actual.length : undefined;
        if (largo !== n) fallo(`esperaba largo ${n} y recibí ${largo}`);
      },
      toThrow(fragmento) {
        let lanzo = false, mensaje = '';
        try { actual(); } catch (e) { lanzo = true; mensaje = e.message; }
        if (!lanzo) fallo('esperaba una excepción y no ocurrió');
        if (fragmento && !mensaje.includes(fragmento)) {
          fallo(`la excepción decía ${formatear(mensaje)} y esperaba ${formatear(fragmento)}`);
        }
      },
    };
  }

  function ejecutar() {
    const salida = { suites: [], total: 0, fallos: 0, ms: 0 };
    const inicio = performance.now();
    for (const suite of suites) {
      const resultadoSuite = { nombre: suite.nombre, casos: [] };
      for (const caso of suite.casos) {
        const t0 = performance.now();
        let estado = 'ok', error = null;
        try {
          suite.antes.forEach((fn) => fn());
          caso.fn();
          suite.despues.forEach((fn) => fn());
        } catch (e) {
          estado = 'fallo';
          error = e && e.message ? e.message : String(e);
          salida.fallos++;
        }
        salida.total++;
        resultadoSuite.casos.push({
          nombre: caso.nombre, estado, error, ms: +(performance.now() - t0).toFixed(3),
        });
      }
      salida.suites.push(resultadoSuite);
    }
    salida.ms = +(performance.now() - inicio).toFixed(2);
    return salida;
  }

  window.describe = describe;
  window.it = it;
  window.beforeEach = beforeEach;
  window.afterEach = afterEach;
  window.expect = expect;
  window.__microtest = { ejecutar, suites };
})();
