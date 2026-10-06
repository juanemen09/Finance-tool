// Plano táctico 2D del hogar y presencias de RuView (emuladas por ahora).
// - Paredes, puertas y anillos del radar: vectores de Leaflet en el Canvas.
// - Cada objetivo tiene UN fantasma (circleMarker en Canvas) y UN pulso (CSS: transform + opacity, en la GPU) que se
//   crean una sola vez y se mueven con setLatLng: nada se destruye ni se recrea en cada tick.

import L from 'leaflet';
import { HABITACIONES, PUERTAS, SENSOR, aLatLng } from '../../shared/plano.js';
import { esc } from '../util.js';

const NEON = '#4ade80';
const FONDO = '#070b10';
const CADUCA_MS = 20_000;
const TAM_PULSO = 44; // px

const FUENTES_RUVIEW = {
  esp32: ['RUVIEW · ESP32', 'ok', 'Lecturas reales de nodos ESP32 (CSI).'],
  wifi: ['RUVIEW · WI-FI', 'ok', 'Lecturas reales del Wi-Fi del PC (solo RSSI: presencia y movimiento, sin posición).'],
  simulated: ['RUVIEW · DEMO', 'aviso', 'RuView está en su modo de demostración (CSI sintético): no son personas reales.'],
};

// Insignia y línea de estado según de dónde vienen las presencias.
export function describirFuente(modo, sensor) {
  if (modo === 'simulador') return { texto: 'SIMULADO', tipo: 'aviso', titulo: 'Emulador de Argos-Atlas: no son personas reales.', estado: 'Emulador por software' };
  if (modo === 'externo') return { texto: 'EXTERNO', tipo: 'aviso', titulo: 'Lecturas publicadas en /ingest/ruview.', estado: 'Esperando lecturas externas' };
  if (!sensor?.conectado) {
    return { texto: 'RUVIEW · SIN CONEXIÓN', tipo: 'error', titulo: 'No hay conexión con el sensing-server de RuView.', estado: sensor?.error ?? 'Conectando con RuView…' };
  }
  const [texto, tipo, titulo] = FUENTES_RUVIEW[sensor.fuente] ?? [`RUVIEW · ${String(sensor.fuente ?? '…').toUpperCase()}`, 'aviso', 'Fuente de RuView sin clasificar.'];
  const nodos = sensor.fuente === 'esp32' ? `${sensor.nodos} nodo${sensor.nodos === 1 ? '' : 's'} · ` : '';
  return { texto, tipo, titulo, estado: `${nodos}${sensor.presencia ? 'presencia detectada' : 'sin presencia'}` };
}

