// Parsers de las fuentes con respuestas de ejemplo en el formato que publica cada operador.
import assert from 'node:assert/strict';
import { test } from 'node:test';

const RESPUESTAS = {
  'opensky-network.org/api/states/all': {
    time: 1759600000,
    states: [
      ['4ca123', 'RYR12A  ', 'Ireland', 1, 2, -0.45, 51.47, 1200, false, 90.2, 270, -5, null, 1250, '1234', false, 0],
      ['400abc', 'BAW1', 'United Kingdom', 1, 2, -0.2, 51.6, null, true, 0, null, null, null, null, null, false, 0],
      ['3c1111', 'DLH9', 'Germany', 1, 2, 8.5, 50.0, 11000, false, 240, 45, 0, null, 11100, null, false, 0], // fuera de la vista
      ['ffffff', '', 'X', 1, 2, null, null, null, false, null, null, null, null, null, null, false, 0], // sin posición
    ],
  },
  'api.adsbdb.com/v0/aircraft/4ca123': {
    response: { aircraft: { type: '737-8AS', icao_type: 'B738', manufacturer: 'Boeing', mode_s: '4CA123', registration: 'EI-DCL', registered_owner: 'Ryanair' } },
  },
  'meri.digitraffic.fi/api/ais/v1/locations': {
    type: 'FeatureCollection',
    features: [
      { mmsi: 230000001, type: 'Feature', geometry: { type: 'Point', coordinates: [24.95, 60.16] }, properties: { mmsi: 230000001, sog: 12.3, cog: 85.1, heading: 84, timestampExternal: Date.now() } },
      { mmsi: 230000002, type: 'Feature', geometry: { type: 'Point', coordinates: [24.9, 60.15] }, properties: { mmsi: 230000002, sog: 0, cog: 360, heading: 511, timestampExternal: Date.now() } },
      { mmsi: 230000003, type: 'Feature', geometry: { type: 'Point', coordinates: [24.9, 60.15] }, properties: { mmsi: 230000003, sog: 5, cog: 10, heading: 10, timestampExternal: Date.now() - 3 * 3600_000 } },
    ],
  },
  'meri.digitraffic.fi/api/ais/v1/vessels': [{ mmsi: 230000001, name: 'VIKING XPRS ' }],
  'api.tfl.gov.uk/Place/Type/JamCam': [
    { id: 'JamCams_00001.01251', commonName: 'Tower Bridge', lat: 51.505, lon: -0.075, additionalProperties: [
      { key: 'available', value: 'true' }, { key: 'imageUrl', value: 'https://s3-eu-west-1.amazonaws.com/jamcams.tfl.gov.uk/00001.01251.jpg' }, { key: 'videoUrl', value: 'https://s3-eu-west-1.amazonaws.com/jamcams.tfl.gov.uk/00001.01251.mp4' } ] },
    { id: 'JamCams_00001.09999', commonName: 'Apagada', lat: 51.5, lon: -0.1, additionalProperties: [{ key: 'available', value: 'false' }, { key: 'imageUrl', value: 'x' }] },
  ],
  'webcams.nyctmc.org/api/cameras': [
    { id: 'abc-1', name: 'Broadway @ 42 St', latitude: 40.756, longitude: -73.986, area: 'Manhattan', isOnline: 'true', imageUrl: 'https://webcams.nyctmc.org/api/cameras/abc-1/image' },
    { id: 'abc-2', name: 'Off', latitude: 40.7, longitude: -73.9, isOnline: 'false' },
  ],
  'tie.digitraffic.fi/api/weathercam/v1/stations': {
    type: 'FeatureCollection',
    features: [{ type: 'Feature', geometry: { type: 'Point', coordinates: [24.94, 60.17, 0] }, properties: { id: 'C01502', name: 'Helsinki Kehä I', collectionStatus: 'GATHERING', presets: [{ id: 'C0150200', inCollection: true }] } }],
  },
};

globalThis.fetch = async (url) => {
  const clave = Object.keys(RESPUESTAS).find((k) => String(url).includes(k));
  if (!clave) return new Response('no', { status: 404 });
  return new Response(JSON.stringify(RESPUESTAS[clave]), { status: 200, headers: { 'x-rate-limit-remaining': '397' } });
};

const { vuelosEn, estadoOpenSky, metadatosAvion } = await import('../server/opensky.js');
const { barcosEn } = await import('../server/ais.js');
const { camarasEn } = await import('../server/camaras.js');

test('vuelos: solo los de la vista, con posición, y créditos restantes', async () => {
  const { vuelos } = await vuelosEn({ lamin: 51.2, lomin: -0.6, lamax: 51.8, lomax: 0.4 });
  assert.deepEqual(vuelos.map((v) => v[0]), ['4ca123', '400abc']);
  assert.equal(vuelos[0][1], 'RYR12A');
  assert.equal(vuelos[1][6], 1, 'en tierra');
  assert.equal(estadoOpenSky().creditosRestantes, 397);
});

test('matrícula desde adsbdb; si no la conoce, campos vacíos', async () => {
  assert.deepEqual(await metadatosAvion('4ca123'), { matricula: 'EI-DCL', modelo: 'Boeing 737-8AS', operador: 'Ryanair' });
  assert.deepEqual(await metadatosAvion('abcdef'), { matricula: null, modelo: null, operador: null });
});

test('barcos: proa 511 = sin dato, posiciones viejas fuera, nombre desde metadatos', async () => {
  const { barcos } = await barcosEn({ lamin: 60, lomin: 24, lamax: 61, lomax: 25.5 });
  assert.deepEqual(barcos, [
    [230000001, 60.16, 24.95, 12.3, 85.1, 84, 'VIKING XPRS', 'dt'],
    [230000002, 60.15, 24.9, 0, 360, null, '', 'dt'],
  ]);
});

test('cámaras: de las tres fuentes, sin las apagadas, con URL de imagen', async () => {
  const mundo = { lamin: -90, lomin: -180, lamax: 90, lomax: 180 };
  const { camaras, total } = await camarasEn(mundo);
  assert.equal(total, 3);
  const porId = Object.fromEntries(camaras.map((c) => [c[0], c]));
  assert.equal(porId['tfl:JamCams_00001.01251'][6].endsWith('.mp4'), true);
  assert.equal(porId['nyc:abc-1'][5], 'https://webcams.nyctmc.org/api/cameras/abc-1/image');
  assert.equal(porId['fi:C0150200'][5], 'https://weathercam.digitraffic.fi/C0150200.jpg');
  const londres = await camarasEn({ lamin: 51.2, lomin: -0.6, lamax: 51.8, lomax: 0.4 });
  assert.equal(londres.camaras.length, 1);
});
