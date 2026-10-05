import assert from 'node:assert/strict';
import { test } from 'node:test';
import { compactar } from '../server/opensky.js';
import { normalizarLectura } from '../server/presencia.js';
import { Cache, bboxEnRejilla, dentro, leerBbox } from '../server/util.js';

test('leerBbox valida y recorta la caja', () => {
  assert.deepEqual(leerBbox({ lamin: '40', lomin: '-4', lamax: '41', lomax: '-3' }), { lamin: 40, lomin: -4, lamax: 41, lomax: -3 });
  assert.equal(leerBbox({ lamin: '41', lomin: '-4', lamax: '40', lomax: '-3' }), null);
  assert.equal(leerBbox({ lamin: 'x', lomin: '0', lamax: '1', lomax: '1' }), null);
  assert.equal(leerBbox({}), null);
  assert.deepEqual(leerBbox({ lamin: '-95', lomin: '-400', lamax: '95', lomax: '400' }), { lamin: -90, lomin: -180, lamax: 90, lomax: 180 });
});

test('bboxEnRejilla redondea hacia fuera y dentro() incluye bordes', () => {
  const b = bboxEnRejilla({ lamin: 40.2, lomin: -3.7, lamax: 40.6, lomax: -3.1 }, 0.5);
  assert.deepEqual(b, { lamin: 40, lomin: -4, lamax: 41, lomax: -3 });
  assert.ok(dentro(b, 40, -3));
  assert.ok(!dentro(b, 41.1, -3.5));
});

test('Cache comparte la petición en curso y respeta el TTL', async () => {
  const c = new Cache({ ttlMs: 50, max: 2 });
  let llamadas = 0;
  const cargar = async () => {
    llamadas++;
    await new Promise((r) => setTimeout(r, 10));
    return llamadas;
  };
  const [a, b] = await Promise.all([c.obtener('k', cargar), c.obtener('k', cargar)]);
  assert.equal(a, 1);
  assert.equal(b, 1);
  await new Promise((r) => setTimeout(r, 60));
  assert.equal(await c.obtener('k', cargar), 2);
  await c.obtener('x', cargar);
  await c.obtener('y', cargar);
  assert.equal(c.datos.size, 2, 'tamaño máximo');
});

test('Cache no guarda los fallos', async () => {
  const c = new Cache({ ttlMs: 10_000 });
  await assert.rejects(c.obtener('k', async () => { throw new Error('caída'); }));
  assert.equal(await c.obtener('k', async () => 'ok'), 'ok');
});

test('compactar convierte un vector de estado de OpenSky', () => {
  const s = ['abc123', 'IBE123  ', 'Spain', 1, 2, -3.7, 40.4, 10000, false, 230.5, 90, -1.2, null, 10100, '7000', false, 0];
  assert.deepEqual(compactar(s), ['abc123', 'IBE123', 'Spain', 40.4, -3.7, 10000, 0, 230.5, 90, -1.2, '7000']);
  assert.equal(compactar(['abc', '', 'X', 1, 2, null, null]), null);
});

test('normalizarLectura acepta el esquema y descarta lo demás', () => {
  const ok = normalizarLectura('{"id":"target_01","room":"Sala","coords":[-0.18,-78.48],"state":"movimiento","resp":15.4,"extra":1}');
  assert.equal(ok, '{"id":"target_01","room":"Sala","coords":[-0.18,-78.48],"state":"movimiento","resp":15}');
  assert.equal(normalizarLectura('no json'), null);
  assert.equal(normalizarLectura('{"id":1,"coords":[0,0]}'), null);
  assert.equal(normalizarLectura('{"id":"a","coords":["x",0]}'), null);
  assert.match(normalizarLectura('{"id":"a","coords":[0,0],"state":"<script>"}'), /"state":"quieto"/);
});