export function crearCapaPlano(map, renderer, { contador, lista, insignia, estado }) {
  const grupoPlano = L.layerGroup();
  const grupoPresencia = L.layerGroup();
  const objetivos = new Map(); // id -> { fantasma, pulso, datos, t, fila }
  let origen = null;
  let limites = null;
  let ws = null;
  let espera = 1000;
  let visible = false;
  let modo = null;

  function dibujar() {
    grupoPlano.clearLayers();
    const ll = (x, y) => aLatLng(origen, x, y);
    for (const h of HABITACIONES) {
      L.polygon([ll(h.x0, h.y0), ll(h.x1, h.y0), ll(h.x1, h.y1), ll(h.x0, h.y1)], {
        renderer,
        color: NEON,
        weight: 2,
        opacity: 0.55,
        fillColor: NEON,
        fillOpacity: 0.05,
        interactive: false,
      })
        .bindTooltip(h.nombre, { permanent: true, direction: 'center', className: 'etiqueta-sala' })
        .addTo(grupoPlano);
    }
    // Puertas: un trazo del color del fondo abre el hueco en la pared.
    for (const p of PUERTAS) {
      const m = p.ancho / 2;
      const ext = p.eje === 'x' ? [ll(p.x - m, p.y), ll(p.x + m, p.y)] : [ll(p.x, p.y - m), ll(p.x, p.y + m)];
      L.polyline(ext, { renderer, color: FONDO, weight: 4, opacity: 1, interactive: false }).addTo(grupoPlano);
    }
    // Radar del sensor: anillos fijos cada 3 m.
    const s = ll(SENSOR.x, SENSOR.y);
    for (const r of [3, 6, 9]) {
      L.circle(s, { renderer, radius: r, color: NEON, weight: 1, opacity: 0.25, dashArray: '2 6', fill: false, interactive: false }).addTo(grupoPlano);
    }
    L.circleMarker(s, { renderer, radius: 3, color: NEON, fillColor: NEON, fillOpacity: 1, weight: 0 })
      .bindTooltip('Nodo RuView (sensor)')
      .addTo(grupoPlano);
    const xs = HABITACIONES.flatMap((h) => [h.x0, h.x1]);
    const ys = HABITACIONES.flatMap((h) => [h.y0, h.y1]);
    limites = L.latLngBounds(ll(Math.min(...xs), Math.min(...ys)), ll(Math.max(...xs), Math.max(...ys)));
  }

  function crearObjetivo(id) {
    const fantasma = L.circleMarker([0, 0], { renderer, radius: 7, color: NEON, weight: 2, fillColor: NEON, fillOpacity: 0.35 });
    const pulso = L.marker([0, 0], {
      icon: L.divIcon({ className: 'pulso-radar', iconSize: [TAM_PULSO, TAM_PULSO] }),
      interactive: false,
      keyboard: false,
    });
    const o = { fantasma, pulso, datos: null, t: 0, fila: document.createElement('li') };
    fantasma.bindTooltip(() => {
      const d = o.datos;
      const extra = d.aprox ? '<br><i>posición aproximada (pico del campo Wi-Fi)</i>' : '';
      const conf = d.conf != null ? ` · confianza ${Math.round(d.conf * 100)} %` : '';
      return `<b>${esc(d.id)}</b><br>${esc(d.room)} · ${esc(d.state)}${conf}<br>respiración ${d.resp ?? '—'} rpm${extra}`;
    });
    lista.append(o.fila);
    grupoPresencia.addLayer(fantasma).addLayer(pulso);
    objetivos.set(id, o);
    return o;
  }

  function actualizar(d) {
    const o = objetivos.get(d.id) ?? crearObjetivo(d.id);
    o.datos = d;
    o.t = Date.now();
    o.fantasma.setLatLng(d.coords);
    o.pulso.setLatLng(d.coords);
    const color = d.state === 'movimiento' ? '#fbbf24' : NEON;
    if (o.fantasma.options.color !== color) o.fantasma.setStyle({ color, fillColor: color });
    o.pulso.getElement()?.classList.toggle('movimiento', d.state === 'movimiento');
    if (o.fantasma.isTooltipOpen()) o.fantasma.getTooltip().update(); // vuelve a evaluar el contenido
    o.fila.textContent = `${d.id} · ${d.room} · ${d.state} · ${d.resp ?? '—'} rpm`;
    contador.textContent = objetivos.size;
  }

  function quitar(id) {
    const o = objetivos.get(id);
    if (!o) return;
    grupoPresencia.removeLayer(o.fantasma).removeLayer(o.pulso);
    o.fila.remove();
    objetivos.delete(id);
  }

  function purgar() {
    const limite = Date.now() - CADUCA_MS;
    for (const [id, o] of objetivos) if (o.t < limite) quitar(id);
    contador.textContent = objetivos.size;
  }

  function mostrarFuente(f) {
    insignia.textContent = f.texto;
    insignia.title = f.titulo;
    insignia.className = `insignia ${f.tipo}`;
    estado.textContent = f.estado;
    estado.className = `estado ${f.tipo === 'error' ? 'error' : ''}`;
  }

  function conectar() {
    const proto = location.protocol === 'https:' ? 'wss' : 'ws';
    ws = new WebSocket(`${proto}://${location.host}/ws/ruview`);
    ws.onopen = () => {
      espera = 1000;
    };
    ws.onmessage = (ev) => {
      let d;
      try {
        d = JSON.parse(ev.data);
      } catch {
        return;
      }
      if (d.tipo === 'hola') {
        modo = d.modo;
        mostrarFuente(describirFuente(modo, d.sensor));
      } else if (d.tipo === 'sensor') {
        mostrarFuente(describirFuente(modo, d.sensor));
      } else if (d.tipo === 'baja') {
        quitar(d.id);
        contador.textContent = objetivos.size;
      } else if (d.id && Array.isArray(d.coords)) {
        actualizar(d);
      }
    };
    ws.onclose = () => {
      ws = null;
      mostrarFuente({ texto: 'SIN PROXY', tipo: 'error', titulo: 'Se perdió la conexión con el proxy de Argos-Atlas.', estado: 'Reconectando con el proxy…' });
      setTimeout(conectar, espera);
      espera = Math.min(espera * 2, 30_000);
    };
  }

  // El plano de la casa solo se pinta de cerca: en la vista de ciudad o del mundo sus etiquetas taparían los datos.
  const ZOOM_MINIMO = 15;
  function ajustarAlZoom() {
    const debeVerse = visible && map.getZoom() >= ZOOM_MINIMO;
    if (debeVerse && !map.hasLayer(grupoPlano)) {
      grupoPlano.addTo(map);
      grupoPresencia.addTo(map);
      // El divIcon se recrea al volver al mapa: reaplica el estado del pulso.
      for (const o of objetivos.values()) o.pulso.getElement()?.classList.toggle('movimiento', o.datos?.state === 'movimiento');
    } else if (!debeVerse && map.hasLayer(grupoPlano)) {
      grupoPlano.remove();
      grupoPresencia.remove();
    }
  }

  return {
    async iniciar() {
      const cfg = await (await fetch('/api/plano')).json();
      origen = cfg.origen;
      dibujar();
      conectar();
      setInterval(purgar, 5000);
    },
    activar() {
      visible = true;
      map.on('zoomend', ajustarAlZoom);
      ajustarAlZoom();
    },
    desactivar() {
      visible = false;
      map.off('zoomend', ajustarAlZoom);
      grupoPlano.remove();
      grupoPresencia.remove();
    },
    irAlPlano() {
      if (!visible) this.activar();
      if (limites) map.flyToBounds(limites, { padding: [40, 40], maxZoom: 23, duration: 1.2 });
    },
  };
}
