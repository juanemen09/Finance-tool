// Los textos vienen de fuentes externas (indicativos, nombres de barcos y cámaras): siempre se escapan.
const MAPA = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' };
export const esc = (v) => String(v ?? '').replace(/[&<>"']/g, (c) => MAPA[c]);

export const fmt = (v, dec = 0) => (v == null || !Number.isFinite(Number(v)) ? '—' : Number(v).toFixed(dec));

export function ficha(filas) {
  return `<dl>${filas.map(([k, v]) => `<dt>${esc(k)}</dt><dd>${v}</dd>`).join('')}</dl>`;
}

export function ponerEstado(el, texto, tipo = '') {
  el.textContent = texto;
  el.className = `estado ${tipo}`;
}

export const hora = () => new Date().toLocaleTimeString('es', { hour12: false });
