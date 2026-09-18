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

async function cargarCadena() {
  const c = await get('/api/admin/clasificador');
  const estados = {
    aceptado: 'ok', baja_confianza: 'warn', no_disponible: 'warn', error: 'warn',
  };
  const motores = c.info.motores.map((m) => {
    const disponible = m.disponible ? 'disponible' : 'no disponible';
    return `<li>
      <span class="nombre">${esc(m.motor)}${m.ultima_instancia ? ' · última instancia' : ''}</span>
      <span class="detalle">${esc(m.descripcion || '')}
        ${m.error ? '<br/>' + esc(m.error) : ''}</span>
      <span class="ms" style="color:${m.disponible ? 'var(--ok)' : 'var(--warn)'}">
        ${disponible} · umbral ${m.umbral}</span></li>`;
  }).join('');
  const resueltas = Object.entries(c.evaluacion.resueltas_por_motor || {})
    .map(([motor, n]) => chip(`${motor}: ${n} casos`, 'ok')).join(' ');
  $('#cadena').innerHTML = `
    <div class="chips" style="margin-bottom:10px">
      ${chip('cadena: ' + c.configurado.join(' → '), 'ok')}
      ${chip('umbral general: ' + c.info.umbral_general)}
      ${chip('accuracy: ' + (c.evaluacion.accuracy * 100).toFixed(1) + '%', 'ok')}
      ${chip('latencia media: ' + c.evaluacion.latencia_media_ms + ' ms', 'ok')}
    </div>
    <ol class="pasos">${motores}</ol>
    <div style="font-size:12px;color:var(--muted);margin-top:10px">
      Quién resolvió los casos de control: ${resueltas || '—'}</div>`;
  const entrada = $('#cadena-motores');
  if (entrada && !entrada.value) entrada.value = c.configurado.join(',');
  $('#badge-edge').textContent = `motores: ${c.configurado.join('→')}`;
  return c;
}

