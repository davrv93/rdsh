// E2E con Playwright. Requiere la app corriendo en http://localhost:8000
// Instalación: npm install && npx playwright install chromium
// Ejecución:   npx playwright test
const { test, expect } = require('@playwright/test');

async function abrirEnModo(page, experto) {
  await page.addInitScript((v) => localStorage.setItem('optimiza_experto', String(v)), experto);
  await page.goto('/');
  await expect(page.locator('#badge-fuente')).toContainText(/Demo|Almacén/);
}

test('modo ejecutivo: respuesta en lenguaje de negocio, KPIs, gráfico y tabla', async ({ page }) => {
  await abrirEnModo(page, false);

  await page.fill('#pregunta', 'Ventas por mes');
  await page.click('#enviar');

  // Respuesta redactada para negocio, sin SQL
  const respuesta = page.locator('.msg.bot').last();
  await expect(respuesta).toContainText(/Ingreso total del periodo/i, { timeout: 15000 });
  await expect(respuesta).not.toContainText('SELECT');

  await expect(page.locator('.resultado-encabezado h2')).toContainText(/Ingreso por mes/i);
  await expect(page.locator('.kpis .kpi').first()).toContainText('Ingreso total');
  // Los resultados viven dentro de la conversación, no en un panel lateral
  await expect(page.locator('.chat-log .resultado')).toHaveCount(1);
  await expect(page.locator('table.datos thead th').first()).toContainText('Periodo');
  await expect(page.locator('table.datos tbody tr').first()).toBeVisible();
  await expect(page.locator('.boton-descarga')).toHaveAttribute('href', /\.csv$/);

  // El paso a paso se explica sin jerga y el detalle técnico está oculto
  await expect(page.locator('details.panel').first()).toContainText('Cómo obtuve esta respuesta');
  await expect(page.locator('details.panel').first()).toContainText('Entendí tu pregunta');
  await expect(page.locator('details.panel', { hasText: 'Detalle técnico' })).toHaveCount(0);
  await expect(page.locator('#badge-intencion')).toContainText('Indicador');
});

test('modo experto: aparece el SQL y el contexto semántico', async ({ page }) => {
  await abrirEnModo(page, true);
  await page.fill('#pregunta', 'Top 10 clientes por ingreso');
  await page.click('#enviar');
  await page.waitForSelector('table.datos tbody tr');

  const tecnico = page.locator('details.panel', { hasText: 'Detalle técnico' });
  await expect(tecnico).toHaveCount(1);
  await tecnico.locator('summary').click();
  await expect(tecnico.locator('pre.sql').first()).toContainText('SELECT');
  // El segundo bloque es la transformación que DuckDB aplica sobre el resultado
  await expect(tecnico.locator('pre.sql').nth(1)).toContainText('OVER');
  await expect(page.locator('details.panel', { hasText: 'Contexto semántico' })).toHaveCount(1);
});

test('una pregunta ambigua pide aclaración y no ejecuta SQL', async ({ page }) => {
  await abrirEnModo(page, false);
  await page.fill('#pregunta', 'ayúdame');
  await page.click('#enviar');
  await expect(page.locator('.msg.bot.warn').last()).toContainText(/contexto para consultar/i, { timeout: 15000 });
});

test('el panel de configuración muestra la cadena de motores y las relaciones candidatas', async ({ page }) => {
  await page.goto('/admin');
  // La cadena de clasificación, con su orden y su precisión
  await expect(page.locator('#cadena')).toContainText('cadena:', { timeout: 15000 });
  await expect(page.locator('#cadena')).toContainText('accuracy');
  await expect(page.locator('#cadena')).toContainText('reglas');
  // Los casos de control, resueltos por algún motor
  await expect(page.locator('#clasificador')).toContainText('Casos de control');
  await expect(page.locator('#relaciones')).toContainText('candidata');
});

test('el panel de configuración ofrece el canal de WhatsApp', async ({ page }) => {
  await page.goto('/admin');
  await expect(page.locator('#whatsapp')).toContainText(/canal:/, { timeout: 15000 });
  await expect(page.locator('#whatsapp')).toContainText('instancia:');
  await expect(page.locator('#wa-vincular')).toBeVisible();
});

test('el panel de configuración muestra la materialización del almacén', async ({ page }) => {
  await page.goto('/admin');
  await expect(page.locator('#sync')).toContainText(/origen:/, { timeout: 15000 });
  await expect(page.locator('#sync')).toContainText('ventas');
  await expect(page.locator('#routing')).toBeVisible();
});
