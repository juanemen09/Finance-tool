// Escena 3D del modo TV, sin librerías: puntos en el espacio proyectados en perspectiva sobre un canvas 2D.
// Núcleo de partículas (el laboratorio), anillos orbitales, los 5 activos como planetas (brillan más cerca de la
// ruptura), Claude y Codex como nodos con paquetes de datos que viajan al núcleo cuando escriben en el diario.
(() => {
  "use strict";
  const canvas = document.getElementById("space");
  const ctx = canvas.getContext("2d");
  const still = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const TAU = Math.PI * 2;
  let W = 0, H = 0, DPR = 1;

  const data = { assets: [], agents: {}, autopilot: false, live: false, section: 0 };
  const packets = []; // {from: "claude"|"chatgpt"|"link", t: 0..1, speed}
  const cam = { yaw: 0, pitch: 0.28, targetYaw: 0, dist: 11 };

  function resize() {
    DPR = Math.min(1.5, window.devicePixelRatio || 1);
    W = canvas.width = Math.round(window.innerWidth * DPR);
    H = canvas.height = Math.round(window.innerHeight * DPR);
  }

  // ---------------------------------------------------------------- geometría
  const fib = (n, r) => Array.from({ length: n }, (_, i) => {
    const y = 1 - (i / (n - 1)) * 2, rad = Math.sqrt(1 - y * y), th = i * 2.399963;
    return { x: Math.cos(th) * rad * r, y: y * r, z: Math.sin(th) * rad * r };
  });
  const core = fib(760, 1.35);
  const stars = Array.from({ length: 520 }, () => {
    const u = Math.random() * TAU, v = Math.acos(2 * Math.random() - 1), r = 16 + Math.random() * 18;
    return { x: r * Math.sin(v) * Math.cos(u), y: r * Math.cos(v), z: r * Math.sin(v) * Math.sin(u), tw: Math.random() * TAU };
  });
  const rings = [[2.3, 0.35, 0], [3.4, -0.22, 1.1], [4.6, 0.12, 2.2]].map(([r, tilt, rot]) =>
    Array.from({ length: 200 }, (_, i) => {
      const a = (i / 200) * TAU;
      return rotY({ x: Math.cos(a) * r, y: Math.sin(a) * r * Math.sin(tilt), z: Math.sin(a) * r * Math.cos(tilt) }, rot);
    }));
  const NODES = { claude: { x: -5.4, y: 2.2, z: 0.8 }, chatgpt: { x: 5.4, y: 2.2, z: -0.8 } };

  function rotY(p, a) { const c = Math.cos(a), s = Math.sin(a); return { x: p.x * c + p.z * s, y: p.y, z: -p.x * s + p.z * c }; }
  function rotX(p, a) { const c = Math.cos(a), s = Math.sin(a); return { x: p.x, y: p.y * c - p.z * s, z: p.y * s + p.z * c }; }
  function project(p) {
    const q = rotX(rotY(p, cam.yaw), cam.pitch);
    const z = q.z + cam.dist;
    if (z < 0.5) return null;
    // El centro de la escena va en el hueco libre bajo el escenario, no detrás del texto de las tarjetas;
    // en pantallas angostas (celular) vuelve al centro.
    const narrow = W / H < 1.2;
    const s = (Math.min(W, H) * (narrow ? 0.8 : 0.62)) / z;
    return { x: W * (narrow ? 0.5 : 0.34) + q.x * s, y: H * (narrow ? 0.5 : 0.74) - q.y * s, s, z };
  }

  // ---------------------------------------------------------------- dibujo
  const lerp = (a, b, t) => a + (b - a) * t;
  function dot(p, size, r, g, b, a) {
    ctx.fillStyle = `rgba(${r},${g},${b},${a})`;
    ctx.fillRect(p.x - size / 2, p.y - size / 2, size, size);
  }
  function glow(p, radius, rgb, alpha) {
    const g = ctx.createRadialGradient(p.x, p.y, 0, p.x, p.y, radius);
    g.addColorStop(0, `rgba(${rgb},${alpha})`);
    g.addColorStop(0.35, `rgba(${rgb},${alpha * 0.45})`);
    g.addColorStop(1, `rgba(${rgb},0)`);
    ctx.fillStyle = g;
    ctx.beginPath();
    ctx.arc(p.x, p.y, radius, 0, TAU);
    ctx.fill();
  }
  function label(p, text, sub, rgb) {
    const f = Math.round(Math.max(11, Math.min(30, p.s * 0.055)) * 1);
    ctx.font = `600 ${f}px "Segoe UI", system-ui, sans-serif`;
    ctx.textAlign = "center";
    ctx.fillStyle = `rgba(${rgb},0.95)`;
    ctx.fillText(text, p.x, p.y - f * 1.1);
    if (sub) {
      ctx.font = `${Math.round(f * 0.78)}px "Segoe UI", system-ui, sans-serif`;
      ctx.fillStyle = "rgba(200,212,255,0.8)";
      ctx.fillText(sub, p.x, p.y + f * 1.9);
    }
  }

  function planetPos(i, t) {
    const r = 2.4 + i * 0.62, a = t * (0.11 - i * 0.012) + i * 1.3;
    return { x: Math.cos(a) * r, y: Math.sin(a * 1.7 + i) * 0.35 + (i - 2) * 0.08, z: Math.sin(a) * r };
  }

  function drawPlanet(asset, i, t) {
    const p = project(planetPos(i, t));
    if (!p) return;
    const gap = asset.gap ?? 0.2;
    const near = Math.max(0, Math.min(1, 1 - gap / 0.15));
    const hot = asset.in_strategy && gap < 0.02;
    const rgb = hot ? "255,77,109" : near > 0.6 ? "255,181,71" : "111,211,255";
    const base = p.s * (0.05 + 0.07 * near) * (asset.in_strategy ? 1 : 0.7);
    glow(p, base * (hot ? 4.2 + Math.sin(t * 5) * 0.8 : 3.2), rgb, asset.in_strategy ? 0.55 : 0.25);
    ctx.fillStyle = `rgba(${rgb},0.95)`;
    ctx.beginPath();
    ctx.arc(p.x, p.y, base * 0.7, 0, TAU);
    ctx.fill();
    label(p, asset.symbol.replace("USDT", ""), asset.gap === undefined ? "" : gap <= 0 ? "¡encima!" : `a ${(gap * 100).toFixed(1)} %`, rgb);
  }

  function drawNode(name, key, t) {
    const p = project(NODES[key]);
    if (!p) return;
    const ok = data.agents[key] !== "bad";
    const rgb = ok ? "69,224,176" : "255,77,109";
    glow(p, p.s * (0.18 + 0.03 * Math.sin(t * (ok ? 2 : 6))), rgb, 0.6);
    // octaedro de alambre que gira: el agente "pensando"
    const r = 0.32, a = t * 0.8;
    const n0 = NODES[key];
    const v = [[r, 0, 0], [-r, 0, 0], [0, r, 0], [0, -r, 0], [0, 0, r], [0, 0, -r]].map(([x, y, z]) => {
      const q = rotX(rotY({ x, y, z }, a), a * 0.6);
      return project({ x: n0.x + q.x, y: n0.y + q.y, z: n0.z + q.z });
    });
    const edges = [[0, 2], [0, 3], [0, 4], [0, 5], [1, 2], [1, 3], [1, 4], [1, 5], [2, 4], [4, 3], [3, 5], [5, 2]];
    ctx.strokeStyle = `rgba(${rgb},0.9)`;
    ctx.lineWidth = Math.max(1, DPR);
    ctx.beginPath();
    for (const [m, n] of edges) if (v[m] && v[n]) { ctx.moveTo(v[m].x, v[m].y); ctx.lineTo(v[n].x, v[n].y); }
    ctx.stroke();
    label(p, name, ok ? "al día" : "atrasado", rgb);
  }

  function drawLink(fromKey, t) {
    const a = project(NODES[fromKey]), b = project({ x: 0, y: 0, z: 0 });
    if (!a || !b) return;
    const g = ctx.createLinearGradient(a.x, a.y, b.x, b.y);
    const rgb = data.agents[fromKey] === "bad" ? "255,77,109" : "111,211,255";
    g.addColorStop(0, `rgba(${rgb},0.35)`);
    g.addColorStop(1, `rgba(${rgb},0.02)`);
    ctx.strokeStyle = g;
    ctx.lineWidth = Math.max(1, DPR);
    ctx.setLineDash([6 * DPR, 10 * DPR]);
    ctx.lineDashOffset = -t * 40 * DPR;
    ctx.beginPath();
    ctx.moveTo(a.x, a.y);
    ctx.quadraticCurveTo((a.x + b.x) / 2, Math.min(a.y, b.y) - 60 * DPR, b.x, b.y);
    ctx.stroke();
    ctx.setLineDash([]);
  }

  function drawPackets(dt) {
    for (let i = packets.length - 1; i >= 0; i--) {
      const k = packets[i];
      k.t += dt * k.speed;
      if (k.t >= 1) { packets.splice(i, 1); continue; }
      let from, to;
      if (k.from === "link") { from = NODES.claude; to = NODES.chatgpt; } else { from = NODES[k.from]; to = { x: 0, y: 0, z: 0 }; }
      const lift = Math.sin(k.t * Math.PI) * (k.from === "link" ? 2.2 : 0.9);
      const p = project({ x: lerp(from.x, to.x, k.t), y: lerp(from.y, to.y, k.t) + lift, z: lerp(from.z, to.z, k.t) });
      if (p) glow(p, p.s * 0.06, k.from === "chatgpt" ? "255,77,109" : "111,211,255", 0.95);
    }
  }

  let last = performance.now(), t = 0, frameSkip = false;
  function frame(now) {
    requestAnimationFrame(frame);
    if (document.hidden) return;
    const night = document.body.classList.contains("night");
    if (night && (frameSkip = !frameSkip)) return; // de noche, 30 cuadros por segundo
    const dt = Math.min(0.05, (now - last) / 1000);
    last = now;
    t += dt;

    // cámara: gira despacio y cada sección la lleva a otro ángulo con una transición suave
    cam.targetYaw += dt * 0.035;
    cam.yaw = lerp(cam.yaw, cam.targetYaw + data.section * 0.72, 0.02);
    cam.pitch = 0.26 + Math.sin(t * 0.13) * 0.08;

    // estela: se borra con transparencia y deja rastro de movimiento
    ctx.fillStyle = "rgba(3,8,24,0.42)";
    ctx.fillRect(0, 0, W, H);

    for (const s of stars) {
      const p = project(s);
      if (p) dot(p, 1.4 * DPR, 190, 205, 255, 0.35 + 0.35 * Math.sin(t * 1.5 + s.tw));
    }
    rings.forEach((ring, ri) => {
      for (const q of ring) {
        const p = project(rotY(q, t * (0.05 + ri * 0.02)));
        if (p) dot(p, 1.6 * DPR, 111, 160, 255, Math.max(0.05, 0.45 - (p.z - cam.dist) * 0.05));
      }
    });

    const order = data.assets.map((a, i) => ({ a, i, z: rotY(planetPos(i, t), cam.yaw).z }));
    for (const o of order) if (o.z > 0) drawPlanet(o.a, o.i, t); // detrás del núcleo
    drawLink("claude", t);
    drawLink("chatgpt", t);

    const beat = data.live ? 1 + 0.08 * Math.sin(t * 9) : 1 + 0.035 * Math.sin(t * 1.6);
    const spin = t * (data.autopilot ? 0.35 : 0.12);
    for (const c of core) {
      const q = rotY({ x: c.x * beat, y: c.y * beat, z: c.z * beat }, spin);
      const p = project(q);
      if (!p) continue;
      const depth = Math.max(0, Math.min(1, (cam.dist + 1.4 - p.z) / 2.8));
      const hot = data.live ? 1 : Math.max(0, c.y / 1.35);
      dot(p, (1.2 + depth * 1.8) * DPR, Math.round(lerp(111, 255, hot)), Math.round(lerp(211, 60, hot)), Math.round(lerp(255, 100, hot)), 0.25 + depth * 0.7);
    }
    const center = project({ x: 0, y: 0, z: 0 });
    if (center) glow(center, center.s * 0.9, data.live ? "220,20,60" : "60,90,220", 0.22);

    for (const o of order) if (o.z <= 0) drawPlanet(o.a, o.i, t);
    drawNode("Claude", "claude", t);
    drawNode("Codex", "chatgpt", t);
    drawPackets(dt);

    // tráfico de fondo: siempre hay algo de conversación visible entre los agentes y el núcleo
    if (Math.random() < dt * 0.6) packets.push({ from: Math.random() < 0.5 ? "claude" : "chatgpt", t: 0, speed: 0.35 + Math.random() * 0.3 });
  }

  window.TV3D = {
    set(patch) { Object.assign(data, patch); },
    // un agente escribió en el diario: ráfaga de paquetes hacia el núcleo y hacia el otro agente
    pulse(agent) {
      const key = agent === "chatgpt" ? "chatgpt" : "claude";
      for (let i = 0; i < 6; i++) packets.push({ from: key, t: -i * 0.08, speed: 0.55 });
      packets.push({ from: "link", t: 0, speed: 0.4 });
    },
  };

  resize();
  window.addEventListener("resize", resize);
  ctx.fillStyle = "#030818";
  ctx.fillRect(0, 0, W, H);
  if (!still) requestAnimationFrame(frame);
  else frame(performance.now());
})();
