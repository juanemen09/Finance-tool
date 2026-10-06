// Argos-Atlas: proxy local (evita CORS) y concentrador de WebSockets de presencia.
// Escucha en 127.0.0.1 (en Docker, HOST=0.0.0.0 dentro del contenedor y el puerto se publica solo en 127.0.0.1).
// Presencia: con RUVIEW_URL se conecta al sensing-server real de RuView; sin él arranca el emulador, salvo
// RUVIEW_SIMULADOR=0 (entonces espera lecturas externas en /ingest/ruview).

import { fork } from 'node:child_process';
import { randomBytes } from 'node:crypto';
import { existsSync } from 'node:fs';
import { createServer } from 'node:http';
import { dirname, join, sep } from 'node:path';
import { fileURLToPath } from 'node:url';
import cors from 'cors';
import express from 'express';
import { WebSocket, WebSocketServer } from 'ws';

const RAIZ = dirname(fileURLToPath(import.meta.url));
try {
  process.loadEnvFile(join(RAIZ, '.env'));
} catch {
  // sin .env: todo funciona en modo anónimo
}

const { vuelosEn, metadatosAvion, estadoOpenSky } = await import('./server/opensky.js');
const { barcosEn, estadoAis } = await import('./server/ais.js');
const { camarasEn, estadoCamaras } = await import('./server/camaras.js');
const { leerBbox } = await import('./server/util.js');
const { normalizarLectura } = await import('./server/presencia.js');
const { iniciarRuView } = await import('./server/ruview.js');
const { ORIGEN_POR_DEFECTO } = await import('./shared/plano.js');

const HOST = process.env.HOST || '127.0.0.1';
const PORT = Number(process.env.PORT) || 8787;
const RUVIEW_URL = process.env.RUVIEW_URL || '';
const MODO = RUVIEW_URL ? 'ruview' : process.env.RUVIEW_SIMULADOR !== '0' ? 'simulador' : 'externo';
const SIMULADOR = MODO === 'simulador';
// Un adaptador de RuView real puede publicar en /ingest/ruview si conoce este token (ARGOS_INGEST_TOKEN en .env).
const TOKEN_INGESTA = process.env.ARGOS_INGEST_TOKEN || randomBytes(16).toString('hex');

const app = express();
app.disable('x-powered-by');
// Solo el propio Argos y el centro de mando de AI Trading Lab (pestaña Seguridad) pueden mostrarlo en un marco.
const PANELES = (process.env.ARGOS_PANELES || 'http://127.0.0.1:8765 http://localhost:8765').split(/\s+/).filter((o) => /^http:\/\/(127\.0\.0\.1|localhost):\d+$/.test(o));
app.use((_req, res, next) => {
  res.setHeader('Content-Security-Policy', `frame-ancestors 'self' ${PANELES.join(' ')}`);
  next();
});
app.use(cors({ origin: [/^http:\/\/(127\.0\.0\.1|localhost):\d+$/] }));

const conBbox = (fn) => async (req, res, next) => {
  const bbox = leerBbox(req.query);
  if (!bbox) return res.status(400).json({ error: 'faltan lamin, lomin, lamax, lomax válidos' });
  try {
    res.json(await fn(bbox));
  } catch (e) {
    next(e);
  }
};

app.get('/api/vuelos', conBbox(async (b) => ({ ...(await vuelosEn(b)), estado: estadoOpenSky() })));
app.get('/api/barcos', conBbox(async (b) => ({ ...(await barcosEn(b)), estado: estadoAis() })));
app.get('/api/camaras', conBbox(async (b) => ({ ...(await camarasEn(b)), estado: estadoCamaras() })));

app.get('/api/vuelos/meta/:icao24', async (req, res) => {
  const icao = String(req.params.icao24).toLowerCase();
  if (!/^[0-9a-f]{6}$/.test(icao)) return res.status(400).json({ error: 'icao24 inválido' });
  res.json(await metadatosAvion(icao));
});

function origenPlano() {
  const lat = Number.parseFloat(process.env.PLANO_LAT);
  const lng = Number.parseFloat(process.env.PLANO_LNG);
  return Number.isFinite(lat) && Number.isFinite(lng) ? { lat, lng } : ORIGEN_POR_DEFECTO;
}

app.get('/api/plano', (_req, res) => {
  res.json({ origen: origenPlano(), modo: MODO });
});

// Lo que el navegador necesita para el mapa de fondo. La clave de CARTO viaja de todos modos en cada URL de tesela.
app.get('/api/config', (_req, res) => {
  res.json({ cartoKey: process.env.CARTO_API_KEY || '' });
});

app.get('/api/estado', (_req, res) => {
  res.json({
    opensky: estadoOpenSky(),
    ais: estadoAis(),
    camaras: estadoCamaras(),
    presencia: { modo: MODO, sensor: estadoSensor, objetivos: ultimos.size },
  });
});

const DIST = join(RAIZ, 'dist');
// La página (index.html) nunca se guarda en caché: tras una actualización pediría archivos con nombres que ya no
// existen y se vería sin estilos ni mapa. Los archivos de /assets llevan un hash en el nombre y sí se guardan.
if (existsSync(DIST)) {
  app.use(
    express.static(DIST, {
      cacheControl: false,
      setHeaders(res, ruta) {
        const inmutable = ruta.includes(`${sep}assets${sep}`);
        res.setHeader('Cache-Control', inmutable ? 'public, max-age=31536000, immutable' : 'no-cache');
      },
    }),
  );
}

