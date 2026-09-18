/**
 * Optimiza Conversacional — interfaz de chat.
 *
 * Una sola columna: cada turno del usuario va seguido de la respuesta y, debajo,
 * el bloque de resultados (indicadores, gráfico, tabla y paneles plegables).
 *
 * Dos modos:
 *  - Ejecutivo (por defecto): lenguaje de negocio, sin SQL ni jerga.
 *  - Experto: agrega SQL, validación, transformación, contexto y tokens.
 */
const F = window.OptimizaFormatos;
const Charts = window.OptimizaCharts;

const estado = {
  sessionId: localStorage.getItem('optimiza_session') || crypto.randomUUID(),
  experto: localStorage.getItem('optimiza_experto') === 'true',
  ultimaRespuesta: null,
  ultimoBloque: null,
};
localStorage.setItem('optimiza_session', estado.sessionId);

const $ = (sel) => document.querySelector(sel);
const chatLog = $('#chat-log');

const escapar = (t) => String(t).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
const marcado = (t) => escapar(t)
  .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
  .replace(/`(.+?)`/g, '<code>$1</code>')
  .replace(/\n/g, '<br/>');

function irAlFinal() {
  window.scrollTo({ top: document.body.scrollHeight, behavior: 'smooth' });
}

/** Deja el turno recién enviado en la parte superior, como en un chat. */
function anclarTurno(elemento) {
  if (!elemento) return;
  const margen = 68;
  const destino = elemento.getBoundingClientRect().top + window.scrollY - margen;
  window.scrollTo({ top: Math.max(0, destino), behavior: 'smooth' });
}

// ---------------------------------------------------------------- chat
function agregarMensaje(texto, clase = 'bot', pie = '', opciones = []) {
  const div = document.createElement('div');
  div.className = `msg ${clase}`;
  div.innerHTML = marcado(texto) + (pie ? `<div class="meta">${pie}</div>` : '');
  if (opciones.length) {
    const cont = document.createElement('div');
    cont.className = 'opciones';
    opciones.forEach((op) => {
      const b = document.createElement('button');
      b.textContent = op.texto;
      b.onclick = () => manejarOpcion(op);
      cont.appendChild(b);
    });
    div.appendChild(cont);
  }
  chatLog.appendChild(div);
  irAlFinal();
  return div;
}

async function manejarOpcion(op) {
  if (op.accion === 'separado') {
    await fetch('/api/relacion/confirmar', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ session_id: estado.sessionId, aceptar: false }),
    });
    agregarMensaje('De acuerdo. Pídeme cada tabla por separado y te muestro ambas.', 'bot');
    return;
  }
  if (op.accion === 'probar_relacion') {
    const r = await fetch('/api/relacion/confirmar', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ session_id: estado.sessionId, aceptar: true, declarar: true }),
    }).then((x) => x.json());
    agregarMensaje(r.mensaje, 'bot');
  }
}

async function preguntar(texto) {
  const empty = $('#empty');
  if (empty) empty.remove();
  chatLog.classList.remove('vacio');

  const turno = agregarMensaje(texto, 'user');
  const boton = $('#enviar');
  boton.disabled = true;
  const cargando = agregarMensaje('<span class="spinner"></span> Buscando la respuesta…', 'bot');
  try {
    const respuesta = await fetch('/api/preguntar', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ pregunta: texto, session_id: estado.sessionId }),
    });
    const data = await respuesta.json();
    cargando.remove();
    if (!respuesta.ok) {
      agregarMensaje('No pude completar la consulta. Vuelve a intentarlo o reformula la pregunta.', 'bot error');
      return;
    }
    estado.ultimaRespuesta = data;
    F.setMoneda(data.metricas.moneda);

    const clase = data.estado === 'error' ? 'bot error'
      : (data.estado === 'necesita_confirmacion' || data.estado === 'aclaracion') ? 'bot warn' : 'bot';
    agregarMensaje(data.respuesta, clase, pieDeMensaje(data), data.opciones || []);

    $('#badge-intencion').textContent = data.intencion.etiqueta;
    $('#badge-intencion').title = `Intención técnica: ${data.intencion.intent} · confianza ${(data.intencion.confidence * 100).toFixed(0)} %`;

    if (data.filas.length || data.sql) {
      const bloque = construirResultado(data);
      chatLog.appendChild(bloque);
      estado.ultimoBloque = bloque;
    }
    mostrarSugerencias(true);
    anclarTurno(turno);
  } catch (err) {
    cargando.remove();
    agregarMensaje('No pude conectarme al servicio. Revisa que la aplicación siga encendida.', 'bot error');
  } finally {
    boton.disabled = false;
  }
}

