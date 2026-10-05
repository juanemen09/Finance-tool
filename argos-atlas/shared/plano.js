// Plano 2D del hogar, compartido por el emulador (Node) y el mapa (navegador).
// Las habitaciones son rectángulos en metros (x hacia el este, y hacia el norte) desde la esquina suroeste.
// Las puertas están sobre la pared común de dos habitaciones: cruzar por ellas mantiene las trayectorias dentro del plano.

export const HABITACIONES = [
  { nombre: 'Sala', x0: 0, y0: 0, x1: 6, y1: 5 },
  { nombre: 'Cocina', x0: 6, y0: 0, x1: 10, y1: 5 },
  { nombre: 'Pasillo', x0: 0, y0: 5, x1: 10, y1: 7 },
  { nombre: 'Habitación Principal', x0: 0, y0: 7, x1: 10, y1: 12 },
];

export const PUERTAS = [
  { entre: ['Sala', 'Pasillo'], x: 3, y: 5, ancho: 1, eje: 'x' },
  { entre: ['Cocina', 'Pasillo'], x: 8, y: 5, ancho: 0.9, eje: 'x' },
  { entre: ['Sala', 'Cocina'], x: 6, y: 2.5, ancho: 1.2, eje: 'y' },
  { entre: ['Pasillo', 'Habitación Principal'], x: 5, y: 7, ancho: 1, eje: 'x' },
];

// Posición del sensor (el nodo ESP32 de RuView, cuando exista) para dibujar los anillos del radar.
export const SENSOR = { x: 7.5, y: 6 };

// Origen por defecto: un punto genérico en Quito. Cámbialo con PLANO_LAT / PLANO_LNG en .env, sin subir tu dirección al repo.
export const ORIGEN_POR_DEFECTO = { lat: -0.18065, lng: -78.48525 };

const METROS_POR_GRADO = 111320;

export function aLatLng(origen, x, y) {
  const lat = origen.lat + y / METROS_POR_GRADO;
  const lng = origen.lng + x / (METROS_POR_GRADO * Math.cos((origen.lat * Math.PI) / 180));
  return [round6(lat), round6(lng)];
}

function round6(v) {
  return Math.round(v * 1e6) / 1e6;
}

export function habitacionEn(x, y) {
  return HABITACIONES.find((h) => x >= h.x0 && x <= h.x1 && y >= h.y0 && y <= h.y1) ?? null;
}

export function habitacion(nombre) {
  return HABITACIONES.find((h) => h.nombre === nombre);
}

export function puertaEntre(a, b) {
  return PUERTAS.find((p) => p.entre.includes(a) && p.entre.includes(b)) ?? null;
}

// Ruta más corta (en número de puertas) entre dos habitaciones: lista de puertas a cruzar.
export function rutaDePuertas(desde, hasta) {
  if (desde === hasta) return [];
  const previo = new Map([[desde, null]]);
  const cola = [desde];
  while (cola.length) {
    const actual = cola.shift();
    for (const p of PUERTAS) {
      if (!p.entre.includes(actual)) continue;
      const vecina = p.entre[0] === actual ? p.entre[1] : p.entre[0];
      if (previo.has(vecina)) continue;
      previo.set(vecina, { desde: actual, puerta: p });
      if (vecina === hasta) {
        const ruta = [];
        for (let n = hasta; previo.get(n); n = previo.get(n).desde) ruta.unshift(previo.get(n).puerta);
        return ruta;
      }
      cola.push(vecina);
    }
  }
  return null;
}
