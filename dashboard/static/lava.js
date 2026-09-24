// Lámpara de lava: burbujas crimson y azul que suben, se funden (desenfoque en CSS) y vuelven a caer.
(() => {
  "use strict";
  const canvas = document.getElementById("lava");
  const ctx = canvas.getContext("2d");
  const still = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const palette = [
    [220, 20, 60], [255, 58, 94], [139, 10, 42], [34, 64, 160], [70, 110, 230], [180, 16, 72],
  ];
  const scale = 0.5; // se dibuja a media resolución: el desenfoque oculta la diferencia y ahorra batería
  let w = 0, h = 0, blobs = [];

  function resize() {
    w = canvas.width = Math.round(window.innerWidth * scale);
    h = canvas.height = Math.round(window.innerHeight * scale);
  }

  function seed() {
    blobs = Array.from({ length: 14 }, (_, i) => ({
      x: Math.random(),
      phase: Math.random() * Math.PI * 2,
      speed: 0.018 + Math.random() * 0.03,
      drift: 0.02 + Math.random() * 0.05,
      r: 0.09 + Math.random() * 0.12,
      color: palette[i % palette.length],
    }));
  }

  function draw(t) {
    ctx.clearRect(0, 0, w, h);
    ctx.globalCompositeOperation = "lighter";
    const base = Math.min(w, h);
    for (const b of blobs) {
      // Sube y baja como la cera caliente: posición vertical con un vaivén lento y desfasado.
      const y = 0.5 + 0.46 * Math.sin(t * b.speed + b.phase);
      const x = b.x + b.drift * Math.sin(t * b.speed * 0.7 + b.phase * 2);
      const r = base * b.r * (0.85 + 0.15 * Math.sin(t * b.speed * 1.9 + b.phase));
      const g = ctx.createRadialGradient(x * w, y * h, 0, x * w, y * h, r);
      const [cr, cg, cb] = b.color;
      g.addColorStop(0, `rgba(${cr},${cg},${cb},0.85)`);
      g.addColorStop(0.55, `rgba(${cr},${cg},${cb},0.35)`);
      g.addColorStop(1, `rgba(${cr},${cg},${cb},0)`);
      ctx.fillStyle = g;
      ctx.beginPath();
      ctx.arc(x * w, y * h, r, 0, Math.PI * 2);
      ctx.fill();
    }
    ctx.globalCompositeOperation = "source-over";
  }

  let start = performance.now();
  function frame(now) {
    if (!document.hidden) draw((now - start) / 1000);
    requestAnimationFrame(frame);
  }

  resize();
  seed();
  draw(40); // primer cuadro inmediato: con la pestaña en segundo plano el navegador no anima
  window.addEventListener("resize", () => { resize(); draw(40); });
  if (!still) requestAnimationFrame(frame);
})();
