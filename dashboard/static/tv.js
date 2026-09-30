// Modo TV: lo esencial del centro de mando en una pantalla fija para el segundo monitor (solo lectura).
// Todo texto que viene de la base o de internet se inserta con textContent, nunca como HTML.
(() => {
  "use strict";

  const AGENT_NAMES = { claude: "Claude", chatgpt: "Codex" };
  const STATUS_TEXT = {
    AWAITING_REVIEW: "Esperando la revisión del otro agente.",
    NOT_APPROVED: "El revisor no la aprobó: no se ejecuta.",
    AWAITING_USER_AUTHORIZATION: "No se ejecuta sola: falta un requisito o tu «autorizo».",
    READY_TO_EXECUTE: "Lista para ejecutar: Codex la opera en su próxima corrida.",
  };
  const OFFLINE_SECONDS = 90;
  const SHIFT_PX = 8; // desplazamiento máximo contra el marcado de la pantalla por imagen fija

  let state = null, radar = null, lastOk = 0, tickerKey = "", chartKey = "";
  let chart = null, candleSeries = null, priceLines = [];

  // ---------------------------------------------------------------- utilidades
  function h(tag, props, ...children) {
    const el = document.createElement(tag);
    for (const [k, v] of Object.entries(props || {})) {
      if (v === null || v === undefined || v === false) continue;
      if (k === "class") el.className = v;
      else if (k === "text") el.textContent = v;
      else el.setAttribute(k, v);
    }
    for (const c of children.flat()) {
      if (c === null || c === undefined || c === false) continue;
      el.append(c instanceof Node ? c : document.createTextNode(String(c)));
    }
    return el;
  }
  const $ = (id) => document.getElementById(id);
  const fill = (id, ...nodes) => $(id).replaceChildren(...nodes.flat().filter(Boolean));
  const num = (v, d = 2) => (v === null || v === undefined || Number.isNaN(Number(v)))
    ? "—" : Number(v).toLocaleString("es-EC", { minimumFractionDigits: d, maximumFractionDigits: d });
  const signed = (v, d = 2) => (v > 0 ? "+" : "") + num(v, d);
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
  const radarRow = (symbol) => (radar?.rows || []).find((r) => r.symbol === symbol && !r.error);
  const activeProposal = () => (state?.proposals || []).find((p) => !["EXECUTED", "EXPIRED"].includes(p.status));

  async function getJSON(url) {
    const r = await fetch(url, { cache: "no-store" });
    const body = await r.json();
    if (!r.ok) throw new Error(body.error || r.status);
    return body;
  }

  // ---------------------------------------------------------------- cada segundo
  // Fin de la ventana de veto: última revisión APPROVE del otro agente + los minutos de la autorización vigente.
  function vetoEnd(p) {
    const sa = state?.standing_authorization;
    if (!p || !sa || !sa.active || p.last_verdict !== "APPROVE" || !p.last_review_at) return null;
    if (p.auto && p.auto.not_vetoed === false) return null;
    return new Date(p.last_review_at).getTime() + Number(sa.veto_minutes) * 60_000;
  }

  function renderVeto() {
    const box = $("veto");
    const p = activeProposal();
    const end = vetoEnd(p);
    const live = end !== null && Date.now() < end;
    box.classList.toggle("live", live);
    if (!state) return fill("veto", h("h2", { text: "Propuestas" }), h("p", { class: "sub", text: "Conectando…" }));
    if (!p) {
      return fill("veto", h("h2", { text: "Propuestas" }), h("div", { class: "title", text: "Ninguna activa" }),
        h("p", { class: "sub", text: "S-CHANNEL-1D decide tras el cierre diario: 19:00 de Quito (00:00 UTC)." }));
    }
    const levels = h("p", { class: "sub", text: `Zona ${num(p.entry_low, 4)} – ${num(p.entry_high, 4)} · stop ${num(p.invalidation, 4)} · pérdida máx. ${num(p.auto?.estimated_max_loss_usdt, 2)} USDT` });
    if (live) {
      return fill("veto", h("h2", { text: "Ventana de veto abierta" }),
        h("div", { class: "title", text: `${p.side === "BUY" ? "Compra" : "Venta"} ${p.symbol.replace("USDT", "")}` }),
        h("div", { class: "count", text: clock((end - Date.now()) / 1000) }),
        h("div", {}, "Para vetarla escribe a Claude o a Codex:"),
        h("code", { text: `veto ${p.proposal_id}` }), levels);
    }
    const vetoed = p.auto && p.auto.not_vetoed === false;
    return fill("veto", h("h2", { text: "Propuesta" }),
      h("div", { class: "title", text: `${p.side === "BUY" ? "Compra" : "Venta"} ${p.symbol.replace("USDT", "")} ` },
        h("span", { class: "badge", text: vetoed ? "VETADA" : p.status })),
      h("p", { text: vetoed ? "La vetaste: no se ejecuta." : (STATUS_TEXT[p.status] || "") }), levels);
  }

  function tick() {
    const now = new Date();
    $("clock-quito").textContent = quitoFmt.format(now);
    $("clock-utc").textContent = utcFmt.format(now);
    const close = Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate() + 1);
    $("countdown").textContent = clock((close - now) / 1000);
    const hour = Number(quitoHour.format(now)) % 24;
    document.body.classList.toggle("night", hour >= 23 || hour < 7);
    renderVeto();
    const silent = (Date.now() - lastOk) / 1000;
    const banner = $("offline");
    banner.hidden = silent < OFFLINE_SECONDS;
    if (!banner.hidden) {
      banner.textContent = lastOk ? `Sin datos del diario desde hace ${Math.round(silent / 60)} min: revisa el panel o la conexión.`
        : "Conectando con el centro de mando…";
    }
  }

  // ---------------------------------------------------------------- paneles
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
    if (!pos) {
      fill("position", h("span", { class: "k", text: "Posición" }), h("b", { text: "Ninguna" }),
        h("span", { class: "sub", text: "Esperando la próxima ruptura" }));
      return;
    }
    const price = radarRow(pos.symbol)?.price;
    const entry = Number(pos.entry_price), stop = Number(pos.stop ?? pos.invalidation);
    const pnl = price ? (price - entry) * Number(pos.quantity) : null;
    fill("position", h("span", { class: "k", text: `Posición · ${pos.symbol.replace("USDT", "")}` }),
      h("b", { class: pnl === null ? "" : pnl >= 0 ? "up" : "down" }, pnl === null ? "—" : signed(pnl, 2), h("small", { text: "USDT" })),
      h("span", { class: "sub", text: price ? `${signed((price / entry - 1) * 100, 1)} % · a ${num((price / stop - 1) * 100, 1)} % del stop` : "Esperando precio" }));
  }

  function renderHealth() {
    fill("health", state.agents.map((a) => h("div", { class: `agent ${a.state === "ok" ? "" : "bad"}` },
      h("i"), h("b", { text: AGENT_NAMES[a.agent_id] || a.agent_id }),
      h("span", { class: "sub", text: a.state === "ok" ? `Al día · ${ago(a.last_activity)}` : (a.reason || a.state) }))));
  }

  function renderAlerts() {
    const events = state.open_events.filter((e) => e.severity !== "info").slice(0, 3);
    const box = $("alerts");
    box.hidden = events.length === 0;
    box.replaceChildren(h("h2", { text: "Alertas abiertas" }), ...events.map((e) => h("div", { class: `alert ${e.severity === "critical" ? "critical" : ""}` },
      h("b", { text: `${e.kind} · ` }), e.message.length > 160 ? `${e.message.slice(0, 160)}…` : e.message)));
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
    const chars = items.reduce((s, n) => s + (n.title || "").length, 0);
    track.style.animationDuration = `${Math.max(60, Math.round(chars * 0.16))}s`;
  }

  function renderRadar() {
    const forecast = Object.fromEntries((state?.forecast?.latest || []).filter((f) => f.horizon_days === 7)
      .map((f) => [f.symbol, f.median_return]));
    const rows = radar?.rows || [];
    fill("radar",
      h("div", { class: "radar-row sub" }, h("span", { text: "" }), h("span", { text: "Distancia a la compra (máx. 20 días)" }),
        h("span", { text: "Precio" }), h("span", { class: "val", text: "Falta" }), h("span", { class: "val", text: "TimesFM 7 d" })),
      rows.map((r) => {
        if (r.error) return h("div", { class: "radar-row muted" }, h("b", { text: r.symbol.replace("USDT", "") }), h("span", { text: "sin datos" }));
        const gap = r.gap_to_entry;
        const closeness = Math.max(0.03, Math.min(1, 1 - gap / 0.15));
        const track = h("div", { class: `track ${r.in_strategy && gap < 0.02 ? "near" : ""}` }, h("span"));
        track.firstChild.style.width = `${(closeness * 100).toFixed(1)}%`;
        const f = forecast[r.symbol];
        return h("div", { class: `radar-row ${r.in_strategy ? "" : "muted"}` },
          h("b", { text: r.symbol.replace("USDT", "") }), track,
          h("span", { class: "price", text: num(r.price, r.price < 10 ? 4 : 2) }),
          h("span", { class: "val", text: gap <= 0 ? "¡encima!" : `${num(gap * 100, 1)} %` }),
          h("span", { class: `val ${f > 0 ? "up" : f < 0 ? "down" : ""}`, text: f === undefined ? "—" : `${signed(f * 100, 1)} %` }));
      }),
      h("div", { class: "radar-note", text: "La compra se decide con el cierre diario, no con el precio de ahora. ONDO no entra en S-CHANNEL-1D. TimesFM es papel, no señal." }));
  }

  // ---------------------------------------------------------------- gráfico de la posición o la propuesta
  function focusTarget() {
    const pos = state?.open_positions?.[0];
    if (pos) return { symbol: pos.symbol, interval: "1h", title: `Posición abierta · ${pos.symbol} · velas de 1 h`,
      lines: [[pos.entry_price, "#45e0b0", "entrada"], [pos.stop ?? pos.invalidation, "#ffb547", "stop"]] };
    const p = activeProposal();
    if (p) return { symbol: p.symbol, interval: "1d", title: `Propuesta · ${p.symbol} · velas diarias`,
      lines: [[p.entry_high, "#ff4d6d", "zona alta"], [p.entry_low, "#ff4d6d", "zona baja"], [p.invalidation, "#ffb547", "stop"]] };
    return null;
  }

  async function renderFocus(force) {
    const target = focusTarget();
    const box = $("chart");
    box.closest(".focus").classList.toggle("with-chart", !!target);
    box.hidden = !target;
    $("focus-title").textContent = target ? target.title : "Radar S-CHANNEL-1D";
    if (!target) { chartKey = ""; return; }
    const key = `${target.symbol}|${target.interval}|${target.lines.map((l) => l[0]).join(",")}`;
    if (key === chartKey && !force) return;
    if (!chart) {
      const LWC = window.LightweightCharts;
      chart = LWC.createChart(box, {
        layout: { background: { type: "solid", color: "transparent" }, textColor: "#9aa8cf", fontSize: 16 },
        grid: { vertLines: { color: "rgba(130,160,255,0.06)" }, horzLines: { color: "rgba(130,160,255,0.06)" } },
        rightPriceScale: { borderColor: "rgba(130,160,255,0.16)" },
        timeScale: { borderColor: "rgba(130,160,255,0.16)", timeVisible: true },
        handleScroll: false, handleScale: false, autoSize: true,
      });
      candleSeries = chart.addCandlestickSeries({ upColor: "#6fd3ff", downColor: "#dc143c", borderUpColor: "#6fd3ff",
        borderDownColor: "#dc143c", wickUpColor: "#6fd3ff", wickDownColor: "#dc143c" });
    }
    try {
      const data = await getJSON(`/api/candles?symbol=${target.symbol}&interval=${target.interval}`);
      candleSeries.setData(data.candles.slice(-120).map(({ time, open, high, low, close }) => ({ time, open, high, low, close })));
      for (const line of priceLines) candleSeries.removePriceLine(line);
      priceLines = target.lines.filter(([price]) => price).map(([price, color, title]) =>
        candleSeries.createPriceLine({ price: Number(price), color, lineWidth: 2, lineStyle: 2, axisLabelVisible: true, title }));
      chart.timeScale().fitContent();
      chartKey = key;
    } catch (e) {
      $("focus-title").textContent = `${target.title} · sin velas: ${e.message}`;
    }
  }

  // ---------------------------------------------------------------- ciclos
  async function refreshState() {
    try {
      state = await getJSON("/api/state");
      lastOk = Date.now();
      for (const fn of [renderTop, renderHealth, renderAlerts, renderBottom, renderRadar, renderVeto]) {
        try { fn(); } catch (e) { console.error(fn.name, e); }
      }
      renderFocus(false);
    } catch (e) {
      console.error("estado", e);
    }
  }

  async function refreshRadar() {
    try {
      radar = await getJSON("/api/radar");
      if (state) { renderRadar(); renderTop(); }
    } catch (e) {
      console.error("radar", e);
    }
  }

  // Mientras la pestaña está visible, la pantalla no se apaga por inactividad (API Wake Lock; 127.0.0.1 cuenta
  // como contexto seguro). Windows la suelta si la ventana se oculta, así que se pide de nuevo al volver.
  async function keepAwake() {
    try {
      if ("wakeLock" in navigator && document.visibilityState === "visible") await navigator.wakeLock.request("screen");
    } catch (e) { console.warn("wake lock", e); }
  }

  function shiftPixels() {
    const r = () => Math.round((Math.random() * 2 - 1) * SHIFT_PX);
    $("stage").style.transform = `translate(${r()}px, ${r()}px)`;
  }

  tick();
  setInterval(tick, 1000);
  refreshRadar().then(refreshState);
  setInterval(refreshState, 20_000);
  setInterval(refreshRadar, 30_000);
  setInterval(() => renderFocus(true), 60_000);
  setInterval(shiftPixels, 180_000);
  setTimeout(() => location.reload(), 6 * 3_600_000); // una pantalla que nunca se cierra toma el código nuevo sola
  document.addEventListener("visibilitychange", keepAwake);
  keepAwake();
})();
