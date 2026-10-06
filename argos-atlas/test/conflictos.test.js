// Conflictos (GDELT 2.0): ZIP, filtrado CAMEO 18-20, agrupación por lugar e ingesta con respuestas simuladas.
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { crc32, deflateRawSync } from 'node:zlib';

process.env.ARGOS_GDELT_PAUSA_MS = '0';

// ZIP de un solo archivo, como los que publica GDELT.
function zipUnico(nombre, contenido) {
  const datos = Buffer.from(contenido);
  const comp = deflateRawSync(datos);
  const n = Buffer.from(nombre);
  const crc = crc32(datos);
  const local = Buffer.alloc(30);
  local.writeUInt32LE(0x04034b50, 0);
  local.writeUInt16LE(20, 4);
  local.writeUInt16LE(8, 8);
  local.writeUInt32LE(crc, 14);
  local.writeUInt32LE(comp.length, 18);
  local.writeUInt32LE(datos.length, 22);
  local.writeUInt16LE(n.length, 26);
  const central = Buffer.alloc(46);
  central.writeUInt32LE(0x02014b50, 0);
  central.writeUInt16LE(20, 4);
  central.writeUInt16LE(20, 6);
  central.writeUInt16LE(8, 10);
  central.writeUInt32LE(crc, 16);
  central.writeUInt32LE(comp.length, 20);
  central.writeUInt32LE(datos.length, 24);
  central.writeUInt16LE(n.length, 28);
  central.writeUInt32LE(0, 42);
  const inicioCentral = local.length + n.length + comp.length;
  const fin = Buffer.alloc(22);
  fin.writeUInt32LE(0x06054b50, 0);
  fin.writeUInt16LE(1, 8);
  fin.writeUInt16LE(1, 10);
  fin.writeUInt32LE(central.length + n.length, 12);
  fin.writeUInt32LE(inicioCentral, 16);
  return Buffer.concat([local, n, comp, central, n, fin]);
}

// Fila de 61 columnas del export de GDELT 2.0 con los campos que usamos.
function fila({ id = '1', codigo = '190', raiz = '19', quad = '4', lat = '50.45', lon = '30.52', lugar = 'Kyiv, Kyyiv, Misto, Ukraine', pais = 'UP', geoTipo = '4', fecha, url = 'https://example.org/noticia', fuentes = '3' }) {
  const c = Array(61).fill('');
  c[0] = id;
  c[26] = codigo;
  c[28] = raiz;
  c[29] = quad;
  c[31] = '5';
  c[32] = fuentes;
  c[51] = geoTipo;
  c[52] = lugar;
  c[53] = pais;
  c[56] = lat;
  c[57] = lon;
  c[59] = fecha;
  c[60] = url;
  return c.join('\t');
}

const sello = (ms) => new Date(ms).toISOString().replace(/[-:T]/g, '').slice(0, 14);

const { descomprimirZipUnico, parsearEventos, agrupar, actualizarConflictos, conflictosEn, estadoConflictos } = await import('../server/conflictos.js');

test('descomprime el ZIP de un solo archivo', () => {
  const texto = 'hola\tmundo\n'.repeat(1000);
  assert.equal(descomprimirZipUnico(zipUnico('20261006141500.export.CSV', texto)).toString(), texto);
  assert.throws(() => descomprimirZipUnico(Buffer.from('no es un zip')), /directorio central/);
});