function pieDeMensaje(data) {
  const m = data.metricas;
  const base = [`<span class="chip">respuesta en ${F.duracion(m.latencia_total_ms)}</span>`];
  if (estado.experto) {
    base.push(`<span class="chip">intención: ${escapar(data.intencion.intent)} (${(data.intencion.confidence * 100).toFixed(0)} %)</span>`);
    base.push(`<span class="chip">clasificador: ${F.duracion(m.latencia_clasificador_ms)}</span>`);
    base.push(`<span class="chip ${m.modo_demo ? 'warn' : 'ok'}">${escapar(m.fuente)}</span>`);
    base.push(`<span class="chip">costo IA: ${m.costo_llm_usd.toFixed(6)} USD</span>`);
  }
  return base.join(' ');
}

// ------------------------------------------------------------ resultados
function construirResultado(data) {
  const bloque = document.createElement('div');
  bloque.className = 'resultado';
  bloque.id = 'results';

  bloque.appendChild(encabezadoResultado(data));
  if (data.tarjetas_kpi && data.tarjetas_kpi.length) bloque.appendChild(tarjetasKpi(data));
  if (data.grafico && data.grafico.spec && data.filas.length) bloque.appendChild(tarjetaGrafico(data));
  if (data.filas.length) bloque.appendChild(tarjetaTabla(data));
  bloque.appendChild(panelComoLoHice(data));
  if (estado.experto) {
    if (data.sql) bloque.appendChild(panelTecnico(data));
    bloque.appendChild(panelContexto(data));
    bloque.appendChild(panelComparativa());
  }
  return bloque;
}

function repintarUltimoResultado() {
  if (!estado.ultimaRespuesta || !estado.ultimoBloque) return;
  const nuevo = construirResultado(estado.ultimaRespuesta);
  estado.ultimoBloque.replaceWith(nuevo);
  estado.ultimoBloque = nuevo;
}

function encabezadoResultado(data) {
  const div = document.createElement('div');
  div.className = 'resultado-encabezado';
  const m = data.metricas;
  const fuente = {
    duckdb_demo: `datos de demostración al ${F.fecha(m.fecha_datos)}`,
    duckdb_cache: 'copia local del almacén',
    redshift: 'consultado en el almacén',
  }[m.fuente] || m.fuente;
  div.innerHTML = `
    <h2>${escapar(data.titulo || 'Resultado')}</h2>
    <p>${data.total_filas} ${data.total_filas === 1 ? 'registro' : 'registros'} · ${escapar(fuente)}</p>
    <span class="etiqueta-intencion">${escapar(data.intencion.etiqueta)}</span>`;
  return div;
}

function tarjetasKpi(data) {
  const cont = document.createElement('div');
  cont.className = 'kpis';
  cont.innerHTML = data.tarjetas_kpi.map((k) => {
    const principal = F.valor(k.valor, k.formato);
    const negativo = typeof k.detalle === 'number' && k.detalle < 0 ? ' negativo' : '';
    const detalle = k.detalle !== undefined && k.detalle !== null
      ? `<div class="detalle${negativo}">${F.valor(k.detalle, k.formato_detalle || 'decimal')}</div>` : '';
    return `<div class="kpi"><div class="label">${escapar(k.label)}</div>
      <div class="valor">${escapar(principal)}</div>${detalle}</div>`;
  }).join('');
  return cont;
}

function tarjetaGrafico(data) {
  const card = document.createElement('div');
  card.className = 'card';
  const nota = estado.experto ? `<span class="chip" style="margin-left:auto">${escapar(data.grafico.motivo || '')}</span>` : '';
  card.innerHTML = `<header><strong>Vista gráfica</strong>${nota}</header>
    <div class="body"><div class="grafico" id="grafico"></div></div>`;
  setTimeout(() => Charts.renderGrafico(card.querySelector('.grafico'), data.grafico, data.filas, data.columnas_meta), 0);
  return card;
}

