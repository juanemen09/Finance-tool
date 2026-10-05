// Vuelos en vivo desde OpenSky Network (https://opensky-network.org), filtrados por bounding box.
// Sin credenciales funciona en modo anónimo (pocos créditos al día). Con una cuenta gratuita y un cliente API
// (OPENSKY_CLIENT_ID / OPENSKY_CLIENT_SECRET) el cupo diario es 10 veces mayor.

import { Cache, ErrorFuente, USER_AGENT, bboxEnRejilla, dentro, pedirJson } from './util.js';

const API = 'https://opensky-network.org/api';
const TOKEN_URL = 'https://auth.opensky-network.org/auth/realms/opensky-network/protocol/openid-connect/token';

const estado = { creditosRestantes: null, bloqueadoHasta: 0, autenticado: false, ultimoError: null };
const cacheEstados = new Cache({ ttlMs: 10_000, max: 30 });
const cacheMeta = new Cache({ ttlMs: 24 * 3600_000, max: 2000 });
let token = null;

export function estadoOpenSky() {
  return { ...estado, bloqueadoHasta: estado.bloqueadoHasta > Date.now() ? estado.bloqueadoHasta : 0 };
}

async function cabeceraAuth() {
  const id = process.env.OPENSKY_CLIENT_ID;
  const secreto = process.env.OPENSKY_CLIENT_SECRET;
  if (!id || !secreto) return {};
  if (!token || Date.now() > token.expira) {
    const r = await fetch(TOKEN_URL, {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded', 'User-Agent': USER_AGENT },
      body: new URLSearchParams({ grant_type: 'client_credentials', client_id: id, client_secret: secreto }),
      signal: AbortSignal.timeout(15000),
    });
    if (!r.ok) {
      await r.body?.cancel();
      estado.autenticado = false;
      throw new ErrorFuente(`OpenSky rechazó las credenciales (${r.status}); revisa OPENSKY_CLIENT_ID/SECRET en .env`);
    }
    const j = await r.json();
    token = { valor: j.access_token, expira: Date.now() + Math.max((j.expires_in ?? 1800) - 60, 30) * 1000 };
  }
  estado.autenticado = true;
  return { Authorization: `Bearer ${token.valor}` };
}

// Vector compacto: [icao24, indicativo, país, lat, lon, altitud_m, en_tierra(0/1), velocidad_m_s, rumbo, vel_vertical, squawk]
export function compactar(s) {
  const lat = s[6];
  const lon = s[5];
  if (lat == null || lon == null) return null;
  return [s[0], (s[1] ?? '').trim(), s[2], lat, lon, s[7] ?? s[13] ?? null, s[8] ? 1 : 0, s[9], s[10], s[11], s[14]];
}

async function pedirEstados(caja) {
  if (estado.bloqueadoHasta > Date.now()) {
    throw new ErrorFuente('cupo de OpenSky agotado', { status: 429, reintentarEn: Math.ceil((estado.bloqueadoHasta - Date.now()) / 1000) });
  }
  const url = `${API}/states/all?lamin=${caja.lamin}&lomin=${caja.lomin}&lamax=${caja.lamax}&lomax=${caja.lomax}`;
  const headers = { 'User-Agent': USER_AGENT, Accept: 'application/json', ...(await cabeceraAuth()) };
  let r;
  try {
    r = await fetch(url, { headers, signal: AbortSignal.timeout(20000) });
  } catch (e) {
    throw new ErrorFuente(`OpenSky no responde: ${e.name === 'TimeoutError' ? 'tiempo agotado' : e.message}`);
  }
  const restantes = r.headers.get('x-rate-limit-remaining');
  if (restantes != null) estado.creditosRestantes = Number(restantes);
  if (r.status === 429) {
    await r.body?.cancel();
    const espera = Number(r.headers.get('x-rate-limit-retry-after-seconds')) || 300;
    estado.bloqueadoHasta = Date.now() + espera * 1000;
    throw new ErrorFuente('cupo de OpenSky agotado', { status: 429, reintentarEn: espera });
  }
  if (r.status === 401) token = null;
  if (!r.ok) {
    await r.body?.cancel();
    throw new ErrorFuente(`OpenSky respondió ${r.status}`);
  }
  const j = await r.json();
  return { t: j.time, estados: (j.states ?? []).map(compactar).filter(Boolean) };
}

export async function vuelosEn(bbox) {
  const caja = bboxEnRejilla(bbox, 0.5);
  const clave = `${caja.lamin},${caja.lomin},${caja.lamax},${caja.lomax}`;
  try {
    const { t, estados } = await cacheEstados.obtener(clave, () => pedirEstados(caja));
    estado.ultimoError = null;
    return { t, vuelos: estados.filter((v) => dentro(bbox, v[3], v[4])) };
  } catch (e) {
    estado.ultimoError = e.message;
    throw e;
  }
}

// Matrícula y modelo: no vienen en los vectores de estado, se piden solo al abrir el popup de un avión.
// OpenSky retiró su endpoint de metadatos (410 Gone, 2026); se usa adsbdb.com (gratuito, sin clave).
// Un fallo no se guarda en caché: el siguiente clic lo vuelve a intentar.
export async function metadatosAvion(icao24) {
  try {
    return await cacheMeta.obtener(icao24, async () => {
      const { json } = await pedirJson(`https://api.adsbdb.com/v0/aircraft/${icao24}`, { timeoutMs: 10000 });
      const a = json?.response?.aircraft ?? {};
      return {
        matricula: a.registration || null,
        modelo: [a.manufacturer, a.type].filter(Boolean).join(' ') || a.icao_type || null,
        operador: a.registered_owner || null,
      };
    });
  } catch {
    return { matricula: null, modelo: null, operador: null };
  }
}
