/**
 * Renderizador de gráficos.
 * Primero intenta Vega-Lite (CDN). Si no está disponible (sin internet),
 * usa un renderizador SVG propio para que la demo nunca se quede sin gráfico.
 */
(function () {
  const PALETA = ['#2563eb', '#0f8a5f', '#c2870b', '#d33b3b', '#7c5cd6', '#0d9dd6', '#d9538f'];
  const COLOR_EJE = '#767d8a';
  const COLOR_GRILLA = '#eef0f3';

  // Ejes y tooltips en español: sin esto Vega rotula los meses en inglés.
  const LOCALE_TIEMPO = {
    dateTime: '%A, %e de %B de %Y, %X',
    date: '%d/%m/%Y',
    time: '%H:%M:%S',
    periods: ['AM', 'PM'],
    days: ['domingo', 'lunes', 'martes', 'miércoles', 'jueves', 'viernes', 'sábado'],
    shortDays: ['dom', 'lun', 'mar', 'mié', 'jue', 'vie', 'sáb'],
    months: ['enero', 'febrero', 'marzo', 'abril', 'mayo', 'junio', 'julio', 'agosto',
             'septiembre', 'octubre', 'noviembre', 'diciembre'],
    shortMonths: ['ene', 'feb', 'mar', 'abr', 'may', 'jun', 'jul', 'ago', 'sep', 'oct', 'nov', 'dic'],
  };
  // Mismo criterio que Intl es-PE en tablas y tarjetas: punto decimal, coma de miles.
  const LOCALE_NUMERO = { decimal: '.', thousands: ',', grouping: [3], currency: ['', ''] };

  function aplicarLocale() {
    if (!window.vega || aplicarLocale.hecho) return;
    try {
      window.vega.timeFormatLocale(LOCALE_TIEMPO);
      window.vega.formatLocale(LOCALE_NUMERO);
      aplicarLocale.hecho = true;
    } catch (e) { /* si falla, Vega usa su locale por defecto */ }
  }

  function formatearNumero(valor) {
    if (valor === null || valor === undefined || Number.isNaN(valor)) return '—';
    const abs = Math.abs(valor);
    if (abs >= 1e9) return (valor / 1e9).toFixed(2) + ' MM';
    if (abs >= 1e6) return (valor / 1e6).toFixed(2) + ' M';
    if (abs >= 1e3) return (valor / 1e3).toFixed(1) + ' k';
    if (abs < 1 && abs > 0) return valor.toFixed(3);
    if (Number.isInteger(valor)) return String(valor);
    return valor.toFixed(2);
  }

  /** Formato Vega-Lite y título legible según el tipo semántico de la columna. */
  function infoColumna(columnasMeta, nombre) {
    const meta = (columnasMeta || []).find((c) => c.nombre === nombre);
    if (!meta) return { etiqueta: nombre, formato: null };
    const formato = meta.tipo === 'porcentaje' ? '.1%'
      : meta.tipo === 'moneda' ? ',.0f'
      : meta.tipo === 'entero' ? ',.0f'
      : meta.tipo === 'ratio' ? ',.2f'
      : null;
    return { etiqueta: meta.etiqueta, formato, tipo: meta.tipo };
  }

  function aplicarEtiquetas(spec, columnasMeta) {
    if (!columnasMeta || !spec.encoding) return spec;
    ['x', 'y', 'color', 'theta'].forEach((canal) => {
      const enc = spec.encoding[canal];
      if (enc && enc.field) {
        const info = infoColumna(columnasMeta, enc.field);
        enc.title = info.etiqueta;
        if (enc.type === 'quantitative') {
          // Pocos rótulos: en fondo claro y ancho reducido, muchos ticks se pisan
          const eje = Object.assign({ tickCount: 4, labelOverlap: 'greedy' }, enc.axis || {});
          if (info.tipo === 'moneda') {
            // Etiquetas cortas con símbolo: "S/ 9M" en lugar de "9,000,000"
            eje.labelExpr = `'${(window.OptimizaFormatos && window.OptimizaFormatos.simbolo()) || 'S/'} ' + format(datum.value, '~s')`;
          } else if (info.formato) {
            eje.format = info.formato;
          }
          enc.axis = eje;
        }
        if (enc.type === 'temporal') {
          enc.axis = Object.assign({ format: '%b %Y', labelAngle: 0, tickCount: 6 }, enc.axis || {});
        }
      }
    });
    if (Array.isArray(spec.encoding.tooltip)) {
      spec.encoding.tooltip = spec.encoding.tooltip.map((t) => {
        const info = infoColumna(columnasMeta, t.field);
        return Object.assign({}, t, { title: info.etiqueta },
          info.formato && t.type === 'quantitative' ? { format: info.formato } : {});
      });
    }
    return spec;
  }

  function renderGrafico(contenedor, visual, filas, columnasMeta) {
    contenedor.innerHTML = '';
    if (!visual || !visual.spec || !filas.length) {
      contenedor.innerHTML = `<div style="color:var(--muted);font-size:12.5px;padding:14px">${
        (visual && visual.motivo) || 'Sin gráfico para este resultado.'}</div>`;
      return;
    }
    aplicarLocale();
    const spec = aplicarEtiquetas(JSON.parse(JSON.stringify(visual.spec)), columnasMeta);
    spec.data = { values: filas };
    spec.width = 'container';
    spec.height = Math.min(300, Math.max(210, (filas.length <= 8 ? 210 : 260)));
    spec.background = 'transparent';
    spec.config = {
      font: 'Inter, system-ui, sans-serif',
      axis: {
        labelColor: COLOR_EJE, titleColor: COLOR_EJE, gridColor: COLOR_GRILLA,
        domainColor: COLOR_GRILLA, tickColor: COLOR_GRILLA, labelFontSize: 10.5,
        titleFontSize: 11, titleFontWeight: 500, titlePadding: 8,
      },
      legend: { labelColor: COLOR_EJE, titleColor: COLOR_EJE, labelFontSize: 10.5, titleFontSize: 11 },
      view: { stroke: 'transparent' },
      range: { category: PALETA },
      mark: { color: PALETA[0] },
    };
    if (window.vegaEmbed) {
      window.vegaEmbed(contenedor, spec, { actions: false, renderer: 'svg' })
        .catch(() => renderFallback(contenedor, visual, filas, columnasMeta));
    } else {
      renderFallback(contenedor, visual, filas, columnasMeta);
    }
  }

  /** Renderizador SVG mínimo: barras, líneas, dona y dispersión. */
  function renderFallback(contenedor, visual, filas, columnasMeta) {
    const campos = visual.campos || {};
    const fmt = (v, campo) => {
      const info = infoColumna(columnasMeta, campo);
      return window.OptimizaFormatos
        ? window.OptimizaFormatos.valor(v, info.tipo || 'decimal')
        : formatearNumero(v);
    };
    const ancho = contenedor.clientWidth || 700;
    const alto = 260;
    const margen = { top: 16, right: 20, bottom: 46, left: 78 };
    const w = ancho - margen.left - margen.right;
    const h = alto - margen.top - margen.bottom;
    const svg = (contenido) =>
      `<svg viewBox="0 0 ${ancho} ${alto}" width="100%" height="${alto}" font-family="system-ui" font-size="11">${contenido}</svg>`;
    const eje = (x1, y1, x2, y2) => `<line x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}" stroke="#e6e8ec"/>`;

    if (visual.tipo === 'barras') {
      const dim = campos.dimension, medida = campos.medida;
      const datos = filas.slice(0, 15);
      const max = Math.max(...datos.map((d) => Math.abs(Number(d[medida]) || 0))) || 1;
      const paso = h / datos.length;
      const barras = datos.map((d, i) => {
        const valor = Number(d[medida]) || 0;
        const largo = (Math.abs(valor) / max) * w;
        const y = margen.top + i * paso + paso * 0.15;
        const alturaBarra = paso * 0.7;
        const color = valor < 0 ? '#d33b3b' : PALETA[0];
        const etiqueta = String(d[dim]).slice(0, 22);
        return `<rect x="${margen.left}" y="${y}" width="${largo}" height="${alturaBarra}" fill="${color}" rx="3"/>
          <text x="${margen.left - 6}" y="${y + alturaBarra / 2 + 4}" text-anchor="end" fill="#767d8a">${etiqueta}</text>
          <text x="${margen.left + largo + 6}" y="${y + alturaBarra / 2 + 4}" fill="#16191f">${fmt(valor, medida)}</text>`;
      }).join('');
      contenedor.innerHTML = svg(eje(margen.left, margen.top, margen.left, margen.top + h) + barras);
      return;
    }

    if (visual.tipo === 'linea') {
      const x = campos.x, y = campos.y;
      const datos = filas.filter((d) => d[y] !== null);
      const valores = datos.map((d) => Number(d[y]) || 0);
      const max = Math.max(...valores), min = Math.min(0, ...valores);
      const px = (i) => margen.left + (i / Math.max(1, datos.length - 1)) * w;
      const py = (v) => margen.top + h - ((v - min) / ((max - min) || 1)) * h;
      const puntos = datos.map((d, i) => `${px(i)},${py(Number(d[y]) || 0)}`).join(' ');
      const marcas = datos.map((d, i) => `<circle cx="${px(i)}" cy="${py(Number(d[y]) || 0)}" r="3" fill="${PALETA[0]}"/>`).join('');
      const etiquetas = datos.filter((_, i) => i % Math.ceil(datos.length / 6) === 0)
        .map((d, k) => {
          const i = k * Math.ceil(datos.length / 6);
          const etiquetaX = window.OptimizaFormatos ? window.OptimizaFormatos.fecha(d[x]) : String(d[x]).slice(0, 10);
          return `<text x="${px(i)}" y="${alto - 18}" text-anchor="middle" fill="#767d8a">${etiquetaX}</text>`;
        }).join('');
      contenedor.innerHTML = svg(
        eje(margen.left, margen.top, margen.left, margen.top + h) +
        eje(margen.left, margen.top + h, margen.left + w, margen.top + h) +
        `<text x="${margen.left - 8}" y="${py(max)}" text-anchor="end" fill="#767d8a">${fmt(max, y)}</text>` +
        `<polyline points="${puntos}" fill="none" stroke="${PALETA[0]}" stroke-width="2"/>` + marcas + etiquetas);
      return;
    }

    if (visual.tipo === 'dona') {
      const dim = campos.dimension, medida = campos.medida;
      const total = filas.reduce((a, d) => a + (Number(d[medida]) || 0), 0) || 1;
      const cx = ancho / 2, cy = alto / 2, r = 110, ri = 60;
      let angulo = -Math.PI / 2;
      const arcos = filas.map((d, i) => {
        const porcion = ((Number(d[medida]) || 0) / total) * Math.PI * 2;
        const fin = angulo + porcion;
        const grande = porcion > Math.PI ? 1 : 0;
        const p = [cx + r * Math.cos(angulo), cy + r * Math.sin(angulo), cx + r * Math.cos(fin), cy + r * Math.sin(fin),
                   cx + ri * Math.cos(fin), cy + ri * Math.sin(fin), cx + ri * Math.cos(angulo), cy + ri * Math.sin(angulo)];
        const path = `M${p[0]},${p[1]} A${r},${r} 0 ${grande} 1 ${p[2]},${p[3]} L${p[4]},${p[5]} A${ri},${ri} 0 ${grande} 0 ${p[6]},${p[7]} Z`;
        const etiqueta = `<text x="${cx + (r + 16) * Math.cos((angulo + fin) / 2)}" y="${cy + (r + 16) * Math.sin((angulo + fin) / 2)}" text-anchor="middle" fill="#767d8a">${String(d[dim]).slice(0, 14)}</text>`;
        angulo = fin;
        return `<path d="${path}" fill="${PALETA[i % PALETA.length]}"/>${etiqueta}`;
      }).join('');
      contenedor.innerHTML = svg(arcos);
      return;
    }

    const x = campos.x, y = campos.y;
    const xs = filas.map((d) => Number(d[x]) || 0), ys = filas.map((d) => Number(d[y]) || 0);
    const maxX = Math.max(...xs) || 1, maxY = Math.max(...ys) || 1;
    const puntos = filas.map((d) =>
      `<circle cx="${margen.left + ((Number(d[x]) || 0) / maxX) * w}" cy="${margen.top + h - ((Number(d[y]) || 0) / maxY) * h}" r="4" fill="${PALETA[0]}" opacity=".8"/>`).join('');
    contenedor.innerHTML = svg(
      eje(margen.left, margen.top, margen.left, margen.top + h) +
      eje(margen.left, margen.top + h, margen.left + w, margen.top + h) + puntos);
  }

    window.OptimizaCharts = { renderGrafico, formatearNumero, PALETA };
})();
