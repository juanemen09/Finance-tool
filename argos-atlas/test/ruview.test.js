// Adaptador de RuView contra un servidor falso que imita /ws/sensing del sensing-server real
// (mensajes `sensing_update` a 10 Hz, token Bearer obligatorio).
import assert from 'node:assert/strict';
import { once } from 'node:events';
import { createServer } from 'node:http';
import { test } from 'node:test';
import { WebSocketServer } from 'ws';
import { habitacionEn } from '../shared/plano.js';
import { aPlano, iniciarRuView, leerCalibracion, traducir } from '../server/ruview.js';

const ORIGEN = { lat: -0.18, lng: -78.48 };
const CAL = leerCalibracion({});

function actualizacion(extra = {}) {
  return {
    type: 'sensing_update',
    timestamp: 1759600000.1,
    source: 'esp32',
    tick: 42,
    nodes: [{ node_id: 1, rssi_dbm: -48, position: [0, 0, 0], amplitude: [1, 2], subcarrier_count: 2 }],
    features: { mean_rssi: -48, variance: 1, motion_band_power: 30, breathing_band_power: 2, dominant_freq_hz: 0.25 },
    classification: { motion_level: 'present_moving', presence: true, confidence: 0.8 },
    signal_field: { grid_size: [20, 1, 20], values: [] },
    vital_signs: { breathing_rate_bpm: 15.6, heart_rate_bpm: null, breathing_confidence: 0.7, heartbeat_confidence: 0, signal_quality: 0.9 },
    ...extra,
  };
}

test('el centro del mundo de RuView cae en el centro de la casa y -z es el norte', () => {
  assert.deepEqual(aPlano([0, 0, 0], CAL), [5, 6]);
  const [x, y] = aPlano([1, 0, -2], CAL);
  assert.ok(Math.abs(x - 6) < 1e-9 && Math.abs(y - 8) < 1e-9);
  assert.deepEqual(aPlano([100, 0, 100], CAL), [9.8, 0.2], 'recorta a la casa');
  const girado = aPlano([1, 0, 0], leerCalibracion({ RUVIEW_GIRO: '90' }));
  assert.ok(Math.abs(girado[0] - 5) < 1e-9 && Math.abs(girado[1] - 7) < 1e-9);
});

test('traduce personas con posición, movimiento, confianza y respiración', () => {
  const m = actualizacion({
    persons: [
      { id: 3, confidence: 0.91, keypoints: [], bbox: { x: 0, y: 0, width: 1, height: 1 }, zone: 'zone_1', position: [-3, 0, 3], motion_score: 40 },
      { id: 4, confidence: 0.5, keypoints: [], bbox: { x: 0, y: 0, width: 1, height: 1 }, zone: 'zone_2', position: [0, 0, 0], motion_score: 2 },
    ],
  });
  const [a, b] = traducir(m, ORIGEN, CAL);
  assert.equal(a.id, 'persona_3');
  assert.equal(a.room, 'Sala'); // (2, 3) en metros del plano
  assert.equal(a.state, 'movimiento');
  assert.equal(a.resp, 16);
  assert.equal(a.aprox, true);
  assert.equal(a.conf, 0.91);
  assert.equal(b.state, 'quieto');
  assert.equal(b.room, 'Pasillo', 'sin posición: en el sensor');
});

test('presencia sin personas (Wi-Fi solo RSSI) → un objetivo; ausencia → ninguno', () => {
  const sinPersonas = traducir(actualizacion({ source: 'wifi', vital_signs: { breathing_rate_bpm: 14, breathing_confidence: 0.1 } }), ORIGEN, CAL);
  assert.equal(sinPersonas.length, 1);
  assert.equal(sinPersonas[0].id, 'presencia');
  assert.equal(sinPersonas[0].resp, null, 'respiración con poca confianza no se muestra');
  const vacia = traducir(actualizacion({ classification: { motion_level: 'absent', presence: false, confidence: 0.9 } }), ORIGEN, CAL);
  assert.deepEqual(vacia, []);
});

test('se conecta con token, publica una vez por segundo y da de baja a quien se va', async () => {
  const http = createServer();
  const wss = new WebSocketServer({ server: http, path: '/ws/sensing' });
  const autorizaciones = [];
  let enviar = actualizacion({ persons: [{ id: 1, confidence: 0.9, position: [1, 0, 1], motion_score: 50 }] });
  wss.on('connection', (ws, req) => {
    autorizaciones.push(req.headers.authorization);
    const t = setInterval(() => ws.send(JSON.stringify(enviar)), 100); // 10 Hz como RuView
    ws.on('close', () => clearInterval(t));
  });
  http.listen(0, '127.0.0.1');
  await once(http, 'listening');

  const publicados = [];
  const bajas = [];
  const estados = [];
  const ruview = iniciarRuView({
    url: `ws://127.0.0.1:${http.address().port}/ws/sensing`,
    token: 'secreto',
    origen: ORIGEN,
    publicar: (t) => publicados.push(JSON.parse(t)),
    baja: (id) => bajas.push(id),
    estado: (e) => estados.push(e),
  });

  await new Promise((r) => setTimeout(r, 2300));
  assert.deepEqual(autorizaciones, ['Bearer secreto']);
  assert.ok(publicados.length >= 1 && publicados.length <= 3, `limitado a ~1/s, hubo ${publicados.length}`);
  assert.equal(publicados[0].id, 'persona_1');
  assert.ok(habitacionEn(...aPlano([1, 0, 1], CAL)));
  const ultimo = estados.at(-1);
  assert.equal(ultimo.conectado, true);
  assert.equal(ultimo.fuente, 'esp32');
  assert.equal(ultimo.nodos, 1);

  enviar = actualizacion({ classification: { motion_level: 'absent', presence: false, confidence: 0.9 } });
  await new Promise((r) => setTimeout(r, 1300));
  assert.deepEqual(bajas, ['persona_1']);
  assert.equal(estados.at(-1).presencia, false);

  // Si RuView se cae, las presencias activas se dan de baja.
  enviar = actualizacion({ persons: [{ id: 7, confidence: 0.9, position: [0, 0, 0], motion_score: 0 }] });
  await new Promise((r) => setTimeout(r, 1300));
  for (const c of wss.clients) c.terminate();
  await new Promise((r) => setTimeout(r, 200));
  assert.deepEqual(bajas, ['persona_1', 'persona_7']);
  assert.equal(estados.at(-1).conectado, false);

  ruview.cerrar();
  for (const c of wss.clients) c.terminate();
  wss.close();
  http.close();
});

test('un token rechazado se informa con un motivo claro', async () => {
  let intentos = 0;
  const http = createServer();
  http.on('upgrade', (_req, socket) => {
    intentos++;
    socket.end('HTTP/1.1 401 Unauthorized\r\nContent-Length: 0\r\n\r\n');
  });
  http.listen(0, '127.0.0.1');
  await once(http, 'listening');
  const estados = [];
  const ruview = iniciarRuView({
    url: `ws://127.0.0.1:${http.address().port}/ws/sensing`,
    token: 'malo',
    origen: ORIGEN,
    publicar: () => {},
    baja: () => {},
    estado: (e) => estados.push(e),
  });
  await new Promise((r) => setTimeout(r, 1500));
  ruview.cerrar();
  http.close();
  assert.ok(estados.some((e) => e.error === 'token rechazado (RUVIEW_API_TOKEN)'), JSON.stringify(estados));
  assert.ok(intentos >= 2, `debe reintentar, hubo ${intentos} intento(s)`);
});
