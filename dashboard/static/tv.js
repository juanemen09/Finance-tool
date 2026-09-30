// Modo TV: todo el ecosistema en una pantalla fija sobre la escena 3D (tv3d.js). Solo lectura.
// Secciones que rotan solas con una transición 3D; se navegan con clic, flechas, números o deslizando el dedo.
// Todo texto que viene de la base, de internet o de otros proyectos se inserta con textContent, nunca como HTML.
(() => {
  "use strict";

  const AGENT_NAMES = { claude: "Claude", chatgpt: "Codex" };
  const STATUS_TEXT = {
    AWAITING_REVIEW: "Esperando la revisión del otro agente.",
    NOT_APPROVED: "El revisor no la aprobó: no se ejecuta.",
    AWAITING_USER_AUTHORIZATION: "Incumple un límite: solo sale con tu «autorizo».",
    READY_TO_EXECUTE: "Lista: Codex la ejecuta en su próxima corrida.",
  };
  const KIND_NAMES = { analysis: "análisis", message: "mensaje", review: "revisión", proposal: "propuesta", trade: "operación",
    closure: "cierre", event: "evento", strategy: "estrategia", veto: "veto" };
  const FUNNEL = ["DISCOVERED", "CANDIDATE", "PREREGISTERED", "TESTING", "PAPER", "LIVE_ELIGIBLE", "REJECTED", "NOT_APPLICABLE"];
  const BADGES = new Set(["LIVE_ELIGIBLE", "PAPER", "REJECTED", "published", "failed", "dry_run", "ok", "bad", "mid", "buy"]);
  const SECTION_SECONDS = 22;
  const MANUAL_PAUSE_SECONDS = 60;
  const OFFLINE_SECONDS = 90;
  const SHIFT_PX = 8;

  let state = null, radar = null, workspace = null, lastOk = 0, tickerKey = "", chartKey = "";
  let chart = null, candleSeries = null, priceLines = [], chartLoadedAt = 0;
  let current = 0, sectionStarted = Date.now(), pausedUntil = 0, lastForced = "";
  const seenFeed = new Set();
  const chartBox = document.createElement("div");
  chartBox.className = "tv-chart";

  // ---------------------------------------------------------------- utilidades
  function h(tag, props, ...children) {
    const el = document.createElement(tag);
    for (const [k, v] of Object.entries(props || {})) {
      if (v === null || v === undefined || v === false) continue;
      if (k === "class") el.className = v;
      else if (k === "text") el.textContent = v;
      else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
      else el.setAttribute(k, v);
    }
    for (const c of children.flat()) {
      if (c === null || c === undefined || c === false) continue;
      el.append(c instanceof Node ? c : document.createTextNode(String(c)));
    }
    return el;
  }
  const svg = (tag, attrs, ...kids) => {
    const el = document.createElementNS("http://www.w3.org/2000/svg", tag);
    for (const [k, v] of Object.entries(attrs || {})) el.setAttribute(k, v);
    el.append(...kids);
    return el;
  };
  const $ = (id) => document.getElementById(id);
  const fill = (id, ...nodes) => $(id).replaceChildren(...nodes.flat().filter(Boolean));
  const num = (v, d = 2) => (v === null || v === undefined || Number.isNaN(Number(v)))
    ? "—" : Number(v).toLocaleString("es-EC", { minimumFractionDigits: d, maximumFractionDigits: d });
  const signed = (v, d = 1) => (v === null || v === undefined || Number.isNaN(Number(v))) ? "—" : (v > 0 ? "+" : "") + num(v, d);
  const pct = (v, d = 1) => (v === null || v === undefined) ? "—" : `${num(v * 100, d)} %`;
  const tone = (v) => v > 0 ? "up" : v < 0 ? "down" : "";
  const badge = (text, kind) => h("span", { class: `badge ${BADGES.has(kind || text) ? (kind || text) : ""}`, text });
  const bn = (v) => (v === null || v === undefined) ? "—" : `${num(v / 1e9, 1)} mil M`;
  const hm = (tz) => new Intl.DateTimeFormat("es-EC", { timeZone: tz, hour: "2-digit", minute: "2-digit", hour12: false });
  const quitoFmt = hm("America/Guayaquil"), utcFmt = hm("UTC");
  const quitoHour = new Intl.DateTimeFormat("en-US", { timeZone: "America/Guayaquil", hour: "numeric", hour12: false });
  const clock = (secs) => {
    const s = Math.max(0, Math.floor(secs));
    const hh = Math.floor(s / 3600), mm = Math.floor((s % 3600) / 60), ss = s % 60;
    return (hh ? `${hh}:${String(mm).padStart(2, "0")}` : String(mm)) + `:${String(ss).padStart(2, "0")}`;
  };
  function ago(iso) {
    if (!iso) return "—";
    const s = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
    if (s < 90) return "hace 1 min";
    if (s < 3600) return `hace ${Math.round(s / 60)} min`;
    if (s < 86400) return `hace ${Math.round(s / 3600)} h`;
    return `hace ${Math.round(s / 86400)} d`;
  }
  // La CSP prohíbe atributos style: anchos y posiciones van por CSSOM.
  function bar(fraction, variant) {
    const b = h("span", { class: `bar ${variant || ""}` }, h("i"));
    b.firstChild.style.width = `${(Math.max(0.02, Math.min(1, fraction)) * 100).toFixed(1)}%`;
    return b;
  }
  function ring(fraction, text) {
    const r = 42, c = 2 * Math.PI * r;
    const fillC = svg("circle", { class: "fill-c", cx: "50", cy: "50", r: String(r), "stroke-dasharray": c.toFixed(1), "stroke-dashoffset": c.toFixed(1), transform: "rotate(-90 50 50)" });
    requestAnimationFrame(() => requestAnimationFrame(() => fillC.setAttribute("stroke-dashoffset", (c * (1 - Math.max(0, Math.min(1, fraction)))).toFixed(1))));
    const grad = svg("linearGradient", { id: "ringgrad", x1: "0", x2: "1" },
      svg("stop", { offset: "0%", "stop-color": "#dc143c" }), svg("stop", { offset: "100%", "stop-color": "#6fd3ff" }));
    const label = svg("text", { x: "50", y: "52" });
    label.textContent = text;
    return svg("svg", { class: "ring", viewBox: "0 0 100 100", role: "img", "aria-label": text },
      svg("defs", {}, grad), svg("circle", { class: "track-c", cx: "50", cy: "50", r: String(r) }), fillC, label);
  }
  const radarRow = (symbol) => (radar?.rows || []).find((r) => r.symbol === symbol && !r.error);
  const activeProposal = () => (state?.proposals || []).find((p) => !["EXECUTED", "EXPIRED"].includes(p.status));
  const empty = (text) => h("p", { class: "empty", text });

  async function getJSON(url) {
    const r = await fetch(url, { cache: "no-store" });
    const body = await r.json();
    if (!r.ok) throw new Error(body.error || r.status);
    return body;
  }

  // ---------------------------------------------------------------- secciones
  function focusTarget() {
    const pos = state?.open_positions?.[0];
    if (pos) return { symbol: pos.symbol, interval: "1h", title: `Posición abierta · ${pos.symbol} · velas de 1 h`,
      lines: [[pos.entry_price, "#45e0b0", "entrada"], [pos.stop ?? pos.invalidation, "#ffb547", "stop"]] };
    const p = activeProposal();
    if (p) return { symbol: p.symbol, interval: "1d", title: `Propuesta · ${p.symbol} · velas diarias`,
      lines: [[p.entry_high, "#ff4d6d", "zona alta"], [p.entry_low, "#ff4d6d", "zona baja"], [p.invalidation, "#ffb547", "stop"]] };
    return null;
  }
  const forecastMap = (hz) => Object.fromEntries((state?.forecast?.latest || []).filter((f) => f.horizon_days === hz).map((f) => [f.symbol, f]));

  function secMarket() {
    const target = focusTarget();
    const f7 = forecastMap(7);
    const rows = (radar?.rows || []).map((r) => {
      if (r.error) return h("div", { class: "row radar-row muted" }, h("b", { text: r.symbol.replace("USDT", "") }), h("span", { text: "sin datos" }));
      const gap = r.gap_to_entry, f = f7[r.symbol]?.median_return;
      return h("div", { class: `row radar-row ${r.in_strategy ? "" : "muted"}` },
        h("b", { text: r.symbol.replace("USDT", "") }),
        bar(1 - gap / 0.15, r.in_strategy && gap < 0.02 ? "hot" : gap < 0.05 ? "amber" : ""),
        h("span", { class: "num", text: num(r.price, r.price < 10 ? 4 : 2) }),
        h("span", { class: "num", text: gap <= 0 ? "¡encima!" : `${num(gap * 100, 1)} %` }),
        h("span", { class: `num ${tone(f)}`, text: f === undefined ? "—" : `${signed(f * 100, 1)} %` }));
    });
    if (target) loadChart(target);
    return {
      title: target ? target.title : "Mercado · radar S-CHANNEL-1D",
      sub: "precio en vivo de Binance · la compra se decide con el cierre diario",
      body: [target ? chartBox : null,
        h("div", { class: "rows stagger" },
          h("div", { class: "row radar-row sub" }, h("span"), h("span", { text: "Distancia a la compra (máx. 20 días)" }),
            h("span", { class: "num", text: "Precio" }), h("span", { class: "num", text: "Falta" }), h("span", { class: "num", text: "TimesFM 7 d" })),
          rows.length ? rows : empty("Cargando precios…")),
        h("p", { class: "sub", text: "ONDO no entra en S-CHANNEL-1D. TimesFM es papel hasta pasar su prueba (≈ 6 dic)." })],
    };
  }

  function secAgents() {
    const score = Object.fromEntries((state.scoreboard || []).map((s) => [s.agent_id, s]));
    const sa = state.standing_authorization || {}, limits = state.risk_limits || {};
    const weekly = Number(state.pnl_7d || 0), wl = Number(sa.weekly_loss_limit_usdt || 1);
    const card = (id) => {
      const a = state.last_analyses[id], hl = state.agents.find((x) => x.agent_id === id) || {}, s = score[id] || {};
      return h("div", { class: "tile" },
        h("h3", {}, `${AGENT_NAMES[id]} `, badge(hl.state === "ok" ? "al día" : hl.state || "—", hl.state === "ok" ? "ok" : "bad")),
        a ? h("div", {}, badge(a.proposed_action, a.proposed_action === "BUY_CANDIDATE" ? "buy" : ""), h("span", { class: "sub", text: `  ciclo ${a.cycle_id || "—"} · ${ago(a.created_at)}` })) : empty("Sin análisis todavía."),
        a ? h("p", { class: "clamp-6", text: a.market_regime || "" }) : null,
        h("div", { class: "sub", text: `${state.analyses_count[id] || 0} análisis · ${s.decisions_scored || 0} puntuados · R medio ${s.avg_r_after_fees == null ? "—" : num(s.avg_r_after_fees, 2)}` }));
    };
    return {
      title: "Claude y Codex", sub: "análisis a ciegas, revisión cruzada y quién acierta",
      body: h("div", { class: "grid-3 stagger" }, card("claude"), card("chatgpt"),
        h("div", { class: "tile" }, h("h3", { text: "Reglas vigentes" }),
          h("table", { class: "t" },
            h("tr", {}, h("td", { text: "Piloto automático" }), h("td", { class: "num", text: sa.active ? `sí · veto ${sa.veto_minutes} min` : "apagado" })),
            h("tr", {}, h("td", { text: "Pérdida máx. por operación" }), h("td", { class: "num", text: `${num(sa.max_loss_usdt, 2)} USDT` })),
            h("tr", {}, h("td", { text: "Riesgo/beneficio mín." }), h("td", { class: "num", text: num(sa.min_reward_risk, 1) })),
            h("tr", {}, h("td", { text: "Tamaño máx. · posiciones" }), h("td", { class: "num", text: `${num(limits.max_position_usdt, 0)} USDT · ${limits.max_open_positions ?? "—"}` })),
            h("tr", {}, h("td", { text: "Ejecutor" }), h("td", { class: "num", text: AGENT_NAMES[limits.executor_agent_id] || "—" }))),
          h("div", { class: "sub", text: `Pérdidas 7 días: ${num(weekly, 2)} de −${num(wl, 2)} USDT` }),
          bar(-weekly / wl, "hot"),
          h("p", { class: "sub", text: "Tu silencio tras el veto es aprobación, a cualquier hora (evento 34)." }))),
    };
  }

  function secStrategies() {
    const counts = {};
    for (const s of state.strategies) counts[s.status] = (counts[s.status] || 0) + 1;
    const max = Math.max(1, ...Object.values(counts));
    const order = { LIVE_ELIGIBLE: 0, PAPER: 1, TESTING: 2, PREREGISTERED: 3, CANDIDATE: 4 };
    const list = [...state.strategies].sort((a, b) => (order[a.status] ?? 9) - (order[b.status] ?? 9)).slice(0, 9);
    const signals = (state.signals || []).slice(0, 8);
    return {
      title: "Estrategias", sub: "de la fuente al dinero real: nada opera sin pasar el hard testing",
      body: h("div", { class: "grid-2" },
        h("div", { class: "tile" }, h("h3", { text: "Embudo" }),
          h("div", { class: "rows stagger" }, FUNNEL.filter((k) => counts[k]).map((k) =>
            h("div", { class: "row row3", "data-k": k }, h("span", { text: k }), bar(counts[k] / max, k === "LIVE_ELIGIBLE" ? "" : k === "REJECTED" ? "hot" : "amber"), h("b", { class: "num", text: String(counts[k]) })))),
          h("h3", { text: "Señales del último cierre" }),
          signals.length ? h("ul", { class: "list" }, signals.map((s) => h("li", {}, badge(s.signal, s.signal === "ENTRY" ? "buy" : ""),
            h("span", { text: `${s.strategy_id} · ${s.symbol.replace("USDT", "")}` }), h("span", { class: "sub", text: ago(s.bar_close_time) })))) : empty("Sin señales.")),
        h("div", { class: "tile" }, h("h3", { text: "Catálogo" }),
          h("ul", { class: "list stagger" }, list.map((s) => h("li", {}, badge(s.status),
            h("span", { text: s.strategy_id }), h("span", { class: "sub", text: (s.last_verdict || "").toString() })))))),
    };
  }

  function secForecast() {
    const f = state.forecast || { latest: [], skill: [] };
    const bySym = {};
    for (const r of f.latest) (bySym[r.symbol] ||= {})[r.horizon_days] = r;
    const rel = (r, k) => r ? Number(r.quantiles[k]) / Number(r.last_close) - 1 : null;
    const SPAN = 0.2;
    const pos = (v) => `${(Math.max(0, Math.min(1, (v + SPAN) / (2 * SPAN))) * 100).toFixed(1)}%`;
    const rows = Object.entries(bySym).map(([s, hs]) => {
      const r7 = hs[7];
      const rangeEl = h("div", { class: "range" }, h("u"), h("i"), h("b"));
      if (r7) {
        const lo = rel(r7, "p10"), hi = rel(r7, "p90"), mid = rel(r7, "p50");
        rangeEl.children[0].style.left = pos(0);
        rangeEl.children[1].style.left = pos(lo);
        rangeEl.children[1].style.width = `${((hi - lo) / (2 * SPAN) * 100).toFixed(1)}%`;
        rangeEl.children[2].style.left = pos(mid);
      }
      return h("tr", {}, h("td", {}, h("b", { text: s.replace("USDT", "") })),
        h("td", { class: `num ${tone(rel(hs[1], "p50"))}`, text: hs[1] ? `${signed(rel(hs[1], "p50") * 100)} %` : "—" }),
        h("td", { class: `num ${tone(rel(hs[3], "p50"))}`, text: hs[3] ? `${signed(rel(hs[3], "p50") * 100)} %` : "—" }),
        h("td", { class: `num ${tone(rel(r7, "p50"))}`, text: r7 ? `${signed(rel(r7, "p50") * 100)} %` : "—" }),
        h("td", {}, rangeEl));
    });
    const skill = (f.skill || []).map((s) => h("div", { class: "tile" }, h("h3", { text: `${s.horizon_days} día(s)` }),
      h("div", { class: "big", text: s.skill_vs_random_walk === null ? "—" : `${signed(s.skill_vs_random_walk * 100)} %` }),
      h("div", { class: "sub", text: `skill vs paseo aleatorio · ${s.scored} puntuados · dirección ${pct(s.direction_hit_rate, 0)} · banda ${pct(s.coverage_p10_p90, 0)}` })));
    return {
      title: "TimesFM 3.0 · pronóstico en papel", sub: "mediana y banda p10–p90 del cierre a 1, 3 y 7 días; se puntúa contra el azar",
      body: [rows.length ? h("table", { class: "t" },
        h("tr", {}, h("th", { text: "" }), h("th", { class: "num", text: "1 día" }), h("th", { class: "num", text: "3 días" }), h("th", { class: "num", text: "7 días" }), h("th", { text: "7 días · banda (−20 % a +20 %)" })), rows)
        : empty("Aún no hay pronósticos: la tarea corre a las 19:10 de Quito."),
      h("div", { class: "grid-3 stagger" }, skill.length ? skill : [empty("Todavía no venció ningún pronóstico.")]),
      h("p", { class: "sub", text: "Se decide a los 60 cierres (≈ 6 dic): skill > 0 con IC 95 %, dirección > 55 % y banda 70–90 %." })],
    };
  }

  function secThesis() {
    const t = state.ai_thesis || {};
    const book = t["13F_BOOK"]?.data, demand = t.AI_DEMAND?.data, supply = t.AI_SUPPLY?.data, neck = t.AI_BOTTLENECK;
    const top = book?.book?.[0]?.weight || 1;
    return {
      title: "Tesis de infraestructura de IA", sub: "13F de Situational Awareness, capex de los hiperescaladores y oferta física · investigación",
      body: h("div", { class: "grid-3 stagger" },
        h("div", { class: "tile" }, h("h3", { text: "Cuello de botella" }),
          neck ? [h("div", { class: "sub", text: `${neck.title} · ${neck.as_of}` }), h("p", { class: "clamp-6", text: neck.body })] : empty("Informe mensual pendiente (día 25).")),
        h("div", { class: "tile" }, h("h3", { text: "Libro 13F" }),
          book ? [h("div", { class: "sub", text: `al ${book.report_date} · ${bn(book.total_long_usd)} USD` }),
            h("div", { class: "rows" }, book.book.slice(0, 8).map((b) => h("div", { class: "row row3" },
              h("span", { text: b.ticker || b.issuer.slice(0, 8) }), bar(b.weight / top), h("span", { class: "num", text: pct(b.weight, 1) }))))] : empty("Sin 13F.")),
        h("div", { class: "tile" }, h("h3", { text: "Demanda y oferta" }),
          demand ? [h("div", { class: "big", text: bn(demand.aggregate_buyers?.ttm_usd) }),
            h("div", { class: "sub", text: `USD de capex en 12 meses (${signed(demand.aggregate_buyers?.ttm_growth_pct, 0)} % interanual)` })] : empty("Sin demanda."),
          supply ? h("div", { class: "sub", text: `Memorias de Corea ${signed(supply.headline?.korea_memory_yoy_pct)} % · pedidos TIC de Taiwán ${signed(supply.headline?.taiwan_ict_yoy_pct)} % interanual` }) : null)),
    };
  }

  function secSentiment() {
    const latest = state.sentiment?.latest || [];
    const fg = latest.find((r) => r.metric === "fear_greed");
    const bySym = {};
    for (const r of latest) if (r.symbol) (bySym[r.symbol] ||= {})[r.metric] = r.value;
    const toneBy = Object.fromEntries((state.sentiment?.tone_24h || []).map((x) => [x.symbol, x]));
    const metric = (m) => latest.find((r) => r.metric === m)?.value;
    return {
      title: "Sentimiento y tokenización", sub: "contexto, no señal: los filtros de euforia empeoraban la estrategia",
      body: h("div", { class: "grid-3 stagger" },
        h("div", { class: "tile" }, h("h3", { text: "Fear & Greed" }), fg ? ring(fg.value / 100, String(Math.round(fg.value))) : empty("—"),
          h("div", { class: "sub", text: fg?.label || "" }),
          h("div", { class: "sub", text: `Stablecoins ${bn(metric("stablecoin_supply_usd"))} USD · RWA ${bn(metric("rwa_tvl_usd"))} USD` })),
        h("div", { class: "tile" }, h("h3", { text: "Derivados y tono 24 h" }),
          h("table", { class: "t" }, h("tr", {}, h("th", { text: "" }), h("th", { class: "num", text: "Funding" }), h("th", { class: "num", text: "Largo/corto" }), h("th", { class: "num", text: "Tono" })),
            ["BTCUSDT", "ETHUSDT", "SOLUSDT", "LINKUSDT", "ONDOUSDT"].map((s) => h("tr", {}, h("td", { text: s.replace("USDT", "") }),
              h("td", { class: "num", text: bySym[s] ? pct(bySym[s].funding_rate, 3) : "—" }),
              h("td", { class: "num", text: bySym[s] ? num(bySym[s].long_short_account_ratio, 2) : "—" }),
              h("td", { class: `num ${tone(toneBy[s]?.avg_sentiment)}`, text: toneBy[s] ? num(toneBy[s].avg_sentiment, 2) : "—" }))))),
        h("div", { class: "tile" }, h("h3", { text: "Tokenización y materias primas" }),
          h("ul", { class: "list" }, (state.themes || []).slice(0, 6).map((n) => h("li", {}, h("span", { class: "chip", text: (n.themes || [])[0] || "" }),
            h("span", { class: "clamp", text: n.title }), h("span", { class: "sub", text: ago(n.published_at) })))))),
    };
  }

  function secMoney() {
    const m = workspace?.money;
    if (!m || m.error) return { title: "Money Printer", sub: "shorts automáticos de gadgets", body: empty(m?.error ? `money-engine: ${m.error}` : "Cargando money-engine…") };
    const c = m.counts || {};
    const total = Object.values(c).reduce((a, b) => a + b, 0);
    return {
      title: "Money Printer · shorts automáticos", sub: `${m.niche ? m.niche.split("(")[0].trim() : "gadgets"} · ${(m.platforms || []).join(", ")}`,
      body: h("div", { class: "grid-3 stagger" },
        h("div", { class: "tile" }, h("h3", { text: "Estado" }),
          h("div", { class: "big" }, m.paused ? badge("PAUSADO", "bad") : badge("ACTIVO", "ok")),
          h("div", { class: "sub", text: m.video_engine_up === null ? "motor de video: —" : m.video_engine_up ? "MoneyPrinterTurbo en línea" : "MoneyPrinterTurbo apagado (Docker)" }),
          m.pause_note ? h("div", { class: "sub", text: m.pause_note }) : null,
          ring(m.per_day ? m.published_today / m.per_day : 0, `${m.published_today}/${m.per_day ?? "—"}`),
          h("div", { class: "sub", text: "publicados hoy frente al tope diario" })),
        h("div", { class: "tile" }, h("h3", { text: "Totales" }),
          h("div", { class: "huge", text: String(c.published || 0) }), h("div", { class: "sub", text: "publicados" }),
          h("div", { class: "rows" }, Object.entries(c).map(([k, n]) => h("div", { class: "row row3" }, badge(k), bar(n / Math.max(1, total), k === "failed" ? "hot" : k === "published" ? "" : "amber"), h("span", { class: "num", text: String(n) }))))),
        h("div", { class: "tile" }, h("h3", { text: "Últimos videos" }),
          (m.recent || []).length ? h("ul", { class: "list" }, m.recent.map((p) => h("li", {}, badge(p.status), h("span", { class: "clamp", text: p.title || p.kind }), h("span", { class: "sub", text: ago(p.created_at) })))) : empty("Todavía no hay videos."))),
    };
  }

  function projectCard(p) {
    const authors = Object.entries(p.authors_7d || {});
    const lastC = (p.recent || [])[0];
    return h("div", { class: "tile" }, h("h3", { text: p.name }), h("div", { class: "sub", text: p.role || "" }),
      p.error ? h("p", { class: "empty", text: p.error }) : [
        h("div", { class: "row row3" }, h("span", { class: "big", text: String(p.commits_7d) }), bar(p.commits_7d / 40, p.commits_7d ? "" : "amber"), h("span", { class: "sub", text: "commits 7 días" })),
        lastC ? h("p", { class: "clamp", text: `${lastC.subject} — ${lastC.author}, ${ago(lastC.at)}` }) : h("p", { class: "empty", text: "Sin commits en 14 días." }),
        h("div", {}, authors.map(([a, n]) => h("span", { class: "chip", text: `${a} · ${n}` })))]);
  }

  function secZyneath() {
    const z = workspace?.zyneath;
    const projects = (workspace?.projects || []).filter((p) => /zyneath|medflow/i.test(p.name));
    if (!z) return { title: "Zyneath", sub: "", body: empty(workspace?.configured === false ? "Falta config/workspace.local.json (copia config/workspace.example.json)." : "Cargando…") };
    const needed = Math.ceil(z.target_annual_usd / 12 / z.price_usd_month);
    const active = z.active_clinics;
    return {
      title: "Zyneath", sub: z.stage || "",
      body: h("div", { class: "grid-3 stagger" },
        h("div", { class: "tile" }, h("h3", { text: "Meta de ingresos" }),
          ring(active ? active / needed : 0, active ? `${active}/${needed}` : `0/${needed}`),
          h("div", { class: "sub", text: `${needed} clínicas a ${num(z.price_usd_month, 0)} USD/mes = ${num(z.target_annual_usd / 1e6, 1)} M USD al año · ${num(needed / z.market_clinics * 100, 0)} % de un mercado de ${z.market_clinics}` }),
          active === null || active === undefined ? h("div", { class: "sub warn", text: "Sin dato de clínicas activas: ponlo en active_clinics (config/workspace.local.json)." }) : null),
        ...projects.map(projectCard)),
    };
  }

  function secTeam() {
    const projects = (workspace?.projects || []).filter((p) => p.repo);
    const pending = workspace?.pending || [];
    const byWho = {};
    for (const it of pending) (byWho[it.who] ||= []).push(it);
    const level = (n) => n === 3 ? ["urgente", "bad"] : n === 2 ? ["pendiente", "mid"] : ["aviso", ""];
    const cell = (v, warnAt) => h("td", { class: `num ${v && v >= warnAt ? "warn" : ""}`, text: v === null || v === undefined ? "—" : String(v) });
    const team = state.team || [];
    return {
      title: "Equipo · pendientes y avances", sub: "quién debe hacer commit, push, pull o fusionar",
      body: [
        h("div", { class: "tile" }, h("table", { class: "t" },
          h("tr", {}, ["Proyecto", "Sin commit", "Sin push", "Por traer", "Ramas sin fusionar", "PR abiertos", "Issues", "Commits 7 d"]
            .map((x, i) => h("th", { class: i ? "num" : "", text: x }))),
          projects.map((p) => h("tr", {}, h("td", { text: p.name }), cell(p.repo.uncommitted, 1), cell(p.repo.ahead, 1), cell(p.repo.behind, 1),
            cell((p.repo.unmerged_branches || []).length, 1), cell(p.github_items?.pulls?.length, 1), cell(p.github_items?.issues?.length, 1),
            cell(p.commits_7d, 999))))),
        h("div", { class: "grid-3 stagger" }, Object.keys(byWho).length ? Object.entries(byWho).map(([who, items]) => h("div", { class: "tile" },
          h("h3", { text: who }),
          h("ul", { class: "list" }, items.slice(0, 6).map((it) => {
            const [label, kind] = level(it.level);
            return h("li", {}, badge(label, kind), h("span", { class: "clamp", text: `${it.project}: ${it.text}` }), h("span", { class: "sub", text: it.at ? ago(it.at) : "" }));
          })))) : [empty("Nada pendiente: commits, push y fusiones al día.")]),
        h("p", { class: "sub", text: `${team.length ? `${team.length} miembro(s) registrados. ` : "Aún no hay miembros registrados (python -m team). "}Lo que está sin commit o sin push solo se ve en esta PC; de los demás se ve lo que ya subieron: ramas, PR e issues.` })],
    };
  }

  const SECTIONS = [
    ["Mercado", secMarket], ["Agentes", secAgents], ["Estrategias", secStrategies], ["TimesFM", secForecast],
    ["Tesis IA", secThesis], ["Sentimiento", secSentiment], ["Money Printer", secMoney], ["Zyneath", secZyneath], ["Equipo", secTeam],
  ];

  // ---------------------------------------------------------------- navegación con transición 3D
  function renderTabs() {
    fill("tabs", SECTIONS.map(([name], i) => {
      const b = h("button", { role: "tab", "aria-selected": String(i === current), class: Date.now() < pausedUntil ? "paused" : "",
        onclick: () => go(i, true) }, name, h("i"));
      if (i === current) b.lastChild.style.animationDuration = `${SECTION_SECONDS}s`;
      return b;
    }));
  }

  function paintFace(calm) {
    if (!state) return;
    const face = $("face");
    let s;
    try { s = SECTIONS[current][1](); } catch (e) { console.error(SECTIONS[current][0], e); s = { title: SECTIONS[current][0], sub: "", body: empty("Sin datos para esta sección.") }; }
    face.classList.toggle("calm", !!calm);
    face.replaceChildren(h("div", { class: "title-row" }, h("h2", { text: s.title }), h("span", { class: "sub", text: s.sub })),
      h("div", { class: "body" }, s.body));
  }

  function go(i, manual) {
    const next = (i + SECTIONS.length) % SECTIONS.length;
    if (manual) pausedUntil = Date.now() + MANUAL_PAUSE_SECONDS * 1000;
    if (next === current) return;
    const dir = next > current ? 1 : -1;
    const face = $("face");
    face.classList.add(dir > 0 ? "out-left" : "out-right");
    setTimeout(() => {
      current = next;
      sectionStarted = Date.now();
      face.classList.remove("out-left", "out-right");
      face.classList.add(dir > 0 ? "in-right" : "in-left");
      paintFace(false);
      void face.offsetWidth; // fuerza el punto de partida antes de animar la entrada
      face.classList.remove("in-right", "in-left");
      renderTabs();
      if (window.TV3D) window.TV3D.set({ section: current });
    }, 450);
  }

  function autoAdvance() {
    if (graphOn || Date.now() < pausedUntil) return;
    if (Date.now() - sectionStarted >= SECTION_SECONDS * 1000) go(current + 1, false);
  }

  // ---------------------------------------------------------------- columna, cabecera y pie
  function vetoEnd(p) {
    const sa = state?.standing_authorization;
    if (!p || !sa || !sa.active || p.last_verdict !== "APPROVE" || !p.last_review_at) return null;
    if (p.auto && p.auto.not_vetoed === false) return null;
    return new Date(p.last_review_at).getTime() + Number(sa.veto_minutes) * 60_000;
  }

  function renderVeto() {
    const p = activeProposal();
    const end = vetoEnd(p);
    const live = end !== null && Date.now() < end;
    $("veto").classList.toggle("live", live);
    if (window.TV3D) window.TV3D.set({ live });
    if (!state) return fill("veto", h("h2", { text: "Propuestas" }), h("p", { class: "sub", text: "Conectando…" }));
    if (!p) return fill("veto", h("h2", { text: "Propuestas" }), h("div", { class: "title", text: "Ninguna activa" }),
      h("p", { class: "sub", text: "S-CHANNEL-1D decide tras el cierre diario: 19:00 de Quito." }));
    const side = `${p.side === "BUY" ? "Compra" : "Venta"} ${p.symbol.replace("USDT", "")}`;
    const levels = h("p", { class: "sub", text: `Zona ${num(p.entry_low, 4)} – ${num(p.entry_high, 4)} · stop ${num(p.invalidation, 4)} · pérdida máx. ${num(p.auto?.estimated_max_loss_usdt, 2)} USDT` });
    if (live) return fill("veto", h("h2", { text: "Ventana de veto abierta" }), h("div", { class: "title", text: side }),
      h("div", { class: "count", text: clock((end - Date.now()) / 1000) }), h("div", {}, "Para vetarla escribe a Claude o a Codex:"),
      h("code", { text: `veto ${p.proposal_id}` }), levels);
    const vetoed = p.auto && p.auto.not_vetoed === false;
    return fill("veto", h("h2", { text: "Propuesta" }), h("div", { class: "title" }, `${side} `, badge(vetoed ? "VETADA" : p.status)),
      h("p", { text: vetoed ? "La vetaste: no se ejecuta." : (STATUS_TEXT[p.status] || "") }), levels);
  }

  function renderTop() {
    const sa = state.standing_authorization || {};
    const pilot = $("autopilot");
    pilot.className = `autopilot ${sa.active ? "on" : "off"}`;
    pilot.replaceChildren(h("i"), h("div", {},
      h("div", { text: sa.active ? "PILOTO AUTOMÁTICO" : "PILOTO APAGADO" }),
      h("div", { class: "sub", text: sa.active ? `Veto ${sa.veto_minutes} min · pérdida máx. ${num(sa.max_loss_usdt, 2)} USDT` : "Todo espera tu «autorizo»" })));
    const p = state.portfolio;
    const usdt = p ? p.balances.filter((b) => b.asset === "USDT").reduce((s, b) => s + Number(b.free) + Number(b.locked), 0) : null;
    $("balance").replaceChildren(usdt === null ? "—" : num(usdt, 2), h("small", { text: "USDT" }));
    $("balance-sub").textContent = p ? `Binance · ${ago(p.observed_at)}` : "Sin foto de la cuenta";
    const pos = state.open_positions[0];
    if (!pos) return fill("position", h("span", { class: "k", text: "Posición" }), h("b", { text: "Ninguna" }), h("span", { class: "sub", text: "Esperando la próxima ruptura" }));
    const price = radarRow(pos.symbol)?.price;
    const entry = Number(pos.entry_price), stop = Number(pos.stop ?? pos.invalidation);
    const pnl = price ? (price - entry) * Number(pos.quantity) : null;
    fill("position", h("span", { class: "k", text: `Posición · ${pos.symbol.replace("USDT", "")}` }),
      h("b", { class: pnl === null ? "" : pnl >= 0 ? "up" : "down" }, pnl === null ? "—" : signed(pnl, 2), h("small", { text: "USDT" })),
      h("span", { class: "sub", text: price ? `${signed((price / entry - 1) * 100)} % · a ${num((price / stop - 1) * 100, 1)} % del stop` : "Esperando precio" }));
  }

  function renderHealth() {
    fill("health", state.agents.map((a) => h("div", { class: `agent ${a.state === "ok" ? "" : "bad"}` },
      h("i"), h("b", { text: AGENT_NAMES[a.agent_id] || a.agent_id }),
      h("span", { class: "sub", text: a.state === "ok" ? `Al día · ${ago(a.last_activity)}` : (a.reason || a.state) }))));
    if (window.TV3D) window.TV3D.set({ agents: Object.fromEntries(state.agents.map((a) => [a.agent_id, a.state === "ok" ? "ok" : "bad"])) });
  }

  // Línea de tiempo tipo terminal: lo nuevo entra con un destello y dispara paquetes en la escena 3D.
  function renderFeed() {
    const items = (state.timeline || []).slice(0, 16);
    const first = seenFeed.size === 0;
    fill("feed", items.map((e) => {
      const key = `${e.at}|${e.kind}|${e.ref}`;
      const fresh = !first && !seenFeed.has(key);
      if (fresh && window.TV3D) window.TV3D.pulse(e.agent);
      seenFeed.add(key);
      return h("li", { class: fresh ? "fresh" : "" }, h("span", { class: "when", text: quitoFmt.format(new Date(e.at)) }),
        h("span", { class: `tag ${e.agent === "chatgpt" ? "chatgpt" : "claude"}`, text: `${AGENT_NAMES[e.agent] || e.agent || ""}` }),
        h("span", { text: `${KIND_NAMES[e.kind] || e.kind} · ${e.title || ""}` }));
    }));
  }

  function renderBottom() {
    const t = state.ai_thesis || {};
    const b = t.AI_BOTTLENECK || Object.values(t)[0];
    fill("thesis", b ? [h("span", { class: "k", text: "Tesis IA" }), b.title] : [h("span", { class: "sub", text: "Tesis IA sin informe" })]);
    const items = (state.news || []).slice(0, 15);
    const key = items.map((n) => n.url).join("|");
    if (key === tickerKey) return; // reconstruir la cinta la reiniciaría a mitad de recorrido
    tickerKey = key;
    const track = $("ticker");
    track.replaceChildren(...items.map((n) => h("span", {}, h("em", { text: n.author || n.source }), n.title)));
    track.style.animationDuration = `${Math.max(60, Math.round(items.reduce((s, n) => s + (n.title || "").length, 0) * 0.16))}s`;
  }

  // ---------------------------------------------------------------- gráfico (se reutiliza entre repintados)
  async function loadChart(target) {
    const key = `${target.symbol}|${target.interval}|${target.lines.map((l) => l[0]).join(",")}`;
    if (!chart) {
      const LWC = window.LightweightCharts;
      chart = LWC.createChart(chartBox, {
        layout: { background: { type: "solid", color: "transparent" }, textColor: "#9fb0dc", fontSize: 15 },
        grid: { vertLines: { color: "rgba(130,160,255,0.06)" }, horzLines: { color: "rgba(130,160,255,0.06)" } },
        rightPriceScale: { borderColor: "rgba(130,160,255,0.16)" },
        timeScale: { borderColor: "rgba(130,160,255,0.16)", timeVisible: true },
        handleScroll: false, handleScale: false, autoSize: true,
      });
      candleSeries = chart.addCandlestickSeries({ upColor: "#6fd3ff", downColor: "#dc143c", borderUpColor: "#6fd3ff",
        borderDownColor: "#dc143c", wickUpColor: "#6fd3ff", wickDownColor: "#dc143c" });
    }
    if (key === chartKey && Date.now() - chartLoadedAt < 60_000) return; // velas nuevas como mucho una vez por minuto
    try {
      const data = await getJSON(`/api/candles?symbol=${target.symbol}&interval=${target.interval}`);
      candleSeries.setData(data.candles.slice(-120).map(({ time, open, high, low, close }) => ({ time, open, high, low, close })));
      for (const line of priceLines) candleSeries.removePriceLine(line);
      priceLines = target.lines.filter(([price]) => price).map(([price, color, title]) =>
        candleSeries.createPriceLine({ price: Number(price), color, lineWidth: 2, lineStyle: 2, axisLabelVisible: true, title }));
      chart.timeScale().fitContent();
      chartKey = key;
      chartLoadedAt = Date.now();
    } catch (e) { console.error("velas", e); }
  }

  // ---------------------------------------------------------------- ciclos
  function tick() {
    const now = new Date();
    $("clock-quito").textContent = quitoFmt.format(now);
    $("clock-utc").textContent = utcFmt.format(now);
    $("countdown").textContent = clock((Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate() + 1) - now) / 1000);
    const hour = Number(quitoHour.format(now)) % 24;
    document.body.classList.toggle("night", hour >= 23 || hour < 7);
    renderVeto();
    autoAdvance();
    // una ventana de veto abierta o una posición nueva llevan la pantalla al mercado
    const p = activeProposal(), end = vetoEnd(p);
    const urgent = end !== null && Date.now() < end ? `veto:${p.proposal_id}` : state?.open_positions?.[0] ? `pos:${state.open_positions[0].trade_ref}` : "";
    if (urgent && urgent !== lastForced) { lastForced = urgent; if (graphOn) setGraphMode(false); go(0, true); }
    const silent = (Date.now() - lastOk) / 1000;
    const banner = $("offline");
    banner.hidden = silent < OFFLINE_SECONDS;
    if (!banner.hidden) banner.textContent = lastOk ? `Sin datos del diario desde hace ${Math.round(silent / 60)} min: revisa el panel o la conexión.` : "Conectando con el centro de mando…";
  }

  function pushScene() {
    if (!window.TV3D) return;
    const f7 = forecastMap(7);
    window.TV3D.set({
      autopilot: !!state?.standing_authorization?.active,
      assets: (radar?.rows || []).filter((r) => !r.error).map((r) => ({ symbol: r.symbol, gap: r.gap_to_entry, in_strategy: r.in_strategy, f7: f7[r.symbol]?.median_return })),
    });
  }

  async function refreshState() {
    try {
      state = await getJSON("/api/state");
      lastOk = Date.now();
      for (const fn of [renderTop, renderHealth, renderFeed, renderBottom, renderVeto, pushScene]) {
        try { fn(); } catch (e) { console.error(fn.name, e); }
      }
      if (!$("face").firstChild) { paintFace(false); renderTabs(); if (location.hash === "#mapa") setGraphMode(true); } else paintFace(true);
      if (graphOn) refreshGraph();
    } catch (e) { console.error("estado", e); }
  }
  async function refreshRadar() {
    try { radar = await getJSON("/api/radar"); if (state) { renderTop(); pushScene(); if (current === 0) paintFace(true); } } catch (e) { console.error("radar", e); }
  }
  async function refreshWorkspace() {
    try { workspace = await getJSON("/api/workspace"); if (state && current >= 6) paintFace(true); } catch (e) { console.error("workspace", e); }
  }

  // ---------------------------------------------------------------- mapa 3D: el ecosistema como grafo de conocimiento
  const GROUP_NAMES = {
    hub: "Centro", agent: "Agente al día", alert: "Alerta o agente atrasado", market: "Mercado", asset: "Activo",
    hot: "Activo cerca de la compra", strategy: "Estrategia", rejected: "Estrategias rechazadas", research: "Investigación",
    forecast: "Pronóstico", sentiment: "Sentimiento", project: "Proyecto", person: "Persona", money: "Money Printer",
    zyneath: "Zyneath", rules: "Reglas de riesgo", proposal: "Propuesta o posición", pending: "Pendiente del equipo",
  };
  const GROUP_COLORS = {
    hub: "#ff4d6d", agent: "#45e0b0", alert: "#ff4d6d", market: "#6fd3ff", asset: "#6fd3ff", hot: "#ffb547",
    strategy: "#aa8cff", rejected: "#786ea0", research: "#ffd66e", forecast: "#78e6ff", sentiment: "#d2a0ff",
    project: "#5a96ff", person: "#ebf0ff", money: "#50e68c", zyneath: "#ff82c8", rules: "#ffb547", proposal: "#ff4d6d", pending: "#ff9f43",
  };
  let graphOn = false, graphTourAt = 0, graphTourIdx = 0, graphNodes = new Map();

  function buildGraph() {
    const nodes = [], links = [];
    const add = (id, label, group, size, info) => { nodes.push({ id, label, group, size, info: info.filter(Boolean) }); graphNodes.set(id, nodes[nodes.length - 1]); };
    const link = (a, b, rel, w) => links.push({ source: a, target: b, rel, w: w || 1 });
    graphNodes = new Map();
    const sa = state.standing_authorization || {};
    const usdt = state.portfolio ? state.portfolio.balances.filter((b) => b.asset === "USDT").reduce((s, b) => s + Number(b.free) + Number(b.locked), 0) : null;

    add("lab", "AI Trading Lab", "hub", 2.4, [`Saldo ${num(usdt, 2)} USDT`, `Piloto automático ${sa.active ? "encendido" : "apagado"}`, `${state.open_positions.length} posición(es) abierta(s)`]);
    nodes[0].pinned = true;
    add("founder", "Juan Emilio", "person", 1.6, ["Fundador: autoriza, veta y fija los límites", "Su silencio tras el veto es aprobación (evento 34)"]);
    link("founder", "lab", "dirige", 1.5);
    add("rules", "Reglas de riesgo", "rules", 1.1, [`Veto ${sa.veto_minutes ?? "—"} min`, `Pérdida máx. ${num(sa.max_loss_usdt, 2)} USDT por operación`,
      `Riesgo/beneficio mín. ${num(sa.min_reward_risk, 1)}`, `Pérdida semanal máx. ${num(sa.weekly_loss_limit_usdt, 2)} USDT (llevas ${num(state.pnl_7d, 2)})`,
      "Solo Spot · 5 pares · 7 USDT · 1 posición"]);
    link("founder", "rules", "fija");
    link("rules", "lab", "limita");

    for (const a of state.agents) {
      const la = state.last_analyses[a.agent_id];
      add(`ag:${a.agent_id}`, AGENT_NAMES[a.agent_id], a.state === "ok" ? "agent" : "alert", 1.7, [
        a.state === "ok" ? `Al día · última actividad ${ago(a.last_activity)}` : a.reason,
        la ? `Último análisis: ${la.proposed_action} (ciclo ${la.cycle_id})` : null,
        la?.market_regime ? la.market_regime.slice(0, 220) : null,
        a.agent_id === "chatgpt" ? "Único ejecutor en Binance" : "Solo lectura en Binance: investiga, propone y revisa"]);
      link(`ag:${a.agent_id}`, "lab", "trabaja en", 1.4);
    }
    link("ag:claude", "ag:chatgpt", "revisión cruzada", 0.8);

    add("binance", "Binance Spot", "market", 1.4, [`${num(usdt, 2)} USDT`, state.portfolio ? `Verificado ${ago(state.portfolio.observed_at)}` : null]);
    link("lab", "binance", "opera en", 1.3);
    link("ag:chatgpt", "binance", "ejecuta", 0.6);
    link("ag:claude", "binance", "lee", 0.4);
    const f7 = forecastMap(7);
    for (const r of (radar?.rows || []).filter((x) => !x.error)) {
      const near = Math.max(0, Math.min(1, 1 - r.gap_to_entry / 0.15));
      const f = f7[r.symbol];
      add(`as:${r.symbol}`, r.symbol.replace("USDT", ""), r.in_strategy && r.gap_to_entry < 0.02 ? "hot" : "asset", 0.8 + near * 0.9, [
        `Precio ${num(r.price, r.price < 10 ? 4 : 2)} USDT`, r.gap_to_entry <= 0 ? "Por encima del máximo de 20 días: se decide al cierre" : `A ${num(r.gap_to_entry * 100, 1)} % de la compra (máx. 20 días ${num(r.entry_level, 4)})`,
        `Salida si cierra bajo ${num(r.exit_level, 4)}`, f ? `TimesFM 7 d: mediana ${signed(f.median_return * 100)} %` : null,
        r.in_strategy ? "Lo opera S-CHANNEL-1D" : "Fuera de S-CHANNEL-1D"]);
      link("binance", `as:${r.symbol}`, "cotiza");
    }

    const byStatus = {};
    for (const s of state.strategies) (byStatus[s.status] ||= []).push(s);
    for (const s of state.strategies.filter((x) => ["LIVE_ELIGIBLE", "PAPER", "TESTING", "PREREGISTERED", "CANDIDATE"].includes(x.status))) {
      add(`st:${s.strategy_id}`, s.strategy_id, "strategy", s.status === "LIVE_ELIGIBLE" ? 1.5 : 1, [`${s.status}${s.name ? " · " + s.name : ""}`, s.status_reason ? s.status_reason.slice(0, 200) : null, s.last_verdict ? `Último veredicto: ${s.last_verdict}` : null]);
      link("lab", `st:${s.strategy_id}`, s.status === "LIVE_ELIGIBLE" ? "opera con" : "prueba en papel");
      if (s.strategy_id.startsWith("S-CHANNEL-1D")) {
        for (const r of (radar?.rows || []).filter((x) => x.in_strategy)) link(`st:${s.strategy_id}`, `as:${r.symbol}`, "vigila", 0.5);
      }
    }
    if (byStatus.REJECTED) {
      add("st:rejected", `Rechazadas (${byStatus.REJECTED.length})`, "rejected", 1, ["No pasaron el hard testing:", ...byStatus.REJECTED.slice(0, 10).map((s) => s.strategy_id)]);
      link("lab", "st:rejected", "descartó", 0.4);
    }
    for (const s of (state.signals || []).filter((x) => x.signal === "ENTRY")) {
      if (graphNodes.has(`st:${s.strategy_id}`) && graphNodes.has(`as:${s.symbol}`)) link(`st:${s.strategy_id}`, `as:${s.symbol}`, "señal de ENTRADA", 2);
    }

    const p = activeProposal();
    if (p) {
      add("proposal", `Propuesta ${p.symbol.replace("USDT", "")}`, "proposal", 1.4, [p.proposal_id, p.status, `Zona ${num(p.entry_low, 4)}–${num(p.entry_high, 4)} · stop ${num(p.invalidation, 4)}`]);
      link("proposal", `as:${p.symbol}`, "compra", 1.5);
      link("ag:chatgpt", "proposal", "revisa o ejecuta");
    }
    const pos = state.open_positions[0];
    if (pos) {
      add("position", `Posición ${pos.symbol.replace("USDT", "")}`, "proposal", 1.6, [`Entrada ${num(pos.entry_price, 4)} · stop ${num(pos.stop ?? pos.invalidation, 4)}`, `${num(pos.notional_usdt, 2)} USDT`]);
      link("position", `as:${pos.symbol}`, "en", 2);
      link("binance", "position", "custodia");
    }

    const fs = (state.forecast?.skill || [])[0];
    add("tsfm", "TimesFM 3.0", "forecast", 1.2, ["Pronóstico en papel a 1, 3 y 7 días", fs ? `${fs.scored} puntuados · dirección ${pct(fs.direction_hit_rate, 0)}` : "Aún sin pronósticos vencidos", "Se decide a los 60 cierres (≈ 6 dic)"]);
    link("ag:claude", "tsfm", "cita");
    for (const s of Object.keys(f7)) if (graphNodes.has(`as:${s}`)) link("tsfm", `as:${s}`, "pronostica", 0.4);

    const fg = (state.sentiment?.latest || []).find((r) => r.metric === "fear_greed");
    add("sent", `Sentimiento${fg ? " · " + Math.round(fg.value) : ""}`, "sentiment", 1.1, [fg ? `Fear & Greed ${Math.round(fg.value)} (${fg.label || ""})` : null, "Contexto, no señal: los filtros de euforia empeoraban la estrategia"]);
    link("ag:claude", "sent", "recoge");
    for (const t of (state.sentiment?.tone_24h || []).filter((x) => x.items > 0)) if (graphNodes.has(`as:${t.symbol}`)) link("sent", `as:${t.symbol}`, `tono ${num(t.avg_sentiment, 2)}`, 0.3);

    const th = state.ai_thesis || {};
    add("thesis", "Tesis IA", "research", 1.3, [th.AI_BOTTLENECK ? th.AI_BOTTLENECK.title : "Informe mensual del día 25", "13F de Situational Awareness, capex y oferta física"]);
    link("ag:claude", "thesis", "investiga");
    link("lab", "thesis", "investigación", 0.5);
    if (th.AI_BOTTLENECK) { add("neck", "Cuello de botella", "research", 0.9, [th.AI_BOTTLENECK.body.slice(0, 400)]); link("thesis", "neck", "concluye"); }
    for (const b of (th["13F_BOOK"]?.data?.book || []).slice(0, 5)) {
      add(`13f:${b.cusip}`, b.ticker || b.issuer.slice(0, 10), "research", 0.6 + b.weight * 3, [`${pct(b.weight, 1)} del libro 13F`, b.issuer]);
      link("thesis", `13f:${b.cusip}`, "en el 13F", 0.5);
    }

    for (const pr of workspace?.projects || []) {
      const id = `pj:${pr.name}`;
      add(id, pr.name, /zyneath|medflow/i.test(pr.name) ? "zyneath" : pr.name === "money-engine" ? "money" : "project", 1 + Math.min(1, (pr.commits_7d || 0) / 30),
        [pr.role, pr.error ? pr.error : `${pr.commits_7d} commits en 7 días`, pr.recent?.[0] ? `Último: ${pr.recent[0].subject} (${ago(pr.recent[0].at)})` : null]);
      link("founder", id, "construye", 0.8);
      if (pr.name === "AI Trading Lab") link(id, "lab", "código de", 1.2);
      if (pr.name.startsWith("TimesFM")) link(id, "tsfm", "alimenta", 0.8);
      for (const [author, n] of Object.entries(pr.authors_7d || {})) {
        const pid = /juan|juanemen/i.test(author) ? "founder" : author === "Claude" ? "ag:claude" : `pe:${author}`;
        if (!graphNodes.has(pid)) add(pid, author, "person", 0.9, [author === "Claude" ? "Agente de código" : "Colaborador"]);
        link(pid, id, `${n} commit(s)`, 0.5);
      }
    }
    (workspace?.pending || []).slice(0, 14).forEach((it, i) => {
      const id = `pd:${i}`;
      add(id, it.text.length > 30 ? `${it.text.slice(0, 28)}…` : it.text, "pending", it.level === 3 ? 0.9 : 0.7, [it.project, it.text, `Responsable: ${it.who}`]);
      if (graphNodes.has(`pj:${it.project}`)) link(id, `pj:${it.project}`, "pendiente en", 0.6);
      const person = /juan emilio/i.test(it.who) ? "founder" : it.who === "Claude" ? "ag:claude" : `pe:${it.who}`;
      if (!graphNodes.has(person) && !/sin asignar/.test(it.who)) add(person, it.who, "person", 0.9, ["Colaborador"]);
      if (graphNodes.has(person)) link(person, id, "debe", 0.4);
    });
    const m = workspace?.money;
    if (m && !m.error) {
      add("money", "Money Printer", "money", 1.3, [m.paused ? "PAUSADO" : "Activo", m.video_engine_up ? "MoneyPrinterTurbo en línea" : "MoneyPrinterTurbo apagado",
        `Hoy ${m.published_today}/${m.per_day ?? "—"} · ${Object.entries(m.counts || {}).map(([k, v]) => `${k} ${v}`).join(", ")}`]);
      link("founder", "money", "gana con");
      if (graphNodes.has("pj:money-engine")) link("pj:money-engine", "money", "motor", 1.2);
      add("youtube", (m.platforms || ["youtube"]).join(", "), "money", 0.8, ["Plataforma de publicación de los shorts"]);
      link("money", "youtube", "publica en");
    }
    const z = workspace?.zyneath;
    if (z) {
      const needed = Math.ceil(z.target_annual_usd / 12 / z.price_usd_month);
      add("zyneath", "Zyneath", "zyneath", 1.6, [z.stage, `Meta: ${needed} clínicas × ${num(z.price_usd_month, 0)} USD/mes = ${num(z.target_annual_usd / 1e6, 1)} M USD/año`, z.active_clinics ? `${z.active_clinics} clínicas activas` : "Clínicas activas: sin dato"]);
      link("founder", "zyneath", "funda", 1.2);
      for (const pr of workspace.projects.filter((x) => /zyneath|medflow/i.test(x.name))) link("zyneath", `pj:${pr.name}`, "producto", 1.2);
    }
    for (const t of state.team || []) {
      add(`tm:${t.member_id}`, t.display_name, "person", 0.9, [`Rol: ${t.role || "—"}`, t.active ? "Activo" : "Inactivo", `${t.steps_done} pasos de onboarding`]);
      link(`tm:${t.member_id}`, "lab", "equipo");
    }
    for (const e of state.open_events.filter((x) => x.severity !== "info").slice(0, 4)) {
      add(`ev:${e.id}`, e.kind, "alert", 0.8, [`${e.severity}: ${e.message.slice(0, 240)}`]);
      link(`ev:${e.id}`, e.agent_id ? `ag:${e.agent_id}` : "lab", "alerta", 0.5);
    }
    return { nodes, links };
  }

  function showGraphCard(n) {
    const card = $("graph-card");
    if (!n) { card.hidden = true; return; }
    const neigh = [];
    const g = buildGraph();
    for (const l of g.links) {
      if (l.source === n.id) neigh.push([l.target, l.rel]);
      else if (l.target === n.id) neigh.push([l.source, l.rel]);
    }
    card.hidden = false;
    card.replaceChildren(
      h("div", { class: "kind", text: GROUP_NAMES[n.group] || n.group }),
      h("h3", { text: n.label }),
      h("ul", {}, (n.info || []).map((line) => h("li", { text: line }))),
      neigh.length ? h("div", { class: "links" }, neigh.slice(0, 16).map(([id, rel]) => h("button", { type: "button",
        onclick: () => { const t = window.TV3D.focus(id); graphTourAt = Date.now() + 30_000; showGraphCard(t && graphNodes.get(id)); },
        text: `${rel} → ${graphNodes.get(id)?.label || id}` }))) : null);
  }

  function refreshGraph() {
    if (!state || !window.TV3D) return;
    const g = buildGraph();
    window.TV3D.setGraph(g);
    const present = new Set(g.nodes.map((n) => n.group));
    fill("graph-legend", Object.keys(GROUP_NAMES).filter((k) => present.has(k)).map((k) => {
      const dot = h("i");
      dot.style.color = GROUP_COLORS[k];
      return h("span", {}, dot, GROUP_NAMES[k]);
    }));
  }

  function setGraphMode(on) {
    graphOn = on;
    document.body.classList.toggle("graph", on);
    $("graph-ui").hidden = !on;
    if (window.TV3D) window.TV3D.set({ mode: on ? "graph" : "orbit" });
    if (on) { refreshGraph(); graphTourAt = Date.now() + 6000; } else $("graph-card").hidden = true;
  }

  // Recorrido automático cuando nadie toca nada: va de nodo en nodo por lo más importante y muestra su ficha.
  function graphTour() {
    if (!graphOn || !window.TV3D || !window.TV3D.graphIdle() || Date.now() < graphTourAt) return;
    const order = ["lab", "ag:claude", "ag:chatgpt", "binance", "proposal", "position", "rules", "tsfm", "thesis", "sent", "money", "zyneath", "founder",
      ...[...graphNodes.keys()].filter((k) => k.startsWith("as:") || k.startsWith("st:") || k.startsWith("pj:"))].filter((k) => graphNodes.has(k));
    const id = order[graphTourIdx++ % order.length];
    window.TV3D.focus(id);
    showGraphCard(graphNodes.get(id));
    graphTourAt = Date.now() + 9000;
  }

  $("graph-toggle").addEventListener("click", () => setGraphMode(true));
  $("graph-back").addEventListener("click", () => setGraphMode(false));
  if (window.TV3D) {
    window.TV3D.onGraphSelect((n) => { graphTourAt = Date.now() + 30_000; showGraphCard(n && graphNodes.get(n.id)); });
  }
  setInterval(graphTour, 1000);

  // ---------------------------------------------------------------- interacción
  document.addEventListener("keydown", (e) => {
    if (e.key === "g" || e.key === "G") return setGraphMode(!graphOn);
    if (e.key === "Escape" && graphOn) return setGraphMode(false);
    if (graphOn) return;
    if (e.key === "ArrowRight") go(current + 1, true);
    else if (e.key === "ArrowLeft") go(current - 1, true);
    else if (/^[1-9]$/.test(e.key)) go(Number(e.key) - 1, true);
    else if (e.key === " ") { pausedUntil = Date.now() < pausedUntil ? 0 : Date.now() + 10 * 60_000; renderTabs(); }
  });
  let touchX = null;
  document.addEventListener("touchstart", (e) => { touchX = e.touches[0].clientX; }, { passive: true });
  document.addEventListener("touchend", (e) => {
    if (touchX === null || graphOn) return;
    const dx = e.changedTouches[0].clientX - touchX;
    if (Math.abs(dx) > 60) go(current + (dx < 0 ? 1 : -1), true);
    touchX = null;
  }, { passive: true });
  let idleTimer = null;
  document.addEventListener("mousemove", () => {
    document.body.classList.remove("idle");
    clearTimeout(idleTimer);
    idleTimer = setTimeout(() => document.body.classList.add("idle"), 4000);
  });

  // Mientras la pestaña está visible, la pantalla no se apaga (API Wake Lock; 127.0.0.1 cuenta como contexto seguro).
  async function keepAwake() {
    try { if ("wakeLock" in navigator && document.visibilityState === "visible") await navigator.wakeLock.request("screen"); } catch (e) { console.warn("wake lock", e); }
  }
  const shiftPixels = () => {
    const r = () => Math.round((Math.random() * 2 - 1) * SHIFT_PX);
    $("stage").style.transform = `translate(${r()}px, ${r()}px)`;
  };

  // /tv#7 abre directamente la sección 7 (Money Printer); sin número, empieza por el mercado.
  const fromHash = Number(location.hash.slice(1));
  if (fromHash >= 1 && fromHash <= SECTIONS.length) current = fromHash - 1;
  if (window.TV3D) window.TV3D.set({ section: current });

  document.body.classList.add("idle");
  tick();
  setInterval(tick, 1000);
  Promise.all([refreshRadar(), refreshWorkspace()]).then(refreshState);
  setInterval(refreshState, 20_000);
  setInterval(refreshRadar, 30_000);
  setInterval(refreshWorkspace, 120_000);
  setInterval(shiftPixels, 180_000);
  setTimeout(() => location.reload(), 6 * 3_600_000); // una pantalla que nunca se cierra toma el código nuevo sola
  document.addEventListener("visibilitychange", keepAwake);
  keepAwake();
})();
