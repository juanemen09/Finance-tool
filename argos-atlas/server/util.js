// Utilidades del proxy: bounding box, caché con TTL y fetch con tiempo máximo.

export const USER_AGENT = 'ArgosAtlas/0.1 (uso personal, local)';

// Lee lamin/lomin/lamax/lomax de la query. Devuelve null si faltan o no son válidos.
export function leerBbox(q) {
  const v = ['lamin', 'lomin', 'lamax', 'lomax'].map((k) => Number.parseFloat(q?.[k]));
  if (v.some((n) => !Number.isFinite(n))) return null;
  let [lamin, lomin, lamax, lomax] = v;
  lamin = clamp(lamin, -90, 90);
  lamax = clamp(lamax, -90, 90);
  // Leaflet puede dar longitudes fuera de ±180 al dar la vuelta al mundo: se recorta al rango válido.
  if (lomax - lomin >= 360) [lomin, lomax] = [-180, 180];
  lomin = clamp(lomin, -180, 180);
  lomax = clamp(lomax, -180, 180);
  if (lamin >= lamax || lomin >= lomax) return null;
  return { lamin, lomin, lamax, lomax };
}

export function dentro(b, lat, lon) {
  return lat >= b.lamin && lat <= b.lamax && lon >= b.lomin && lon <= b.lomax;
}

// Redondea la caja hacia fuera a una rejilla, para que vistas parecidas compartan caché aguas arriba.
export function bboxEnRejilla(b, paso) {
  return {
    lamin: Math.max(-90, Math.floor(b.lamin / paso) * paso),
    lomin: Math.max(-180, Math.floor(b.lomin / paso) * paso),
    lamax: Math.min(90, Math.ceil(b.lamax / paso) * paso),
    lomax: Math.min(180, Math.ceil(b.lomax / paso) * paso),
  };
}

function clamp(v, a, b) {
  return Math.min(Math.max(v, a), b);
}

// Caché pequeña con TTL, tamaño máximo y peticiones en curso compartidas (dos pestañas = una sola llamada).
export class Cache {
  constructor({ ttlMs, max = 50 }) {
    this.ttlMs = ttlMs;
    this.max = max;
    this.datos = new Map();
    this.enCurso = new Map();
  }

  async obtener(clave, cargar) {
    const e = this.datos.get(clave);
    if (e && Date.now() - e.t < this.ttlMs) return e.v;
    if (this.enCurso.has(clave)) return this.enCurso.get(clave);
    const p = (async () => {
      try {
        const v = await cargar();
        this.datos.delete(clave);
        this.datos.set(clave, { t: Date.now(), v });
        while (this.datos.size > this.max) this.datos.delete(this.datos.keys().next().value);
        return v;
      } finally {
        this.enCurso.delete(clave);
      }
    })();
    this.enCurso.set(clave, p);
    return p;
  }

  ultimo(clave) {
    return this.datos.get(clave)?.v;
  }
}

export class ErrorFuente extends Error {
  constructor(mensaje, { status = 502, reintentarEn = null } = {}) {
    super(mensaje);
    this.status = status;
    this.reintentarEn = reintentarEn;
  }
}

export async function pedirJson(url, { headers = {}, timeoutMs = 15000 } = {}) {
  let r;
  try {
    r = await fetch(url, {
      headers: { 'User-Agent': USER_AGENT, Accept: 'application/json', ...headers },
      signal: AbortSignal.timeout(timeoutMs),
    });
  } catch (e) {
    throw new ErrorFuente(`sin respuesta de ${new URL(url).host}: ${e.name === 'TimeoutError' ? 'tiempo agotado' : e.message}`);
  }
  if (!r.ok) {
    await r.body?.cancel();
    throw new ErrorFuente(`${new URL(url).host} respondió ${r.status}`, { status: r.status === 429 ? 429 : 502 });
  }
  return { json: await r.json(), headers: r.headers };
}
