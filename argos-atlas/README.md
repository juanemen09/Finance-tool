# Argos-Atlas

Mapa táctico local para la seguridad de casa y oficina. Muestra **vuelos, barcos y cámaras públicas en tiempo real**,
con datos reales de APIs abiertas, y un **plano 2D del hogar** con las presencias que detectaría un sensor RuView.
Ahora mismo esas presencias salen de un emulador, y la interfaz lo marca como `SIMULADO`.

Es una herramienta aparte del AI Trading Lab: no lee ni escribe el diario y no es una señal de trading.

## Arranque (Windows, macOS o Linux)

Necesitas Node.js 20 o superior.

```bash
cd argos-atlas
npm install
npm run dev
```

Abre `http://127.0.0.1:5173`. `npm run dev` levanta el proxy (`http://127.0.0.1:8787`), que arranca el emulador
de RuView en segundo plano, y el servidor de Vite. Ctrl+C cierra los tres.

- `npm start` compila la app y la sirve desde el proxy en `http://127.0.0.1:8787`, sin Vite.
- `npm test` corre las pruebas.

Todo escucha solo en `127.0.0.1`: nadie de tu red puede abrirlo.

## Configuración opcional (`.env`)

Copia `.env.example` como `.env` (git lo ignora).

| Variable | Para qué |
|---|---|
| `OPENSKY_CLIENT_ID`, `OPENSKY_CLIENT_SECRET` | Cuenta gratuita de OpenSky. En modo anónimo el cupo diario se agota en poco más de una hora de uso continuo; con cuenta es unas 10 veces mayor. |
| `AISSTREAM_API_KEY` | Barcos de todo el mundo vía aisstream.io (clave gratuita). Sin ella solo se ven los del Báltico (Digitraffic). |
| `PLANO_LAT`, `PLANO_LNG` | Esquina suroeste del plano doméstico. Tu dirección queda solo en `.env`, nunca en el repo. |
| `RUVIEW_SIMULADOR` | `1` (por defecto) arranca el emulador; `0` lo apaga, a la espera de un RuView real. |
| `ARGOS_INGEST_TOKEN` | Token fijo para que un adaptador de RuView real publique lecturas (ver más abajo). |

## Fuentes de datos

| Capa | Fuente | Clave | Notas |
|---|---|---|---|
| Vuelos | [OpenSky Network](https://opensky-network.org) `/states/all` | Opcional | Solo se pide la zona visible (bounding box). Se renueva cada 15 s. La matrícula y el modelo se piden al abrir el popup. |
| Barcos | [Digitraffic](https://www.digitraffic.fi/en/marine-traffic/) (Fintraffic, CC BY 4.0) | No | AIS real del Báltico. Se renueva cada 20 s y oculta las posiciones de más de 1 h. |
| Barcos | [aisstream.io](https://aisstream.io) | Sí, gratuita | AIS mundial por WebSocket. El servidor solo se suscribe a la zona que estás mirando. |
| Cámaras | [TfL JamCams](https://api.tfl.gov.uk) (Londres) | No | Imagen y clip de vídeo corto. |
| Cámaras | [NYC DOT](https://webcams.nyctmc.org) (Nueva York) | No | Imagen en vivo. |
| Cámaras | [Fintraffic](https://www.digitraffic.fi/en/road-traffic/) (Finlandia) | No | Cámaras de carretera. |

Las cámaras se leen de los catálogos oficiales (cientos por fuente) en vez de una lista fija, para que no queden
enlaces muertos. El catálogo se renueva cada 6 h. Madrid todavía no está: se puede sumar como cuarta fuente en
`server/camaras.js`.

## Rendimiento

- **Bounding box:** cada capa pide solo lo que cabe en la pantalla, y lo vuelve a pedir 400 ms después de que dejes de
  mover el mapa. El proxy redondea la caja a una rejilla de 0,5° y guarda la respuesta 10 s, así dos vistas parecidas
  comparten una sola llamada a OpenSky.
- **Canvas:** `preferCanvas: true` y un único `<canvas>` para aviones, barcos, cámaras, paredes y fantasmas. Los
  aviones y barcos se dibujan orientados según su rumbo directamente en el canvas: no se crea ningún elemento DOM por
  objetivo.
- **Memoria:** cada oleada hace `clearLayers()` antes de pintar. En la prueba de estrés (46 oleadas de 5 000 aviones)
  la memoria de JavaScript se quedó en 12 MB.
- **Presencias:** un fantasma y un pulso por objetivo, creados una sola vez y movidos con `setLatLng()`. El pulso del
  radar es CSS puro (`transform` y `opacity`, acelerado por la GPU), sin `setInterval`.
- **Cámaras:** ninguna imagen ni vídeo se descarga hasta que abres una cámara. Al cerrarla se borran el `<img>` o el
  `<video>` y su temporizador.
- **Pestaña oculta:** se detienen los sondeos y la red queda en reposo.

## Plano doméstico y RuView

`shared/plano.js` define las habitaciones (Sala, Pasillo, Cocina y Habitación Principal), las puertas y el sensor, en
metros. Para que coincida con tu casa, edita esos rectángulos y pon tu origen en `.env`.

`simulador_ruview.js` emula la telemetría de presencia por Wi-Fi (CSI). Cada 2 s envía por WebSocket un JSON por
objetivo:

```json
{ "id": "target_01", "room": "Sala", "coords": [-0.18061, -78.48522], "state": "movimiento", "resp": 15 }
```

La trayectoria es una caminata aleatoria que solo cambia de habitación cruzando las puertas. Las pruebas comprueban que
nunca sale del plano.

**Pasar a un RuView real.** [RuView](https://github.com/ruvnet/RuView) (MIT) necesita nodos ESP32-S3 (unos 9 USD cada
uno). Expone REST, WebSocket y MQTT. Para conectarlo:

1. Pon `RUVIEW_SIMULADOR=0` y un `ARGOS_INGEST_TOKEN` en `.env`.
2. Escribe un adaptador que traduzca su salida al JSON de arriba y lo publique en
   `ws://127.0.0.1:8787/ingest/ruview?token=TU_TOKEN`.

El proxy valida cada lectura antes de reenviarla al mapa. Ten en cuenta que el propio RuView publica una precisión de
presencia del 82 % y marca sus signos vitales como no validados: úsalo como aviso, no como alarma definitiva.

## Uso responsable

Solo se usan datos públicos: ADS-B, AIS y cámaras de tráfico que los operadores publican para el público. No se
evade ninguna protección y no se guarda nada en disco. El plano doméstico es para tu propia casa u oficina. Un sensor
real que detecte personas a través de paredes debe instalarse solo donde quienes viven o trabajan allí lo sepan.
