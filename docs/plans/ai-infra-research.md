# Tesis de infraestructura de IA: libro 13F, demanda y oferta

Pedido del usuario (2026-09-24): tres prompts vistos en un video, pensados para un chat. Aquí se convierten en
herramientas repetibles cuyo resultado queda en el diario. Tamaño: **grande** (fuentes externas nuevas, tablas,
panel y rutina mensual). El usuario aprobó el plan y los commits por adelantado ("apruebo todo lo que necesites
hacer"), así que las dos puertas del orquestador quedan cubiertas por esa autorización escrita.

## Qué pide cada prompt y cómo se resuelve

| Prompt | Pide | Fuente gratuita verificada (2026-09-25) | Qué queda fuera |
|---|---|---|---|
| 1. Clonar el libro | Último 13F-HR de Situational Awareness LP (CIK 0002045724): ticker, acciones, valor, tipo; sin opciones; pesos; órdenes contra un saldo; **no ejecutar** | SEC EDGAR (`data.sec.gov` y el archivo `www.sec.gov/Archives`, que exige un contacto en el User-Agent) y OpenFIGI (CUSIP → ticker, sin clave) | Ninguna orden, nunca. El 13F llega hasta 45 días tarde y solo muestra largos en EE. UU. |
| 2. Demanda en cosas reales | Capex de MSFT, AMZN, GOOGL, META, ORCL y NVDA; si subió; frases textuales que expliquen el cambio; pasarlo a MW, GB de memoria, pies², turbinas; guardarlo con fecha | XBRL de la SEC (`companyconcept`) para el capex trimestral; el 10-Q/10-K para las frases | "Gasto en centros de datos" no se reporta aparte: se usa la compra de activo fijo (capex) y se dice. Las conversiones físicas son **supuestos con rango y fuente**, no datos |
| 3. ¿Se puede fabricar? | Exportaciones mensuales de chips de memoria de Corea, pedidos de exportación de Taiwán, cola de conexión a la red, cartera de pedidos de turbinas de gas; el insumo que es cuello de botella; quién lo controla; qué lo resolvería; comparar con el mes anterior | Comtrade de la ONU (Corea, SA 854232 = memorias, mensual, sin clave); boletín mensual del Ministerio de Economía de Taiwán (ODS con pedidos de información y comunicaciones y de electrónica); obligaciones de desempeño pendientes (cartera) de GE Vernova por XBRL y frases de su 10-Q; capex de Micron | La cola de conexión a la red no tiene fuente mensual gratuita legible por máquina (ERCOT y LBNL publican PDF o informes anuales): se cita a mano con enlace o se declara ausente |

## Diseño

- `ai_trading_lab/research.py`: solo transforma datos ya descargados (probado sin red).
  - 13F: `parse_13f_filings`, `parse_13f_table`, `long_book`, `book_changes`, `size_orders`.
  - Capex: `quarterly_from_ytd`, que saca trimestres de los acumulados del flujo de caja.
  - Otras piezas: `capex_summary`, `extract_quotes`, `to_physical`, `parse_comtrade`, `parse_taiwan_orders_ods`.
- `tools/ai_research.py`: descarga, con subcomandos `book`, `demand`, `supply` y `all`.
  - `--insert` escribe con el rol `lab_ingest` y lee el informe anterior con `dashboard_reader` para comparar.
  - `--out` guarda el JSON.
- `config/ai_infra_assumptions.json`: cada supuesto con valor bajo, medio y alto, unidad y fuente.
- Migración `research_facts`: hechos con clave única, en la que un duplicado se ignora.
- Migración `research_reports`: informes cuya clave es el hash de sus datos, así que sin datos nuevos no hay fila nueva.
- Ambas tablas son append-only, igual que el resto del diario. `lab_ingest` solo puede insertar filas de Claude en ellas.
- El panel tiene una tarjeta "Tesis IA" con el libro 13F y sus cambios, la demanda, la oferta y el último veredicto sobre el cuello de botella.
- Rutina mensual (día 25, tras el boletín de Taiwán):
  - Ejecuta `python -m tools.ai_research all --insert`.
  - Claude escribe el informe `AI_BOTTLENECK` con el insumo, quién lo controla, qué lo resolvería y la comparación con el mes anterior.

## Reglas

- **Solo investigación.** Nada de esto se opera: el laboratorio es Spot de Binance con 5 pares. Un hallazgo se
  informa al usuario y la decisión es suya (misma regla que tokenización).
- El 13F es público y atrasado; copiarlo no es una estrategia validada y no pasa por el hard testing.
- Las frases citadas son textuales y con enlace al documento; los números físicos muestran su cálculo.
