// Windy Webcams v3 con respuestas simuladas en el formato documentado.
import assert from 'node:assert/strict';
import { test } from 'node:test';

process.env.WINDY_API_KEY = 'clave-de-prueba';
const pedidos = [];
globalThis.fetch = async (url, opciones) => {
  pedidos.push({ url: String(url), clave: opciones?.headers?.['x-windy-api-key'] });
  const u = new URL(String(url));
  if (u.pathname.endsWith('/webcams')) {
    return Response.json({
      total: 2,
      webcams: [
        { webcamId: 1700000001, title: 'Quito - Panecillo', status: 'active', location: { city: 'Quito', country: 'Ecuador', latitude: -0.229, longitude: -78.518 } },
        { webcamId: 1700000002, title: 'Volcán Cotopaxi', status: 'active', location: { city: 'Latacunga', country: 'Ecuador', latitude: -0.68, longitude: -78.43 } },
        { webcamId: 1700000003, title: 'Inactiva', status: 'inactive', location: { latitude: -0.2, longitude: -78.5 } },
      ],
    });
  }
  if (u.pathname.endsWith('/webcams/1700000001')) {
    return Response.json({ title: 'Quito - Panecillo', images: { current: { preview: 'https://imgproxy.windy.com/x/preview.jpg?token=1' } }, player: { day: 'https://webcams.windy.com/webcams/public/embed/player/1700000001/day' }, urls: { detail: 'https://www.windy.com/webcams/1700000001' } });
  }
  return new Response('no', { status: 404 });
};

const { camarasWindyEn, detalleWindy, compactarWindy } = await import('../server/windy.js');

test('cámaras de Windy en la vista, con el orden norte-este-sur-oeste de su bbox', async () => {
  const quito = { lamin: -1, lomin: -79, lamax: 0.5, lomax: -78 };
  const camaras = await camarasWindyEn(quito);
  assert.deepEqual(camaras.map((c) => c[0]), ['windy:1700000001', 'windy:1700000002']);
  assert.equal(camaras[0][1], 'Quito - Panecillo', 'el título ya nombra la ciudad');
  assert.equal(camaras[1][1], 'Volcán Cotopaxi · Latacunga, Ecuador');
  const q = new URL(pedidos[0].url).searchParams;
  assert.equal(q.get('bbox'), '1,-78,-1,-79');
  assert.equal(q.get('limit'), '50');
  assert.equal(pedidos[0].clave, 'clave-de-prueba');
});

test('detalle: imagen fresca, reproductor y enlace a Windy', async () => {
  const d = await detalleWindy('1700000001');
  assert.equal(d.imagen, 'https://imgproxy.windy.com/x/preview.jpg?token=1');
  assert.equal(d.enlace, 'https://www.windy.com/webcams/1700000001');
  assert.ok(d.reproductor.includes('/player/'));
});

test('sin coordenadas o inactiva no entra', () => {
  assert.equal(compactarWindy({ webcamId: 1, location: {} }), null);
  assert.equal(compactarWindy({ webcamId: 1, status: 'inactive', location: { latitude: 1, longitude: 1 } }), null);
});
