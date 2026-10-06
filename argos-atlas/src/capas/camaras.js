// Capa de cámaras públicas. Los marcadores son puntos en el Canvas; ninguna imagen ni vídeo se descarga hasta que
// abres una cámara, y al cerrarla se destruyen el <img>/<video> y su temporizador.

import L from 'leaflet';
import { crearSondeo } from '../sondeo.js';
import { hora, ponerEstado } from '../util.js';

const COLOR = '#f472b6';
const REFRESCO_IMAGEN_MS = 10_000;

export function crearCapaCamaras(map, renderer, { contador, estado }) {
  const grupo = L.featureGroup();
  const modal = document.getElementById('modal-camara');
  const cuerpo = document.getElementById('cam-cuerpo');
  const titulo = document.getElementById('cam-titulo');
  const fuente = document.getElementById('cam-fuente');
  const horaEl = document.getElementById('cam-hora');
  const botonVideo = document.getElementById('cam-video');
  let refresco = null;
  let camaraAbierta = null;

  function conMarca(url) {
    return `${url}${url.includes('?') ? '&' : '?'}t=${Date.now()}`;
  }

  function vaciarCuerpo() {
    clearInterval(refresco);
    refresco = null;
    for (const el of cuerpo.querySelectorAll('img, video')) {
      if (el.tagName === 'VIDEO') {
        el.pause();
        el.removeAttribute('src');
        el.load(); // libera el decodificador y corta la descarga
      } else {
        el.removeAttribute('src');
      }
    }
    cuerpo.replaceChildren();
  }

  function mostrarImagen(c) {
    vaciarCuerpo();
    const img = document.createElement('img');
    img.className = 'max-h-[70dvh] w-full object-contain';
    img.alt = c[1];
    img.decoding = 'async';
    img.onerror = () => {
      horaEl.textContent = 'la cámara no devolvió imagen (puede estar fuera de servicio)';
    };
    img.onload = () => {
      horaEl.textContent = `imagen recibida ${hora()} · se renueva cada ${REFRESCO_IMAGEN_MS / 1000} s`;
    };
    img.src = conMarca(c[5]);
    cuerpo.append(img);
    refresco = setInterval(() => {
      if (!document.hidden) img.src = conMarca(c[5]);
    }, REFRESCO_IMAGEN_MS);
  }

  function mostrarVideo(c) {
    vaciarCuerpo();
    const v = document.createElement('video');
    v.className = 'max-h-[70dvh] w-full';
    Object.assign(v, { src: conMarca(c[6]), autoplay: true, muted: true, loop: true, controls: true, playsInline: true });
    v.onerror = () => {
      horaEl.textContent = 'el clip no está disponible ahora';
    };
    cuerpo.append(v);
    horaEl.textContent = 'clip corto que la cámara renueva cada pocos minutos';
  }

  function abrir(c) {
    camaraAbierta = c;
    titulo.textContent = c[1];
    fuente.textContent = `${c[4]} · ${c[2].toFixed(4)}, ${c[3].toFixed(4)}`;
    botonVideo.classList.toggle('hidden', !c[6]);
    botonVideo.textContent = 'Ver clip de vídeo';
    mostrarImagen(c);
    modal.classList.replace('hidden', 'flex');
  }

  function cerrar() {
    vaciarCuerpo();
    camaraAbierta = null;
    modal.classList.replace('flex', 'hidden');
  }

  botonVideo.addEventListener('click', () => {
    if (!camaraAbierta) return;
    if (cuerpo.querySelector('video')) {
      botonVideo.textContent = 'Ver clip de vídeo';
      mostrarImagen(camaraAbierta);
    } else {
      botonVideo.textContent = 'Volver a la imagen';
      mostrarVideo(camaraAbierta);
    }
  });
  document.getElementById('cam-cerrar').addEventListener('click', cerrar);
  modal.addEventListener('click', (e) => {
    if (e.target === modal) cerrar();
  });
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && camaraAbierta) cerrar();
  });

  grupo.on('click', (e) => abrir(e.layer.datos));

  const sondeo = crearSondeo(map, {
    url: '/api/camaras',
    intervaloMs: 10 * 60_000, // el catálogo casi no cambia; se vuelve a pedir sobre todo al mover el mapa
    alRecibir({ camaras, total, estado: est }) {
      grupo.clearLayers();
      for (const c of camaras) {
        const m = L.circleMarker([c[2], c[3]], { renderer, radius: 4, weight: 1, color: COLOR, fillColor: COLOR, fillOpacity: 0.7 });
        m.datos = c;
        grupo.addLayer(m);
      }
      contador.textContent = camaras.length;
      const fallos = Object.entries(est ?? {}).filter(([, v]) => String(v).startsWith('error'));
      const texto = `${total} en catálogo · ${hora()}${fallos.length ? ` · sin respuesta: ${fallos.map(([k]) => k).join(', ')}` : ''}`;
      ponerEstado(estado, texto, fallos.length ? 'aviso' : '');
      estado.title = fallos.map(([k, v]) => `${k}: ${v}`).join('\n'); // el detalle del fallo, al pasar el ratón
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
      cerrar();
      grupo.clearLayers();
      grupo.remove();
      contador.textContent = '—';
    },
  };
}
