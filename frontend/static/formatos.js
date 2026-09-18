/** Formateo de números, fechas y etiquetas para usuarios de negocio. */
(function () {
  const MESES = ['ene', 'feb', 'mar', 'abr', 'may', 'jun', 'jul', 'ago', 'sep', 'oct', 'nov', 'dic'];
  let MONEDA = 'S/';

  const nf = (min, max) => new Intl.NumberFormat('es-PE', { minimumFractionDigits: min, maximumFractionDigits: max });

  function setMoneda(simbolo) { if (simbolo) MONEDA = simbolo; }

  function moneda(valor, compacto = true) {
    const v = Number(valor);
    if (!isFinite(v)) return '—';
    const abs = Math.abs(v);
    if (compacto && abs >= 1e9) return `${MONEDA} ${nf(1, 1).format(v / 1e9)} mil M`;
    if (compacto && abs >= 1e6) return `${MONEDA} ${nf(1, 1).format(v / 1e6)} M`;
    if (abs >= 1000) return `${MONEDA} ${nf(0, 0).format(v)}`;
    return `${MONEDA} ${nf(2, 2).format(v)}`;
  }

  function porcentaje(valor) {
    const v = Number(valor);
    if (!isFinite(v)) return '—';
    return `${nf(1, 1).format(v * 100)} %`;
  }

  function entero(valor) {
    const v = Number(valor);
    return isFinite(v) ? nf(0, 0).format(v) : '—';
  }

  function decimal(valor) {
    const v = Number(valor);
    if (!isFinite(v)) return '—';
    const abs = Math.abs(v);
    if (abs >= 1e6) return `${nf(1, 1).format(v / 1e6)} M`;
    if (abs >= 1000) return nf(0, 0).format(v);
    return nf(2, 2).format(v);
  }

  function fecha(valor) {
    if (valor === null || valor === undefined) return '—';
    const texto = String(valor);
    const m = texto.match(/^(\d{4})-(\d{2})-(\d{2})/);
    if (!m) return texto;
    const [, anio, mes, dia] = m;
    const nombre = MESES[Number(mes) - 1];
    return dia === '01' ? `${nombre} ${anio}` : `${Number(dia)} ${nombre} ${anio}`;
  }

  /** Formatea un valor según el tipo semántico entregado por el backend. */
  function valor(v, tipo, opciones = {}) {
    if (v === null || v === undefined || v === '') return '—';
    switch (tipo) {
      case 'moneda': return moneda(v, opciones.compacto !== false);
      case 'porcentaje': return porcentaje(v);
      case 'ratio': return `${nf(2, 2).format(Number(v))}x`;
      case 'entero': return entero(v);
      case 'decimal': return decimal(v);
      case 'fecha': return fecha(v);
      case 'booleano': return v === true ? 'Sí' : v === false ? 'No' : '—';
      default: return String(v);
    }
  }

  function duracion(ms) {
    const v = Number(ms);
    if (!isFinite(v)) return '—';
    if (v < 0.05) return 'instantáneo';
    if (v < 1) return `${nf(2, 2).format(v)} ms`;
    if (v < 1000) return `${nf(0, 0).format(v)} ms`;
    return `${nf(2, 2).format(v / 1000)} s`;
  }

  /** "0,05 segundos" para el titular ejecutivo. */
  function segundos(ms) {
    const v = Number(ms) / 1000;
    if (v < 0.01) return 'menos de una centésima de segundo';
    return `${nf(2, 2).format(v)} segundos`;
  }

  const simbolo = () => MONEDA;

  window.OptimizaFormatos = { setMoneda, simbolo, valor, moneda, porcentaje, entero, decimal, fecha, duracion, segundos };
})();
