// Centro de mando: lee /api/state y /api/candles (servidor local de solo lectura) y pinta el laboratorio.
// Todo texto que viene de la base o de internet se inserta con textContent, nunca como HTML.
(() => {
  "use strict";

  const UNIVERSE = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "LINKUSDT", "ONDOUSDT"];
  const RADAR = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "LINKUSDT"]; // S-CHANNEL-1D no incluye ONDO
  const INTERVALS = [["1h", "1 h"], ["4h", "4 h"], ["1d", "1 día"]];
  const AGENT_NAMES = { claude: "Claude", chatgpt: "Codex" };
  const KIND_NAMES = {
    analysis: "análisis", message: "mensaje", review: "revisión", proposal: "propuesta", trade: "operación",
    closure: "cierre", event: "evento", strategy: "estrategia", veto: "veto",
  };
  const FUNNEL = ["DISCOVERED", "CANDIDATE", "TESTING", "PAPER", "LIVE_ELIGIBLE", "REJECTED", "NOT_APPLICABLE"];
  const CHECK_NAMES = {
    standing_authorization_active: "Autorización permanente activa",
    strategy_live_eligible: "Estrategia validada",
    reviewed_approve: "Revisión APPROVE",
    veto_window_elapsed: "Pasaron 15 min de veto",
    not_vetoed: "Sin veto",
    not_expired: "No expirada",
    max_loss_ok: "Pérdida ≤ máximo",
    reward_risk_ok: "Riesgo/beneficio ≥ 1,5",
    weekly_loss_ok: "Pérdida semanal OK",
    executor_permissions_ok: "Permisos del ejecutor OK",
    no_open_position: "Sin posición abierta",
    not_executed: "No ejecutada",
  };

  let state = null;
  let symbol = "BTCUSDT";
  let interval = "1d";

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
  const svg = (tag, attrs) => {
    const el = document.createElementNS("http://www.w3.org/2000/svg", tag);
    for (const [k, v] of Object.entries(attrs || {})) el.setAttribute(k, v);
    return el;
  };
  const $ = (id) => document.getElementById(id);
  const fill = (id, ...nodes) => $(id).replaceChildren(...nodes.flat().filter(Boolean));
  const num = (v, d = 2) => (v === null || v === undefined || Number.isNaN(Number(v)))
    ? "—" : Number(v).toLocaleString("es-EC", { minimumFractionDigits: d, maximumFractionDigits: d });
  const pct = (v, d = 2) => (v === null || v === undefined) ? "—" : `${num(v * 100, d)} %`;
  const safeUrl = (u) => (typeof u === "string" && u.startsWith("https://")) ? u : null;
  const quitoFmt = new Intl.DateTimeFormat("es-EC", { timeZone: "America/Guayaquil", hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false });
  const utcFmt = new Intl.DateTimeFormat("es-EC", { timeZone: "UTC", hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false });
  const dayFmt = new Intl.DateTimeFormat("es-EC", { timeZone: "America/Guayaquil", day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit", hour12: false });

  function ago(iso) {
    if (!iso) return "—";
    const s = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
    if (s < 60) return "hace segundos";
    if (s < 3600) return `hace ${Math.round(s / 60)} min`;
    if (s < 86400) return `hace ${Math.round(s / 3600)} h`;
    return `hace ${Math.round(s / 86400)} d`;
  }

  // ---------------------------------------------------------------- relojes
  function tick() {
    const now = new Date();
    $("clock-utc").textContent = utcFmt.format(now);
    $("clock-quito").textContent = quitoFmt.format(now);
    const close = new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate() + 1));
    const left = Math.max(0, Math.floor((close - now) / 1000));
    const hh = String(Math.floor(left / 3600)).padStart(2, "0");
    const mm = String(Math.floor((left % 3600) / 60)).padStart(2, "0");
    const ss = String(left % 60).padStart(2, "0");
    $("countdown").textContent = `${hh}:${mm}:${ss}`;
  }

  // ---------------------------------------------------------------- paneles
  function renderStatus() {
    fill("agent-status", state.agents.map((a) => h("span", {
      class: `pill ${a.state.replace(" ", "-")}`,
      title: a.last_activity ? `Última actividad: ${dayFmt.format(new Date(a.last_activity))}` : "Sin actividad registrada",
    }, h("i"), `${AGENT_NAMES[a.agent_id] || a.agent_id} · ${a.state === "ok" ? ago(a.last_activity) : a.state}`)));
  }

  function renderAlerts() {
    const events = state.open_events.filter((e) => e.severity !== "info");
    const box = $("alerts");
    box.hidden = events.length === 0;
    box.replaceChildren(...events.map((e) => h("div", { class: `alert ${e.severity}` },
      h("b", { text: `${e.severity.toUpperCase()} · ${e.kind}` }), e.message)));
  }

  function sparkline(points) {
    const W = 300, H = 56;
    const el = svg("svg", { viewBox: `0 0 ${W} ${H}`, class: "spark", preserveAspectRatio: "none", role: "img", "aria-label": "Evolución del saldo en USDT" });
    const defs = svg("defs");
    const grad = svg("linearGradient", { id: "sparkfill", x1: "0", y1: "0", x2: "0", y2: "1" });
    grad.append(svg("stop", { offset: "0%", "stop-color": "#6fd3ff", "stop-opacity": "0.35" }),
      svg("stop", { offset: "100%", "stop-color": "#6fd3ff", "stop-opacity": "0" }));
    defs.append(grad);
    el.append(defs);
    if (points.length < 2) return el;
    const vals = points.map((p) => p.usdt);
    const lo = Math.min(...vals), hi = Math.max(...vals);
    const span = hi - lo || Math.max(1, hi * 0.01);
    const xy = vals.map((v, i) => [i / (vals.length - 1) * W, H - 6 - ((v - lo) / span) * (H - 12)]);
    const d = xy.map(([x, y], i) => `${i ? "L" : "M"}${x.toFixed(1)},${y.toFixed(1)}`).join(" ");
    el.append(svg("path", { d: `${d} L${W},${H} L0,${H} Z`, class: "area" }), svg("path", { d, class: "line" }));
    return el;
  }

  function renderAccount() {
    const p = state.portfolio;
    const usdt = p ? p.balances.filter((b) => b.asset === "USDT").reduce((s, b) => s + Number(b.free) + Number(b.locked), 0) : null;
    const others = p ? p.balances.filter((b) => b.asset !== "USDT" && Number(b.free) + Number(b.locked) > 0) : [];
    const limits = state.risk_limits || {};
    const standing = state.standing_authorization || {};
    const weekly = Number(state.pnl_7d || 0);
    const limit = Number(standing.weekly_loss_limit_usdt || 1);
    const used = Math.min(1, Math.max(0, -weekly / limit));
    const meter = h("div", { class: "meter", title: "Pérdidas cerradas de 7 días frente al límite semanal" }, h("span"));
    meter.firstChild.style.width = `${(used * 100).toFixed(1)}%`;
    const pos = state.open_positions[0];
    fill("account",
      h("div", { class: "big" }, usdt === null ? "—" : num(usdt, 2), h("small", { text: "USDT" })),
      h("div", { class: "sub", text: p ? `Verificado en Binance ${ago(p.observed_at)} · ${p.open_orders.length} órdenes abiertas` : "Sin foto de la cuenta" }),
      others.length ? h("div", { class: "sub", text: `También: ${others.map((b) => `${num(Number(b.free) + Number(b.locked), 6)} ${b.asset}`).join(", ")}` }) : null,
      pos ? h("div", { class: "position" },
        h("b", { text: `Posición abierta · ${pos.symbol}` }),
        h("div", { class: "sub", text: `Entrada ${num(pos.entry_price, 4)} · stop ${num(pos.stop ?? pos.invalidation, 4)} · ${num(pos.notional_usdt, 2)} USDT` }))
        : h("div", { class: "position sub", text: "Sin posición abierta" }),
      sparkline(state.equity),
      h("dl", { class: "kv" },
        h("dt", { text: "Pérdidas 7 días" }), h("dd", { text: `${num(weekly, 2)} / −${num(limit, 2)} USDT` })),
      meter,
      h("dl", { class: "kv" },
        h("dt", { text: "Máx. por posición" }), h("dd", { text: `${num(limits.max_position_usdt, 0)} USDT` }),
        h("dt", { text: "Posiciones abiertas máx." }), h("dd", { text: String(limits.max_open_positions ?? "—") }),
        h("dt", { text: "Pérdida máx. por operación" }), h("dd", { text: `${num(standing.max_loss_usdt, 2)} USDT` }),
        h("dt", { text: "Ventana de veto" }), h("dd", { text: standing.active ? `${standing.veto_minutes} min` : "inactiva" }),
        h("dt", { text: "Ejecutor" }), h("dd", { text: AGENT_NAMES[limits.executor_agent_id] || limits.executor_agent_id || "—" })));
  }

  function renderDuel() {
    const score = Object.fromEntries((state.scoreboard || []).map((s) => [s.agent_id, s]));
    fill("duel", ["claude", "chatgpt"].map((id) => {
      const a = state.last_analyses[id];
      const health = state.agents.find((x) => x.agent_id === id) || {};
      const s = score[id] || {};
      return h("article", { class: `agent-card ${id}` },
        h("header", {}, h("h3", { text: AGENT_NAMES[id] }),
          a ? h("span", { class: `badge ${a.proposed_action === "BUY_CANDIDATE" ? "buy" : ""}`, text: a.proposed_action }) : null),
        a ? h("div", { class: "sub", text: `Ciclo ${a.cycle_id || "—"} · ${ago(a.created_at)}` })
          : h("div", { class: "empty", text: "Todavía no escribió ningún análisis." }),
        a ? h("p", { class: "regime", text: a.market_regime || "" }) : null,
        h("div", { class: "stats" },
          h("span", {}, "Análisis ", h("b", { text: String(state.analyses_count[id] || 0) })),
          h("span", {}, "Puntuados ", h("b", { text: String(s.decisions_scored || 0) })),
          h("span", {}, "R medio ", h("b", { text: s.avg_r_after_fees == null ? "—" : num(s.avg_r_after_fees, 2) })),
          h("span", {}, "Estado ", h("b", { text: health.state || "—" }))));
    }));
  }

  function renderProposal() {
    const active = state.proposals.filter((p) => !["EXECUTED", "EXPIRED"].includes(p.status));
    if (!active.length) {
      fill("proposal", h("p", { class: "empty", text: "Sin propuestas activas. S-CHANNEL-1D se evalúa tras el cierre diario (00:00 UTC · 19:00 Quito)." }));
      return;
    }
    const p = active[0];
    const auto = p.auto || {};
    fill("proposal",
      h("div", {}, h("span", { class: `badge ${p.last_verdict || ""}`, text: p.status }), " ",
        h("b", { text: `${p.side} ${p.symbol}` }), h("span", { class: "sub", text: ` · ${p.proposal_id}` })),
      h("dl", { class: "kv" },
        h("dt", { text: "Zona de entrada" }), h("dd", { text: `${num(p.entry_low, 4)} – ${num(p.entry_high, 4)}` }),
        h("dt", { text: "Invalidación (stop)" }), h("dd", { text: num(p.invalidation, 4) }),
        h("dt", { text: "Referencia 2R" }), h("dd", { text: num((p.targets || [])[0], 4) }),
        h("dt", { text: "Pérdida estimada" }), h("dd", { text: `${num(auto.estimated_max_loss_usdt, 3)} USDT` }),
        h("dt", { text: "Riesgo/beneficio" }), h("dd", { text: num(auto.reward_risk, 2) }),
        h("dt", { text: "Expira" }), h("dd", { text: p.expires_at ? dayFmt.format(new Date(p.expires_at)) : "—" })),
      h("ul", { class: "checks" }, Object.entries(CHECK_NAMES).filter(([k]) => k in auto)
        .map(([k, label]) => h("li", { class: auto[k] ? "ok" : "", text: label }))),
      h("p", { class: "sub", text: auto.auto_ok ? "Cumple todo: se ejecutaría sola tras la ventana de veto." : "No se ejecuta sola: falta algún requisito o tu «autorizo»." }));
  }

  async function renderRadar() {
    const rows = await Promise.all(RADAR.map(async (s) => {
      try {
        const data = await getJSON(`/api/candles?symbol=${s}&interval=1d`);
        const last = data.candles[data.candles.length - 1];
        const levels = data.channel.filter((c) => c.entry_level !== null);
        const lvl = levels[levels.length - 1];
        return { s, close: last.close, entry: lvl ? lvl.entry_level : null };
      } catch (e) { return { s, close: null, entry: null }; }
    }));
    fill("radar", h("div", { class: "sub", text: "Radar S-CHANNEL-1D · distancia del último cierre diario al máximo de 20 días (la entrada)" }),
      h("div", { class: "radar" }, rows.map((r) => {
        const gap = (r.entry && r.close) ? (r.entry - r.close) / r.close : null;
        const closeness = gap === null ? 0 : Math.max(0.03, Math.min(1, 1 - gap / 0.15));
        const track = h("div", { class: `track ${gap !== null && gap < 0.02 ? "near" : ""}` }, h("span"));
        track.firstChild.style.width = `${(closeness * 100).toFixed(1)}%`;
        return h("div", { class: "radar-row" }, h("b", { text: r.s.replace("USDT", "") }), track,
          h("span", { class: "val", text: gap === null ? "—" : gap <= 0 ? "¡RUPTURA!" : `a ${num(gap * 100, 1)} %` }));
      })));
  }

  function renderTimeline() {
    fill("timeline", state.timeline.map((e) => h("li", { class: e.kind },
      h("div", { class: "tl-head" },
        h("span", { class: "who", text: AGENT_NAMES[e.agent] || e.agent || "" }),
        h("span", { class: "badge", text: KIND_NAMES[e.kind] || e.kind }),
        h("span", { text: e.title || "" }),
        h("span", { class: "when", text: ago(e.at) })),
      e.detail ? h("div", { class: "tl-detail", text: e.detail }) : null)));
  }

  function renderStrategies() {
    const counts = {};
    for (const s of state.strategies) counts[s.status] = (counts[s.status] || 0) + 1;
    const max = Math.max(1, ...Object.values(counts));
    fill("funnel", FUNNEL.filter((k) => counts[k]).map((k) => {
      const bar = h("div", { class: "bar" }, h("span"));
      bar.firstChild.style.width = `${(counts[k] / max * 100).toFixed(1)}%`;
      return h("div", { class: "funnel-row" }, h("span", { text: k }), bar, h("b", { text: String(counts[k]) }));
    }));
    const order = { LIVE_ELIGIBLE: 0, PAPER: 1, TESTING: 2, PREREGISTERED: 3, CANDIDATE: 4 };
    const list = [...state.strategies].sort((a, b) => (order[a.status] ?? 9) - (order[b.status] ?? 9));
    fill("strategy-list", list.map((s) => h("li", {},
      h("span", { class: `badge ${s.status}`, text: s.status }),
      h("span", { class: "name", text: `${s.strategy_id} · ${s.name}` }),
      h("span", { class: "why", text: s.status_reason || "" }))));
  }

  function gauge(value, label) {
    const box = svg("svg", { viewBox: "0 0 150 88", role: "img", "aria-label": `Fear & Greed ${value}` });
    const defs = svg("defs");
    const g = svg("linearGradient", { id: "fg", x1: "0", x2: "1" });
    g.append(svg("stop", { offset: "0%", "stop-color": "#dc143c" }), svg("stop", { offset: "50%", "stop-color": "#8b93b8" }),
      svg("stop", { offset: "100%", "stop-color": "#6fd3ff" }));
    defs.append(g);
    box.append(defs, svg("path", { d: "M12,80 A63,63 0 0 1 138,80", fill: "none", stroke: "url(#fg)", "stroke-width": "12", "stroke-linecap": "round" }));
    const angle = Math.PI * (1 - Math.max(0, Math.min(100, value)) / 100);
    box.append(svg("line", { x1: "75", y1: "80", x2: String(75 + 52 * Math.cos(angle)), y2: String(80 - 52 * Math.sin(angle)), stroke: "#e8eeff", "stroke-width": "3", "stroke-linecap": "round" }),
      svg("circle", { cx: "75", cy: "80", r: "5", fill: "#e8eeff" }));
    return h("div", { class: "gauge" }, box, h("div", {}, h("div", { class: "value", text: String(value) }), h("div", { class: "label", text: label || "" })));
  }

  function renderSentiment() {
    const latest = state.sentiment.latest;
    const fg = latest.find((r) => r.metric === "fear_greed");
    const bySym = {};
    for (const r of latest) if (r.symbol) (bySym[r.symbol] ||= {})[r.metric] = r.value;
    const tone = Object.fromEntries(state.sentiment.tone_24h.map((t) => [t.symbol, t]));
    const toneCell = (t) => t ? h("td", { class: `num ${t.avg_sentiment > 0.05 ? "tone-pos" : t.avg_sentiment < -0.05 ? "tone-neg" : ""}`, text: `${num(t.avg_sentiment, 2)} (${t.items})` }) : h("td", { class: "num", text: "—" });
    fill("sentiment",
      fg ? gauge(Math.round(fg.value), `${fg.label || ""} · Fear & Greed`) : h("p", { class: "empty", text: "Aún sin Fear & Greed." }),
      h("table", { class: "mini-table" },
        h("thead", {}, h("tr", {}, h("th", { text: "Par" }), h("th", { text: "Funding (cobro)" }), h("th", { text: "Largo/corto" }), h("th", { text: "Tono 24 h" }))),
        h("tbody", {}, UNIVERSE.map((s) => h("tr", {},
          h("td", { text: s.replace("USDT", "") }),
          h("td", { class: "num", text: bySym[s] ? pct(bySym[s].funding_rate, 4) : "—" }),
          h("td", { class: "num", text: bySym[s] ? num(bySym[s].long_short_account_ratio, 2) : "—" }),
          toneCell(tone[s]))),
          h("tr", {}, h("td", { text: "Mercado" }), h("td"), h("td"), toneCell(tone.MERCADO)))),
      h("p", { class: "sub", text: "Probado el 2026-09-24: abstenerse en euforia empeoraba S-CHANNEL-1D; esto es solo contexto." }));
  }

  function renderNews() {
    fill("news", state.news.map((n) => {
      const url = safeUrl(n.url);
      const title = url ? h("a", { href: url, target: "_blank", rel: "noopener noreferrer", text: n.title }) : h("span", { text: n.title });
      const cls = n.sentiment <= -0.3 ? "neg" : n.sentiment >= 0.3 ? "pos" : "";
      return h("li", {}, h("span", { class: `tone ${cls}`, title: `Tono ${num(n.sentiment, 2)}` }),
        h("div", {}, title, h("div", { class: "meta", text: `${n.author || n.source} · ${ago(n.published_at)}${n.symbols.length ? " · " + n.symbols.map((s) => s.replace("USDT", "")).join(" ") : ""}` })));
    }));
  }

  function renderResearch() {
    fill("research", state.research.map((r) => {
      const url = safeUrl(r.url);
      return h("li", {}, url ? h("a", { href: url, target: "_blank", rel: "noopener noreferrer", text: r.title }) : h("b", { text: r.title }),
        h("div", { class: "meta", text: `${r.source} · ${ago(r.created_at)}` }), h("p", { text: r.own_summary || "" }));
    }));
  }

  const THEME_NAMES = { tokenizacion: "tokenización", materias_primas: "materias primas" };
  let liqChart = null, liqSeries = null;

  function renderThemes() {
    const items = state.themes || [];
    if (!items.length) { fill("themes", h("li", { class: "empty", text: "Aún no hay titulares de estos temas." })); return; }
    fill("themes", items.map((n) => {
      const url = safeUrl(n.url);
      const title = url ? h("a", { href: url, target: "_blank", rel: "noopener noreferrer", text: n.title }) : h("span", { text: n.title });
      const cls = n.sentiment <= -0.3 ? "neg" : n.sentiment >= 0.3 ? "pos" : "";
      return h("li", {}, h("span", { class: `tone ${cls}` }),
        h("div", {}, n.themes.map((t) => h("span", { class: `badge theme ${t}`, text: THEME_NAMES[t] || t })), title,
          h("div", { class: "meta", text: `${n.author || n.source} · ${ago(n.published_at)}` })));
    }));
  }

  async function renderLiquidity() {
    try {
      const data = await getJSON("/api/liquidity");
      const supply = data.supply, growth = data.growth_30d;
      const last = supply[supply.length - 1], g = growth[growth.length - 1];
      const rwa = (state?.rwa || [])[0];
      const box = h("div", { class: "liq-chart", id: "liq-chart" });
      fill("liquidity",
        h("div", { class: "liq-stats" },
          h("div", {}, h("div", { class: "sub", text: "Oferta de stablecoins (dólar tokenizado)" }),
            h("div", { class: "big", text: last ? `${num(last.value / 1e9, 1)} mil M` : "—" })),
          h("div", {}, h("div", { class: "sub", text: "Crecimiento 30 días" }),
            h("div", { class: `big ${g && g.value > 0 ? "tone-pos" : "tone-neg"}`, text: g ? `${g.value > 0 ? "+" : ""}${num(g.value * 100, 2)} %` : "—" })),
          h("div", {}, h("div", { class: "sub", text: "Activos del mundo real tokenizados" }),
            h("div", { class: "big", text: rwa ? `${num(rwa.value / 1e9, 2)} mil M` : "—" }))),
        box,
        h("p", { class: "sub", text: "Fuente: DefiLlama. Liquidez entrando = más dólares tokenizados disponibles para comprar cripto." }));
      const LWC = window.LightweightCharts;
      liqChart = LWC.createChart(box, {
        layout: { background: { type: "solid", color: "transparent" }, textColor: "#9aa8cf" },
        grid: { vertLines: { visible: false }, horzLines: { color: "rgba(130,160,255,0.06)" } },
        rightPriceScale: { borderVisible: false }, timeScale: { borderVisible: false }, autoSize: true,
        handleScroll: false, handleScale: false,
      });
      liqSeries = liqChart.addAreaSeries({ lineColor: "#6fd3ff", topColor: "rgba(111,211,255,0.35)", bottomColor: "rgba(111,211,255,0)", lineWidth: 2,
        priceFormat: { type: "custom", formatter: (v) => `${(v / 1e9).toFixed(0)} mil M` } });
      liqSeries.setData(supply);
      liqChart.timeScale().fitContent();
    } catch (e) {
      fill("liquidity", h("p", { class: "empty", text: `Liquidez no disponible: ${e.message}` }));
    }
  }

  // ---------------------------------------------------------------- gráfico
  let chart = null, candleSeries = null, volumeSeries = null, entryLine = null, exitLine = null, priceLines = [];

  function initChart() {
    const LWC = window.LightweightCharts;
    chart = LWC.createChart($("chart"), {
      layout: { background: { type: "solid", color: "transparent" }, textColor: "#9aa8cf", fontFamily: "Segoe UI, system-ui, sans-serif" },
      grid: { vertLines: { color: "rgba(130,160,255,0.06)" }, horzLines: { color: "rgba(130,160,255,0.06)" } },
      rightPriceScale: { borderColor: "rgba(130,160,255,0.16)" },
      timeScale: { borderColor: "rgba(130,160,255,0.16)", timeVisible: true },
      crosshair: { mode: LWC.CrosshairMode.Normal },
      autoSize: true,
    });
    candleSeries = chart.addCandlestickSeries({
      upColor: "#6fd3ff", downColor: "#dc143c", borderUpColor: "#6fd3ff", borderDownColor: "#dc143c",
      wickUpColor: "#6fd3ff", wickDownColor: "#dc143c",
    });
    volumeSeries = chart.addHistogramSeries({ priceFormat: { type: "volume" }, priceScaleId: "vol", color: "rgba(111,211,255,0.25)" });
    chart.priceScale("vol").applyOptions({ scaleMargins: { top: 0.82, bottom: 0 } });
    entryLine = chart.addLineSeries({ color: "#ff4d6d", lineWidth: 2, lineStyle: LWC.LineStyle.Dashed, priceLineVisible: false, lastValueVisible: true, title: "entrada 20d" });
    exitLine = chart.addLineSeries({ color: "#7aa2ff", lineWidth: 1, lineStyle: LWC.LineStyle.Dotted, priceLineVisible: false, lastValueVisible: true, title: "salida 10d" });
  }

  function tabs(id, items, current, onPick) {
    fill(id, items.map(([value, label]) => h("button", {
      role: "tab", "aria-selected": String(value === current), text: label, onclick: () => onPick(value),
    })));
  }

  async function loadChart() {
    tabs("symbol-tabs", UNIVERSE.map((s) => [s, s.replace("USDT", "")]), symbol, (s) => { symbol = s; loadChart(); });
    tabs("interval-tabs", INTERVALS, interval, (i) => { interval = i; loadChart(); });
    try {
      const data = await getJSON(`/api/candles?symbol=${symbol}&interval=${interval}`);
      candleSeries.setData(data.candles.map(({ time, open, high, low, close }) => ({ time, open, high, low, close })));
      volumeSeries.setData(data.candles.map((c) => ({ time: c.time, value: c.volume, color: c.close >= c.open ? "rgba(111,211,255,0.25)" : "rgba(220,20,60,0.3)" })));
      const channel = data.channel.filter((c) => c.entry_level !== null);
      entryLine.setData(channel.map((c) => ({ time: c.time, value: c.entry_level })));
      exitLine.setData(channel.map((c) => ({ time: c.time, value: c.exit_level })));
      for (const line of priceLines) candleSeries.removePriceLine(line);
      priceLines = [];
      const proposal = (state?.proposals || []).find((p) => p.symbol === symbol && !["EXECUTED", "EXPIRED"].includes(p.status));
      const position = (state?.open_positions || []).find((p) => p.symbol === symbol);
      const add = (price, color, title) => price && priceLines.push(candleSeries.createPriceLine({ price: Number(price), color, lineWidth: 1, lineStyle: 2, axisLabelVisible: true, title }));
      if (proposal) { add(proposal.entry_high, "#ff4d6d", "zona alta"); add(proposal.entry_low, "#ff4d6d", "zona baja"); add(proposal.invalidation, "#ffb547", "stop"); }
      if (position) { add(position.entry_price, "#45e0b0", "entrada"); add(position.stop ?? position.invalidation, "#ffb547", "stop"); }
      chart.timeScale().fitContent();
      const last = data.candles[data.candles.length - 1];
      const legend = [h("span", { text: `${symbol} · ${interval} · último cierre ${num(last?.close, 4)}` })];
      if (interval === "1d") legend.push(h("span", { class: "sw entry" }), "entrada (máx. 20 días)", h("span", { class: "sw exit" }), "salida (mín. 10 días)");
      if (proposal || position) legend.push(h("span", { class: "sw stop" }), "stop");
      fill("chart-legend", legend);
    } catch (e) {
      fill("chart-legend", h("span", { text: `No se pudieron cargar velas: ${e.message}` }));
    }
  }

  // ---------------------------------------------------------------- ciclo
  async function getJSON(url) {
    const r = await fetch(url, { cache: "no-store" });
    const body = await r.json();
    if (!r.ok) throw new Error(body.error || r.status);
    return body;
  }

  async function refresh() {
    try {
      state = await getJSON("/api/state");
      for (const fn of [renderStatus, renderAlerts, renderAccount, renderDuel, renderProposal, renderTimeline, renderStrategies, renderSentiment, renderNews, renderResearch, renderThemes]) {
        try { fn(); } catch (e) { console.error(fn.name, e); }
      }
      $("updated").textContent = `Actualizado ${quitoFmt.format(new Date())} (Quito) · se refresca cada 30 s`;
    } catch (e) {
      $("updated").textContent = `Sin conexión con el diario: ${e.message}`;
    }
  }

  tick();
  setInterval(tick, 1000);
  initChart();
  refresh().then(() => { loadChart(); renderRadar(); renderLiquidity(); });
  setInterval(renderLiquidity, 3_600_000);
  setInterval(refresh, 30_000);
  setInterval(() => { loadChart(); renderRadar(); }, 120_000);
})();