app.use((err, _req, res, _next) => {
  const status = err.status ?? 500;
  if (status >= 500 && !err.reintentarEn) console.error('[proxy]', err.message);
  res.status(status).json({ error: err.message, reintentarEn: err.reintentarEn ?? null });
});

// --- WebSockets: el emulador (o un adaptador de RuView real) publica; los navegadores escuchan -------------------
const servidor = createServer(app);
const wssNavegador = new WebSocketServer({ noServer: true, maxPayload: 4096 });
const wssIngesta = new WebSocketServer({ noServer: true, maxPayload: 4096 });
const ultimos = new Map(); // id -> { t, texto }
const OBJETIVO_CADUCA_MS = 20_000;
let estadoSensor = null; // solo con RuView real: conexión, fuente (esp32/wifi/simulated), nodos

function difundir(texto) {
  for (const cliente of wssNavegador.clients) {
    // Un navegador lento no acumula memoria en el servidor: si tiene cola, se salta este tick.
    if (cliente.readyState === WebSocket.OPEN && cliente.bufferedAmount < 64 * 1024) cliente.send(texto);
  }
}

function publicarLectura(bruto) {
  const texto = normalizarLectura(bruto);
  if (!texto) return;
  ultimos.set(JSON.parse(texto).id, { t: Date.now(), texto });
  difundir(texto);
}

function bajaObjetivo(id) {
  if (ultimos.delete(id)) difundir(JSON.stringify({ tipo: 'baja', id }));
}

const mensajeHola = () => JSON.stringify({ tipo: 'hola', modo: MODO, sensor: estadoSensor });

servidor.on('upgrade', (req, socket, head) => {
  const url = new URL(req.url, `http://${HOST}`);
  if (url.pathname === '/ws/ruview') {
    wssNavegador.handleUpgrade(req, socket, head, (ws) => wssNavegador.emit('connection', ws));
  } else if (url.pathname === '/ingest/ruview' && url.searchParams.get('token') === TOKEN_INGESTA) {
    wssIngesta.handleUpgrade(req, socket, head, (ws) => wssIngesta.emit('connection', ws));
  } else {
    socket.destroy();
  }
});

wssIngesta.on('connection', (ws) => {
  ws.on('message', (raw) => publicarLectura(raw.toString()));
});

wssNavegador.on('connection', (ws) => {
  ws.vivo = true;
  ws.on('pong', () => {
    ws.vivo = true;
  });
  ws.send(mensajeHola());
  const limite = Date.now() - OBJETIVO_CADUCA_MS;
  for (const { t, texto } of ultimos.values()) if (t > limite) ws.send(texto);
});

setInterval(() => {
  for (const ws of wssNavegador.clients) {
    if (!ws.vivo) ws.terminate();
    else {
      ws.vivo = false;
      ws.ping();
    }
  }
  const limite = Date.now() - OBJETIVO_CADUCA_MS;
  for (const [id, { t }] of ultimos) if (t < limite) ultimos.delete(id);
}, 30_000).unref();

// --- Emulador de RuView en segundo plano -----------------------------------------------------------------------
let simulador = null;
let ruview = null;
let cerrando = false;

function arrancarSimulador(espera = 1000) {
  simulador = fork(join(RAIZ, 'simulador_ruview.js'), [], {
    env: { ...process.env, ARGOS_INGEST_URL: `ws://${HOST}:${PORT}/ingest/ruview?token=${TOKEN_INGESTA}` },
    stdio: ['ignore', 'inherit', 'inherit', 'ipc'],
  });
  const inicio = Date.now();
  simulador.on('exit', (code) => {
    simulador = null;
    if (cerrando) return;
    // Si se cae, se reinicia con espera creciente (y vuelve a 1 s si llevaba más de un minuto vivo).
    const siguiente = Date.now() - inicio > 60_000 ? 1000 : Math.min(espera * 2, 60_000);
    console.error(`[simulador] terminó (código ${code}); reinicio en ${siguiente / 1000} s`);
    setTimeout(() => arrancarSimulador(siguiente), siguiente);
  });
}

function cerrar() {
  cerrando = true;
  simulador?.kill('SIGTERM');
  ruview?.cerrar();
  servidor.close();
  process.exit(0);
}
process.on('SIGINT', cerrar);
process.on('SIGTERM', cerrar);

servidor.listen(PORT, HOST, () => {
  console.log(`[argos-atlas] proxy en http://${HOST}:${PORT}${existsSync(DIST) ? ' (sirve la app compilada)' : ''}`);
  if (SIMULADOR) {
    arrancarSimulador();
    console.log('[argos-atlas] emulador de RuView activo (datos SIMULADOS)');
  } else if (MODO === 'ruview') {
    ruview = iniciarRuView({
      url: RUVIEW_URL,
      token: process.env.RUVIEW_API_TOKEN || '',
      origen: origenPlano(),
      publicar: publicarLectura,
      baja: bajaObjetivo,
      estado: (info) => {
        const antes = estadoSensor;
        estadoSensor = info;
        if (antes?.conectado !== info.conectado || antes?.error !== info.error) {
          console.log(`[ruview] ${info.conectado ? `conectado (${info.fuente ?? 'sin datos aún'})` : `desconectado${info.error ? `: ${info.error}` : ''}`}`);
        }
        difundir(JSON.stringify({ tipo: 'sensor', sensor: info }));
      },
    });
    console.log(`[argos-atlas] presencia desde RuView real: ${RUVIEW_URL}`);
  } else {
    console.log('[argos-atlas] presencia: esperando lecturas en /ingest/ruview');
  }
});
