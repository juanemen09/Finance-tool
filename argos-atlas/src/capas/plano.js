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

export function crearCapaPlano(map, renderer, { contador, lista, insignia }) {
  const grupoPlano = L.layerGroup();
  const grupoPresencia = L.layerGroup();
  const objetivos = new Map(); // id -> { fantasma, pulso, datos, t, fila }
  let origen = null;
  let limites = null;
  let ws = null;
  let espera = 1000;
  let visible = false;

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
      return `<b>${esc(d.id)}</b><br>${esc(d.room)} · ${esc(d.state)}<br>respiración ${d.resp ?? '—'} rpm`;
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

  function purgar() {
    const limite = Date.now() - CADUCA_MS;
    for (const [id, o] of objetivos) {
      if (o.t >= limite) continue;
      grupoPresencia.removeLayer(o.fantasma).removeLayer(o.pulso);
      o.fila.remove();
      objetivos.delete(id);
    }
    contador.textContent = objetivos.size;
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
        const simulado = d.fuente === 'simulador';
        insignia.textContent = simulado ? 'SIMULADO' : 'RUVIEW';
        insignia.title = simulado ? 'Datos del emulador por software: no son personas reales.' : 'Lecturas de un sensor RuView.';
        return;
      }
      if (d.id && Array.isArray(d.coords)) actualizar(d);
    };
    ws.onclose = () => {
      ws = null;
      setTimeout(conectar, espera);
      espera = Math.min(espera * 2, 30_000);
    };
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
      grupoPlano.addTo(map);
      grupoPresencia.addTo(map);
      // El divIcon se recrea al volver al mapa: reaplica el estado del pulso.
      for (const o of objetivos.values()) o.pulso.getElement()?.classList.toggle('movimiento', o.datos?.state === 'movimiento');
    },
    desactivar() {
      visible = false;
      grupoPlano.remove();
      grupoPresencia.remove();
    },
    irAlPlano() {
      if (!visible) this.activar();
      if (limites) map.flyToBounds(limites, { padding: [40, 40], maxZoom: 23, duration: 1.2 });
    },
  };
}
