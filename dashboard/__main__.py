"""Arranca el centro de mando:  python -m dashboard [--port 8765] [--no-browser]

Necesita en .env (fuera de git) la conexión del rol de solo lectura:
  DASHBOARD_DATABASE_URL=postgresql://dashboard_reader.<ref>:<contraseña>@<host del pooler>:5432/postgres
"""
import argparse
import logging
import sys
import threading
import time
import webbrowser
from datetime import datetime, timezone

import psycopg
from psycopg.rows import dict_row

from dashboard.config import load_env
from dashboard.market import CandleCache
from dashboard.queries import build_state
from dashboard.server import make_server

STATE_SECONDS = 20


class ReadOnlyDatabase:
    def __init__(self, url):
        self._url, self._conn, self._lock = url, None, threading.Lock()

    def _connect(self):
        # prepare_threshold=None: el pooler de Supabase en modo transacción no admite sentencias preparadas.
        conn = psycopg.connect(self._url, autocommit=True, row_factory=dict_row, connect_timeout=10,
                               prepare_threshold=None, application_name="ai-trading-lab-dashboard")
        conn.execute("set session characteristics as transaction read only")
        return conn

    def run(self, sql):
        with self._lock:
            for attempt in (1, 2):
                try:
                    if self._conn is None or self._conn.closed:
                        self._conn = self._connect()
                    return self._conn.execute(sql).fetchall()
                except psycopg.OperationalError:
                    self._conn = None  # conexión caída: se reintenta una vez con otra nueva
                    if attempt == 2:
                        raise


class CachedState:
    def __init__(self, db):
        self._db, self._lock, self._at, self._value = db, threading.Lock(), 0.0, None

    def __call__(self):
        with self._lock:
            if self._value is None or time.monotonic() - self._at > STATE_SECONDS:
                self._value = build_state(self._db.run, datetime.now(timezone.utc))
                self._at = time.monotonic()
            return self._value


def main():
    parser = argparse.ArgumentParser(description="Centro de mando local de AI Trading Lab (solo lectura)")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    url = load_env().get("DASHBOARD_DATABASE_URL")
    if not url:
        sys.exit("Falta DASHBOARD_DATABASE_URL en .env (conexión del rol dashboard_reader). Ver README.")
    if "dashboard_reader" not in url:
        sys.exit("DASHBOARD_DATABASE_URL debe usar el rol de solo lectura dashboard_reader, no otro usuario.")

    candles = CandleCache()
    try:
        server = make_server(args.port, state_provider=CachedState(ReadOnlyDatabase(url)), candles_provider=candles.get)
    except OSError:
        sys.exit(f"El puerto {args.port} ya está en uso: probablemente el panel ya está abierto. Ciérralo o usa --port.")
    address = f"http://127.0.0.1:{server.server_address[1]}/"
    print(f"Centro de mando en {address}  (Ctrl+C para cerrar)")
    if not args.no_browser:
        webbrowser.open(address)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
