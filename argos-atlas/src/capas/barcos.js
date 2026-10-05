// Capa marítima: AIS abierto (Digitraffic y, con clave, aisstream.io). El icono apunta a la proa si el barco la
// transmite, si no al rumbo sobre el fondo; parado o sin datos, es un punto.

import L from 'leaflet';
import { MarcadorRumbo } from '../marcadores.js';
import { crearSondeo } from '../sondeo.js';
import { esc, ficha, fmt, hora, ponerEstado } from '../util.js';

const COLOR = '#22d3ee';
const FUENTES = { dt: 'Digitraffic', as: 'aisstream.io' };

export function crearCapaBarcos(map, renderer, { contador, estado }) {
  const grupo = L.featureGroup();

  grupo.on('click', (e) => {
    const [mmsi, , , sog, cog, proa, nombre, fuente] = e.layer.datos;
    L.popup({ maxWidth: 260 })
      .setLatLng(e.latlng)
      .setContent(
        ficha([
          ['Nombre', esc(nombre || '—')],
          ['MMSI', esc(mmsi)],
          ['Velocidad', sog == null ? '—' : `${fmt(sog, 1)} kn`],
          ['Rumbo', cog == null ? '—' : `${fmt(cog)}°`],
          ['Proa', proa == null ? '—' : `${fmt(proa)}°`],
          ['Fuente', esc(FUENTES[fuente] ?? fuente)],
        ]),
      )
      .openOn(map);
  });

  const sondeo = crearSondeo(map, {
    url: '/api/barcos',
    intervaloMs: 20_000,
    alRecibir({ barcos, recortado, estado: est }) {
      grupo.clearLayers();
      for (const b of barcos) {
        const [, lat, lon, sog, cog, proa] = b;
        const enMarcha = sog != null && sog > 0.5;
        const rumbo = proa ?? (enMarcha && cog != null && cog < 360 ? cog : null);
        const m = new MarcadorRumbo([lat, lon], {
          renderer,
          forma: 'barco',
          rumbo,
          radius: rumbo == null ? 3 : 6,
          weight: 1,
          color: COLOR,
          fillColor: COLOR,
          fillOpacity: enMarcha ? 0.8 : 0.35,
        });
        m.datos = b;
        grupo.addLayer(m);
      }
      contador.textContent = barcos.length;
      const fuentes = [`Digitraffic: ${est?.digitraffic ?? '—'}`, `aisstream: ${est?.aisstream ?? '—'}`].join(' · ');
      ponerEstado(estado, `${hora()} · ${fuentes}${recortado ? ' · acerca el zoom para ver todos' : ''}`, est?.digitraffic === 'ok' ? '' : 'aviso');
    },
    alError(e) {
      ponerEstado(estado, e.message, 'error');
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
