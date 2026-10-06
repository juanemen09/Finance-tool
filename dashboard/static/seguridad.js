// Pestaña Seguridad: muestra Argos-Atlas (otro servidor de este PC) dentro del centro de mando.
(function () {
  "use strict";
  const marco = document.getElementById("argos");
  const caido = document.getElementById("argos-caido");
  const estado = document.getElementById("argos-estado");
  const comando = document.getElementById("argos-comando");

  const FUENTES = { esp32: "RuView · ESP32", wifi: "RuView · Wi-Fi", simulated: "RuView · demo" };

  function textoPresencia(p) {
    if (!p) return "";
    if (p.modo === "simulador") return "presencia: emulador (simulado)";
    if (p.modo === "externo") return "presencia: lecturas externas";
    const s = p.sensor;
    if (!s || !s.conectado) return "presencia: RuView sin conexión";
    return `presencia: ${FUENTES[s.fuente] || s.fuente || "RuView"}${s.presencia ? " · detectada" : ""}`;
  }

  async function comprobar() {
    let r = null;
    try {
      r = await (await fetch("/api/argos", { cache: "no-store" })).json();
    } catch (e) {
      r = null;
    }
    const ok = Boolean(r && r.ok);
    // ?v= evita que el navegador muestre una versión guardada de Argos tras actualizarlo.
    if (ok && !marco.src) marco.src = `${r.url}/?v=${Date.now()}`;
    marco.hidden = !ok;
    caido.hidden = ok;
    if (r && r.arranque) comando.textContent = r.arranque;
    estado.textContent = ok ? `En línea · ${textoPresencia(r.presencia)}` : "Fuera de línea";
    estado.className = `argos-estado ${ok ? "ok" : "caido"}`;
    setTimeout(comprobar, ok ? 15000 : 5000);
  }
  comprobar();
})();