function tarjetaTabla(data) {
  const card = document.createElement('div');
  card.className = 'card';
  const meta = {};
  (data.columnas_meta || []).forEach((c) => { meta[c.nombre] = c; });
  const columnas = estado.experto
    ? data.columnas
    : data.columnas.filter((c) => !/^(participacion_acumulada|media_movil_3|ventas_contadas|ventas_atribuidas|ranking_caida)$/.test(c));

  const encabezado = columnas.map((c) => {
    const info = meta[c] || { etiqueta: c, tipo: 'texto' };
    const alineado = ['texto', 'fecha', 'booleano'].includes(info.tipo) ? '' : ' class="num"';
    return `<th${alineado} title="${escapar(c)}">${escapar(info.etiqueta)}</th>`;
  }).join('');

  const cuerpo = data.filas.slice(0, 200).map((f) => `<tr>${columnas.map((c) => {
    const info = meta[c] || { tipo: 'texto' };
    const numerico = !['texto', 'fecha', 'booleano'].includes(info.tipo);
    const texto = F.valor(f[c], info.tipo, { compacto: false });
    const negativo = numerico && Number(f[c]) < 0 ? ' negativo' : '';
    const clase = (numerico ? 'num' : '') + negativo;
    return `<td${clase ? ` class="${clase}"` : ''}>${escapar(texto)}</td>`;
  }).join('')}</tr>`).join('');

  const avisos = [];
  if (data.truncado) avisos.push('<span class="chip warn">primeros registros</span>');
  if (data.pii_enmascarada.length) avisos.push('<span class="chip ok">datos personales protegidos</span>');

  const urlCsv = (data.exportacion && data.exportacion.url) || `/api/export/${estado.sessionId}.csv`;
  card.innerHTML = `<header><strong>Detalle</strong>
      <span class="chip">${data.total_filas} ${data.total_filas === 1 ? 'registro' : 'registros'}</span>
      ${avisos.join(' ')}
      <a class="boton-descarga" href="${urlCsv}">Descargar</a></header>
    <div class="body tight"><div class="tabla-scroll"><table class="datos">
      <thead><tr>${encabezado}</tr></thead><tbody>${cuerpo}</tbody></table></div></div>`;
  return card;
}

function panelComoLoHice(data) {
  const det = document.createElement('details');
  det.className = 'panel';
  const total = data.metricas.latencia_total_ms;
  const pasos = data.pasos.map((p) => {
    const ancho = Math.max(2, (p.ms / Math.max(total, 1)) * 100);
    return `<li>
      <span class="nombre">${escapar(p.titulo || p.nombre)}</span>
      <span class="detalle">${escapar(estado.experto ? p.detalle : (p.descripcion || p.detalle))}
        <div class="barra-tiempo" style="width:${ancho}%"></div></span>
      <span class="ms">${F.duracion(p.ms)}</span></li>`;
  }).join('');
  det.innerHTML = `<summary>Cómo obtuve esta respuesta · ${F.duracion(total)}</summary>
    <div class="body">
      <ol class="pasos">${pasos}</ol>
      <div class="nota-confianza">Consulta de solo lectura, con límite de registros y datos personales ocultos.</div>
    </div>`;
  return det;
}

function panelTecnico(data) {
  const det = document.createElement('details');
  det.className = 'panel';
  const v = data.validacion || {};
  const avisos = (v.advertencias || []).map((a) => `<span class="chip warn">${escapar(a)}</span>`).join(' ');
  det.innerHTML = `<summary>Detalle técnico: consulta, validación y transformación</summary>
    <div class="body">
      <div class="nota">${marcado(data.respuesta_tecnica || data.explicacion_plan || '')}</div>
      <pre class="sql">${escapar(data.sql)}</pre>
      <div class="chips" style="margin:8px 0">
        <span class="chip ${v.ok ? 'ok' : 'warn'}">validación: ${v.ok ? 'OK' : 'rechazada'}</span>
        <span class="chip">riesgo de escaneo: ${escapar(v.riesgo_full_scan || '—')}</span>
        <span class="chip">filas estimadas: ${v.filas_estimadas ?? '—'}</span>
        <span class="chip">límite: ${v.limite_aplicado ?? '—'}</span>
        <span class="chip">origen del SQL: ${escapar(data.metricas.origen_sql)}</span>
        <span class="chip">tokens: ${data.metricas.tokens.input} / ${data.metricas.tokens.output}</span>
        ${avisos}
      </div>
      ${data.transformacion_duckdb ? `<div class="nota">Transformación ejecutada en DuckDB sobre el resultado:</div>
        <pre class="sql">${escapar(data.transformacion_duckdb)}</pre>` : ''}
    </div>`;
  return det;
}

