// Conflictos casi en tiempo real desde GDELT 2.0 (https://www.gdeltproject.org): cada 15 minutos publica un ZIP con
// los eventos que codificó automáticamente de noticias de todo el mundo. Se quedan solo los de conflicto material:
//   18 = agresión, 19 = combate, 20 = violencia masiva no convencional (códigos CAMEO).
// Son eventos REPORTADOS en noticias, codificados por máquina: hay ruido y duplicados. Se agrupan por lugar y se
// muestran con sus fuentes para que cada uno se pueda comprobar.
//
// Sin clave. Al arrancar se cargan las últimas 2 h; después, cada archivo nuevo. Se guardan 24 h en memoria.

import { inflateRawSync } from 'node:zlib';
import { USER_AGENT, dentro } from './util.js';

const ULTIMO = 'http://data.gdeltproject.org/gdeltv2/lastupdate.txt';
const PERIODO_MS = 15 * 60_000;
const VENTANA_MS = 24 * 3600_000;
const ARCHIVOS_INICIALES = 8; // 2 h
const pausaEntreDescargas = () => Number(process.env.ARGOS_GDELT_PAUSA_MS ?? 6000); // GDELT: como mucho 1 petición cada 5 s
const MAX_EVENTOS = 60_000;

export const TIPOS = { 18: 'Agresión', 19: 'Combate', 20: 'Violencia masiva' };
const SUBTIPOS = { 183: 'Atentado suicida o con coche bomba', 190: 'Uso de fuerza militar', 193: 'Combate con armas ligeras', 194: 'Combate con artillería o tanques', 195: 'Ataque aéreo', 186: 'Asesinato', 200: 'Violencia masiva' };

const estado = { ultimoArchivo: null, archivos: 0, eventos: 0, error: null };
let eventos = []; // { id, t, tipo, sub, lat, lon, lugar, pais, fuentes, menciones, url, aprox }
const vistos = new Set(); // archivos ya procesados
let arrancado = false;

export function estadoConflictos() {
  return { ...estado };
}

// --- ZIP mínimo: GDELT publica un único CSV comprimido con deflate por archivo -------------------------------------
export function descomprimirZipUnico(buf) {
  // Directorio central: más fiable que la cabecera local (puede no traer el tamaño).
  let fin = -1;
  for (let i = buf.length - 22; i >= Math.max(0, buf.length - 65_557); i--) {
    if (buf.readUInt32LE(i) === 0x06054b50) {
      fin = i;
      break;
    }
  }
  if (fin < 0) throw new Error('ZIP sin directorio central');
  const dir = buf.readUInt32LE(fin + 16);
  if (buf.readUInt32LE(dir) !== 0x02014b50) throw new Error('ZIP con directorio central inválido');
  const metodo = buf.readUInt16LE(dir + 10);
  const comprimido = buf.readUInt32LE(dir + 20);
  const local = buf.readUInt32LE(dir + 42);
  if (buf.readUInt32LE(local) !== 0x04034b50) throw new Error('ZIP con cabecera local inválida');
  const inicio = local + 30 + buf.readUInt16LE(local + 26) + buf.readUInt16LE(local + 28);
  const datos = buf.subarray(inicio, inicio + comprimido);
  if (metodo === 0) return datos;
  if (metodo === 8) return inflateRawSync(datos);
  throw new Error(`ZIP con compresión no soportada (${metodo})`);
}

// --- Filas del CSV de eventos de GDELT 2.0 (61 columnas separadas por tabulador, sin cabecera) ----------------------
const C = { id: 0, raiz: 25, codigo: 26, codigoRaiz: 28, quad: 29, menciones: 31, fuentes: 32, geoTipo: 51, geoNombre: 52, geoPais: 53, lat: 56, lon: 57, fecha: 59, url: 60 };

function fechaGdelt(s) {
  // AAAAMMDDHHMMSS en UTC
  if (!/^\d{14}$/.test(s)) return null;
  return Date.UTC(+s.slice(0, 4), +s.slice(4, 6) - 1, +s.slice(6, 8), +s.slice(8, 10), +s.slice(10, 12), +s.slice(12, 14));
}

export function parsearEventos(texto) {
  const out = [];
  for (const linea of texto.split('\n')) {
    const c = linea.split('\t');
    if (c.length < 61) continue;
    const tipo = Number(c[C.codigoRaiz]);
    if (!(tipo in TIPOS) || c[C.quad] !== '4') continue;
    const lat = Number.parseFloat(c[C.lat]);
    const lon = Number.parseFloat(c[C.lon]);
    if (!Number.isFinite(lat) || !Number.isFinite(lon) || (lat === 0 && lon === 0)) continue;
    const t = fechaGdelt(c[C.fecha]);
    if (!t) continue;
    out.push({
      id: c[C.id],
      t,
      tipo,
      sub: Number(c[C.codigo].slice(0, 3)),
      lat,
      lon,
      lugar: c[C.geoNombre] || 'Lugar sin nombre',
      pais: c[C.geoPais] || '',
      fuentes: Number(c[C.fuentes]) || 1,
      menciones: Number(c[C.menciones]) || 1,
      url: /^https?:\/\//.test(c[C.url]) ? c[C.url].slice(0, 500) : null,
      aprox: c[C.geoTipo] === '1' || c[C.geoTipo] === '5', // solo país o región: punto en el centro
    });
  }
  return out;
}

