// Adaptador de RuView real: se conecta al WebSocket del sensing-server (/ws/sensing) y traduce cada
// `sensing_update` al esquema de Argos-Atlas, ya colocado sobre el plano de la casa.
//
// Qué manda RuView (v2/crates/wifi-densepose-sensing-server, struct SensingUpdate):
//   { type: "sensing_update", source: "esp32" | "wifi" | "simulated" | ..., nodes: [...],
//     classification: { motion_level: "absent" | "present_still" | "present_moving", presence, confidence },
//     vital_signs?: { breathing_rate_bpm, breathing_confidence, ... },
//     persons?: [{ id, confidence, zone, position: [x, 0, z], motion_score: 0..100 }], estimated_persons? }
// `position` es el pico del campo de señal en metros del "Observatory" de RuView, centrado en la sala (x hacia la
// derecha, z hacia el observador). RuView avisa de que es una posición aproximada, no una triangulación: se marca así.
//
// RuView emite a 10 Hz; aquí se procesa como mucho una vez por segundo (se queda solo con el último mensaje).

import WebSocket from 'ws';
import { HABITACIONES, SENSOR, aLatLng, habitacionEn } from '../shared/plano.js';

const PERIODO_MS = 1000;
const UMBRAL_MOVIMIENTO = 15; // motion_score de RuView va de 0 a 100
const CONFIANZA_RESPIRACION = 0.3;

const X0 = Math.min(...HABITACIONES.map((h) => h.x0));
const X1 = Math.max(...HABITACIONES.map((h) => h.x1));
const Y0 = Math.min(...HABITACIONES.map((h) => h.y0));
const Y1 = Math.max(...HABITACIONES.map((h) => h.y1));

function num(v, porDefecto) {
  const n = Number.parseFloat(v);
  return Number.isFinite(n) ? n : porDefecto;
}

// Calibración: dónde cae en el plano el origen del mundo de RuView, giro y escala. Por defecto, el centro de la casa.
export function leerCalibracion(env = process.env) {
  return {
    ox: num(env.RUVIEW_ORIGEN_X, (X0 + X1) / 2),
    oy: num(env.RUVIEW_ORIGEN_Y, (Y0 + Y1) / 2),
    giro: (num(env.RUVIEW_GIRO, 0) * Math.PI) / 180,
    escala: num(env.RUVIEW_ESCALA, 1),
  };
}

// Mundo de RuView (x, z) → metros del plano (x hacia el este, y hacia el norte), recortado a la casa.
export function aPlano([wx, , wz], cal) {
  const ex = wx * cal.escala;
  const ny = -wz * cal.escala; // z de RuView apunta hacia el observador: el norte del plano es -z
  const x = cal.ox + ex * Math.cos(cal.giro) - ny * Math.sin(cal.giro);
  const y = cal.oy + ex * Math.sin(cal.giro) + ny * Math.cos(cal.giro);
  return [Math.min(Math.max(x, X0 + 0.2), X1 - 0.2), Math.min(Math.max(y, Y0 + 0.2), Y1 - 0.2)];
}

// Un `sensing_update` → lecturas por persona en el esquema de Argos-Atlas.
export function traducir(m, origen, cal) {
  const cls = m.classification ?? {};
  const presente = cls.presence === true || (cls.motion_level && cls.motion_level !== 'absent');
  const vs = m.vital_signs;
  const resp = vs?.breathing_rate_bpm != null && (vs.breathing_confidence ?? 0) >= CONFIANZA_RESPIRACION ? Math.round(vs.breathing_rate_bpm) : null;
  const movimientoSala = cls.motion_level === 'present_moving';

  const lectura = (id, x, y, enMovimiento, aprox, conf) => ({
    id,
    room: habitacionEn(x, y)?.nombre ?? 'Desconocida',
    coords: aLatLng(origen, x, y),
    state: enMovimiento ? 'movimiento' : 'quieto',
    resp,
    aprox,
    conf: conf == null ? null : Math.round(conf * 100) / 100,
  });

  const personas = Array.isArray(m.persons) ? m.persons : [];
  if (personas.length > 0) {
    return personas.map((p) => {
      const pos = Array.isArray(p.position) ? p.position : [0, 0, 0];
      const sinPosicion = pos.every((v) => !v);
      const [x, y] = sinPosicion ? [SENSOR.x, SENSOR.y] : aPlano(pos, cal);
      const mov = p.motion_score != null ? p.motion_score >= UMBRAL_MOVIMIENTO : movimientoSala;
      return lectura(`persona_${p.id}`, x, y, mov, true, p.confidence);
    });
  }
  // Presencia sin personas localizadas (p. ej. modo Wi-Fi solo RSSI): un único objetivo en la zona del sensor.
  if (presente) return [lectura('presencia', SENSOR.x, SENSOR.y, movimientoSala, true, cls.confidence)];
  return [];
}

