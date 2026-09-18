/**
 * Dobles de prueba: respuestas simuladas de la API y utilidades.
 *
 * `app.js` llama a la API apenas se carga. Aquí se intercepta `fetch` para que
 * las pruebas no dependan del backend y sean deterministas.
 */
(function () {
  const respuestas = {
    '/api/salud': {
      ok: true, fuente: 'duckdb_cache', modo_demo: false,
      fecha_referencia_datos: '2025-09-30', routing: 'auto',
      cache: { tablas_materializadas: ['ventas', 'clientes'], max_age_min: 720 },
      capa_semantica: { documentos: 128, dimension: 512 },
      llm: { habilitado: false, modelo: null },
    },
    '/api/ejemplos': {
      preguntas: [
        { texto: 'Ventas por mes', titulo: '¿Cómo evolucionaron las ventas mes a mes?' },
        { texto: 'Top 10 clientes por ingreso', titulo: '¿Quiénes son mis 10 mejores clientes?' },
        { texto: '¿Qué tablas no relacionadas puedo combinar?',
          titulo: '¿Qué tablas no relacionadas puedo combinar?', solo_experto: true },
      ],
    },
    '/api/comparativa': {
      tradicional: { duracion_total_minutos: 165, latencia_dato_horas: 12 },
      conversacional: { medido: { latencia_media_ms: 21.4, consultas_registradas: 7 } },
      conclusion: 'El proceso nocturno tarda 165 minutos.',
    },
  };

  window.__llamadas = [];

  window.fetch = function (url, opciones) {
    window.__llamadas.push({ url: String(url), opciones });
    const clave = Object.keys(respuestas).find((k) => String(url).startsWith(k));
    const cuerpo = clave ? respuestas[clave] : { ok: false };
    return Promise.resolve({
      ok: Boolean(clave),
      status: clave ? 200 : 404,
      json: () => Promise.resolve(cuerpo),
    });
  };

  window.__respuestas = respuestas;

  /** Devuelve un fixture ya cargado por el runner (ver fixtures.js). */
  window.cargarFixture = function (nombre) {
    const datos = (window.__fixtures || {})[nombre];
    if (!datos) throw new Error('Fixture no encontrado: ' + nombre);
    return JSON.parse(JSON.stringify(datos));
  };
})();
