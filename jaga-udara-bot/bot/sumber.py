"""Mengambil data dari sumber terbuka.

- NASA FIRMS  : titik api dari satelit (perlu MAP_KEY gratis)
- Open-Meteo  : prakiraan PM2.5 per jam dari model CAMS (gratis, tanpa kunci)
- WAQI        : stasiun pemantau terdekat (perlu token gratis, opsional)

Kalau variabel lingkungan FIXTURES berisi nama folder, data dibaca dari file
di folder itu (untuk uji tanpa internet).
"""
import csv
import io
import json
import os
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone

USER_AGENT = "JagaUdaraBot/0.1 (relawan; github.com)"
FIRMS_SUMBER = ["VIIRS_SNPP_NRT", "VIIRS_NOAA20_NRT", "VIIRS_NOAA21_NRT"]


class GagalAmbil(Exception):
    pass


def _get(url, timeout=60, tries=3):
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read().decode("utf-8", errors="replace")
        except Exception as e:  # jaringan putus, server sibuk, dll.
            last = e
            time.sleep(3 * (i + 1))
    raise GagalAmbil(f"{url.split('?')[0]}: {last}")


def _fixture(nama):
    folder = os.environ.get("FIXTURES")
    if not folder:
        return None
    path = os.path.join(folder, nama)
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return f.read()
    return None


# ---------------------------------------------------------------- FIRMS
def titik_api(bbox, map_key, hari=3):
    """Semua deteksi titik api VIIRS di dalam kotak bbox (barat, selatan, timur, utara).

    Mengembalikan list dict: lat, lon, waktu (datetime UTC), satelit, keyakinan, frp.
    """
    hasil = []
    for sumber in FIRMS_SUMBER:
        teks = _fixture(f"firms_{sumber}.csv")
        if teks is None:
            if not map_key:
                raise GagalAmbil("FIRMS_MAP_KEY belum diisi")
            area = ",".join(f"{x:.3f}" for x in bbox)
            url = f"https://firms.modaps.eosdis.nasa.gov/api/area/csv/{map_key}/{sumber}/{area}/{hari}"
            teks = _get(url)
        if not teks.lstrip().lower().startswith("latitude"):
            # FIRMS mengembalikan pesan teks kalau kunci salah / kuota habis
            raise GagalAmbil(f"FIRMS {sumber}: {teks.strip()[:120]}")
        for row in csv.DictReader(io.StringIO(teks)):
            try:
                jam = row["acq_time"].zfill(4)
                waktu = datetime.strptime(row["acq_date"] + jam, "%Y-%m-%d%H%M").replace(tzinfo=timezone.utc)
                hasil.append({
                    "lat": float(row["latitude"]),
                    "lon": float(row["longitude"]),
                    "waktu": waktu,
                    "satelit": sumber,
                    "keyakinan": (row.get("confidence") or "").strip().lower(),
                    "frp": float(row.get("frp") or 0),
                })
            except (KeyError, ValueError):
                continue
    return hasil


# ---------------------------------------------------------------- Open-Meteo
def prakiraan_pm25(lat, lon, nama_fixture=None):
    """PM2.5 per jam (µg/m³), waktu lokal WIB, kemarin s.d. 3 hari ke depan."""
    teks = _fixture(f"openmeteo_{nama_fixture}.json") if nama_fixture else None
    if teks is None:
        q = urllib.parse.urlencode({
            "latitude": f"{lat:.4f}", "longitude": f"{lon:.4f}",
            "hourly": "pm2_5", "timezone": "Asia/Jakarta",
            "past_days": 1, "forecast_days": 3,
        })
        teks = _get("https://air-quality-api.open-meteo.com/v1/air-quality?" + q)
    d = json.loads(teks)
    jam = d["hourly"]["time"]
    nilai = d["hourly"]["pm2_5"]
    return [(t, v) for t, v in zip(jam, nilai) if v is not None]


# ---------------------------------------------------------------- WAQI
def stasiun_terdekat(lat, lon, token, nama_fixture=None):
    """Stasiun pemantau terdekat dari WAQI. None kalau tidak ada token atau gagal."""
    teks = _fixture(f"waqi_{nama_fixture}.json") if nama_fixture else None
    if teks is None:
        if not token:
            return None
        try:
            teks = _get(f"https://api.waqi.info/feed/geo:{lat:.4f};{lon:.4f}/?token={urllib.parse.quote(token)}", tries=2)
        except GagalAmbil:
            return None
    try:
        d = json.loads(teks)
        if d.get("status") != "ok":
            return None
        x = d["data"]
        aqi = int(x["aqi"])
        geo = (x.get("city") or {}).get("geo") or [None, None]
        sumber = [a.get("name", "").split("|")[0].strip() for a in x.get("attributions", []) if "waqi" not in a.get("name", "").lower()]
        return {
            "nama": (x.get("city") or {}).get("name", "Stasiun").replace(", Indonesia", ""),
            "aqi": aqi,
            "lat": geo[0], "lon": geo[1],
            "waktu_iso": (x.get("time") or {}).get("iso"),
            "sumber": sumber[0] if sumber else "",
        }
    except (ValueError, KeyError, TypeError):
        return None
