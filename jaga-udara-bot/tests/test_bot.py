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
from bot import analisis, main, pesan, sumber, telegram  # noqa: E402


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

    def test_arah_angin(self):
        # angin DATANG dari tenggara (135°) -> asap terbawa ke barat laut
        now = datetime(2026, 10, 10, 23, tzinfo=timezone.utc)
        jam = [f"2026-10-11T{h:02d}:00" for h in range(24)]
        grid = {"lats": [0], "lons": [0], "titik": [{"lat": 0, "lon": 0, "waktu": jam,
                                                      "laju": [10] * 24, "arah": [135] * 24}]}
        a = analisis.ringkas_angin(grid, now)
        self.assertEqual(analisis.nama_arah(a["arah_ke"]), "barat laut")
        self.assertFalse(a["lemah"])
        self.assertIn("barat laut", pesan.kalimat_angin(a))

    def test_arah_angin_delapan_arah(self):
        # Open-Meteo memberi arah DATANG angin; kartu harus menyebut arah PERGI asap (kebalikannya)
        now = datetime(2026, 10, 10, 23, tzinfo=timezone.utc)
        jam = [f"2026-10-11T{h:02d}:00" for h in range(24)]
        harapan = {0: "selatan", 45: "barat daya", 90: "barat", 135: "barat laut",
                   180: "utara", 225: "timur laut", 270: "timur", 315: "tenggara"}
        for dari, ke in harapan.items():
            grid = {"lats": [0], "lons": [0], "titik": [{"lat": 0, "lon": 0, "waktu": jam,
                                                          "laju": [12] * 24, "arah": [dari] * 24}]}
            a = analisis.ringkas_angin(grid, now)
            self.assertEqual(analisis.nama_arah(a["arah_ke"]), ke, f"angin dari {dari}°")

    def test_klaster(self):
        t = [{"lat": -2.0 + i * 0.001, "lon": 113.0} for i in range(30)] + \
            [{"lat": -3.0, "lon": 111.0 + i * 0.001} for i in range(20)] + [{"lat": 0.5, "lon": 115.0}]
        k = analisis.klaster_titik(t)
        self.assertEqual([x["n"] for x in k], [30, 20])  # 20 >= 30% x 30

    def test_tren(self):
        self.assertTrue(pesan.tren(100, 40).startswith("naik"))
        self.assertTrue(pesan.tren(10, 60).startswith("turun"))


class TesGrid(unittest.TestCase):
    def test_potong_grid_urutan_tetap(self):
        lats, lons = sumber._titik_grid((110, -4, 118, 2), 0.5)
        grid = {"lats": lats, "lons": lons, "titik": [{"lat": la, "lon": lo} for la in lats for lo in lons]}
        g = sumber.potong_grid(grid, (112.2, -2.1, 114.0, -1.0), 0.5)
        self.assertEqual(g["lons"][0], 112.0)  # satu titik di luar tepi barat 112,2
        self.assertEqual(g["lats"][-1], -0.5)
        # tetap berurutan baris per baris, jadi bisa dibentuk jadi matriks
        self.assertEqual([(p["lat"], p["lon"]) for p in g["titik"]],
                         [(la, lo) for la in g["lats"] for lo in g["lons"]])

    def test_jatah_per_menit(self):
        tidur = []
        asli_sleep, asli_mono = sumber.time.sleep, sumber.time.monotonic
        jam = [1000.0]
        sumber.time.sleep = lambda d: (tidur.append(d), jam.__setitem__(0, jam[0] + d))
        sumber.time.monotonic = lambda: jam[0]
        sumber._riwayat_om.clear()
        try:
            for n in (250, 250, 250, 25):
                sumber._jatah_open_meteo(n)
        finally:
            sumber.time.sleep, sumber.time.monotonic = asli_sleep, asli_mono
            sumber._riwayat_om.clear()
        self.assertEqual(len(tidur), 1)  # 500 lokasi pertama langsung, sisanya setelah jeda 1 menit


