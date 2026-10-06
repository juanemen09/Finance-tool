import 'leaflet/dist/leaflet.css';
import './style.css';
import L from 'leaflet';
import { crearCapaBarcos } from './capas/barcos.js';
import { crearCapaCamaras } from './capas/camaras.js';
import { crearCapaPlano } from './capas/plano.js';
import { crearCapaVuelos } from './capas/vuelos.js';
import { ponerMapaBase } from './mapaBase.js';

const CLAVE_VISTA = 'argos-atlas:vista';
const $ = (id) => document.getElementById(id);

function vistaGuardada() {
  try {
    const v = JSON.parse(localStorage.getItem(CLAVE_VISTA));
    if (Number.isFinite(v?.lat) && Number.isFinite(v?.lng) && Number.isFinite(v?.zoom)) return v;
  } catch {
    // almacenamiento no disponible: vista por defecto
  }
  return { lat: 51.5, lng: -0.12, zoom: 9 }; // Londres: aviones, cámaras de TfL y el Támesis
}

const vista = vistaGuardada();
const map = L.map('map', {
  preferCanvas: true, // todo vector sin renderer propio va al Canvas, no al DOM
  center: [vista.lat, vista.lng],
  zoom: vista.zoom,
  minZoom: 2,
  maxZoom: 23,
  worldCopyJump: true,
  zoomControl: false,
});
L.control.zoom({ position: 'topright' }).addTo(map);
L.control.scale({ position: 'bottomright', imperial: false }).addTo(map);
let config = {};
try {
  config = await (await fetch('/api/config')).json();
} catch {
  // sin proxy: mapa de fondo sin clave
}
ponerMapaBase(map, { cartoKey: config.cartoKey });

map.on('moveend', () => {
  const c = map.getCenter();
  try {
    localStorage.setItem(CLAVE_VISTA, JSON.stringify({ lat: c.lat, lng: c.lng, zoom: map.getZoom() }));
  } catch {
    // sin almacenamiento: no pasa nada
  }
});

// Un único lienzo para todas las capas: un solo <canvas> que repintar.
const renderer = L.canvas({ padding: 0.2, tolerance: 4 });

const capas = {
  vuelos: crearCapaVuelos(map, renderer, { contador: $('n-vuelos'), estado: $('e-vuelos') }),
  barcos: crearCapaBarcos(map, renderer, { contador: $('n-barcos'), estado: $('e-barcos') }),
  camaras: crearCapaCamaras(map, renderer, { contador: $('n-camaras'), estado: $('e-camaras') }),
  plano: crearCapaPlano(map, renderer, {
    contador: $('n-presencia'),
    lista: $('lista-presencia'),
    insignia: $('fuente-presencia'),
    estado: $('e-presencia'),
  }),
};

await capas.plano.iniciar().catch((e) => {
  $('fuente-presencia').textContent = 'SIN PROXY';
  console.error('[plano]', e);
});

for (const nombre of Object.keys(capas)) {
  const interruptor = $(`t-${nombre}`);
  const aplicar = () => (interruptor.checked ? capas[nombre].activar() : capas[nombre].desactivar());
  interruptor.addEventListener('change', aplicar);
  aplicar();
}

// Ir al plano y volver: en el plano (zoom de casa) no hay aviones, barcos ni cámaras, así que se recuerda la vista
// anterior para regresar a ella.
const VISTA_GENERAL = { lat: 51.5, lng: -0.12, zoom: 9 };
let vistaAnterior = vista.zoom < 17 ? vista : VISTA_GENERAL;

$('ir-plano').addEventListener('click', () => {
  if (map.getZoom() < 17) vistaAnterior = { ...map.getCenter(), zoom: map.getZoom() };
  $('t-plano').checked = true;
  capas.plano.irAlPlano();
});
$('ver-mapa').addEventListener('click', () => {
  map.flyTo([vistaAnterior.lat, vistaAnterior.lng], vistaAnterior.zoom, { duration: 1.2 });
});
