"""Membuat data contoh (bukan data asli) untuk uji tanpa internet. Jalankan: python tests/buat_fixture.py"""
import json, os, random, math
from datetime import datetime, timedelta, timezone
random.seed(7)
D = os.path.join(os.path.dirname(__file__), "fixtures")
os.makedirs(D, exist_ok=True)
SEKARANG = datetime(2026, 10, 10, 23, 0, tzinfo=timezone.utc)  # 11 Okt 2026, 06.00 WIB
# klaster kebakaran: (lat, lon, jumlah 24 jam terakhir, jumlah 24-48 jam lalu, sebaran derajat)
KLASTER = [(-2.45, 114.0, 70, 25, 0.18), (-2.75, 113.1, 30, 22, 0.15), (-2.95, 111.9, 12, 14, 0.15),
           (-2.8, 114.55, 18, 6, 0.2), (-1.5, 113.5, 9, 8, 0.4), (-0.8, 112.5, 5, 7, 0.5)]
HEAD = "latitude,longitude,bright_ti4,scan,track,acq_date,acq_time,satellite,instrument,confidence,version,bright_ti5,frp,daynight\n"
for sat, kode in (("VIIRS_SNPP_NRT", "N"), ("VIIRS_NOAA20_NRT", "N20"), ("VIIRS_NOAA21_NRT", "N21")):
    rows = []
    for lat, lon, n1, n2, sd in KLASTER:
        for n, jam_lalu in ((n1, (1, 23)), (n2, (25, 47))):
            for _ in range(max(1, n // 2)):
                t = SEKARANG - timedelta(hours=random.uniform(*jam_lalu))
                conf = random.choice(["n", "n", "h", "l"])
                rows.append(f"{lat+random.gauss(0,sd):.5f},{lon+random.gauss(0,sd):.5f},{random.uniform(330,367):.2f},0.39,0.36,"
                            f"{t:%Y-%m-%d},{t:%H%M},{kode},VIIRS,{conf},2.0NRT,{random.uniform(285,300):.2f},{random.uniform(1,40):.2f},N")
    open(os.path.join(D, f"firms_{sat}.csv"), "w").write(HEAD + "\n".join(rows) + "\n")
KOTA = {"palangka_raya": 165, "sampit": 95, "pangkalan_bun": 60, "kuala_kapuas": 110, "buntok": 40, "muara_teweh": 22}
mulai = datetime(2026, 10, 10, 0, 0)
for nama, dasar in KOTA.items():
    t, v = [], []
    for h in range(24 * 4):
        w = mulai + timedelta(hours=h)
        pagi = math.exp(-((w.hour - 7) / 2.5) ** 2)
        tren = 1 + 0.15 * math.sin(h / 30)
        t.append(w.strftime("%Y-%m-%dT%H:00"))
        v.append(round(dasar * tren * (0.6 + 0.9 * pagi), 1))
    json.dump({"latitude": 0, "longitude": 0, "hourly": {"time": t, "pm2_5": v}}, open(os.path.join(D, f"openmeteo_{nama}.json"), "w"))
json.dump({"status": "ok", "data": {"aqi": 214, "city": {"name": "Palangka Raya, Indonesia", "geo": [-2.21, 113.92]},
           "attributions": [{"name": "BMKG | Badan Meteorologi, Klimatologi dan Geofisika"}, {"name": "World Air Quality Index Project"}],
           "time": {"iso": "2026-11-10T05:00:00+07:00".replace("2026-11-10", "2026-10-11")}}},
          open(os.path.join(D, "waqi_palangka_raya.json"), "w"))
print("fixture dibuat di", D)