export function iniciarRuView({ url, token, origen, publicar, baja, estado }) {
  const cal = leerCalibracion();
  let ws = null;
  let espera = 1000;
  let reintento = null;
  let cerrado = false;
  let ultimo = null;
  let activos = new Set();
  let info = { conectado: false, fuente: null, nodos: 0, presencia: false, personas: 0, error: null };

  const emitirEstado = (cambios) => {
    info = { ...info, ...cambios };
    estado(info);
  };

  function conectar() {
    const sock = new WebSocket(url, { headers: token ? { Authorization: `Bearer ${token}` } : {}, handshakeTimeout: 10_000 });
    ws = sock;
    ws.on('open', () => {
      espera = 1000;
      emitirEstado({ conectado: true, error: null });
    });
    ws.on('message', (raw) => {
      ultimo = raw;
    });
    ws.on('unexpected-response', (_req, res) => {
      const motivo = { 401: 'token rechazado (RUVIEW_API_TOKEN)', 421: 'host no permitido (SENSING_ALLOWED_HOSTS)' }[res.statusCode];
      emitirEstado({ error: motivo ?? `RuView respondió ${res.statusCode}` });
      res.resume();
      sock.terminate(); // aborta el intento y emite 'close', que programa el reintento
    });
    ws.on('close', () => {
      ws = null;
      if (cerrado) return;
      // Sin conexión no se sabe quién sigue ahí: se quitan las presencias en vez de dejarlas congeladas.
      for (const id of activos) baja(id);
      activos = new Set();
      ultimo = null;
      emitirEstado({ conectado: false, presencia: false, personas: 0 });
      reintento = setTimeout(conectar, espera);
      espera = Math.min(espera * 2, 30_000);
    });
    ws.on('error', (e) => {
      if (!info.error || info.conectado) emitirEstado({ error: e.code === 'ECONNREFUSED' ? 'RuView no está corriendo en esa dirección' : e.message });
    });
  }

  const temporizador = setInterval(() => {
    if (!ultimo) return;
    const raw = ultimo;
    ultimo = null;
    let m;
    try {
      m = JSON.parse(raw);
    } catch {
      return;
    }
    if (m.type !== 'sensing_update') return;
    const lecturas = traducir(m, origen, cal);
    const ahora = new Set(lecturas.map((l) => l.id));
    for (const id of activos) if (!ahora.has(id)) baja(id);
    activos = ahora;
    for (const l of lecturas) publicar(JSON.stringify(l));
    const nodos = Array.isArray(m.nodes) ? m.nodes.length : 0;
    const presencia = lecturas.length > 0;
    if (info.fuente !== m.source || info.nodos !== nodos || info.presencia !== presencia || info.personas !== lecturas.length) {
      emitirEstado({ fuente: m.source ?? null, nodos, presencia, personas: lecturas.length });
    }
  }, PERIODO_MS);
  temporizador.unref();

  conectar();
  return {
    estado: () => info,
    cerrar() {
      cerrado = true;
      clearInterval(temporizador);
      clearTimeout(reintento);
      ws?.terminate();
    },
  };
}