function panelContexto(data) {
  const det = document.createElement('details');
  det.className = 'panel';
  const filas = (data.contexto_semantico || []).map((c) =>
    `<li><span class="nombre">${escapar(c.tipo)}</span>
      <span class="detalle">${escapar(c.texto)}</span>
      <span class="ms">${c.score.toFixed(3)}</span></li>`).join('');
  det.innerHTML = `<summary>Contexto semántico recuperado (RAG sobre metadata)</summary>
    <div class="body"><ol class="pasos">${filas || '<li>Sin contexto</li>'}</ol></div>`;
  return det;
}

function panelComparativa() {
  const det = document.createElement('details');
  det.className = 'panel comparativa';
  det.innerHTML = '<summary>Antes y ahora: reporte nocturno vs pregunta directa</summary><div class="body">Cargando…</div>';
  fetch('/api/comparativa').then((r) => r.json()).then((c) => {
    const t = c.tradicional, v = c.conversacional;
    const horas = Math.floor(t.duracion_total_minutos / 60);
    const minutos = t.duracion_total_minutos % 60;
    det.querySelector('.body').innerHTML = `
      <div class="grid-2">
        <div>
          <h4>Proceso nocturno actual</h4>
          <div class="total lento">${horas} h ${minutos} min por corrida</div>
          <ul>
            <li>El dato llega con ${t.latencia_dato_horas} horas de retraso</li>
            <li>Una sola actualización al día</li>
            <li>Cada pregunta nueva requiere trabajo del equipo técnico</li>
          </ul>
        </div>
        <div>
          <h4>Pregunta directa</h4>
          <div class="total rapido">${v.medido.latencia_media_ms ? F.duracion(v.medido.latencia_media_ms) : '—'} en promedio</div>
          <ul>
            <li>El dato es el de este momento, sin retraso</li>
            <li>${v.medido.consultas_registradas} preguntas respondidas en esta demostración</li>
            <li>Preguntas nuevas sin cambios de código</li>
          </ul>
        </div>
      </div>
      <p class="nota" style="margin-top:8px">${escapar(c.conclusion)}</p>`;
  });
  return det;
}

// ------------------------------------------------------------ arranque
function mostrarSugerencias(visible) {
  const cont = $('#sugerencias');
  if (cont) cont.style.display = visible ? 'flex' : 'none';
}

async function inicializar() {
  aplicarModo();
  const salud = await fetch('/api/salud').then((r) => r.json());
  const badge = $('#badge-fuente');
  const enVivo = salud.fuente === 'redshift';
  const copias = (salud.cache && salud.cache.tablas_materializadas) || [];
  badge.textContent = enVivo
    ? (copias.length ? 'Almacén + copia local' : 'Almacén en vivo')
    : `Demo · al ${F.fecha(salud.fecha_referencia_datos)}`;
  badge.className = `badge ${enVivo ? 'live' : 'demo'}`;
  badge.title = enVivo
    ? `Redshift en solo lectura · ${copias.length} tablas materializadas en DuckDB · ruteo ${salud.routing}`
    : 'Datos simulados sobre DuckDB, sin conexión al almacén';

  const ejemplos = await fetch('/api/ejemplos').then((r) => r.json());
  const sugerencias = $('#sugerencias');
  const grid = $('#ejemplos-grid');
  const visibles = ejemplos.preguntas.filter((p) => estado.experto || !p.solo_experto);
  sugerencias.innerHTML = '';
  mostrarSugerencias(Boolean(estado.ultimaRespuesta));
  if (!estado.ultimaRespuesta) chatLog.classList.add('vacio');
  if (grid) grid.innerHTML = '';
  visibles.forEach((p, i) => {
    const etiqueta = estado.experto ? p.texto : (p.titulo || p.texto);
    if (i < 3) {
      const b = document.createElement('button');
      b.textContent = etiqueta;
      b.onclick = () => preguntar(p.texto);
      sugerencias.appendChild(b);
    }
    if (grid && i < 6) {
      const card = document.createElement('button');
      card.className = 'ejemplo-card';
      card.textContent = etiqueta;
      card.onclick = () => preguntar(p.texto);
      grid.appendChild(card);
    }
  });
}

function aplicarModo() {
  document.body.classList.toggle('experto', estado.experto);
  $('#modo-experto').checked = estado.experto;
}

$('#modo-experto').addEventListener('change', (e) => {
  estado.experto = e.target.checked;
  localStorage.setItem('optimiza_experto', String(estado.experto));
  aplicarModo();
  inicializar();
  repintarUltimoResultado();
});

$('#composer').addEventListener('submit', (e) => {
  e.preventDefault();
  const texto = $('#pregunta').value.trim();
  if (!texto) return;
  $('#pregunta').value = '';
  preguntar(texto);
});

inicializar();
