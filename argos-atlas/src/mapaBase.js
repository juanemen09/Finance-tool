// Mapa de fondo. CARTO exige clave desde el 25-09-2026 (sin ella sirve teselas con la marca «API KEY REQUIRED»):
// con CARTO_API_KEY se usa su Dark Matter; sin clave, el lienzo gris oscuro de Esri. Si un proveedor falla seguido,
// se pasa al siguiente, y el último recurso es OpenStreetMap oscurecido con un filtro CSS.

import L from 'leaflet';

const OSM = '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>';
const ESRI = 'Teselas &copy; <a href="https://www.esri.com/">Esri</a>';

function proveedores(cartoKey) {
  const lista = [];
  if (cartoKey) {
    lista.push({
      nombre: 'CARTO',
      capas: [
        L.tileLayer(`https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png?key=${encodeURIComponent(cartoKey)}`, {
          subdomains: 'abcd',
          maxNativeZoom: 20,
          attribution: `${OSM} &copy; <a href="https://carto.com/attributions">CARTO</a>`,
        }),
      ],
    });
  }
  const esri = (servicio) => `https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/${servicio}/MapServer/tile/{z}/{y}/{x}`;
  lista.push({
    nombre: 'Esri',
    capas: [
      L.tileLayer(esri('World_Dark_Gray_Base'), { maxNativeZoom: 16, attribution: `${ESRI}, ${OSM}` }),
      L.tileLayer(esri('World_Dark_Gray_Reference'), { maxNativeZoom: 16 }), // nombres de lugares
    ],
  });
  lista.push({
    nombre: 'OpenStreetMap',
    capas: [L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', { maxNativeZoom: 19, className: 'mapa-oscurecido', attribution: OSM })],
  });
  return lista;
}

export function ponerMapaBase(map, { cartoKey = '' } = {}) {
  const lista = proveedores(cartoKey);
  let i = -1;

  function siguiente() {
    if (i >= 0) for (const c of lista[i].capas) c.remove();
    i += 1;
    if (i >= lista.length) return;
    const actual = lista[i];
    let cargadas = 0;
    let fallidas = 0;
    const base = actual.capas[0];
    base.on('tileload', () => {
      cargadas += 1;
    });
    // Muchas teselas fallidas sin ninguna buena: el proveedor no sirve desde aquí, se cambia.
    base.on('tileerror', () => {
      fallidas += 1;
      if (fallidas >= 6 && cargadas === 0 && i < lista.length - 1 && lista[i] === actual) siguiente();
    });
    for (const c of actual.capas) c.addTo(map).bringToBack();
  }

  siguiente();
}