class TesRekapIndonesia(unittest.TestCase):
    def test_rekap_per_provinsi(self):
        import shutil
        from bot import rekap_indonesia
        with tempfile.TemporaryDirectory() as d:
            fx = os.path.join(d, "fx")
            shutil.copytree(os.path.join(os.path.dirname(__file__), "fixtures"), fx)
            shutil.copy(os.path.join(os.path.dirname(__file__), "..", "data", "batas-provinsi.geojson"),
                        os.path.join(fx, "batas_indonesia.geojson"))
            env = {"FIXTURES": fx, "LAPORAN_DIR": d, "WAKTU_UJI": "2026-10-11T06:00:00+07:00"}
            lama = {k: os.environ.get(k) for k in env}
            os.environ.update(env)
            try:
                dasar = rekap_indonesia.jalankan(7)
            finally:
                for k, v in lama.items():
                    os.environ.pop(k) if v is None else os.environ.__setitem__(k, v)
            data = json.load(open(dasar + ".json"))
            self.assertEqual(data["provinsi"][0]["provinsi"], "Kalimantan Tengah")
            self.assertTrue(os.path.exists(dasar + ".png"))
            self.assertIn("| 1 | Kalimantan Tengah | Kalimantan |", open(dasar + ".md").read())

    def test_nama_inggris(self):
        from bot.rekap_indonesia import indonesiakan, nama_pulau
        self.assertEqual(indonesiakan("Central Kalimantan"), "Kalimantan Tengah")
        self.assertEqual(indonesiakan("South Papua"), "Papua Selatan")
        self.assertEqual(nama_pulau(indonesiakan("East Nusa Tenggara")), "Bali & Nusa Tenggara")
        self.assertEqual(nama_pulau("Kepulauan Riau"), "Sumatra")


class TesPanduan(unittest.TestCase):
    def test_pesan_tanpa_tautan_artifact(self):
        hasil = {"nama": "Kalimantan Tengah", "waktu": datetime(2026, 10, 10, 23, tzinfo=timezone.utc), "tingkat": 0,
                 "titik_prov_24j": 0, "titik_prov_24j_sebelumnya": 0, "kota": []}
        tg = pesan.harian(hasil, 50)
        self.assertNotIn("claude.ai", tg)
        self.assertIn("PDF", tg)
        self.assertNotIn("PDF", pesan.harian(hasil, 50, wa=True))  # Saluran WhatsApp tidak memuat PDF

    def test_pdf_ikut_pesan_disematkan_sekali(self):
        kirim, pin = [], []
        asli = telegram.kirim_dokumen, telegram.sematkan
        telegram.kirim_dokumen = lambda *a: kirim.append(a) or 42
        telegram.sematkan = lambda *a: pin.append(a)
        try:
            pdf = os.path.join(AKAR, "docs", "panduan-asap-keluarga.pdf")
            prov = {"id": "uji", "nama": "Uji"}
            sha = main._kirim_panduan("t", "@c", pdf, "", prov)
            self.assertEqual((len(kirim), len(pin)), (1, 1))
            self.assertEqual(main._kirim_panduan("t", "@c", pdf, sha, prov), sha)
            self.assertEqual(len(kirim), 1)  # tanpa pesan: tidak dikirim ulang kalau isinya sama
            main._kirim_panduan("t", "@c", pdf, sha, prov, selalu=True)
            self.assertEqual((len(kirim), len(pin)), (2, 1))  # ikut pesan, tapi tidak disematkan ulang
        finally:
            telegram.kirim_dokumen, telegram.sematkan = asli


