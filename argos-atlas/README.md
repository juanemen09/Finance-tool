# Argos-Atlas

Mapa táctico local para la seguridad de casa y oficina. Muestra **vuelos, barcos y cámaras públicas en tiempo real**,
con datos reales de APIs abiertas, y un **plano 2D del hogar** con las presencias que detecta
[RuView](https://github.com/ruvnet/RuView) (Wi-Fi como sensor, sin cámaras).

Es una herramienta aparte del AI Trading Lab: no lee ni escribe el diario y no es una señal de trading.

## Arranque con Docker (recomendado)

Con Docker Desktop abierto, en una terminal dentro de `argos-atlas/`:

```powershell
copy .env.example .env        # una vez; luego edita .env (todo es opcional)
docker compose up -d --build
```

Abre `http://127.0.0.1:8787`. Vuelos, barcos y cámaras salen de las APIs reales desde el primer momento. El
puerto solo se publica en `127.0.0.1`: nadie de tu red puede abrirlo.

- Ver lo que pasa: `docker compose logs -f argos`
- Parar: `docker compose down`
- Actualizar tras un `git pull`: `docker compose up -d --build`

### Con RuView real (nodos ESP32)

1. Flashea y configura tus ESP32-S3 con el firmware de RuView (su README, «Option 2a»), apuntando `--target-ip` a la IP
   de este PC.
2. En `.env`:
   ```
   RUVIEW_URL=ws://ruview:3001/ws/sensing
   RUVIEW_API_TOKEN=<un secreto largo>
   CSI_SOURCE=esp32
   ```
3. `docker compose --profile ruview up -d --build`

Eso levanta además el servidor oficial de RuView (`ruvnet/wifi-densepose`): recibe las tramas CSI por UDP 5005 y su
propia interfaz queda en `http://127.0.0.1:3000`. Argos-Atlas se conecta a su WebSocket con el token, apaga el
emulador y la insignia pasa a **RUVIEW · ESP32** con el número de nodos.

En Docker Desktop para Windows, varios ESP32 llegan como uno solo por UDP. RuView documenta el arreglo: cambiar el
puerto a `5006:5005/udp` y correr su `scripts/udp-relay.py`. Con un solo nodo no hace falta.

### Sin hardware: Wi-Fi del PC (solo Windows, solo RSSI)

RuView puede usar la tarjeta Wi-Fi del PC con `netsh` (presencia y movimiento, sin posición). Eso no funciona dentro
de Docker: hay que compilar su `sensing-server` en Windows (Rust) y correrlo como administrador:

```powershell
git clone --recursive https://github.com/ruvnet/RuView; cd RuView\v2
cargo build --release -p wifi-densepose-sensing-server
.\target\release\sensing-server.exe --source wifi --http-port 3000 --ws-port 3001 --tick-ms 500
```

Después corre Argos-Atlas con Node (no en Docker) y `RUVIEW_URL=ws://127.0.0.1:3001/ws/sensing` en `.env`. La presencia
aparece en la zona del sensor, porque RSSI no da posición.

### Qué dice la insignia del plano

| Insignia | Significado |
|---|---|
| `RUVIEW · ESP32` | Lecturas reales de tus nodos. |
| `RUVIEW · WI-FI` | Lecturas reales del Wi-Fi del PC (solo presencia y movimiento). |
| `RUVIEW · DEMO` | RuView corre con `CSI_SOURCE=simulated`: no son personas reales. |
| `RUVIEW · SIN CONEXIÓN` | Argos no llega a RuView. La línea de debajo dice por qué (token, host o servidor apagado). |
| `SIMULADO` | No hay `RUVIEW_URL`: es el emulador de Argos-Atlas. |

La posición viene del pico del campo de señal que calcula RuView. El propio RuView avisa de que es aproximada y no una
triangulación, y el mapa la marca así. Para alinearla con tu plano usa `RUVIEW_ORIGEN_X`, `RUVIEW_ORIGEN_Y`,
`RUVIEW_GIRO` y `RUVIEW_ESCALA`.

## Arranque sin Docker

Necesitas Node.js 20 o superior: `npm install` y luego `npm run dev`, y abre `http://127.0.0.1:5173`. `npm start`
compila y sirve todo en `:8787`. `npm test` corre las pruebas.

## Configuración opcional (`.env`)

Copia `.env.example` como `.env` (git lo ignora).

| Variable | Para qué |
|---|---|
| `OPENSKY_CLIENT_ID`, `OPENSKY_CLIENT_SECRET` | Cuenta gratuita de OpenSky. En modo anónimo el cupo diario se agota en poco más de una hora de uso continuo; con cuenta es unas 10 veces mayor. |
| `AISSTREAM_API_KEY` | Barcos de todo el mundo vía aisstream.io (clave gratuita). Sin ella solo se ven los del Báltico (Digitraffic). |
| `PLANO_LAT`, `PLANO_LNG` | Esquina suroeste del plano doméstico. Tu dirección queda solo en `.env`, nunca en el repo. |
| `RUVIEW_URL`, `RUVIEW_API_TOKEN` | WebSocket y token del sensing-server de RuView. Con ellos, presencia real. |
| `CSI_SOURCE` | Para el contenedor de RuView: `esp32` (real) o `simulated` (su demo). |
| `RUVIEW_ORIGEN_X/Y`, `RUVIEW_GIRO`, `RUVIEW_ESCALA` | Calibración de la sala de RuView sobre el plano. |
| `RUVIEW_SIMULADOR` | Solo sin `RUVIEW_URL`: `1` arranca el emulador; `0` espera lecturas en `/ingest/ruview`. |

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

## Plano doméstico

`shared/plano.js` define las habitaciones (Sala, Pasillo, Cocina y Habitación Principal), las puertas y el sensor, en
metros. Para que coincida con tu casa, edita esos rectángulos y pon tu origen en `.env`.

Cada presencia llega al navegador con este formato. Viene de RuView (`server/ruview.js`) o del emulador
(`simulador_ruview.js`):

```json
{ "id": "persona_1", "room": "Sala", "coords": [-0.18061, -78.48522], "state": "movimiento", "resp": 15, "aprox": true, "conf": 0.82 }
```

El adaptador lee los `sensing_update` de RuView (10 por segundo) y procesa uno por segundo. Si alguien se va o se corta
la conexión, quita su marcador. La respiración solo se muestra cuando RuView da una confianza de al menos 0,3. RuView
publica una precisión de presencia del 82 % y marca sus signos vitales como no validados: úsalo como aviso, no como
alarma definitiva.

## Uso responsable

Solo se usan datos públicos: ADS-B, AIS y cámaras de tráfico que los operadores publican para el público. No se
evade ninguna protección y no se guarda nada en disco. El plano doméstico es para tu propia casa u oficina. Un sensor
real que detecte personas a través de paredes debe instalarse solo donde quienes viven o trabajan allí lo sepan.
