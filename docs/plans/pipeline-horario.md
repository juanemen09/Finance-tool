# Pipeline horario con Obsidian como sistema nervioso

Pedido del usuario (2026-09-30). Este documento fija qué corre en cada minuto de la hora, qué parte de la propuesta
original se adoptó tal cual, qué se adaptó y por qué, y qué queda pendiente de una decisión suya.

## 1. Plano minuto a minuto (hora UTC; Quito = UTC − 5)

| Minuto | Quién | Qué hace | Dónde queda |
|---|---|---|---|
| 00 | Binance | Cierra la vela de 1 h. | — |
| 01 | Orquestador (`tools/orquestador.py`, Programador de tareas) | Indicadores de 1 h de los 5 pares; guardia de ejecución (spread y deslizamiento desde el libro de órdenes); Fear & Greed y tono de titulares; TimesFM a 1–4 h (servicio residente o proceso efímero); tono FinBERT de los titulares de 24 h; horas parecidas del pasado. | Nota `AI Trading Lab/Horas/AAAA-MM-DD_HHH00` (Local REST API; si Obsidian está cerrado, el archivo) |
| 01 | Orquestador | Completa las 8 horas previas: tesis de Claude y de Codex y, a las 4 h, su resultado (`#tesis-exitosa`, `#tesis-fallida`, `#anomalia`). | Las mismas notas |
| ≤ 04 | Orquestador | Tope de 170 s: termina siempre antes del ciclo de Claude. | `data/raw/horas/log.txt` |
| 05–14 | Claude (tarea programada) | Lee la nota de la hora, analiza a ciegas, propone o revisa y avisa por correo si hay una decisión. No coloca órdenes. | Diario de Supabase (`analyses`, `trade_proposals`, `risk_reviews`) |
| 15 | Codex (automatización de ChatGPT) | Único ejecutor. Buzón, posiciones y lo que esté `READY_TO_EXECUTE`: antes de enviar la orden recalcula la guardia en vivo y aborta si el spread > 0,2 % o el deslizamiento > 0,15 %. | Binance (MCP) y diario |
| cada hora | Sincronizador (`tools/obsidian_sync.py`) | Mapa de conocimiento: agentes, activos, estrategias, reglas, decisiones, proyectos, memoria de Claude y protocolo. | `AI Trading Lab/…` |

El ciclo de Claude corre en el minuto 05 (más un margen al azar), después de que la nota esté escrita.
La TV muestra la nota en la sección «Hora» (`/api/hora`): mercado de 1 h, banda de TimesFM a 4 h, guardia, tono FinBERT,
horas parecidas y el resultado de la última hora evaluada, más el estado del servicio de TimesFM.

## 2. Qué se adoptó, qué se adaptó y por qué

| Propuesta | Estado | Motivo |
|---|---|---|
| Claude analiza y revisa; Codex es el único que ejecuta | **Igual** | Ya era así (AGENTS.md). |
| Obsidian Local REST API para leer y escribir | **Adoptada** | Puerto real 27124 (HTTPS); el 13585 no existe en esta configuración. Certificado propio del plugin fijado la primera vez; respaldo a archivo si Obsidian está cerrado. |
| Frontmatter YAML tipado para Dataview | **Adoptada** | Un campo plano por activo y métrica (`btc_p10_4h`, `eth_spread_pct`…). Metadata Menu no está instalado; Dataview no lo necesita. Tablero listo en `Tablero horario`. |
| Enlaces `[[ ]]` a la hora anterior y a patrones parecidos | **Adoptada** | La memoria de «horas parecidas» compara retorno y RSI de BTC, volatilidad, Fear & Greed y tono (distancia euclídea normalizada). No enlaza horas de las últimas 24 h: serían parecidas solo por vecinas. |
| Etiquetas `#tesis-exitosa`, `#tesis-fallida`, `#anomalia` | **Adoptada, con regla medible** | Exitosa o fallida solo si Claude propuso comprar o vender y el precio a 4 h fue o no en esa dirección; anomalía si algún cierre real quedó fuera de la banda p10–p90 de TimesFM. |
| TimesFM a 1–4 h como «suelo y techo» de la tesis | **Adaptada: contexto en papel** | Aún no pasó su prueba hacia delante (se decide a los 60 cierres, ≈ 6 dic). Usarlo como límite de decisión sería operar con una señal no validada. Queda en cada nota y se puntúa sola. |
| Templater dispara scripts de Windows | **Reemplazada** por el Programador de tareas | Templater solo corre con Obsidian abierto y ejecutar comandos del sistema desde una nota abre una puerta de seguridad. La plantilla `protocolo_operaciones` queda para abrir horas a mano con el mismo esquema. |
| Contenedores efímeros «run-and-die» | **Adoptada** | `docker run --rm --memory N --network none`; el orquestador nunca descarga imágenes. TimesFM corre como proceso efímero con su propio Python: al cerrarse libera toda su RAM sin Docker. |
| `gc.collect()` y `torch.cuda.empty_cache()` | **Adaptada** | El orquestador no carga modelos en su propio proceso: la memoria vuelve al sistema cuando el proceso hijo termina, que es más fuerte que vaciar cachés. Se llama a `gc.collect()` tras cada etapa. |
| FinBERT para el tono de titulares | **Adoptada (2026-09-30), sin Docker** | Aprobada por el usuario. Proceso efímero con su propio Python (`%LOCALAPPDATA%i-trading-labinbert`, torch de CPU + transformers; aparte del de TimesFM porque transformers exige otra versión de `huggingface_hub`). Modelo ProsusAI/finbert en una revisión fijada, convertido a safetensors. Un contenedor haría crecer la máquina virtual de Docker, que no devuelve la RAM a Windows. Corre si hay ≥ 1,2 GB libres; VADER sigue en el diario. Contexto, no señal. |
| Llama-3.2-Vision / Moondream2 sobre capturas de Binance | **Pospuesta** | Llama-3.2-Vision 11B necesita ≥ 8 GB y hay ≈ 2–3 GB libres. Además, los indicadores ya se calculan exactos desde las velas: un modelo de visión leyendo una captura solo añade errores y la captura de pantalla mostraría el gráfico en el monitor. Si se quiere, Moondream2 (≈ 4 GB) sobre un gráfico renderizado sin ventana. |
| MemGPT (Letta) + ChromaDB | **Reemplazada por una memoria ligera** | La memoria de horas parecidas y el grafo de Obsidian cubren la consulta de patrones sin un servidor ni una base vectorial residente. Se puede sumar ChromaDB después si la memoria ligera se queda corta. |
| Obsidian Git con push automático | **Aprobada; configuración en curso** (2026-09-30) | Repositorio separado y privado para la bóveda. Es una copia navegable de Supabase y del repositorio de implementación; excluye credenciales, certificados y estado local de plugins. |
| Correo de aprobación antes de cada operación | **Descartada por el usuario** (2026-09-30) | Sigue el evento 34: su silencio tras 1 minuto de veto es aprobación. |
| Máximo 2,5 % del saldo por transacción | **Descartada por el usuario** (2026-09-30) | «Sigue trabajando con los parámetros que ya establecimos»: rigen los de `standing_authorizations` fila 4 (7 USDT por posición, pérdida 1,20, R:R 1,2, semanal 2,5 USDT). |
| Abortar si spread > 0,2 % o deslizamiento > 0,15 % | **Adoptada** | En la guardia de cada nota y como regla de Codex antes de enviar la orden (`python -m tools.orquestador guardia <PAR>`). |