// --- Descarga ------------------------------------------------------------------------------------------------------
async function pedir(url, { binario = false } = {}) {
  let ultimoError;
  // GDELT publica sus enlaces con http; se intenta primero https.
  for (const u of [url.replace(/^http:/, 'https:'), url]) {
    try {
      const r = await fetch(u, { headers: { 'User-Agent': USER_AGENT }, signal: AbortSignal.timeout(60_000) });
      if (!r.ok) {
        await r.body?.cancel();
        throw new Error(`GDELT respondió ${r.status}`);
      }
      return binario ? Buffer.from(await r.arrayBuffer()) : await r.text();
    } catch (e) {
      ultimoError = e;
    }
  }
  throw ultimoError;
}

function urlDeExport(ms) {
  const d = new Date(ms);
  const p = (n) => String(n).padStart(2, '0');
  const sello = `${d.getUTCFullYear()}${p(d.getUTCMonth() + 1)}${p(d.getUTCDate())}${p(d.getUTCHours())}${p(d.getUTCMinutes())}00`;
  return `http://data.gdeltproject.org/gdeltv2/${sello}.export.CSV.zip`;
}

function selloDeUrl(url) {
  const m = url.match(/(\d{14})\.export\.CSV\.zip$/);
  return m ? fechaGdelt(m[1]) : null;
}

async function cargarArchivo(url) {
  if (vistos.has(url)) return;
  vistos.add(url);
  try {
    const csv = descomprimirZipUnico(await pedir(url, { binario: true })).toString('utf8');
    const nuevos = parsearEventos(csv);
    const limite = Date.now() - VENTANA_MS;
    eventos = eventos.filter((e) => e.t >= limite).concat(nuevos);
    if (eventos.length > MAX_EVENTOS) eventos = eventos.slice(-MAX_EVENTOS);
    estado.archivos += 1;
    estado.eventos = eventos.length;
    estado.error = null;
  } catch (e) {
    vistos.delete(url); // se reintenta en la siguiente vuelta
    // Un archivo que GDELT no publicó (hueco de 15 min) no es un fallo del servicio.
    if (!/respondió 404/.test(e.message)) estado.error = e.message;
  }
}

export async function actualizarConflictos() {
  try {
    const texto = await pedir(ULTIMO);
    const url = texto.split('\n').map((l) => l.trim().split(/\s+/)[2]).find((u) => u?.endsWith('.export.CSV.zip'));
    if (!url) throw new Error('lastupdate.txt sin archivo de eventos');
    const sello = selloDeUrl(url);
    // Primera vez: rellena las últimas 2 h, de la más antigua a la más reciente, sin pasar del límite de GDELT.
    const urls = [url];
    if (!arrancado && sello) for (let i = 1; i < ARCHIVOS_INICIALES; i++) urls.unshift(urlDeExport(sello - i * PERIODO_MS));
    arrancado = true;
    for (const u of urls) {
      if (vistos.has(u)) continue;
      await cargarArchivo(u);
      if (u !== url) await new Promise((r) => setTimeout(r, pausaEntreDescargas()));
    }
    estado.ultimoArchivo = sello ? new Date(sello).toISOString() : null;
  } catch (e) {
    estado.error = e.message;
  }
}

let temporizador = null;
export function iniciarConflictos() {
  if (temporizador) return;
  actualizarConflictos();
  temporizador = setInterval(actualizarConflictos, 5 * 60_000); // GDELT publica cada 15 min; se mira cada 5
  temporizador.unref();
}

// --- Consulta: agrupa por lugar (rejilla de ~11 km) para no pintar miles de puntos repetidos ------------------------
export function agrupar(lista, bbox, paso = 0.1) {
  const grupos = new Map();
  for (const e of lista) {
    if (!dentro(bbox, e.lat, e.lon)) continue;
    const clave = `${Math.round(e.lat / paso)},${Math.round(e.lon / paso)}`;
    let g = grupos.get(clave);
    if (!g) {
      g = { lat: e.lat, lon: e.lon, lugar: e.lugar, pais: e.pais, n: 0, tipos: {}, ultimo: 0, aprox: e.aprox, urls: new Set(), fuentes: 0, sub: {} };
      grupos.set(clave, g);
    }
    g.n += 1;
    g.fuentes += e.fuentes;
    g.tipos[e.tipo] = (g.tipos[e.tipo] ?? 0) + 1;
    if (SUBTIPOS[e.sub]) g.sub[SUBTIPOS[e.sub]] = (g.sub[SUBTIPOS[e.sub]] ?? 0) + 1;
    if (e.t > g.ultimo) g.ultimo = e.t;
    if (e.url && g.urls.size < 5) g.urls.add(e.url);
  }
  // Vector compacto: [lat, lon, lugar, pais, eventos, {tipo:n}, ultimo_ms, aprox, [urls], {subtipo:n}]
  return [...grupos.values()]
    .sort((a, b) => b.n - a.n)
    .slice(0, 3000)
    .map((g) => [g.lat, g.lon, g.lugar, g.pais, g.n, g.tipos, g.ultimo, g.aprox, [...g.urls], g.sub]);
}

export function conflictosEn(bbox, horas = 24) {
  const limite = Date.now() - Math.min(Math.max(horas, 1), 24) * 3600_000;
  const recientes = eventos.filter((e) => e.t >= limite);
  return { grupos: agrupar(recientes, bbox), total: recientes.length };
}
