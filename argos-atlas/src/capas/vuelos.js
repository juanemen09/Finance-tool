// Capa de aviación: OpenSky, cada 15 s, solo la zona visible. En cada oleada se vacía la capa (clearLayers) antes de
// pintar, así no quedan marcadores viejos en memoria tras horas de uso.

import L from 'leaflet';
import { MarcadorRumbo } from '../marcadores.js';
import { crearSondeo } from '../sondeo.js';
import { esc, ficha, fmt, hora, ponerEstado } from '../util.js';

const COLOR = '#fbbf24';
const COLOR_TIERRA = '#64748b';

export function crearCapaVuelos(map, renderer, { contador, estado }) {
  const grupo = L.featureGroup();
  let datosPopup = null;

  grupo.on('click', (e) => abrirPopup(e.layer.datos, e.latlng));

  async function abrirPopup(v, latlng) {
    const [icao, indicativo, pais, , , alt, enTierra, vel, rumbo, vVert, squawk] = v;
    datosPopup = icao;
    const contenido = (meta) =>
      ficha([
        ['Matrícula', meta ? esc(meta.matricula ?? 'no registrada') : '…'],
        ['Indicativo', esc(indicativo || '—')],
        ['ICAO24', esc(icao)],
        ['País', esc(pais)],
        ['Velocidad', vel == null ? '—' : `${fmt(vel * 3.6)} km/h · ${fmt(vel * 1.94384)} kn`],
        ['Altitud', enTierra ? 'en tierra' : alt == null ? '—' : `${fmt(alt)} m · ${fmt(alt * 3.28084)} ft`],
        ['Rumbo', rumbo == null ? '—' : `${fmt(rumbo)}°`],
        ['Vel. vertical', vVert == null ? '—' : `${fmt(vVert, 1)} m/s`],
        ['Squawk', esc(squawk ?? '—')],
        ...(meta?.modelo ? [['Modelo', esc(meta.modelo)]] : []),
        ...(meta?.operador ? [['Operador', esc(meta.operador)]] : []),
      ]);
    const popup = L.popup({ maxWidth: 280 }).setLatLng(latlng).setContent(contenido(null)).openOn(map);
    try {
      const meta = await (await fetch(`/api/vuelos/meta/${encodeURIComponent(icao)}`)).json();
      if (datosPopup === icao && popup.isOpen()) popup.setContent(contenido(meta));
    } catch {
      if (popup.isOpen()) popup.setContent(contenido({ matricula: 'sin datos' }));
    }
  }

  const sondeo = crearSondeo(map, {
    url: '/api/vuelos',
    intervaloMs: 15_000,
    alRecibir({ vuelos, estado: est }) {
      grupo.clearLayers();
      for (const v of vuelos) {
        const m = new MarcadorRumbo([v[3], v[4]], {
          renderer,
          forma: 'avion',
          rumbo: v[8],
          radius: 6,
          weight: 1,
          color: v[6] ? COLOR_TIERRA : COLOR,
          fillColor: v[6] ? COLOR_TIERRA : COLOR,
          fillOpacity: 0.85,
        });
        m.datos = v;
        grupo.addLayer(m);
      }
      contador.textContent = vuelos.length;
      const extra = est?.creditosRestantes != null ? ` · créditos ${est.creditosRestantes}` : '';
      ponerEstado(estado, `OpenSky ${est?.autenticado ? '(cuenta)' : '(anónimo)'} · ${hora()}${extra}`);
    },
    alError(e) {
      // Se conservan los últimos aviones pintados y se avisa: un fallo puntual no vacía el mapa.
      const espera = e.reintentarEn ? ` · reintento en ${Math.ceil(e.reintentarEn / 60)} min` : '';
      ponerEstado(estado, `${e.message}${espera}`, e.reintentarEn ? 'aviso' : 'error');
    },
  });

  return {
    activar() {
      grupo.addTo(map);
      sondeo.iniciar();
    },
    desactivar() {
      sondeo.detener();
      grupo.clearLayers();
      grupo.remove();
      contador.textContent = '—';
    },
  };
}
