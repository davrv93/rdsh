/**
 * Servidor estático para las pruebas unitarias del frontend.
 *
 * Sirve el repositorio (frontend/static y tests/unit-web) y genera al vuelo
 * `/tests/unit-web/fixtures.js` con todos los JSON de la carpeta fixtures.
 */
import fs from 'node:fs/promises';
import http from 'node:http';
import os from 'node:os';
import path from 'node:path';

const TIPOS = {
  '.html': 'text/html; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.mjs': 'text/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.svg': 'image/svg+xml',
};

async function fixturesComoScript(raiz) {
  const carpeta = path.join(raiz, 'tests/unit-web/fixtures');
  let archivos = [];
  try {
    archivos = (await fs.readdir(carpeta)).filter((f) => f.endsWith('.json'));
  } catch {
    return 'window.__fixtures = {};';
  }
  const datos = {};
  for (const archivo of archivos) {
    datos[archivo] = JSON.parse(await fs.readFile(path.join(carpeta, archivo), 'utf-8'));
  }
  return `window.__fixtures = ${JSON.stringify(datos)};`;
}

/** IPv4 de esta máquina o contenedor, para que un navegador externo la alcance. */
function ipLocal() {
  for (const interfaces of Object.values(os.networkInterfaces())) {
    for (const i of interfaces || []) {
      if (i.family === 'IPv4' && !i.internal) return i.address;
    }
  }
  return '127.0.0.1';
}

/**
 * `host` es la interfaz donde escucha y `anuncio` la dirección con la que el
 * navegador debe alcanzarlo. Difieren cuando Lightpanda corre en otro
 * contenedor: ahí se escucha en 0.0.0.0 y se anuncia la IP del contenedor,
 * porque el nombre del servicio no siempre se resuelve desde el otro lado.
 */
export async function iniciarServidor(raiz, host = process.env.TEST_BIND || '127.0.0.1',
                                      anuncio = process.env.TEST_HOST || null) {
  if (!anuncio) anuncio = host === '0.0.0.0' ? ipLocal() : host;
  const servidor = http.createServer(async (req, res) => {
    const url = new URL(req.url, 'http://localhost');
    let ruta = decodeURIComponent(url.pathname);

    if (ruta === '/tests/unit-web/fixtures.js') {
      res.writeHead(200, { 'Content-Type': TIPOS['.js'] });
      res.end(await fixturesComoScript(raiz));
      return;
    }

    const destino = path.join(raiz, ruta);
    // No servir nada fuera del repositorio
    if (!destino.startsWith(raiz)) {
      res.writeHead(403).end('Prohibido');
      return;
    }
    try {
      const contenido = await fs.readFile(destino);
      res.writeHead(200, { 'Content-Type': TIPOS[path.extname(destino)] || 'application/octet-stream' });
      res.end(contenido);
    } catch {
      res.writeHead(404, { 'Content-Type': 'text/plain; charset=utf-8' });
      res.end('No encontrado: ' + ruta);
    }
  });

  await new Promise((resolve) => servidor.listen(0, host, resolve));
  const { port } = servidor.address();
  return {
    puerto: port,
    base: `http://${anuncio}:${port}`,
    cerrar: () => new Promise((resolve) => servidor.close(resolve)),
  };
}
