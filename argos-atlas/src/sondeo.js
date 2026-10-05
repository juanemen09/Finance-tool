// Sondeo de una capa por bounding box: pide solo lo visible, se reprograma tras cada respuesta, cancela la petición
// anterior al mover el mapa y se detiene con la pestaña oculta (cero CPU y red en segundo plano).

const ESPERA_MOVIMIENTO_MS = 400;

export function crearSondeo(map, { url, intervaloMs, alRecibir, alError }) {
  let activo = false;
  let temporizador = null;
  let rebote = null;
  let ctrl = null;
  let generacion = 0;

  function programar(ms) {
    clearTimeout(temporizador);
    temporizador = activo ? setTimeout(ciclo, ms) : null;
  }

  async function ciclo() {
    clearTimeout(temporizador);
    temporizador = null;
    if (!activo || document.hidden) return;
    const gen = ++generacion;
    ctrl?.abort();
    ctrl = new AbortController();
    const b = map.getBounds();
    const q = new URLSearchParams({
      lamin: b.getSouth().toFixed(4),
      lomin: b.getWest().toFixed(4),
      lamax: b.getNorth().toFixed(4),
      lomax: b.getEast().toFixed(4),
    });
    let siguiente = intervaloMs;
    try {
      const r = await fetch(`${url}?${q}`, { signal: ctrl.signal });
      const j = await r.json();
      if (gen !== generacion || !activo) return;
      if (!r.ok) {
        const e = new Error(j.error ?? `HTTP ${r.status}`);
        e.reintentarEn = j.reintentarEn;
        throw e;
      }
      alRecibir(j);
    } catch (e) {
      if (e.name === 'AbortError' || gen !== generacion) return;
      alError(e);
      if (e.reintentarEn) siguiente = Math.max(siguiente, e.reintentarEn * 1000);
    }
    programar(siguiente);
  }

  const alMover = () => {
    clearTimeout(rebote);
    rebote = setTimeout(ciclo, ESPERA_MOVIMIENTO_MS);
  };
  const alCambiarVisibilidad = () => {
    if (!document.hidden && activo) ciclo();
  };

  return {
    iniciar() {
      if (activo) return;
      activo = true;
      map.on('moveend', alMover);
      document.addEventListener('visibilitychange', alCambiarVisibilidad);
      ciclo();
    },
    detener() {
      activo = false;
      generacion++;
      ctrl?.abort();
      clearTimeout(temporizador);
      clearTimeout(rebote);
      map.off('moveend', alMover);
      document.removeEventListener('visibilitychange', alCambiarVisibilidad);
    },
  };
}