class TesLogJadwal(unittest.TestCase):
    def test_slot_dan_keterlambatan(self):
        lama = main.LOG_JADWAL
        main.LOG_JADWAL = os.path.join(tempfile.mkdtemp(), "log.csv")
        env = {k: os.environ.get(k) for k in ("GITHUB_ACTIONS", "GITHUB_EVENT_NAME", "FIXTURES", "PEMICU")}
        os.environ.update(GITHUB_ACTIONS="true", GITHUB_EVENT_NAME="schedule")
        os.environ.pop("FIXTURES", None)
        try:
            # 15.27 WIB -> slot 15.00, terlambat 27 menit
            main._catat_jadwal(datetime(2026, 10, 10, 8, 27, tzinfo=timezone.utc), "harian", 3)
            with open(main.LOG_JADWAL, encoding="utf-8") as f:
                isi = f.read().splitlines()
            self.assertEqual(isi[1], "2026-10-10 15.27,jadwal,2026-10-10 15.00,27,harian,3")
            # cron-job.org memicu lewat workflow_dispatch dengan pemicu=eksternal
            os.environ.update(GITHUB_EVENT_NAME="workflow_dispatch", PEMICU="eksternal")
            main._catat_jadwal(datetime(2026, 10, 10, 23, 1, tzinfo=timezone.utc), "harian", 15)
            with open(main.LOG_JADWAL, encoding="utf-8") as f:
                self.assertEqual(f.read().splitlines()[2], "2026-10-11 06.01,eksternal,2026-10-11 06.00,1,harian,15")
        finally:
            main.LOG_JADWAL = lama
            for k, v in env.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v


class TesPencegahDobel(unittest.TestCase):
    """cron-job.org dan cron GitHub bisa jalan untuk slot yang sama; pesan hanya boleh terkirim sekali."""

    def setUp(self):
        self.env_lama = dict(os.environ)
        os.environ.update(FIXTURES=os.path.join(AKAR, "tests", "fixtures"), WAKTU_UJI="2026-10-10T23:00:00+00:00",
                          ARSIP_DIR=tempfile.mkdtemp(), STATE_DIR=tempfile.mkdtemp(),
                          TELEGRAM_BOT_TOKEN="x", TELEGRAM_CHAT_KALTENG="@uji")
        self.kirim = []
        self.asli = (telegram.kirim_foto, telegram.kirim_teks, telegram.kirim_dokumen, telegram.sematkan)
        telegram.kirim_foto = lambda *a: self.kirim.append("foto")
        telegram.kirim_teks = lambda *a: self.kirim.append("teks")
        telegram.kirim_dokumen = lambda *a: self.kirim.append("pdf") or 1
        telegram.sematkan = lambda *a: None

    def tearDown(self):
        telegram.kirim_foto, telegram.kirim_teks, telegram.kirim_dokumen, telegram.sematkan = self.asli
        os.environ.clear()
        os.environ.update(self.env_lama)

    def test_slot_sama_tidak_dikirim_dua_kali(self):
        main.jalankan("otomatis", hanya={"kalteng"})
        self.assertEqual(self.kirim, ["foto", "teks", "pdf"])
        main.jalankan("otomatis", hanya={"kalteng"})  # pemicu kedua di slot 06.00 yang sama
        self.assertEqual(len(self.kirim), 3)

    def test_slot_berikutnya_dikirim_lagi(self):
        main.jalankan("otomatis", hanya={"kalteng"})
        os.environ["WAKTU_UJI"] = "2026-10-11T02:05:00+00:00"  # 09.05 WIB, slot baru
        main.jalankan("otomatis", hanya={"kalteng"})
        self.assertEqual(len(self.kirim), 6)

    def test_manual_harian_tetap_kirim(self):
        main.jalankan("otomatis", hanya={"kalteng"})
        main.jalankan("harian", hanya={"kalteng"})  # tombol Run manual tidak dihalangi
        self.assertEqual(len(self.kirim), 6)


class TesUjung(unittest.TestCase):
    def test_jalan_dengan_data_contoh(self):
        # arsip uji ditulis ke folder sementara, supaya tidak tercampur dengan arsip asli
        arsip = tempfile.mkdtemp()
        env = dict(os.environ, FIXTURES=os.path.join(AKAR, "tests", "fixtures"),
                   WAKTU_UJI="2026-10-10T23:00:00+00:00", ARSIP_DIR=arsip)
        r = subprocess.run([sys.executable, "-m", "bot.main", "--coba", "--provinsi", "kalteng"], cwd=AKAR, env=env,
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("[kalteng]", r.stdout)
        self.assertNotIn("[kalbar]", r.stdout)  # --provinsi membatasi provinsi yang dijalankan
        self.assertNotIn("gagal", r.stdout)  # grid angin dan asap dari data contoh terbaca


if __name__ == "__main__":
    unittest.main()
