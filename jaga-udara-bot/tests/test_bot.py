"""Uji dasar. Jalankan: python -m unittest discover tests"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

AKAR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, AKAR)
from bot import analisis, pesan  # noqa: E402


class TesAnalisis(unittest.TestCase):
    def test_ispu(self):
        self.assertEqual(analisis.ispu(15.5), 50)
        self.assertEqual(analisis.ispu(55.4), 100)
        self.assertEqual(analisis.ispu(150.4), 200)
        self.assertEqual(analisis.kategori_ispu(301), 4)

    def test_di_wilayah(self):
        kotak = {"type": "Polygon", "coordinates": [[[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]]]}
        self.assertTrue(analisis.di_wilayah(5, 5, kotak))
        self.assertFalse(analisis.di_wilayah(15, 5, kotak))

    def test_saring_titik(self):
        now = datetime(2026, 10, 10, 23, tzinfo=timezone.utc)
        t = [
            {"lat": 1.0, "lon": 1.0, "waktu": now - timedelta(hours=2), "keyakinan": "n", "frp": 5},
            {"lat": 1.001, "lon": 1.001, "waktu": now - timedelta(hours=3), "keyakinan": "h", "frp": 9},  # duplikat sel
            {"lat": 2.0, "lon": 2.0, "waktu": now - timedelta(hours=2), "keyakinan": "l", "frp": 5},      # keyakinan rendah
            {"lat": 3.0, "lon": 3.0, "waktu": now - timedelta(hours=30), "keyakinan": "n", "frp": 5},     # kemarin
        ]
        baru, lama = analisis.saring_titik(t, now)
        self.assertEqual(len(baru), 1)
        self.assertEqual(len(lama), 1)

    def test_tren(self):
        self.assertTrue(pesan.tren(100, 40).startswith("naik"))
        self.assertTrue(pesan.tren(10, 60).startswith("turun"))


class TesUjung(unittest.TestCase):
    def test_jalan_dengan_data_contoh(self):
        # arsip uji ditulis ke folder sementara, supaya tidak tercampur dengan arsip asli
        arsip = tempfile.mkdtemp()
        env = dict(os.environ, FIXTURES=os.path.join(AKAR, "tests", "fixtures"),
                   WAKTU_UJI="2026-10-10T23:00:00+00:00", ARSIP_DIR=arsip)
        r = subprocess.run([sys.executable, "-m", "bot.main", "--coba"], cwd=AKAR, env=env,
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("[kalteng]", r.stdout)


if __name__ == "__main__":
    unittest.main()