## 3. Esquema de la nota horaria

Nombre `AAAA-MM-DD_HHH00` (hora UTC de cierre de la vela). Frontmatter:

| Campo | Tipo | Ejemplo |
|---|---|---|
| `tipo` | texto | `"hora"` |
| `hora_utc`, `ciclo` | texto ISO | `"2026-09-30T17:00:00+00:00"`, `"2026-09-30T17Z"` |
| `fear_greed`, `sentimiento_mercado` | número | `71.0`, `-0.02` |
| `tesis_claude`, `tesis_codex` | texto o null | `"DO_NOTHING"` |
| `resultado` | texto | `pendiente`, `exitosa`, `fallida`, `sin-tesis-direccional` |
| `guardia_abortar` | booleano | `false` |
| `<par>_precio`, `<par>_rsi14`, `<par>_p10_4h`, `<par>_p50_4h`, `<par>_p90_4h`, `<par>_spread_pct` | número o null | `btc_p10_4h: 83900.5` |
| `tags` | lista | `["hora", "anomalia"]` |

El cuerpo es un bloque generado (entre marcadores): lo que escribas fuera de él se conserva. El frontmatter se
regenera en cada corrida.

## 4. Memoria

- Supabase conserva el diario compartido append-only y sigue siendo la fuente canónica de análisis, propuestas, revisiones y operaciones.
- La bitácora diaria de Codex se reconstruye desde `analyses` y se enlaza desde `Mente de Codex`; cada entrada conserva ciclo e identificador de procedencia.
- Obsidian es la corteza asociativa: conecta contexto, protocolo y memorias, pero nunca autoriza una orden ni sustituye una comprobación directa en Binance o Supabase.
- Para mantener el análisis a ciegas, Codex escribe primero su análisis del ciclo y no lee la tesis de Claude del mismo ciclo hasta haberlo hecho. Puede consultar ciclos ya cerrados.
- Se mide antes de cada etapa pesada. TimesFM necesita ≥ 4,5 GB libres; si no los hay, la nota lo dice y la hora sigue.
- Docker Desktop reserva RAM para su máquina virtual (WSL) aunque no haya contenedores: al abrirlo, la memoria libre
  bajó de 2,8 a 2,1 GB. Conviene fijarle un techo en `%UserProfile%\.wslconfig` (`[wsl2]` → `memory=4GB`) o cerrarlo
  cuando no se usen contenedores. Es un ajuste del sistema: lo decide el usuario.
- El servidor MCP de TimesFM de Claude Desktop mantiene el modelo cargado mientras Claude Desktop está abierto.

## 5. Decisiones pendientes del usuario

Resueltas el 2026-09-30: el 2,5 % y el correo previo quedan descartados, FinBERT va, el ciclo de Claude ya está en el minuto 05 y la bóveda tendrá repositorio privado.

1. ¿Moondream2 (≈ 4 GB) sobre un gráfico renderizado? No cabe en esta PC con 12 GB (ver §4); iría en un servidor en la nube.
2. Poner la clave de la Local REST API en `.env` como `OBSIDIAN_API_KEY` (la copia el usuario desde los ajustes del
   plugin; nunca pasa por el chat). Sin ella, el orquestador escribe los archivos directamente.
