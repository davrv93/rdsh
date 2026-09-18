#!/usr/bin/env node
/**
 * Motor de pruebas unitarias del frontend, sobre Lightpanda.
 *
 * Cada archivo de `specs/` se ejecuta en una página nueva y aislada, junto con
 * los módulos del frontend que declara en su cabecera:
 *
 *     // modulos: /frontend/static/formatos.js, /frontend/static/charts.js
 *
 * Uso:
 *     node tests/unit-web/runner.mjs                 # todas las pruebas
 *     node tests/unit-web/runner.mjs formatos        # solo los specs que coincidan
 *     MOTOR_PRUEBAS=chromium node tests/unit-web/runner.mjs
 *     node tests/unit-web/runner.mjs --json          # salida para CI
 */
import fs from 'node:fs/promises';
import path from 'node:path';
import process from 'node:process';
import { fileURLToPath } from 'node:url';

import { abrirNavegador } from './navegador.mjs';
import { iniciarServidor } from './servidor.mjs';

const AQUI = path.dirname(fileURLToPath(import.meta.url));
const RAIZ = path.resolve(AQUI, '../..');
const SPECS = path.join(AQUI, 'specs');

const COLOR = process.stdout.isTTY && !process.env.NO_COLOR;
const c = {
  gris: (t) => (COLOR ? `\x1b[90m${t}\x1b[0m` : t),
  verde: (t) => (COLOR ? `\x1b[32m${t}\x1b[0m` : t),
  rojo: (t) => (COLOR ? `\x1b[31m${t}\x1b[0m` : t),
  negrita: (t) => (COLOR ? `\x1b[1m${t}\x1b[0m` : t),
};

/** Lee la cabecera `// modulos:` del spec para saber qué cargar antes. */
async function modulosDelSpec(archivo) {
  const contenido = await fs.readFile(archivo, 'utf-8');
  const linea = contenido.split('\n').find((l) => l.trim().startsWith('// modulos:'));
  if (!linea) return [];
  return linea.split(':').slice(1).join(':').split(',').map((m) => m.trim()).filter(Boolean);
}

async function main() {
  const argumentos = process.argv.slice(2);
  const comoJson = argumentos.includes('--json');
  const filtros = argumentos.filter((a) => !a.startsWith('--'));

  const archivos = (await fs.readdir(SPECS))
    .filter((f) => f.endsWith('.spec.js'))
    .filter((f) => !filtros.length || filtros.some((t) => f.includes(t)))
    .sort();

  if (!archivos.length) {
    console.error('No hay specs que coincidan con:', filtros.join(', ') || '(todos)');
    process.exit(1);
  }

  const servidor = await iniciarServidor(RAIZ);
  const navegador = await abrirNavegador(RAIZ);
  const inicio = Date.now();
  const informe = { motor: navegador.motor, version: navegador.version, archivos: [] };
  let total = 0, fallos = 0;

  if (!comoJson) {
    console.log(c.negrita(`\nPruebas unitarias del frontend · motor ${navegador.motor} ${c.gris(navegador.version)}\n`));
  }

  for (const archivo of archivos) {
    const modulos = await modulosDelSpec(path.join(SPECS, archivo));
    const url = `${servidor.base}/tests/unit-web/harness.html`
      + `?spec=/tests/unit-web/specs/${archivo}`
      + `&modulos=${encodeURIComponent(modulos.join(','))}`;

    const pagina = await navegador.abrirPagina(url);
    let resultado;
    try {
      resultado = await pagina.evaluar(async () => {
        const limite = Date.now() + 10000;
        while (!window.__listo && Date.now() < limite) {
          await new Promise((r) => setTimeout(r, 5));
        }
        return window.__resultado || { errorDeCarga: 'La página no terminó de cargar' };
      });
    } finally {
      await pagina.cerrar();
    }

    if (resultado.errorDeCarga) {
      fallos++;
      total++;
      informe.archivos.push({ archivo, errorDeCarga: resultado.errorDeCarga });
      if (!comoJson) console.log(`${c.rojo('✗')} ${archivo} ${c.rojo(resultado.errorDeCarga)}`);
      continue;
    }

    total += resultado.total;
    fallos += resultado.fallos;
    informe.archivos.push({ archivo, ...resultado, erroresDePagina: pagina.errores });

    if (!comoJson) {
      console.log(c.negrita(archivo) + c.gris(`  ${resultado.total} casos · ${resultado.ms} ms`));
      for (const suite of resultado.suites) {
        console.log('  ' + c.gris(suite.nombre));
        for (const caso of suite.casos) {
          const marca = caso.estado === 'ok' ? c.verde('✓') : c.rojo('✗');
          console.log(`    ${marca} ${caso.nombre} ${c.gris(caso.ms + ' ms')}`);
          if (caso.error) console.log(`        ${c.rojo(caso.error)}`);
        }
      }
      if (pagina.errores.length) {
        console.log('  ' + c.rojo('errores de la página: ' + pagina.errores.join(' · ')));
      }
      console.log('');
    }
  }

  await navegador.cerrar();
  await servidor.cerrar();

  informe.total = total;
  informe.fallos = fallos;
  informe.ms = Date.now() - inicio;

  if (comoJson) {
    console.log(JSON.stringify(informe, null, 2));
  } else {
    const resumen = `${total - fallos}/${total} casos en ${informe.ms} ms`;
    console.log(fallos ? c.rojo(`✗ ${resumen} · ${fallos} con fallo`) : c.verde(`✓ ${resumen}`));
  }
  process.exit(fallos ? 1 : 0);
}

main().catch((error) => {
  console.error('\nEl motor de pruebas falló:', error.message);
  process.exit(2);
});
