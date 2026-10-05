// Emulador por software de RuView: imita la telemetría de presencia por Wi-Fi (CSI) sin hardware.
// Cada 2 s envía por WebSocket un JSON compacto por objetivo:
//   { "id": "target_01", "room": "Sala", "coords": [lat, lng], "state": "movimiento", "resp": 15 }
// Los datos son SIMULADOS: caminata aleatoria por el plano de shared/plano.js, cruzando solo por las puertas.
// Coste por tick: unas pocas sumas por objetivo, sin bucles largos ni trigonometría pesada.

import { fileURLToPath } from 'node:url';
import WebSocket from 'ws';
import { HABITACIONES, ORIGEN_POR_DEFECTO, aLatLng, habitacionEn, rutaDePuertas } from './shared/plano.js';

export const INTERVALO_MS = 2000;
const MARGEN = 0.4; // metros a las paredes
const PASO_MIN = 0.9; // metros por tick (≈ 0,45-0,7 m/s al caminar)
const PASO_MAX = 1.4;

export function crearObjetivo(id, rng = Math.random) {
  const h = HABITACIONES[Math.floor(rng() * HABITACIONES.length)];
  const [x, y] = puntoEn(h, rng);
  return { id, x, y, ruta: [], quieto: 0, resp: 14 + rng() * 3 };
}

function puntoEn(h, rng) {
  return [h.x0 + MARGEN + rng() * (h.x1 - h.x0 - 2 * MARGEN), h.y0 + MARGEN + rng() * (h.y1 - h.y0 - 2 * MARGEN)];
}

function planificar(o, rng) {
  if (rng() < 0.35) {
    o.quieto = 2 + Math.floor(rng() * 7);
    return;
  }
  const actual = habitacionEn(o.x, o.y)?.nombre ?? HABITACIONES[0].nombre;
  const destino = rng() < 0.4 ? HABITACIONES[Math.floor(rng() * HABITACIONES.length)] : HABITACIONES.find((h) => h.nombre === actual);
  const puertas = rutaDePuertas(actual, destino.nombre) ?? [];
  o.ruta = [...puertas.map((p) => [p.x, p.y]), puntoEn(destino, rng)];
}

// Avanza un tick y devuelve el mensaje listo para enviar.
export function avanzar(o, origen, rng = Math.random) {
  let estado = 'quieto';
  if (o.quieto > 0) {
    o.quieto -= 1;
  } else {
    if (o.ruta.length === 0) planificar(o, rng);
    if (o.ruta.length > 0) {
      let presupuesto = PASO_MIN + rng() * (PASO_MAX - PASO_MIN);
      while (presupuesto > 0 && o.ruta.length > 0) {
        const [tx, ty] = o.ruta[0];
        const dx = tx - o.x;
        const dy = ty - o.y;
        const d = Math.hypot(dx, dy);
        if (d <= presupuesto) {
          o.x = tx;
          o.y = ty;
          o.ruta.shift();
          presupuesto -= d;
        } else {
          o.x += (dx / d) * presupuesto;
          o.y += (dy / d) * presupuesto;
          presupuesto = 0;
        }
      }
      estado = 'movimiento';
    }
  }
  // Respiración: deriva suave hacia 13-15 rpm en reposo y 17-20 en movimiento.
  const objetivoResp = estado === 'movimiento' ? 18.5 : 14;
  o.resp += (objetivoResp - o.resp) * 0.3 + (rng() - 0.5) * 0.8;
  return {
    id: o.id,
    room: habitacionEn(o.x, o.y)?.nombre ?? 'Desconocida',
    coords: aLatLng(origen, o.x, o.y),
    state: estado,
    resp: Math.round(o.resp),
  };
}

function origenDesdeEntorno() {
  const lat = Number.parseFloat(process.env.PLANO_LAT);
  const lng = Number.parseFloat(process.env.PLANO_LNG);
  return Number.isFinite(lat) && Number.isFinite(lng) ? { lat, lng } : ORIGEN_POR_DEFECTO;
}

function main() {
  const url = process.env.ARGOS_INGEST_URL;
  if (!url) {
    console.error('[simulador] falta ARGOS_INGEST_URL; lo arranca server.js');
    process.exit(1);
  }
  const origen = origenDesdeEntorno();
  const total = Math.min(Math.max(Number.parseInt(process.env.RUVIEW_OBJETIVOS ?? '2', 10) || 2, 1), 6);
  const objetivos = Array.from({ length: total }, (_, i) => crearObjetivo(`target_${String(i + 1).padStart(2, '0')}`));
  let ws = null;
  let espera = 1000;

  const conectar = () => {
    ws = new WebSocket(url);
    ws.on('open', () => {
      espera = 1000;
    });
    ws.on('close', () => {
      ws = null;
      setTimeout(conectar, espera);
      espera = Math.min(espera * 2, 30000);
    });
    ws.on('error', () => {}); // el cierre posterior reintenta
  };
  conectar();

  setInterval(() => {
    for (const o of objetivos) {
      const msg = avanzar(o, origen);
      if (ws?.readyState === WebSocket.OPEN) ws.send(JSON.stringify(msg));
    }
  }, INTERVALO_MS);

  const salir = () => {
    ws?.close();
    process.exit(0);
  };
  process.on('SIGTERM', salir);
  process.on('SIGINT', salir);
  process.on('disconnect', salir); // si muere el servidor padre
}

if (process.argv[1] && fileURLToPath(import.meta.url) === process.argv[1]) main();
