/** Panel de administración: fuentes, clasificador, relaciones, embeddings y metadata. */
const $ = (s) => document.querySelector(s);
const esc = (t) => String(t).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
const chip = (t, clase = '') => `<span class="chip ${clase}">${esc(t)}</span>`;

async function get(url) { return (await fetch(url)).json(); }
async function post(url, body, metodo = 'POST') {
  const r = await fetch(url, { method: metodo, headers: { 'Content-Type': 'application/json' }, body: body ? JSON.stringify(body) : undefined });
  return { ok: r.ok, data: await r.json() };
}

async function cargarFuentes() {
  const f = await get('/api/admin/fuentes');
  $('#badge-fuente').textContent = `fuente: ${f.fuente_activa}`;
  $('#badge-fuente').className = `badge ${f.fuente_activa === 'redshift' ? 'live' : 'demo'}`;
  $('#fuentes').innerHTML = `
    <div class="chips" style="margin-bottom:10px">
      ${chip('modo: ' + f.modo)}${chip('fuente activa: ' + f.fuente_activa, f.fuente_activa === 'redshift' ? 'ok' : 'warn')}
      ${chip('max_rows: ' + f.limites.max_rows)}${chip('timeout: ' + f.limites.timeout_s + 's')}
      ${chip('mask_pii: ' + f.limites.mask_pii, f.limites.mask_pii ? 'ok' : 'warn')}
      ${chip('LLM: ' + (f.llm.habilitado ? f.llm.modelo : 'deshabilitado'))}
    </div>
    <div style="font-size:12.5px;color:var(--muted)">
      <div><strong>Redshift</strong>: ${f.redshift.configurado ? 'credenciales presentes' : 'sin credenciales (modo demo)'} ·
        driver ${f.redshift.driver_disponible ? 'disponible' : 'no instalado'} ${f.redshift.host ? '· host ' + esc(f.redshift.host) : ''}
        ${f.redshift.error ? '· ' + esc(f.redshift.error) : ''}</div>
      <div style="margin-top:6px"><strong>DuckDB</strong>: ${f.duckdb.tablas.map((t) => chip(t)).join(' ')}</div>
      <div style="margin-top:6px"><strong>Copia local materializada</strong>: ${
        f.duckdb.cache.length ? f.duckdb.cache.map((t) => chip(t, 'ok')).join(' ') : chip('vacía', 'warn')}</div>
    </div>`;
}

async function cargarSync() {
  const s = await get('/api/admin/sync');
  const corrida = s.ultima_corrida;
  const filas = s.tablas.map((t) => {
    const estadoTxt = !t.materializada ? 'sin copia local'
      : t.fresca ? 'copia vigente' : 'copia vencida';
    const color = !t.materializada ? 'var(--warn)' : t.fresca ? 'var(--ok)' : 'var(--warn)';
    const antiguedad = t.antiguedad_min === null ? '—'
      : t.antiguedad_min < 60 ? `${t.antiguedad_min} min`
      : `${(t.antiguedad_min / 60).toFixed(1)} h`;
    return `<li><span class="nombre">${esc(t.tabla)}</span>
      <span class="detalle">${t.filas.toLocaleString('es-PE')} filas · marca ${esc(t.marca || '—')}
        · columna ${esc(t.columna_marca || '—')} · actualizada hace ${antiguedad}</span>
      <span class="ms" style="color:${color}">${estadoTxt}</span></li>`;
  }).join('');
  $('#sync').innerHTML = `
    <div class="chips" style="margin-bottom:10px">
      ${chip('origen: ' + s.origen, s.origen === 'redshift' ? 'ok' : 'warn')}
      ${chip('ruteo: ' + s.routing)}
      ${chip('vigencia: ' + s.cache_max_age_min + ' min')}
      ${corrida ? chip('última corrida: ' + corrida.filas_nuevas.toLocaleString('es-PE') + ' filas en ' + Math.round(corrida.ms_total) + ' ms', 'ok') : chip('sin corridas todavía', 'warn')}
    </div>
    <ol class="pasos">${filas}</ol>`;
  const selector = $('#routing');
  if (selector) selector.value = s.routing;
}

