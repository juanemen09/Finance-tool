# Fuentes de datos de pago: qué compraríamos y en qué orden

Pedido del usuario (2026-10-12): potenciar el rastreo del laboratorio y del radar de memecoins, evaluando también
opciones de pago. Precios consultados el 2026-10-12 en fuentes públicas: varios proveedores cambiaron sus planes en
2026 y algunas cifras no coinciden entre fuentes, así que se confirman en la página oficial antes de pagar.

**Regla de proporción:** el capital en juego hoy es de ~90 USDT en Binance más lo que el usuario ponga en memecoins.
Un gasto fijo en datos de cientos de dólares al mes no se recupera con ese capital. Se compra primero lo que cubre un
hueco real, por uso, y se mide si cambia los resultados antes de subir de plan.

## Huecos reales hoy

| Hueco | Por qué importa | Hoy |
|---|---|---|
| X (Twitter) | Es donde nace la mayoría del bombo de memecoins y donde salen primero las noticias del mercado | Sin acceso (la API gratuita no existe) |
| Historial de billeteras en Solana | Seguir billeteras que entran temprano en los que luego suben (fase 2 del radar) | El RPC público corta con 429 |
| Liquidaciones e interés abierto | Contexto de derivados para BTC, ETH y SOL (barridos de liquidez, sobreapalancamiento) | Solo funding y largo/corto gratuitos |

## Recomendación por niveles

| Nivel | Fuente | Precio | Para qué | Veredicto |
|---|---|---|---|---|
| 0 | [Helius](https://www.helius.dev/docs/billing/plans) Free | 0 USD (1 M créditos/mes, 10 RPC/s) | Fase 2: historial de billeteras, datos de transacciones decodificados | **Ya**: el usuario crea la cuenta y pega `HELIUS_API_KEY` en `.env` |
| 1 | [X API](https://postproxy.dev/blog/x-api-pricing-2026/) pago por uso | ~0,005 USD por post leído; búsqueda solo de 7 días | Menciones de los tokens del radar y de los 15 pares | **Sí**, con tope: solo búsquedas de tokens ya marcados por el radar. ~2 000 lecturas/mes ≈ 10 USD |
| 1 | [CoinGlass](https://www.coinglass.com/pricing) Hobbyist | ~29–35 USD/mes, uso personal | Liquidaciones, interés abierto, flujo de taker | **Sí, después** de medir si el contexto de derivados ayuda (antes, pre-registrar la hipótesis) |
| 2 | [Nansen API](https://www.kucoin.com/news/flash/nansen-launches-pay-per-use-model-on-base-and-solana-with-usdc-settlement) pago por uso | 0,01 USD/llamada básica, 0,05 USD/señal de smart money | "Smart money" etiquetado en Solana | **Solo sobre alertas**: una consulta por alerta (~0,15 USD) cabe en unos pocos dólares al mes |
| 2 | Helius Developer | 49 USD/mes (10 M créditos) | Si el plan gratuito se queda corto con el seguimiento de billeteras | Solo si el plan Free se agota |
| No | [Birdeye](https://bds.birdeye.so/pricing) | 99–199 USD/mes | Precios y trades de Solana | Se solapa con DexScreener + Helius |
| No | [LunarCrush](https://lunarcrush.com/pricing) | 90–900 USD/mes | Social agregado | Se solapa con X + Reddit; caro para el capital actual |
| No | Nansen Pro, X Enterprise, Helius Business | 49 USD a miles al mes | — | Desproporcionado hoy |

Proveedores no oficiales que copian datos de X son más baratos, pero incumplen los términos de X: no se usan.

## Orden de trabajo

1. El usuario crea la cuenta gratuita de Helius y pega la clave en `.env` (`HELIUS_API_KEY`). Nunca por el chat.
2. Fase 2 del radar con Helius: billeteras que entran temprano y su historial.
3. X por uso, con un tope de gasto mensual en el panel de X, solo para los tokens que el radar ya marcó.
4. Con 4 semanas de alertas medidas (`v_meme_alert_skill`), decidir si X o Nansen mejoran el acierto antes de
   pagar más.
5. CoinGlass para el laboratorio principal, con un pre-registro de qué dato de derivados se probaría como filtro.
