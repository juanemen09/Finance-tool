// Lecturas de presencia (emulador o RuView real) hacia el navegador.

// Valida y recompacta: al navegador solo llega el esquema acordado.
export function normalizarLectura(texto) {
  let m;
  try {
    m = JSON.parse(texto);
  } catch {
    return null;
  }
  const [lat, lng] = Array.isArray(m?.coords) ? m.coords : [];
  if (typeof m?.id !== 'string' || m.id.length > 32 || !Number.isFinite(lat) || !Number.isFinite(lng)) return null;
  return JSON.stringify({
    id: m.id,
    room: String(m.room ?? '').slice(0, 40),
    coords: [lat, lng],
    state: m.state === 'movimiento' ? 'movimiento' : 'quieto',
    resp: Number.isFinite(m.resp) ? Math.round(m.resp) : null,
    ...(m.aprox === true ? { aprox: true } : {}),
    ...(Number.isFinite(m.conf) ? { conf: Math.min(Math.max(m.conf, 0), 1) } : {}),
  });
}
