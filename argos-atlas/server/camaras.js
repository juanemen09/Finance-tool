// Cámaras públicas reales con imagen en vivo, leídas de los catálogos abiertos de cada operador (no hay lista fija
// que se quede vieja):
// - Transport for London, JamCams (Londres): imagen y clip de vídeo corto que se renuevan cada pocos minutos.
// - NYC DOT, Traffic Management Center (Nueva York): imagen en vivo.
// - Fintraffic, cámaras de carretera (Finlandia): imagen por preset.
// El servidor solo entrega coordenadas y URLs: las imágenes las pide el navegador al abrir cada cámara.

import { Cache, ErrorFuente, dentro, pedirJson } from './util.js';
import { camarasWindyEn, estadoWindy } from './windy.js';

// Catálogo completo: 6 h. Si alguna fuente falló, se reintenta a los 5 min en vez de esperar 6 h sin ella.
const cache = new Cache({ ttlMs: 6 * 3600_000, max: 1, ttlDe: (c) => (c.parcial ? 5 * 60_000 : 6 * 3600_000) });
const estado = {};

export function estadoCamaras() {
  const w = estadoWindy();
  return { ...estado, Windy: w.activo ? (w.error ? `error: ${w.error}` : 'activo') : 'sin clave' };
}

// Vector compacto: [id, nombre, lat, lon, fuente, url_imagen, url_video|null]
async function tfl() {
  const { json } = await pedirJson('https://api.tfl.gov.uk/Place/Type/JamCam', { timeoutMs: 20000 });
  return (json ?? []).flatMap((c) => {
    const prop = Object.fromEntries((c.additionalProperties ?? []).map((p) => [p.key, p.value]));
    if (prop.available === 'false' || !prop.imageUrl || c.lat == null) return [];
    return [[`tfl:${c.id}`, c.commonName ?? c.id, c.lat, c.lon, 'TfL Londres', prop.imageUrl, prop.videoUrl ?? null]];
  });
}

async function nyc() {
  const { json } = await pedirJson('https://webcams.nyctmc.org/api/cameras', { timeoutMs: 40000 });
  return (json ?? []).flatMap((c) => {
    if (c.latitude == null || String(c.isOnline) === 'false') return [];
    const img = c.imageUrl || `https://webcams.nyctmc.org/api/cameras/${c.id}/image`;
    return [[`nyc:${c.id}`, c.name ?? c.id, Number(c.latitude), Number(c.longitude), 'NYC DOT', img, null]];
  });
}

async function fintraffic() {
  const { json } = await pedirJson('https://tie.digitraffic.fi/api/weathercam/v1/stations', {
    headers: { 'Digitraffic-User': 'ArgosAtlas/0.1' },
    timeoutMs: 20000,
  });
  return (json?.features ?? []).flatMap((f) => {
    const [lon, lat] = f.geometry?.coordinates ?? [];
    const p = f.properties ?? {};
    const preset = (p.presets ?? []).find((x) => x.inCollection !== false);
    if (lat == null || !preset?.id || p.collectionStatus === 'REMOVED_PERMANENTLY') return [];
    return [[`fi:${preset.id}`, p.name ?? preset.id, lat, lon, 'Fintraffic', `https://weathercam.digitraffic.fi/${preset.id}.jpg`, null]];
  });
}

const FUENTES = { 'TfL Londres': tfl, 'NYC DOT': nyc, Fintraffic: fintraffic };

async function catalogo() {
  return cache.obtener('todo', async () => {
    const resultados = await Promise.allSettled(Object.values(FUENTES).map((f) => f()));
    const todas = [];
    let parcial = false;
    Object.keys(FUENTES).forEach((nombre, i) => {
      const r = resultados[i];
      estado[nombre] = r.status === 'fulfilled' ? `${r.value.length} cámaras` : `error: ${r.reason?.message ?? r.reason}`;
      if (r.status === 'fulfilled') todas.push(...r.value);
      else parcial = true;
    });
    if (todas.length === 0) throw new ErrorFuente('ninguna fuente de cámaras respondió');
    return { todas, parcial };
  });
}

// Catálogos fijos (TfL, NYC, Fintraffic) más las de Windy en la zona visible, de todo el mundo.
export async function camarasEn(bbox) {
  const [fijas, windy] = await Promise.all([
    catalogo().then(({ todas }) => todas).catch(() => []),
    camarasWindyEn(bbox),
  ]);
  if (fijas.length === 0 && windy.length === 0 && Object.values(estado).every((v) => String(v).startsWith('error'))) {
    throw new ErrorFuente('ninguna fuente de cámaras respondió');
  }
  const camaras = fijas.filter((c) => dentro(bbox, c[2], c[3])).concat(windy);
  return { camaras, total: fijas.length + windy.length };
}