async function ejecutarSync(incremental) {
  $('#sync').innerHTML = '<span class="spinner"></span> Materializando desde el almacén…';
  const { ok, data } = await post('/api/admin/sync', { incremental });
  if (!ok) {
    $('#sync').innerHTML = `<div class="nota">${esc(data.detail || 'No se pudo sincronizar')}</div>`;
    return;
  }
  await cargarSync();
}

async function cargarClasificador() {
  const c = await get('/api/admin/clasificador');
  $('#badge-edge').textContent = `edge: ${c.backend}`;
  const casos = c.evaluacion.casos.map((k) =>
    `<li><span class="nombre">${esc(k.esperado)}</span>
      <span class="detalle">${esc(k.texto)} → <strong>${esc(k.obtenido)}</strong></span>
      <span class="ms" style="color:${k.ok ? 'var(--accent-2)' : 'var(--danger)'}">${k.latency_ms.toFixed(2)} ms</span></li>`).join('');
  $('#clasificador').innerHTML = `
    <div class="chips" style="margin-bottom:10px">
      ${chip('backend: ' + c.backend)}${chip('configurado: ' + c.configurado)}
      ${chip('accuracy eval: ' + (c.evaluacion.accuracy * 100).toFixed(1) + '%', 'ok')}
      ${chip('latencia media: ' + c.evaluacion.latencia_media_ms + ' ms', 'ok')}
      ${Object.entries(c.info).map(([k, v]) => chip(k + ': ' + v)).join('')}
    </div>
    <div style="font-size:12px;color:var(--muted);margin-bottom:6px">Intenciones acertadas en la evaluación:
      ${c.evaluacion.intenciones_correctas.map((i) => chip(i, 'ok')).join(' ')}</div>
    <ol class="pasos">${casos}</ol>`;
}

async function cargarRelaciones() {
  const r = await get('/api/admin/relaciones');
  const lista = (arr, clase) => arr.map((x) =>
    `<li><span class="nombre">${clase}</span>
      <span class="detalle">${esc(x.left)} = ${esc(x.right)} · ${esc(x.type)}${x.nota ? ' · ' + esc(x.nota) : ''}</span>
      <span class="ms">${x.virtual ? `<button class="ghost" data-left="${esc(x.left)}" data-right="${esc(x.right)}">borrar</button>` : ''}</span></li>`).join('');
  const candidatas = r.candidatas.map((c) =>
    `<li><span class="nombre">${c.confiable ? 'candidata' : 'descartada'}</span>
      <span class="detalle">${esc(c.izquierda)} ↔ ${esc(c.derecha)} · cobertura ${(c.cobertura_izquierda * 100).toFixed(0)}%
        · ${esc(c.cardinalidad)} · ${c.valores_comunes} valores comunes</span>
      <span class="ms" style="color:${c.confiable ? 'var(--accent-2)' : 'var(--warn)'}">${c.confiable ? 'confiable' : 'no usar'}</span></li>`).join('');
  $('#relaciones').innerHTML = `<ol class="pasos">${lista(r.declaradas, 'declarada')}${lista(r.virtuales, 'virtual')}${candidatas}</ol>`;
  $('#relaciones').querySelectorAll('button[data-left]').forEach((b) => {
    b.onclick = async () => {
      await post(`/api/admin/relaciones?left=${encodeURIComponent(b.dataset.left)}&right=${encodeURIComponent(b.dataset.right)}`, null, 'DELETE');
      cargarRelaciones();
    };
  });
}

async function cargarEmbeddings(docs) {
  const lista = docs || (await get('/api/admin/embeddings')).documentos;
  $('#embeddings').innerHTML = `<ol class="pasos">${lista.map((d) =>
    `<li><span class="nombre">${esc(d.tipo)}</span>
      <span class="detalle">${esc(d.texto)}
        <div class="vector-preview">[${(d.vector_preview || []).join(', ')}…]</div></span>
      <span class="ms">${d.score !== undefined ? d.score.toFixed(3) : ''}</span></li>`).join('')}</ol>`;
}

async function cargarMetadata() {
  const m = await get('/api/admin/metadata');
  $('#metadata').value = JSON.stringify(m.metadata, null, 2);
}

