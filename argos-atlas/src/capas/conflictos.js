// Capa de conflictos: eventos de agresión, combate y violencia masiva de las últimas 24 h según GDELT 2.0,
// agrupados por lugar. Son eventos REPORTADOS en noticias y codificados por máquina: el popup enseña las fuentes.

import L from 'leaflet';
import { crearSondeo } from '../sondeo.js';
import { esc, ficha, hora, ponerEstado } from '../util.js';

const COLOR = '#ef4444';
const TIPOS = { 18: 'Agresión', 19: 'Combate', 20: 'Violencia masiva' };

function haceCuanto(ms) {
  const min = Math.max(0, Math.round((Date.now() - ms) / 60_000));
  return min < 60 ? `hace ${min} min` : `hace ${Math.round(min / 60)} h`;
}

function dominio(url) {
  try {
    return new URL(url).hostname.replace(/^www\./, '');
  } catch {
    return 'fuente';
  }
}

export function crearCapaConflictos(map, renderer, { contador, estado }) {
  const grupo = L.featureGroup();

  grupo.on('click', (e) => {
    const [, , lugar, pais, n, tipos, ultimo, aprox, urls, sub] = e.layer.datos;
    const desglose = Object.entries(tipos)
      .map(([t, k]) => `${TIPOS[t] ?? t}: ${k}`)
      .join(' · ');
    const detalle = Object.entries(sub ?? {})
      .sort((a, b) => b[1] - a[1])
      .slice(0, 3)
      .map(([t, k]) => `${esc(t)} (${k})`)
      .join('<br>');
    const fuentes = urls.map((u) => `<a href="${esc(u)}" target="_blank" rel="noopener noreferrer">${esc(dominio(u))}</a>`).join('<br>');
    L.popup({ maxWidth: 320 })
      .setLatLng(e.latlng)
      .setContent(
        ficha([
          ['Lugar', `${esc(lugar)}${aprox ? ' <i>(centro del país o región)</i>' : ''}`],
          ['País', esc(pais || '—')],
          ['Eventos 24 h', `${n} · ${esc(desglose)}`],
          ...(detalle ? [['Detalle', detalle]] : []),
          ['Último', haceCuanto(ultimo)],
          ['Fuentes', fuentes || '—'],
        ]) + '<p style="margin-top:6px;color:#64748b;font-size:11px">Reportado en noticias y codificado por máquina (GDELT). Puede contener errores: revisa las fuentes.</p>',
      )
      .openOn(map);
  });

  const sondeo = crearSondeo(map, {
    url: '/api/conflictos',
    intervaloMs: 5 * 60_000, // GDELT publica cada 15 min
    alRecibir({ grupos, total, estado: est }) {
      grupo.clearLayers();
      for (const g of grupos) {
        const m = L.circleMarker([g[0], g[1]], {
          renderer,
          radius: Math.min(4 + Math.sqrt(g[4]) * 1.6, 22),
          weight: 1,
          color: COLOR,
          fillColor: COLOR,
          fillOpacity: g[7] ? 0.18 : 0.4,
          dashArray: g[7] ? '3 3' : null,
        });
        m.datos = g;
        grupo.addLayer(m);
      }
      contador.textContent = grupos.length;
      const cargando = !est?.ultimoArchivo && !est?.error ? ' · cargando las últimas 2 h…' : '';
      const texto = `GDELT · ${total} eventos 24 h en el mundo · ${hora()}${cargando}${est?.error ? ` · ${est.error}` : ''}`;
      ponerEstado(estado, texto, est?.error ? 'aviso' : '');
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
