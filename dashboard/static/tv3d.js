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

  // ---------------------------------------------------------------- mapa 3D (grafo de conocimiento, como Obsidian)
  // Cada cosa del laboratorio es un nodo y cada relación real es un enlace; las posiciones salen de una simulación de
  // fuerzas en 3D (repulsión entre nodos, resortes en los enlaces y gravedad hacia el centro).
  const GROUP_RGB = {
    hub: "255,77,109", agent: "69,224,176", alert: "255,77,109", market: "111,211,255", asset: "111,211,255",
    hot: "255,181,71", strategy: "170,140,255", rejected: "120,110,160", research: "255,214,110", forecast: "120,230,255",
    sentiment: "210,160,255", project: "90,150,255", person: "235,240,255", money: "80,230,140", zyneath: "255,130,200",
    rules: "255,181,71", proposal: "255,77,109",
  };
  const graph = { nodes: [], links: [], byId: new Map(), alpha: 1, hover: null, selected: null, onSelect: null };
  const gcam = { yaw: 0.4, pitch: 0.35, dist: 22, dragging: false, lastX: 0, lastY: 0, idleAt: 0, targetYaw: null };

  function setGraph(g) {
    const old = graph.byId;
    graph.byId = new Map();
    graph.nodes = g.nodes.map((n) => {
      const prev = old.get(n.id);
      const node = Object.assign(prev || { x: (Math.random() - 0.5) * 8, y: (Math.random() - 0.5) * 8, z: (Math.random() - 0.5) * 8, vx: 0, vy: 0, vz: 0 }, n);
      graph.byId.set(n.id, node);
      return node;
    });
    graph.links = g.links.filter((l) => graph.byId.has(l.source) && graph.byId.has(l.target))
      .map((l) => ({ ...l, a: graph.byId.get(l.source), b: graph.byId.get(l.target) }));
    // un nodo nuevo nace junto a su primer vecino, no en cualquier lugar
    for (const l of graph.links) {
      for (const [m, o] of [[l.a, l.b], [l.b, l.a]]) {
        if (!old.has(m.id) && old.has(o.id) && !m.placed) { m.x = o.x + (Math.random() - 0.5); m.y = o.y + (Math.random() - 0.5); m.z = o.z + (Math.random() - 0.5); }
        m.placed = true;
      }
    }
    graph.neighbors = new Map(graph.nodes.map((n) => [n.id, new Set([n.id])]));
    for (const l of graph.links) { graph.neighbors.get(l.a.id).add(l.b.id); graph.neighbors.get(l.b.id).add(l.a.id); }
    if (graph.selected && !graph.byId.has(graph.selected.id)) graph.selected = null;
    else if (graph.selected) graph.selected = graph.byId.get(graph.selected.id);
    graph.alpha = Math.max(graph.alpha, old.size ? 0.3 : 1);
  }

  function simulate() {
    const ns = graph.nodes, a = Math.max(0.02, graph.alpha);
    for (let i = 0; i < ns.length; i++) {
      const p = ns[i];
      for (let j = i + 1; j < ns.length; j++) {
        const q = ns[j];
        let dx = p.x - q.x, dy = p.y - q.y, dz = p.z - q.z;
        const d2 = dx * dx + dy * dy + dz * dz + 0.01;
        const f = (a * 1.6 * (p.size || 1) * (q.size || 1)) / d2;
        const d = Math.sqrt(d2);
        dx /= d; dy /= d; dz /= d;
        p.vx += dx * f; p.vy += dy * f; p.vz += dz * f;
        q.vx -= dx * f; q.vy -= dy * f; q.vz -= dz * f;
      }
    }
    for (const l of graph.links) {
      const dx = l.b.x - l.a.x, dy = l.b.y - l.a.y, dz = l.b.z - l.a.z;
      const d = Math.sqrt(dx * dx + dy * dy + dz * dz) + 0.001;
      const rest = 1.6 + ((l.a.size || 1) + (l.b.size || 1)) * 0.45;
      const f = (d - rest) * 0.06 * a * Math.min(1.5, l.w || 1);
      l.a.vx += (dx / d) * f; l.a.vy += (dy / d) * f; l.a.vz += (dz / d) * f;
      l.b.vx -= (dx / d) * f; l.b.vy -= (dy / d) * f; l.b.vz -= (dz / d) * f;
    }
    for (const p of ns) {
      if (p.pinned) { p.x = p.y = p.z = 0; p.vx = p.vy = p.vz = 0; continue; }
      p.vx -= p.x * 0.012 * a; p.vy -= p.y * 0.012 * a; p.vz -= p.z * 0.012 * a;
      p.vx *= 0.82; p.vy *= 0.82; p.vz *= 0.82;
      p.x += p.vx; p.y += p.vy; p.z += p.vz;
    }
    graph.alpha *= 0.992;
  }

  function gproject(p) {
    const q = rotX(rotY(p, gcam.yaw), gcam.pitch);
    const z = q.z + gcam.dist;
    if (z < 0.5) return null;
    const s = (Math.min(W, H) * 1.05) / z;
    return { x: W * 0.5 + q.x * s, y: H * 0.5 - q.y * s, s, z };
  }

  function drawGraph(dt, t) {
    for (let k = 0; k < 2; k++) simulate();
    // encuadre automático: la cámara se aleja o acerca para que todo el grafo quepa, salvo que el usuario haya hecho zoom
    if (Date.now() > (gcam.userZoomUntil || 0)) {
      let r = 1;
      for (const n of graph.nodes) r = Math.max(r, Math.hypot(n.x, n.y, n.z));
      gcam.dist += (Math.max(10, Math.min(90, r * 2.2)) - gcam.dist) * 0.03;
    }
    if (!gcam.dragging && Date.now() > gcam.idleAt) {
      if (gcam.targetYaw !== null) {
        let diff = gcam.targetYaw - gcam.yaw;
        diff = Math.atan2(Math.sin(diff), Math.cos(diff));
        gcam.yaw += diff * 0.03;
        if (Math.abs(diff) < 0.01) gcam.targetYaw = null;
      } else gcam.yaw += dt * 0.06;
    }
    const focus = graph.hover || graph.selected;
    const lit = focus ? graph.neighbors.get(focus.id) : null;
    for (const n of graph.nodes) n._p = gproject(n);

    ctx.lineWidth = Math.max(1, DPR);
    for (const l of graph.links) {
      const a = l.a._p, b = l.b._p;
      if (!a || !b) continue;
      const on = lit && lit.has(l.a.id) && lit.has(l.b.id) && (l.a === focus || l.b === focus);
      const rgb = GROUP_RGB[l.b.group] || "150,170,255";
      ctx.strokeStyle = `rgba(${rgb},${on ? 0.85 : lit ? 0.05 : 0.2})`;
      ctx.beginPath();
      ctx.moveTo(a.x, a.y);
      ctx.lineTo(b.x, b.y);
      ctx.stroke();
      // pulso de datos que recorre el enlace
      if (on || Math.random() < 0.002) l.pulse = l.pulse ?? 0;
      if (l.pulse !== undefined) {
        l.pulse += dt * 0.6;
        const k = l.pulse % 1;
        glow({ x: a.x + (b.x - a.x) * k, y: a.y + (b.y - a.y) * k }, 5 * DPR, rgb, on ? 0.9 : 0.5);
        if (!on && l.pulse > 1) delete l.pulse;
      }
    }

    const order = graph.nodes.filter((n) => n._p).sort((m, n) => n._p.z - m._p.z);
    for (const n of order) {
      const p = n._p, rgb = GROUP_RGB[n.group] || "200,210,255";
      const dim = lit && !lit.has(n.id);
      const r = Math.max(4 * DPR, p.s * 0.13 * (n.size || 1));
      const breathe = n.group === "alert" || n.group === "hot" || n.group === "proposal" ? 1 + 0.15 * Math.sin(t * 5) : 1;
      glow(p, r * 3.2 * breathe, rgb, dim ? 0.12 : 0.4);
      ctx.fillStyle = `rgba(${rgb},${dim ? 0.4 : 0.95})`;
      ctx.beginPath();
      ctx.arc(p.x, p.y, r * breathe, 0, TAU);
      ctx.fill();
      if (n === focus) {
        ctx.strokeStyle = "rgba(255,255,255,0.9)";
        ctx.lineWidth = 2 * DPR;
        ctx.beginPath();
        ctx.arc(p.x, p.y, r * 1.6 + Math.sin(t * 4) * 2 * DPR, 0, TAU);
        ctx.stroke();
      }
      if (n.size >= 1.2 || (lit && lit.has(n.id)) || (!lit && n.size >= 0.9)) {
        const f = Math.round(Math.max(11 * DPR, Math.min(26 * DPR, p.s * 0.045 * Math.sqrt(n.size || 1))));
        ctx.font = `${n.size >= 1.6 ? 700 : 500} ${f}px "Segoe UI", system-ui, sans-serif`;
        ctx.textAlign = "center";
        ctx.fillStyle = `rgba(238,242,255,${dim ? 0.35 : 0.92})`;
        ctx.fillText(n.label, p.x, p.y + r + f * 1.1);
      }
    }
  }

  function pickNode(clientX, clientY) {
    const x = clientX * DPR, y = clientY * DPR;
    let best = null, bestD = Infinity;
    for (const n of graph.nodes) {
      if (!n._p) continue;
      const r = Math.max(12 * DPR, n._p.s * 0.13 * (n.size || 1) * 1.8);
      const d = Math.hypot(n._p.x - x, n._p.y - y);
      if (d < r && d < bestD) { best = n; bestD = d; }
    }
    return best;
  }

  canvas.addEventListener("pointerdown", (e) => {
    if (data.mode !== "graph") return;
    gcam.dragging = true; gcam.moved = 0; gcam.lastX = e.clientX; gcam.lastY = e.clientY;
    canvas.setPointerCapture(e.pointerId);
  });
  canvas.addEventListener("pointermove", (e) => {
    if (data.mode !== "graph") return;
    if (gcam.dragging) {
      const dx = e.clientX - gcam.lastX, dy = e.clientY - gcam.lastY;
      gcam.moved += Math.abs(dx) + Math.abs(dy);
      gcam.yaw += dx * 0.006;
      gcam.pitch = Math.max(-1.2, Math.min(1.2, gcam.pitch + dy * 0.004));
      gcam.lastX = e.clientX; gcam.lastY = e.clientY;
      gcam.targetYaw = null;
    } else {
      const n = pickNode(e.clientX, e.clientY);
      if (n !== graph.hover) { graph.hover = n; canvas.style.cursor = n ? "pointer" : "grab"; if (n && graph.onHover) graph.onHover(n); }
    }
    gcam.idleAt = Date.now() + 8000;
  });
  canvas.addEventListener("pointerup", (e) => {
    if (data.mode !== "graph") return;
    gcam.dragging = false;
    if (gcam.moved < 6) {
      const n = pickNode(e.clientX, e.clientY);
      graph.selected = n;
      if (graph.onSelect) graph.onSelect(n, true);
    }
    gcam.idleAt = Date.now() + 8000;
  });
  canvas.addEventListener("pointerleave", () => { graph.hover = null; });
  canvas.addEventListener("wheel", (e) => {
    if (data.mode !== "graph") return;
    e.preventDefault();
    gcam.dist = Math.max(6, Math.min(120, gcam.dist * (1 + Math.sign(e.deltaY) * 0.08)));
    gcam.userZoomUntil = Date.now() + 60_000;
    gcam.idleAt = Date.now() + 8000;
  }, { passive: false });

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
    // en el mapa se borra del todo: la estela dejaría copias fantasma de los nodos al girar
    ctx.fillStyle = data.mode === "graph" ? "rgb(3,8,24)" : "rgba(3,8,24,0.42)";
    ctx.fillRect(0, 0, W, H);

    for (const s of stars) {
      const p = project(s);
      if (p) dot(p, 1.4 * DPR, 190, 205, 255, 0.35 + 0.35 * Math.sin(t * 1.5 + s.tw));
    }
    if (data.mode === "graph") { drawGraph(dt, t); return; }
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
    setGraph,
    onGraphSelect(fn) { graph.onSelect = fn; },
    onGraphHover(fn) { graph.onHover = fn; },
    // recorrido automático: selecciona un nodo y gira la cámara para ponerlo de frente
    focus(id) {
      const n = graph.byId.get(id);
      if (!n) return null;
      graph.selected = n;
      gcam.targetYaw = -Math.atan2(n.x, n.z);
      return n;
    },
    graphIdle: () => Date.now() > gcam.idleAt,
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
