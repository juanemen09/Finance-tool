// Marcador con forma de avión o barco, orientado según su rumbo y dibujado directamente en el Canvas compartido
// de Leaflet (sin elementos DOM por objetivo). Hereda de CircleMarker para reutilizar el clic y los límites.

import L from 'leaflet';

const FORMAS = {
  avion: [
    [0, -1.2], [0.18, -0.6], [0.18, -0.15], [1, 0.3], [1, 0.5], [0.18, 0.3], [0.14, 0.85], [0.45, 1.05],
    [0.45, 1.2], [0, 1.08], [-0.45, 1.2], [-0.45, 1.05], [-0.14, 0.85], [-0.18, 0.3], [-1, 0.5], [-1, 0.3],
    [-0.18, -0.15], [-0.18, -0.6],
  ],
  barco: [[0, -1.2], [0.45, -0.45], [0.45, 1], [-0.45, 1], [-0.45, -0.45]],
};

export const MarcadorRumbo = L.CircleMarker.extend({
  options: { forma: 'avion', rumbo: null },

  _updateBounds() {
    const r = this._radius * 1.25 + this._clickTolerance() + 1;
    this._pxBounds = new L.Bounds(this._point.subtract([r, r]), this._point.add([r, r]));
  },

  _updatePath() {
    const ren = this._renderer;
    const rumbo = this.options.rumbo;
    if (rumbo == null || !ren._ctx) {
      ren._updateCircle(this); // sin rumbo conocido: punto
      return;
    }
    if (!ren._drawing || this._empty()) return;
    const ctx = ren._ctx;
    const { x, y } = this._point;
    const s = this._radius;
    const a = (rumbo * Math.PI) / 180;
    const c = Math.cos(a) * s;
    const n = Math.sin(a) * s;
    const puntos = FORMAS[this.options.forma];
    ctx.beginPath();
    for (let i = 0; i < puntos.length; i++) {
      const [dx, dy] = puntos[i];
      const px = x + dx * c - dy * n;
      const py = y + dx * n + dy * c;
      if (i === 0) ctx.moveTo(px, py);
      else ctx.lineTo(px, py);
    }
    ctx.closePath();
    ren._fillStroke(ctx, this);
  },
});