async function cargarAuditoria() {
  const a = await get('/api/admin/auditoria?limite=25');
  $('#auditoria').innerHTML = `<ol class="pasos">${a.eventos.map((e) =>
    `<li><span class="nombre">${esc(e.evento)}</span>
      <span class="detalle">${esc(e.pregunta || e.sql || JSON.stringify(e).slice(0, 160))}</span>
      <span class="ms">${esc((e.ts || '').slice(11, 19))}</span></li>`).join('') || '<li>Sin eventos</li>'}</ol>`;
}

$('#btn-intencion').onclick = async () => {
  const texto = $('#texto-intencion').value.trim();
  if (!texto) return;
  const r = await get(`/api/intencion?texto=${encodeURIComponent(texto)}`);
  $('#resultado-intencion').innerHTML = `<div class="chips">
    ${chip('intención: ' + r.intent, 'ok')}${chip('confianza: ' + (r.confidence * 100).toFixed(1) + '%')}
    ${chip('latencia: ' + r.latency_ms.toFixed(3) + ' ms', 'ok')}${chip('backend: ' + r.backend)}
    ${r.fallback_used ? chip('fallback de reglas usado', 'warn') : ''}</div>
    <div class="chips" style="margin-top:6px">${Object.entries(r.scores).slice(0, 7).map(([k, v]) => chip(`${k}: ${(v * 100).toFixed(1)}%`)).join('')}</div>`;
};

$('#btn-buscar').onclick = async () => {
  const consulta = $('#consulta-semantica').value.trim();
  if (!consulta) return cargarEmbeddings();
  const tipo = $('#tipo-doc').value;
  const { data } = await post('/api/admin/buscar', { consulta, k: 15, tipos: tipo ? [tipo] : null });
  cargarEmbeddings(data.resultados.map((r) => ({ ...r, vector_preview: [] })));
};

$('#btn-reindexar').onclick = async () => { await post('/api/admin/reindexar'); cargarEmbeddings(); };

$('#btn-relacion').onclick = async () => {
  const { ok, data } = await post('/api/admin/relaciones', {
    left: $('#rel-left').value.trim(), right: $('#rel-right').value.trim(),
    tipo: $('#rel-tipo').value, nota: 'Declarada desde el panel admin',
  });
  $('#resultado-relacion').textContent = ok ? 'Relación virtual creada y reindexada.' : (data.detail || 'Error');
  cargarRelaciones();
};

$('#btn-metadata').onclick = async () => {
  try {
    const metadata = JSON.parse($('#metadata').value);
    const { ok, data } = await post('/api/admin/metadata', { metadata });
    $('#resultado-metadata').textContent = ok
      ? `Metadata cargada: ${data.documentos_indexados} documentos reindexados.`
      : (data.detail || 'Error');
    cargarEmbeddings();
  } catch (e) {
    $('#resultado-metadata').textContent = 'JSON inválido: ' + e.message;
  }
};

$('#probar').onclick = async () => {
  const { data } = await post('/api/admin/fuentes/probar');
  alert(`Redshift: ${data.redshift.ok ? 'OK' : data.redshift.motivo}\nDuckDB: ${data.duckdb.tablas} tablas`);
  cargarFuentes();
};

$('#sync-incremental').onclick = () => ejecutarSync(true);
$('#sync-completa').onclick = () => ejecutarSync(false);
$('#routing').onchange = async (e) => {
  const { data } = await post('/api/admin/routing', { routing: e.target.value });
  $('#resultado-routing').textContent = `Ruteo aplicado: ${data.routing}`;
  cargarSync(); cargarFuentes();
};
$('#btn-introspectar').onclick = async () => {
  const { ok, data } = await post('/api/admin/metadata/introspectar');
  $('#resultado-routing').textContent = ok
    ? `Catálogo releído: ${data.tablas} tablas, ${data.documentos_indexados} documentos indexados.`
    : (data.detail || 'Error');
  cargarMetadata(); cargarEmbeddings();
};

cargarSync(); cargarFuentes(); cargarClasificador(); cargarRelaciones(); cargarEmbeddings(); cargarMetadata(); cargarAuditoria();