test('solo conflicto material (CAMEO 18-20, QuadClass 4) con coordenadas', () => {
  const ahora = sello(Date.now());
  const texto = [
    fila({ id: 'a', fecha: ahora }),
    fila({ id: 'b', codigo: '195', raiz: '19', fecha: ahora }),
    fila({ id: 'c', codigo: '042', raiz: '04', quad: '1', fecha: ahora }), // reunión: fuera
    fila({ id: 'd', lat: '', lon: '', fecha: ahora }), // sin coordenadas: fuera
    fila({ id: 'e', codigo: '200', raiz: '20', geoTipo: '1', lugar: 'Sudan', pais: 'SU', lat: '15', lon: '30', fecha: ahora }),
    fila({ id: 'f', url: 'javascript:alert(1)', fecha: ahora }),
    'basura\tcorta',
  ].join('\n');
  const ev = parsearEventos(texto);
  assert.deepEqual(ev.map((e) => e.id), ['a', 'b', 'e', 'f']);
  assert.equal(ev.find((e) => e.id === 'e').aprox, true, 'solo país: punto aproximado');
  assert.equal(ev.find((e) => e.id === 'f').url, null, 'no se aceptan enlaces que no sean http(s)');
});

test('agrupa por lugar dentro de la vista', () => {
  const t = Date.now();
  const base = { tipo: 19, sub: 193, fuentes: 2, menciones: 2, aprox: false, lugar: 'Kyiv', pais: 'UP' };
  const lista = [
    { ...base, id: 1, t, lat: 50.45, lon: 30.52, url: 'https://a.org/1' },
    { ...base, id: 2, t: t - 1000, lat: 50.46, lon: 30.53, tipo: 18, sub: 183, url: 'https://b.org/2' },
    { ...base, id: 3, t, lat: 15, lon: 30, lugar: 'Sudan', pais: 'SU' },
  ];
  const ucrania = agrupar(lista, { lamin: 44, lomin: 22, lamax: 53, lomax: 41 });
  assert.equal(ucrania.length, 1);
  const [lat, lon, lugar, pais, n, tipos, ultimo, aprox, urls, sub] = ucrania[0];
  assert.equal(lugar, 'Kyiv');
  assert.equal(n, 2);
  assert.deepEqual(tipos, { 18: 1, 19: 1 });
  assert.equal(ultimo, t);
  assert.deepEqual(urls, ['https://a.org/1', 'https://b.org/2']);
  assert.equal(Object.keys(sub).length, 2);
  assert.ok(Number.isFinite(lat) && Number.isFinite(lon) && aprox === false && pais === 'UP');
});

test('ingesta: lee lastupdate.txt, rellena 2 h y no repite archivos', async () => {
  const ahora = Math.floor(Date.now() / 900_000) * 900_000;
  const nombre = (ms) => `${sello(ms)}.export.CSV.zip`;
  const pedidos = [];
  globalThis.fetch = async (url) => {
    const u = String(url);
    pedidos.push(u);
    if (u.endsWith('lastupdate.txt')) {
      return new Response(`123 abc http://data.gdeltproject.org/gdeltv2/${nombre(ahora)}\n456 def http://data.gdeltproject.org/gdeltv2/${sello(ahora)}.mentions.CSV.zip\n`);
    }
    const m = u.match(/(\d{14})\.export\.CSV\.zip$/);
    if (m) {
      const ms = Date.UTC(+m[1].slice(0, 4), +m[1].slice(4, 6) - 1, +m[1].slice(6, 8), +m[1].slice(8, 10), +m[1].slice(10, 12));
      if (ms === ahora - 3 * 900_000) return new Response('no', { status: 404 }); // hueco en GDELT
      return new Response(zipUnico('x.CSV', fila({ id: m[1], fecha: m[1] })));
    }
    return new Response('no', { status: 404 });
  };
  await actualizarConflictos();
  const zips = pedidos.filter((u) => u.endsWith('.zip') && u.startsWith('https:'));
  assert.equal(zips.length, 8, 'las últimas 2 h, por https primero');
  const { grupos, total } = conflictosEn({ lamin: -90, lomin: -180, lamax: 90, lomax: 180 });
  assert.equal(total, 7, '8 archivos, uno no existe');
  assert.equal(grupos.length, 1);
  assert.equal(estadoConflictos().error, null, 'un 404 de un archivo no es un error del servicio');

  pedidos.length = 0;
  await actualizarConflictos();
  assert.equal(pedidos.filter((u) => u.endsWith('.zip')).length, 0, 'los ya leídos no se vuelven a pedir');
});
