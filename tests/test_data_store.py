import hashlib
import io
import unittest
import zipfile
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from ai_trading_lab import data_store


def zip_bytes(rows):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("k.csv", "\n".join(",".join(map(str, r)) for r in rows))
    return buf.getvalue()


ROW_MS = [1_704_067_200_000, 100, 110, 90, 105, 1, 0, 0, 0, 0, 0, 0]
ROW_US = [1_735_689_600_000_000, 200, 210, 190, 205, 1, 0, 0, 0, 0, 0, 0]


class ResampleTest(unittest.TestCase):
    H = 3_600_000
    T0 = 1_790_208_000_000  # 2026-09-24T00:00Z, múltiplo de 4h y de 1d

    def hourly(self, n, start=None):
        import numpy as np
        from ai_trading_lab.backtest import Bars
        start = self.T0 if start is None else start
        t = start + np.arange(n, dtype=np.int64) * self.H
        o = np.arange(n, dtype=float) + 100
        return Bars(t, o, o + 2, o - 1, o + 0.5, np.ones(n))

    def test_aggregates_ohlcv_in_utc_aligned_blocks(self):
        b = data_store.resample(self.hourly(8), 4)
        self.assertEqual(list(b.open_time), [self.T0, self.T0 + 4 * self.H])
        self.assertEqual(list(b.open), [100, 104])
        self.assertEqual(list(b.high), [105, 109])   # máximo de las 4 horas
        self.assertEqual(list(b.low), [99, 103])     # mínimo de las 4 horas
        self.assertEqual(list(b.close), [103.5, 107.5])
        self.assertEqual(list(b.volume), [4, 4])

    def test_drops_block_that_has_not_closed(self):
        b = data_store.resample(self.hourly(6), 4)  # el segundo bloque solo tiene 2 de 4 horas
        self.assertEqual(len(b), 1)

    def test_daily_blocks_start_at_midnight_utc(self):
        b = data_store.resample(self.hourly(48, start=self.T0 - 5 * self.H), 24)
        self.assertEqual(list(b.open_time), [self.T0])  # el día parcial previo y el último incompleto se descartan


class DataStoreTest(unittest.TestCase):
    def fake_get(self, payload, checksum):
        return lambda url: checksum.encode() if url.endswith(".CHECKSUM") else payload

    def test_rejects_file_whose_checksum_does_not_match(self):
        payload = zip_bytes([ROW_MS])
        with TemporaryDirectory() as tmp, mock.patch.object(data_store, "ROOT", Path(tmp)), \
                mock.patch.object(data_store, "_get", self.fake_get(payload, "0" * 64 + "  f.zip")):
            with self.assertRaises(data_store.ChecksumMismatch):
                data_store._month_file("BTCUSDT", "1h", 2024, 1)
            self.assertFalse(any(Path(tmp).rglob("*.zip")), "no debe cachear un archivo corrupto")

    def test_caches_verified_file(self):
        payload = zip_bytes([ROW_MS])
        good = hashlib.sha256(payload).hexdigest() + "  f.zip"
        with TemporaryDirectory() as tmp, mock.patch.object(data_store, "ROOT", Path(tmp)), \
                mock.patch.object(data_store, "_get", self.fake_get(payload, good)):
            path = data_store._month_file("BTCUSDT", "1h", 2024, 1)
            self.assertEqual(path.read_bytes(), payload)

    def test_remembers_months_before_listing(self):
        calls = []

        def not_found(url):
            calls.append(url)
            raise data_store.urllib.error.HTTPError(url, 404, "Not Found", {}, None)

        with TemporaryDirectory() as tmp, mock.patch.object(data_store, "ROOT", Path(tmp)), \
                mock.patch.object(data_store, "_get", not_found):
            self.assertIsNone(data_store._month_file("ONDOUSDT", "1h", 2019, 1))
            self.assertIsNone(data_store._month_file("ONDOUSDT", "1h", 2019, 1))
        self.assertEqual(len(calls), 1, "el segundo intento no debe volver a pedir el mes inexistente")

    def test_hash_depends_on_data_not_on_query_time(self):
        from datetime import datetime, timezone
        from ai_trading_lab.candles import Candle
        candles = [Candle(1_790_208_000_000 + i * 3_600_000, 1_790_208_000_000 + (i + 1) * 3_600_000 - 1,
                          100, 101, 99, 100.5, 1) for i in range(3)]
        early = datetime(2026, 9, 24, 3, 5, tzinfo=timezone.utc)
        later = datetime(2026, 9, 24, 3, 40, tzinfo=timezone.utc)  # mismas velas cerradas, otra hora de consulta
        with mock.patch.object(data_store, "_month_file", return_value=None), \
                mock.patch.object(data_store, "fetch_klines", return_value=candles):
            _, h1 = data_store.load("BTCUSDT", since=early.date(), now=early)
            _, h2 = data_store.load("BTCUSDT", since=early.date(), now=later)
        self.assertEqual(h1, h2)

    def test_normalizes_microsecond_timestamps(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "x.zip"
            path.write_bytes(zip_bytes([["open_time", "o", "h", "l", "c", "v"], ROW_MS, ROW_US]))
            rows = list(data_store._rows_from_zip(path))
        self.assertEqual([r[0] for r in rows], [1_704_067_200_000, 1_735_689_600_000])


if __name__ == "__main__":
    unittest.main()
