"""Servidor HTTP del panel. Solo escucha en 127.0.0.1, solo GET, solo archivos de una lista fija.

El chequeo del encabezado Host impide que una web ajena lea el panel mediante DNS rebinding.
"""
import json
import logging
import mimetypes
import socket
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from dashboard.market import MarketError, validate_candles_request

STATIC = Path(__file__).resolve().parent / "static"
FILES = {
    "/": "index.html",
    "/static/app.css": "app.css",
    "/static/app.js": "app.js",
    "/static/lava.js": "lava.js",
    "/static/vendor/lightweight-charts.js": "vendor/lightweight-charts.standalone.production.js",
}
CSP = ("default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; "
       "frame-ancestors 'none'; base-uri 'none'; form-action 'none'")
log = logging.getLogger("dashboard")


def make_handler(state_provider, candles_provider, allowed_hosts):
    class Handler(BaseHTTPRequestHandler):
        server_version = "ai-trading-lab"
        sys_version = ""

        def log_message(self, fmt, *args):  # las URLs no llevan secretos, pero no hace falta ruido en consola
            log.debug(fmt, *args)

        def _send(self, status, body, content_type, cache="no-store"):
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", cache)
            self.send_header("Content-Security-Policy", CSP)
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("X-Frame-Options", "DENY")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, status, payload):
            self._send(status, json.dumps(payload, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

        def do_GET(self):
            if self.headers.get("Host", "") not in allowed_hosts:
                return self._json(403, {"error": "host no permitido"})
            url = urlsplit(self.path)
            try:
                if url.path == "/api/state":
                    return self._json(200, state_provider())
                if url.path == "/api/candles":
                    params = parse_qs(url.query)
                    symbol = params.get("symbol", [""])[0]
                    interval = params.get("interval", [""])[0]
                    return self._json(200, candles_provider(*validate_candles_request(symbol, interval)))
            except MarketError as error:
                return self._json(400, {"error": str(error)})
            except Exception as error:  # la base o Binance caídos: el panel lo muestra, no se cae
                log.warning("fallo en %s: %s", url.path, type(error).__name__)
                return self._json(503, {"error": f"{type(error).__name__}: fuente no disponible"})
            name = FILES.get(url.path)
            if name is None:
                return self._json(404, {"error": "no encontrado"})
            path = STATIC / name
            content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
            if content_type.startswith("text/") or content_type.endswith("javascript"):
                content_type += "; charset=utf-8"
            return self._send(200, path.read_bytes(), content_type, cache="no-cache")

        def _refuse(self):
            self._json(405, {"error": "solo lectura"})

        do_POST = do_PUT = do_DELETE = do_PATCH = _refuse

    return Handler


class LocalServer(ThreadingHTTPServer):
    # En Windows, SO_REUSEADDR deja que dos procesos compartan el puerto: un panel viejo con otra configuración
    # seguía contestando. Con el puerto exclusivo, el segundo arranque falla con un error claro.
    allow_reuse_address = False
    daemon_threads = True

    def server_bind(self):
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


def make_server(port, state_provider, candles_provider):
    server = LocalServer(("127.0.0.1", port), None)
    real_port = server.server_address[1]
    allowed = {f"127.0.0.1:{real_port}", f"localhost:{real_port}"}
    server.RequestHandlerClass = make_handler(state_provider, candles_provider, allowed)
    return server
