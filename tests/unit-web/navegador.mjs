/**
 * Capa de navegador para el motor de pruebas.
 *
 * Motor principal: Lightpanda, un navegador headless sin motor gráfico. Arranca
 * en milisegundos y consume una fracción de la memoria de Chromium, lo que
 * permite usar una página nueva por archivo de pruebas sin penalización.
 *
 * Motor de respaldo: el Chromium de Playwright, por si Lightpanda no está
 * instalado o si se quiere contrastar un resultado sospechoso.
 */
import { spawn } from 'node:child_process';
import dns from 'node:dns/promises';
import fs from 'node:fs';
import net from 'node:net';
import path from 'node:path';

const esperar = (ms) => new Promise((r) => setTimeout(r, ms));

function rutaLightpanda(raiz) {
  const candidatos = [
    process.env.LIGHTPANDA_BIN,
    path.join(raiz, 'bin/lightpanda'),
    '/usr/local/bin/lightpanda',
    '/usr/bin/lightpanda',
  ].filter(Boolean);
  return candidatos.find((c) => fs.existsSync(c)) || null;
}

async function puertoLibre() {
  return new Promise((resolve) => {
    const s = net.createServer();
    s.listen(0, '127.0.0.1', () => {
      const { port } = s.address();
      s.close(() => resolve(port));
    });
  });
}

/**
 * Sustituye el nombre de host por su IP.
 *
 * Los servidores CDP rechazan con 403 el handshake WebSocket cuyo header Host
 * no es una IP o localhost: es la defensa clásica contra DNS rebinding. Al
 * conectarse entre contenedores (`ws://lightpanda:9222`) hay que resolverlo.
 */
async function conIP(ws) {
  try {
    const url = new URL(ws);
    if (net.isIP(url.hostname) || url.hostname === 'localhost') return ws;
    const { address } = await dns.lookup(url.hostname, { family: 4 });
    url.hostname = address;
    return url.toString().replace(/\/$/, '');
  } catch {
    return ws;
  }
}

async function esperarCDP(url, intentos = 150) {
  for (let i = 0; i < intentos; i++) {
    try {
      const r = await fetch(`${url}/json/version`);
      if (r.ok) return await r.json();
    } catch { /* todavía no levanta */ }
    await esperar(100);
  }
  throw new Error(
    `El servidor CDP no respondió en ${url} tras ${(intentos / 10).toFixed(0)} s. ` +
    '¿Está levantado Lightpanda? (docker compose --profile test up -d lightpanda)'
  );
}

/** Lightpanda: se conecta a uno existente o levanta uno propio. */
async function abrirLightpanda(raiz) {
  const puppeteer = (await import('puppeteer-core')).default;
  let proceso = null;
  let ws = process.env.LIGHTPANDA_WS || null;
  let version = 'externo';

  if (!ws) {
    const binario = rutaLightpanda(raiz);
    if (!binario) return null;
    const puerto = await puertoLibre();
    proceso = spawn(binario, [
      'serve', '--host', '127.0.0.1', '--port', String(puerto),
      '--log-level', 'error', '--log-format', 'logfmt',
    ], { stdio: ['ignore', 'ignore', 'pipe'] });
    proceso.stderr.on('data', (d) => {
      const texto = d.toString().trim();
      if (texto && process.env.LIGHTPANDA_DEBUG) console.error('[lightpanda]', texto);
    });
    const info = await esperarCDP(`http://127.0.0.1:${puerto}`);
    version = info['Lightpanda-Version'] || info.Browser || 'desconocida';
    ws = `ws://127.0.0.1:${puerto}`;
  } else {
    const info = await esperarCDP(ws.replace(/^ws/, 'http'));
    version = info['Lightpanda-Version'] || info.Browser || 'desconocida';
  }

  const navegador = await puppeteer.connect({ browserWSEndpoint: await conIP(ws) });

  return {
    motor: 'lightpanda',
    version,
    async abrirPagina(url) {
      const contexto = await navegador.createBrowserContext();
      const pagina = await contexto.newPage();
      const errores = [];
      pagina.on('pageerror', (e) => errores.push(String(e.message || e)));
      await pagina.goto(url, { waitUntil: 'load' });
      return {
        evaluar: (fn, ...args) => pagina.evaluate(fn, ...args),
        errores,
        cerrar: async () => { await pagina.close(); await contexto.close(); },
      };
    },
    async cerrar() {
      await navegador.disconnect();
      if (proceso) proceso.kill('SIGTERM');
    },
  };
}

/** Respaldo: Chromium de Playwright. */
async function abrirChromium() {
  let chromium;
  try {
    ({ chromium } = await import('playwright'));
  } catch {
    return null;
  }
  const navegador = await chromium.launch();
  return {
    motor: 'chromium',
    version: navegador.version(),
    async abrirPagina(url) {
      const contexto = await navegador.newContext();
      const pagina = await contexto.newPage();
      const errores = [];
      pagina.on('pageerror', (e) => errores.push(String(e.message || e)));
      await pagina.goto(url, { waitUntil: 'load' });
      return {
        evaluar: (fn, ...args) => pagina.evaluate(fn, ...args),
        errores,
        cerrar: async () => { await contexto.close(); },
      };
    },
    cerrar: () => navegador.close(),
  };
}

export async function abrirNavegador(raiz, motorPedido = process.env.MOTOR_PRUEBAS || 'auto') {
  if (motorPedido === 'chromium') {
    const c = await abrirChromium();
    if (!c) throw new Error('Playwright no está instalado: npm install && npx playwright install chromium');
    return c;
  }
  const lp = await abrirLightpanda(raiz);
  if (lp) return lp;
  if (motorPedido === 'lightpanda') {
    throw new Error(
      'Lightpanda no está disponible. Instálalo con scripts/instalar_lightpanda.sh ' +
      'o apunta LIGHTPANDA_WS a un servidor CDP.'
    );
  }
  const c = await abrirChromium();
  if (!c) throw new Error('No hay ningún navegador disponible (ni Lightpanda ni Chromium)');
  return c;
}
