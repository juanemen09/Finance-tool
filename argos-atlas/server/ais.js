// Barcos en vivo desde redes AIS abiertas:
// - Digitraffic (Fintraffic, Finlandia): AIS real del Báltico, sin clave, CC BY 4.0. Siempre activo.
// - aisstream.io: AIS mundial por WebSocket con clave gratuita (AISSTREAM_API_KEY). Se suscribe solo a la zona que
//   estás mirando, así el servidor no procesa el tráfico de todo el planeta.

import WebSocket from 'ws';
import { Cache, bboxEnRejilla, dentro, pedirJson } from './util.js';

const DIGITRAFFIC = 'https://meri.digitraffic.fi/api/ais/v1';
const CABECERA_DT = { 'Digitraffic-User': 'ArgosAtlas/0.1' };
const MAX_EDAD_MS = 60 * 60_000; // posiciones de más de 1 h no se pintan
const MAX_RESULTADOS = 4000;

const cachePosiciones = new Cache({ ttlMs: 30_000, max: 1 });
const cacheNombres = new Cache({ ttlMs: 6 * 3600_000, max: 1 });
const estado = { digitraffic: null, aisstream: process.env.AISSTREAM_API_KEY ? 'conectando' : 'sin clave' };

export function estadoAis() {
  return { ...estado, barcosAisstream: flota.size };
}

// Vector compacto: [mmsi, lat, lon, velocidad_nudos, rumbo_fondo, proa|null, nombre, fuente]
async function posicionesDigitraffic() {
  return cachePosiciones.obtener('todo', async () => {
    const [{ json }, nombres] = await Promise.all([
      pedirJson(`${DIGITRAFFIC}/locations`, { headers: CABECERA_DT, timeoutMs: 25000 }),
      nombresDigitraffic().catch(() => new Map()),
    ]);
    const limite = Date.now() - MAX_EDAD_MS;
    const out = [];
    for (const f of json.features ?? []) {
      const [lon, lat] = f.geometry?.coordinates ?? [];
      const p = f.properties ?? {};
      if (lat == null || lon == null) continue;
      if (p.timestampExternal && p.timestampExternal < limite) continue;
      const mmsi = f.mmsi ?? p.mmsi;
      out.push([mmsi, lat, lon, p.sog ?? null, p.cog ?? null, p.heading === 511 ? null : (p.heading ?? null), nombres.get(mmsi) ?? '', 'dt']);
    }
    return out;
  });
}

async function nombresDigitraffic() {
  return cacheNombres.obtener('todo', async () => {
    const { json } = await pedirJson(`${DIGITRAFFIC}/vessels`, { headers: CABECERA_DT, timeoutMs: 25000 });
    return new Map((json ?? []).map((v) => [v.mmsi, (v.name ?? '').trim()]));
  });
}

// --- aisstream.io --------------------------------------------------------------------------------------------
const flota = new Map(); // mmsi -> vector compacto + marca de tiempo al final
let socket = null;
let cajaSuscrita = null;
let cajaPendiente = null;
let temporizadorSuscripcion = null;
let espera = 2000;

function conectarAisstream() {
  const clave = process.env.AISSTREAM_API_KEY;
  if (!clave) return;
  socket = new WebSocket('wss://stream.aisstream.io/v0/stream');
  socket.on('open', () => {
    espera = 2000;
    estado.aisstream = 'conectado';
    if (cajaSuscrita) suscribir(cajaSuscrita);
  });
  socket.on('message', (raw) => {
    let m;
    try {
      m = JSON.parse(raw);
    } catch {
      return;
    }
    if (m.error) {
      estado.aisstream = `error: ${m.error}`;
      return;
    }
    const meta = m.MetaData;
    const pr = m.Message?.PositionReport;
    if (!meta || !pr) return;
    const heading = pr.TrueHeading === 511 ? null : pr.TrueHeading;
    flota.set(meta.MMSI, [meta.MMSI, meta.latitude, meta.longitude, pr.Sog, pr.Cog, heading, (meta.ShipName ?? '').trim(), 'as', Date.now()]);
  });
  socket.on('close', () => {
    socket = null;
    estado.aisstream = 'reconectando';
    setTimeout(conectarAisstream, espera);
    espera = Math.min(espera * 2, 60000);
  });
  socket.on('error', () => {});
}

function suscribir(caja) {
  if (socket?.readyState !== WebSocket.OPEN) return;
  socket.send(
    JSON.stringify({
      APIKey: process.env.AISSTREAM_API_KEY,
      BoundingBoxes: [[[caja.lamin, caja.lomin], [caja.lamax, caja.lomax]]],
      FilterMessageTypes: ['PositionReport'],
    }),
  );
}

// aisstream admite como mucho una actualización de suscripción por segundo: se agrupan los movimientos del mapa.
function pedirZona(bbox) {
  const caja = bboxEnRejilla(bbox, 1);
  if (cajaSuscrita && JSON.stringify(caja) === JSON.stringify(cajaSuscrita)) return;
  cajaPendiente = caja;
  if (temporizadorSuscripcion) return;
  temporizadorSuscripcion = setTimeout(() => {
    temporizadorSuscripcion = null;
    cajaSuscrita = cajaPendiente;
    suscribir(cajaSuscrita);
  }, 1500);
}

// Limpieza: se olvidan los barcos sin noticias en la última hora (memoria acotada aunque pasen días).
setInterval(() => {
  const limite = Date.now() - MAX_EDAD_MS;
  for (const [mmsi, v] of flota) if (v[8] < limite) flota.delete(mmsi);
}, 60_000).unref();

conectarAisstream();

// --------------------------------------------------------------------------------------------------------------
export async function barcosEn(bbox) {
  if (process.env.AISSTREAM_API_KEY) pedirZona(bbox);
  const porMmsi = new Map();
  try {
    for (const b of await posicionesDigitraffic()) if (dentro(bbox, b[1], b[2])) porMmsi.set(b[0], b);
    estado.digitraffic = 'ok';
  } catch (e) {
    estado.digitraffic = e.message;
  }
  for (const v of flota.values()) if (dentro(bbox, v[1], v[2])) porMmsi.set(v[0], v.slice(0, 8));
  const barcos = [...porMmsi.values()];
  return { barcos: barcos.slice(0, MAX_RESULTADOS), recortado: barcos.length > MAX_RESULTADOS };
}
