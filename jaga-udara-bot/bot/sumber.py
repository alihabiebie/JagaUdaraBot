"""Mengambil data dari sumber terbuka.

- NASA FIRMS  : titik panas (hotspot) dari satelit (perlu MAP_KEY gratis)
- Open-Meteo  : prakiraan PM2.5 per jam dari model CAMS dan angin 10 m (gratis, tanpa kunci)
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
from datetime import datetime, timedelta, timezone

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
FIRMS_HARI_MAKS = 5  # batas API area FIRMS per permintaan


def _potongan_hari(hari, hari_ini):
    """[(tanggal_mulai atau None, jumlah_hari)]: lebih dari 5 hari dipecah memakai parameter tanggal FIRMS."""
    if hari <= FIRMS_HARI_MAKS:
        return [(None, hari)]
    hasil, akhir = [], hari_ini
    while hari > 0:
        n = min(FIRMS_HARI_MAKS, hari)
        mulai = akhir - timedelta(days=n - 1)
        hasil.append((mulai.isoformat(), n))
        akhir, hari = mulai - timedelta(days=1), hari - n
    return hasil


def titik_api(bbox, map_key, hari=3):
    """Semua deteksi titik panas VIIRS di dalam kotak bbox (barat, selatan, timur, utara).

    Mengembalikan list dict: lat, lon, waktu (datetime UTC), satelit, keyakinan, frp.
    """
    if not map_key and not os.environ.get("FIXTURES"):
        raise GagalAmbil("FIRMS_MAP_KEY belum diisi")
    hasil, gagal = [], []
    for sumber in FIRMS_SUMBER:
        try:
            teks = _csv_firms(sumber, bbox, map_key, hari)
        except GagalAmbil as e:
            # Server NASA kadang lambat/504. Ketiga satelit memotret daerah yang hampir sama,
            # jadi kalau satu gagal, data dua satelit lain tetap dipakai.
            gagal.append(str(e))
            continue
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
    if len(gagal) == len(FIRMS_SUMBER):
        raise GagalAmbil("semua satelit gagal: " + " | ".join(gagal))
    for g in gagal:
        print(f"Peringatan: satu sumber satelit dilewati, data dari satelit lain tetap dipakai ({g})")
    return hasil


def _csv_firms(sumber, bbox, map_key, hari):
    teks = _fixture(f"firms_{sumber}.csv")
    if teks is None:
        area = ",".join(f"{x:.3f}" for x in bbox)
        bagian = []
        for mulai, n in _potongan_hari(hari, datetime.now(timezone.utc).date()):
            url = f"https://firms.modaps.eosdis.nasa.gov/api/area/csv/{map_key}/{sumber}/{area}/{n}"
            # batas waktu lebih pendek supaya server NASA yang macet tidak menghabiskan 15 menit jatah run
            bagian.append(_get(url + (f"/{mulai}" if mulai else ""), timeout=40, tries=2))
        # gabungkan CSV: kepala kolom hanya dari bagian pertama
        teks = bagian[0] + "".join("\n" + b.split("\n", 1)[1] if "\n" in b else "" for b in bagian[1:])
    if not teks.lstrip().lower().startswith("latitude"):
        # FIRMS mengembalikan pesan teks kalau kunci salah / kuota habis
        raise GagalAmbil(f"FIRMS {sumber}: {teks.strip()[:120]}")
    return teks


# ---------------------------------------------------------------- Open-Meteo
# Batas gratis Open-Meteo: 600 lokasi per menit, 5.000 per jam, 10.000 per hari.
# Permintaan banyak lokasi dihitung per lokasi, jadi grid dipecah dan diberi jeda.
BATAS_PER_MENIT = 500
POTONGAN_GRID = 250
_riwayat_om = []  # (waktu, jumlah lokasi) permintaan Open-Meteo dalam 1 menit terakhir


def _jatah_open_meteo(n):
    """Tunggu seperlunya supaya permintaan n lokasi tidak melewati batas per menit."""
    while True:
        kini = time.monotonic()
        _riwayat_om[:] = [(t, x) for t, x in _riwayat_om if kini - t < 61]
        if not _riwayat_om or sum(x for _, x in _riwayat_om) + n <= BATAS_PER_MENIT:
            _riwayat_om.append((kini, n))
            return
        time.sleep(61 - (kini - _riwayat_om[0][0]))


def prakiraan_pm25(lat, lon, nama_fixture=None):
    """PM2.5 per jam (µg/m³), waktu lokal WIB, kemarin s.d. 3 hari ke depan."""
    teks = _fixture(f"openmeteo_{nama_fixture}.json") if nama_fixture else None
    if teks is None:
        q = urllib.parse.urlencode({
            "latitude": f"{lat:.4f}", "longitude": f"{lon:.4f}",
            "hourly": "pm2_5", "timezone": "Asia/Jakarta",
            "past_days": 1, "forecast_days": 3,
        })
        _jatah_open_meteo(1)
        teks = _get("https://air-quality-api.open-meteo.com/v1/air-quality?" + q)
    d = json.loads(teks)
    jam = d["hourly"]["time"]
    nilai = d["hourly"]["pm2_5"]
    return [(t, v) for t, v in zip(jam, nilai) if v is not None]


def _titik_grid(bbox, langkah):
    """Titik-titik grid teratur di dalam kotak (barat, selatan, timur, utara)."""
    x0, y0, x1, y1 = bbox
    lons = [round(x0 + i * langkah, 3) for i in range(int((x1 - x0) / langkah) + 2)]
    lats = [round(y0 + j * langkah, 3) for j in range(int((y1 - y0) / langkah) + 2)]
    return lats, lons


def _ambil_grid(url_dasar, param, bbox, langkah, nama_fixture):
    """Permintaan Open-Meteo untuk banyak lokasi sekaligus (dipecah per POTONGAN_GRID lokasi).

    Mengembalikan (lats, lons, daftar) dengan daftar berurutan baris per baris
    (lintang dari selatan ke utara, bujur dari barat ke timur).
    """
    lats, lons = _titik_grid(bbox, langkah)
    teks = _fixture(nama_fixture) if nama_fixture else None
    if teks is None:
        titik = [(la, lo) for la in lats for lo in lons]
        daftar = []
        for i in range(0, len(titik), POTONGAN_GRID):
            bagian = titik[i:i + POTONGAN_GRID]
            q = urllib.parse.urlencode(dict(param,
                                            latitude=",".join(f"{la:.3f}" for la, _ in bagian),
                                            longitude=",".join(f"{lo:.3f}" for _, lo in bagian),
                                            timezone="Asia/Jakarta", forecast_days=2))
            _jatah_open_meteo(len(bagian))
            d = json.loads(_get(url_dasar + "?" + q, tries=3))
            daftar += d if isinstance(d, list) else [d]
    else:
        d = json.loads(teks)
        daftar = d if isinstance(d, list) else [d]
    if len(daftar) != len(lats) * len(lons):
        raise GagalAmbil(f"grid Open-Meteo: jumlah lokasi {len(daftar)}, seharusnya {len(lats) * len(lons)}")
    return lats, lons, daftar


def potong_grid(grid, bbox, langkah):
    """Bagian grid yang menutupi kotak bbox (ditambah satu langkah di tiap sisi)."""
    if not grid:
        return grid
    x0, y0, x1, y1 = bbox
    lats = [la for la in grid["lats"] if y0 - langkah <= la <= y1 + langkah]
    lons = [lo for lo in grid["lons"] if x0 - langkah <= lo <= x1 + langkah]
    sl, so = set(lats), set(lons)
    return {"lats": lats, "lons": lons,
            "titik": [p for p in grid["titik"] if p["lat"] in sl and p["lon"] in so]}


def angin_grid(bbox, langkah=1.0, nama_fixture=None):
    """Angin 10 m per jam di grid. Arah = arah DATANG angin (derajat, konvensi meteorologi)."""
    lats, lons, daftar = _ambil_grid(
        "https://api.open-meteo.com/v1/forecast",
        {"hourly": "wind_speed_10m,wind_direction_10m", "wind_speed_unit": "kmh"},
        bbox, langkah, nama_fixture)
    hasil = []
    for i, d in enumerate(daftar):
        h = d["hourly"]
        hasil.append({"lat": lats[i // len(lons)], "lon": lons[i % len(lons)], "waktu": h["time"],
                      "laju": h["wind_speed_10m"], "arah": h["wind_direction_10m"]})
    return {"lats": lats, "lons": lons, "titik": hasil}


def pm25_grid(bbox, langkah=0.5, nama_fixture=None):
    """Prakiraan PM2.5 per jam (µg/m³) di grid, model CAMS global."""
    lats, lons, daftar = _ambil_grid(
        "https://air-quality-api.open-meteo.com/v1/air-quality",
        {"hourly": "pm2_5", "domains": "cams_global"},
        bbox, langkah, nama_fixture)
    hasil = []
    for i, d in enumerate(daftar):
        h = d["hourly"]
        hasil.append({"lat": lats[i // len(lons)], "lon": lons[i % len(lons)],
                      "seri": [(t, v) for t, v in zip(h["time"], h["pm2_5"]) if v is not None]})
    return {"lats": lats, "lons": lons, "titik": hasil}


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
