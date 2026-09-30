---
tags: ["centro"]
fuente: "ai-trading-lab"
---
# Tablero horario
Lo alimentan las notas de [[AI Trading Lab]] en la carpeta Horas (una por hora, minuto 01). Necesita el plugin Dataview.

## Últimas 24 horas
```dataview
TABLE WITHOUT ID file.link AS "Hora (UTC)", tesis_claude AS "Claude", tesis_codex AS "Codex", fear_greed AS "F&G",
  round(btc_precio, 0) AS "BTC", round(btc_p10_4h, 0) AS "BTC p10 4h", round(btc_p90_4h, 0) AS "BTC p90 4h",
  choice(guardia_abortar, "⚠", "") AS "Guardia", resultado AS "Resultado"
FROM "AI Trading Lab/Horas"
WHERE tipo = "hora"
SORT hora_utc DESC
LIMIT 24
```

## Resultados acumulados
```dataview
TABLE WITHOUT ID resultado AS "Resultado", length(rows) AS "Horas"
FROM "AI Trading Lab/Horas"
WHERE tipo = "hora"
GROUP BY resultado
```

## Anomalías (el precio real salió de la banda p10–p90 de TimesFM a 4 h)
```dataview
LIST
FROM "AI Trading Lab/Horas" AND #anomalia
SORT hora_utc DESC
LIMIT 20
```

## Tesis direccionales
```dataview
TABLE WITHOUT ID file.link AS "Hora", tesis_claude AS "Claude", resultado AS "Resultado"
FROM "AI Trading Lab/Horas"
WHERE tesis_claude = "BUY_CANDIDATE" OR tesis_claude = "SELL_CANDIDATE"
SORT hora_utc DESC
```
