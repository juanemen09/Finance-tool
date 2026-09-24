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

    def test_normalizes_microsecond_timestamps(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "x.zip"
            path.write_bytes(zip_bytes([["open_time", "o", "h", "l", "c", "v"], ROW_MS, ROW_US]))
            rows = list(data_store._rows_from_zip(path))
        self.assertEqual([r[0] for r in rows], [1_704_067_200_000, 1_735_689_600_000])


if __name__ == "__main__":
    unittest.main()
