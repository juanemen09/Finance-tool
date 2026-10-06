// Cámaras públicas de todo el mundo con Windy Webcams API v3 (https://api.windy.com/webcams): más de 70 000
// cámaras de ciudades, playas, volcanes, puertos y carreteras que sus dueños publican en Windy. Clave gratuita
// (WINDY_API_KEY). Windy exige citarlo: «Webcams provided by Windy.com», con enlace a cada cámara.
//
// Plan gratuito: hasta 50 por página y offset hasta 1000; las URL de imagen caducan en ~10 min, así que la lista
// solo trae la ubicación y la imagen se pide al abrir cada cámara.

import { Cache, ErrorFuente, bboxEnRejilla, dentro, pedirJson } from './util.js';

const API = 'https://api.windy.com/webcams/api/v3/webcams';
const POR_PAGINA = 50;
const PAGINAS = 4; // hasta 200 cámaras por zona visible
const cacheZonas = new Cache({ ttlMs: 30 * 60_000, max: 60 });
const cacheDetalle = new Cache({ ttlMs: 5 * 60_000, max: 300 });
const estado = { activo: false, error: null };

export function estadoWindy() {
  return { ...estado, activo: Boolean(process.env.WINDY_API_KEY) };
}

const cabeceras = () => ({ 'x-windy-api-key': process.env.WINDY_API_KEY });

// Vector compacto, el mismo de las demás cámaras: [id, nombre, lat, lon, fuente, url_imagen|null, url_video|null]
export function compactarWindy(w) {
  const loc = w.location ?? {};
  if (loc.latitude == null || loc.longitude == null) return null;
  if (w.status && w.status !== 'active') return null;
  const lugar = [loc.city, loc.country].filter(Boolean).join(', ');
  const titulo = w.title || `Cámara ${w.webcamId}`;
  const nombre = lugar && !(loc.city && titulo.includes(loc.city)) ? `${titulo} · ${lugar}` : titulo;
  return [`windy:${w.webcamId}`, nombre, loc.latitude, loc.longitude, 'Windy', null, null];
}

async function zona(caja) {
  const clave = `${caja.lamin},${caja.lomin},${caja.lamax},${caja.lomax}`;
  return cacheZonas.obtener(clave, async () => {
    const out = [];
    for (let p = 0; p < PAGINAS; p++) {
      const q = new URLSearchParams({
        bbox: `${caja.lamax},${caja.lomax},${caja.lamin},${caja.lomin}`, // Windy: norte, este, sur, oeste
        limit: String(POR_PAGINA),
        offset: String(p * POR_PAGINA),
        include: 'location',
      });
      const { json } = await pedirJson(`${API}?${q}`, { headers: cabeceras(), timeoutMs: 20000 });
      const lote = (json?.webcams ?? []).map(compactarWindy).filter(Boolean);
      out.push(...lote);
      if ((json?.webcams ?? []).length < POR_PAGINA || (p + 1) * POR_PAGINA >= (json?.total ?? 0)) break;
    }
    return out;
  });
}

export async function camarasWindyEn(bbox) {
  if (!process.env.WINDY_API_KEY) return [];
  try {
    const caja = bboxEnRejilla(bbox, 1);
    const lista = await zona(caja);
    estado.error = null;
    return lista.filter((c) => dentro(bbox, c[2], c[3]));
  } catch (e) {
    estado.error = e.status === 429 ? 'cupo de Windy agotado por ahora' : e.message;
    return [];
  }
}

// Al abrir una cámara: imagen fresca (la URL caduca), reproductor y enlace a su página en Windy.
export async function detalleWindy(id) {
  if (!process.env.WINDY_API_KEY) throw new ErrorFuente('falta WINDY_API_KEY', { status: 404 });
  return cacheDetalle.obtener(id, async () => {
    const { json } = await pedirJson(`${API}/${id}?include=images,player,urls,location`, { headers: cabeceras(), timeoutMs: 15000 });
    const img = json?.images?.current ?? json?.images?.daylight ?? {};
    return {
      imagen: img.preview || img.thumbnail || null,
      reproductor: json?.player?.day || json?.player?.live || null,
      enlace: json?.urls?.detail || `https://www.windy.com/webcams/${id}`,
      titulo: json?.title ?? null,
    };
  });
}