async function cargarClasificador() {
  const c = await get('/api/admin/clasificador');
  const casos = c.evaluacion.casos.map((k) =>
    `<li><span class="nombre">${esc(k.esperado)}</span>
      <span class="detalle">${esc(k.texto)} → <strong>${esc(k.obtenido)}</strong>
        ${k.relevos ? ' · ' + k.relevos + ' relevo(s)' : ''}</span>
      <span class="ms" style="color:${k.ok ? 'var(--ok)' : 'var(--danger)'}">${esc(k.motor)} · ${k.latency_ms.toFixed(2)} ms</span></li>`).join('');
  $('#clasificador').innerHTML = `
    <div style="font-size:12px;color:var(--muted);margin-bottom:6px">
      Casos de control · intenciones acertadas:
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

$('#btn-cadena').onclick = async () => {
  const motores = $('#cadena-motores').value.split(',').map((m) => m.trim()).filter(Boolean);
  const umbral = parseFloat($('#cadena-umbral').value);
  const { ok, data } = await post('/api/admin/clasificador/cadena', {
    motores, umbral: Number.isFinite(umbral) ? umbral : null,
  });
  $('#resultado-cadena').textContent = ok
    ? `Cadena aplicada: ${data.cadena.join(' → ')} · accuracy ${(data.evaluacion.accuracy * 100).toFixed(1)}%`
    : (data.detail || 'Error');
  cargarCadena(); cargarClasificador();
};

$('#btn-intencion').onclick = async () => {
  const texto = $('#texto-intencion').value.trim();
  if (!texto) return;
  const r = await get(`/api/intencion?texto=${encodeURIComponent(texto)}`);
  $('#resultado-intencion').innerHTML = `<div class="chips">
    ${chip('intención: ' + r.intent, 'ok')}${chip('confianza: ' + (r.confidence * 100).toFixed(1) + '%')}
    ${chip('latencia: ' + r.latency_ms.toFixed(3) + ' ms', 'ok')}${chip('motor: ' + r.motor)}
    ${r.relevos ? chip(r.relevos + ' relevo(s)', 'warn') : ''}</div>
    <ol class="pasos" style="margin-top:8px">${(r.intentos || []).map((i) =>
      `<li><span class="nombre">${esc(i.motor)}</span>
        <span class="detalle">${esc(i.detalle || '')}</span>
        <span class="ms" style="color:${i.estado === 'aceptado' ? 'var(--ok)' : 'var(--warn)'}">${esc(i.estado)}</span></li>`).join('')}</ol>
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

cargarSync(); cargarFuentes(); cargarCadena(); cargarClasificador(); cargarRelaciones(); cargarEmbeddings(); cargarMetadata(); cargarAuditoria();

// ---------------------------------------------------------------- WhatsApp
async function cargarWhatsapp() {
  const w = await get('/api/canales/whatsapp/estado');
  const sesion = w.sesion || {};
  const estadoSesion = sesion.state || sesion.error || 'sin instancia';
  const colorSesion = estadoSesion === 'open' ? 'ok' : estadoSesion === 'connecting' ? 'warn' : 'warn';
  const servicio = w.servicio || {};
  const webhook = w.webhook || {};

  $('#whatsapp').innerHTML = `
    <div class="chips" style="margin-bottom:10px">
      ${chip('canal: ' + (w.habilitado ? 'activo' : 'inactivo'), w.habilitado ? 'ok' : 'warn')}
      ${chip('sesión: ' + estadoSesion, colorSesion)}
      ${chip('instancia: ' + esc(w.instancia))}
      ${chip('números autorizados: ' + w.autorizados, w.autorizados ? 'ok' : 'warn')}
      ${servicio.version ? chip('Evolution API ' + esc(servicio.version)) : ''}
      ${webhook.url ? chip('webhook configurado', 'ok') : chip('sin webhook', 'warn')}
    </div>
    <div style="font-size:12.5px;color:var(--muted)">
      <div><strong>Servicio</strong>: ${esc(w.url)} ${servicio.error ? '· ' + esc(servicio.error) : '· responde'}</div>
      ${webhook.url ? `<div style="margin-top:4px"><strong>Webhook</strong>: ${esc(webhook.url)} · eventos ${(webhook.events || []).map((e) => esc(e)).join(', ')}</div>` : ''}
      ${w.autorizados === 0 ? '<div style="margin-top:6px;color:var(--warn)">Sin números autorizados el canal no responde a nadie. Es intencional: WhatsApp es un canal abierto.</div>' : ''}
    </div>`;

  $('#wa-habilitado').checked = Boolean(w.habilitado);
  if (!$('#wa-webhook').value) {
    $('#wa-webhook').value = webhook.url || 'http://app:8000/api/canales/whatsapp/webhook';
  }
  if (!$('#wa-base').value && w.base_publica) $('#wa-base').value = w.base_publica;
  return w;
}

$('#wa-refrescar').onclick = () => cargarWhatsapp();

$('#wa-vincular').onclick = async () => {
  $('#wa-qr').innerHTML = '<span class="spinner"></span> Generando código…';
  const { ok, data } = await post('/api/canales/whatsapp/instancia');
  if (!ok) {
    $('#wa-qr').innerHTML = `<div class="nota">${esc(data.detail || 'No se pudo generar el código')}</div>`;
    return;
  }
  $('#wa-qr').innerHTML = data.qr_base64
    ? `<div style="font-size:12.5px;color:var(--muted);margin-bottom:6px">
         Abre WhatsApp en el teléfono → Dispositivos vinculados → Vincular dispositivo</div>
       <img src="${data.qr_base64}" alt="Código QR para vincular WhatsApp" width="240" height="240"
            style="border:1px solid var(--border);border-radius:8px" />`
    : `<div class="nota">Estado: ${esc(data.estado || 'sin QR')} (si ya está vinculado, no hace falta)</div>`;
  cargarWhatsapp();
};

$('#wa-guardar').onclick = async () => {
  const autorizados = $('#wa-autorizados').value.split(',').map((n) => n.trim()).filter(Boolean);
  const { ok, data } = await post('/api/canales/whatsapp/configurar', {
    habilitado: $('#wa-habilitado').checked,
    autorizados,
    base_publica: $('#wa-base').value.trim() || null,
  });
  $('#wa-resultado').textContent = ok ? 'Configuración guardada.' : (data.detail || 'Error');
  cargarWhatsapp();
};

$('#wa-webhook-set').onclick = async () => {
  const { ok, data } = await post('/api/canales/whatsapp/configurar', {
    url_webhook: $('#wa-webhook').value.trim(),
  });
  const error = data.webhook && data.webhook.error;
  $('#wa-resultado').textContent = ok && !error ? 'Webhook aplicado en Evolution API.' : (error || data.detail || 'Error');
  cargarWhatsapp();
};

async function probarWhatsapp(enviar) {
  const texto = $('#wa-prueba').value.trim();
  if (!texto) return;
  $('#wa-vista').style.display = 'block';
  $('#wa-vista').textContent = 'Consultando…';
  const { ok, data } = await post('/api/canales/whatsapp/probar', {
    texto, numero: $('#wa-numero').value.trim() || null, enviar,
  });
  $('#wa-vista').textContent = ok
    ? data.texto + `\n\n— ${data.caracteres} caracteres · intención ${data.intencion} · ${data.filas} registros`
      + (enviar ? '\n— Enviado por WhatsApp' : '')
    : (data.detail || 'Error');
}

$('#wa-probar').onclick = () => probarWhatsapp(false);
$('#wa-enviar').onclick = () => probarWhatsapp(true);

cargarWhatsapp();
