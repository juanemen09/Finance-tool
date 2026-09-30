---
tipo: "hora"
hora_utc: "<% tp.date.now('YYYY-MM-DD[T]HH:00:00[+00:00]', 0, tp.file.title, 'YYYY-MM-DD_HH[H00]') %>"
ciclo: "<% tp.date.now('YYYY-MM-DD[T]HH[Z]', 0, tp.file.title, 'YYYY-MM-DD_HH[H00]') %>"
fuente: "manual"
fear_greed: null
sentimiento_mercado: null
tesis_claude: null
tesis_codex: null
resultado: "pendiente"
guardia_abortar: false
btc_precio: null
btc_rsi14: null
btc_p10_4h: null
btc_p50_4h: null
btc_p90_4h: null
btc_spread_pct: null
eth_precio: null
eth_rsi14: null
eth_p10_4h: null
eth_p50_4h: null
eth_p90_4h: null
eth_spread_pct: null
sol_precio: null
sol_rsi14: null
sol_p10_4h: null
sol_p50_4h: null
sol_p90_4h: null
sol_spread_pct: null
link_precio: null
link_rsi14: null
link_p10_4h: null
link_p50_4h: null
link_p90_4h: null
link_spread_pct: null
ondo_precio: null
ondo_rsi14: null
ondo_p10_4h: null
ondo_p50_4h: null
ondo_p90_4h: null
ondo_spread_pct: null
tags: ["hora"]
---
<%*
/* Plantilla de protocolo_operaciones (Templater). Nombra la nota AAAA-MM-DD_HHH00 en hora UTC, p. ej. 2026-09-30_17H00.
   Las notas de cada hora las crea solo el orquestador (tools/orquestador.py, minuto 01) con este mismo esquema;
   esta plantilla sirve para abrir una hora a mano con los mismos campos que lee Dataview.
   No ejecuta scripts de Windows: la automatización vive en el Programador de tareas, que funciona aunque
   Obsidian esté cerrado. */
const t = tp.file.title;
const prev = window.moment.utc(t, "YYYY-MM-DD_HH[H00]").subtract(1, "hour").format("YYYY-MM-DD_HH[H00]");
-%>
# Hora <% tp.file.title %> (UTC)
[[AI Trading Lab]] · anterior: [[<% prev %>]]
Patrones parecidos: (los agrega el orquestador; a mano, enlaza aquí [[AAAA-MM-DD_HHH00]] de una hora similar)

## Mercado (velas de 1 h)
| Activo | Precio | 1 h | 24 h | RSI 14 | Sobre EMA50 | ATR % | Vol. rel. |
|---|---|---|---|---|---|---|---|
| [[BTC]] | | | | | | | |
| [[ETH]] | | | | | | | |
| [[SOL]] | | | | | | | |
| [[LINK]] | | | | | | | |
| [[ONDO]] | | | | | | | |

## Oráculo [[TimesFM]] a 4 h (papel, no señal)
| Activo | p10 | p50 | p90 |
|---|---|---|---|

## Guardia de ejecución (Codex la recalcula en vivo antes de operar)
Aborta si el spread > 0,2 % o el deslizamiento estimado > 0,15 %.

## [[Sentimiento]]

## Tesis de los agentes
- [[Claude]]:
- [[Codex]]:

## Resultado
pendiente · al cerrar: #tesis-exitosa, #tesis-fallida o #anomalia

```json
{
  "datos_modelos": {
    "timesfm": {},
    "guardia": {},
    "sentimiento": {"fear_greed": null, "tono_mercado": null, "modelo": "VADER"},
    "contenedores": {}
  },
  "evaluacion_4h": {}
}
```
