"""Mengolah data mentah menjadi status per kota.

Status memakai empat tingkat: AMAN < WASPADA < SIAGA < BAHAYA.
Status kota = tingkat TERTINGGI dari tiga penilaian:
  1. prakiraan PM2.5 rata-rata 24 jam ke depan (kategori ISPU, Permen LHK 14/2020)
  2. jumlah titik panas (deteksi panas satelit) dalam radius kota selama 24 jam terakhir
  3. angka stasiun pemantau terdekat (kalau ada, skala AQI Amerika)
Ambang titik panas di bawah ini adalah AMBANG AWAL dan perlu disesuaikan
setelah dipakai beberapa minggu.
"""
import math
from datetime import datetime, timedelta, timezone

WIB = timezone(timedelta(hours=7))

TINGKAT = ["AMAN", "WASPADA", "SIAGA", "BAHAYA"]

# Batas PM2.5 (µg/m³, rata-rata 24 jam) per kategori ISPU
ISPU_BP = [(0, 15.5, 0, 50), (15.5, 55.4, 50, 100), (55.4, 150.4, 100, 200),
           (150.4, 250.4, 200, 300), (250.4, 500, 300, 500)]
ISPU_NAMA = ["Baik", "Sedang", "Tidak Sehat", "Sangat Tidak Sehat", "Berbahaya"]
ISPU_KE_TINGKAT = [0, 1, 2, 3, 3]

# Titik panas dalam radius kota, 24 jam terakhir -> tingkat (ambang awal)
AMBANG_TITIK_API = [(0, 0), (10, 1), (50, 2), (200, 3)]

# AQI Amerika (WAQI) -> tingkat
AMBANG_AQI = [(0, 0), (101, 1), (151, 2), (201, 3)]

SEL_DEDUP = 0.01  # derajat (~1 km): deteksi dari beberapa satelit di sel yang sama dihitung satu


def ispu(pm):
    if pm is None:
        return None
    if pm <= 0:
        return 0
    for lo, hi, ilo, ihi in ISPU_BP:
        if pm <= hi:
            return round(ilo + (pm - lo) * (ihi - ilo) / (hi - lo))
    return 500


def kategori_ispu(nilai):
    if nilai is None:
        return None
    for i, batas in enumerate([50, 100, 200, 300]):
        if nilai <= batas:
            return i
    return 4


def _tingkat_dari_ambang(nilai, ambang):
    t = 0
    for batas, tk in ambang:
        if nilai >= batas:
            t = tk
    return t


def jarak_km(lat1, lon1, lat2, lon2):
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


# ---------------------------------------------------------------- wilayah
def _di_ring(lon, lat, ring):
    dalam = False
    j = len(ring) - 1
    for i in range(len(ring)):
        xi, yi = ring[i]
        xj, yj = ring[j]
        if (yi > lat) != (yj > lat) and lon < (xj - xi) * (lat - yi) / (yj - yi + 1e-12) + xi:
            dalam = not dalam
        j = i
    return dalam


def di_wilayah(lon, lat, geom):
    polys = geom["coordinates"] if geom["type"] == "MultiPolygon" else [geom["coordinates"]]
    for poly in polys:
        if poly and _di_ring(lon, lat, poly[0]) and not any(_di_ring(lon, lat, h) for h in poly[1:]):
            return True
    return False


def bbox_wilayah(geom, tambah=0.6):
    polys = geom["coordinates"] if geom["type"] == "MultiPolygon" else [geom["coordinates"]]
    xs = [p[0] for poly in polys for p in poly[0]]
    ys = [p[1] for poly in polys for p in poly[0]]
    return (min(xs) - tambah, min(ys) - tambah, max(xs) + tambah, max(ys) + tambah)


# ---------------------------------------------------------------- titik panas
def saring_titik(titik, sekarang):
    """Buang keyakinan rendah, bagi ke 24 jam terakhir dan 24 jam sebelumnya, hapus duplikat."""
    batas1 = sekarang - timedelta(hours=24)
    batas2 = sekarang - timedelta(hours=48)
    baru, lama = {}, {}
    for t in titik:
        if t["keyakinan"] in ("l", "low"):
            continue
        sel = (round(t["lat"] / SEL_DEDUP), round(t["lon"] / SEL_DEDUP))
        if t["waktu"] >= batas1:
            if sel not in baru or t["frp"] > baru[sel]["frp"]:
                baru[sel] = t
        elif t["waktu"] >= batas2:
            if sel not in lama or t["frp"] > lama[sel]["frp"]:
                lama[sel] = t
    return list(baru.values()), list(lama.values())


# ---------------------------------------------------------------- prakiraan
def ringkas_prakiraan(seri, sekarang):
    """Rata-rata 24 jam ke depan, puncak, dan jam puncaknya (WIB)."""
    kini = sekarang.astimezone(WIB).strftime("%Y-%m-%dT%H")
    depan = [(t, v) for t, v in seri if t[:13] >= kini][:24]
    if not depan:
        return None
    rata = sum(v for _, v in depan) / len(depan)
    puncak_t, puncak_v = max(depan, key=lambda x: x[1])
    return {"rata24": rata, "puncak": puncak_v, "jam_puncak": puncak_t, "jumlah_jam": len(depan)}


# ---------------------------------------------------------------- angin dan asap (grid)
ARAH = ["utara", "timur laut", "timur", "tenggara", "selatan", "barat daya", "barat", "barat laut"]


def nama_arah(derajat):
    """0 = utara, 90 = timur (searah jarum jam)."""
    return ARAH[int(((derajat % 360) + 22.5) // 45) % 8]


def _jam_depan(waktu, sekarang, jam):
    kini = sekarang.astimezone(WIB).strftime("%Y-%m-%dT%H")
    return [i for i, t in enumerate(waktu) if t[:13] >= kini][:jam]


def ringkas_angin(grid, sekarang, jam=12):
    """Rata-rata vektor angin untuk `jam` ke depan.

    Open-Meteo memberi arah DATANG angin. Asap terbawa ke arah sebaliknya, jadi
    vektor (u, v) di sini menunjuk ke arah PERGI angin: u ke timur, v ke utara (km/jam).
    """
    if not grid:
        return None
    titik, us, vs, laju_skalar = [], [], [], []
    for p in grid["titik"]:
        idx = [i for i in _jam_depan(p["waktu"], sekarang, jam)
               if p["laju"][i] is not None and p["arah"][i] is not None]
        if not idx:
            continue
        u = sum(-p["laju"][i] * math.sin(math.radians(p["arah"][i])) for i in idx) / len(idx)
        v = sum(-p["laju"][i] * math.cos(math.radians(p["arah"][i])) for i in idx) / len(idx)
        titik.append({"lat": p["lat"], "lon": p["lon"], "u": u, "v": v})
        us.append(u)
        vs.append(v)
        laju_skalar.append(sum(p["laju"][i] for i in idx) / len(idx))
    if not titik:
        return None
    u, v = sum(us) / len(us), sum(vs) / len(vs)
    laju = math.hypot(u, v)
    rata_skalar = sum(laju_skalar) / len(laju_skalar)
    return {
        "titik": titik, "jam": jam,
        "u": u, "v": v, "laju": rata_skalar,
        "arah_ke": math.degrees(math.atan2(u, v)) % 360,
        # angin lemah atau arahnya saling meniadakan -> asap cenderung diam/berputar
        "lemah": rata_skalar < 4,
        "berubah": laju < 0.5 * rata_skalar,
    }


def ringkas_asap_grid(grid, sekarang):
    """PM2.5 rata-rata 24 jam ke depan di tiap titik grid -> matriks [baris lintang][kolom bujur]."""
    if not grid:
        return None
    nilai = []
    for p in grid["titik"]:
        r = ringkas_prakiraan(p["seri"], sekarang)
        nilai.append(r["rata24"] if r else None)
    if all(x is None for x in nilai):
        return None
    n = len(grid["lons"])
    return {"lats": grid["lats"], "lons": grid["lons"],
            "pm": [nilai[i:i + n] for i in range(0, len(nilai), n)]}


RADIUS_KLASTER_KM = 30


def klaster_titik(titik, minimal=15, maks=2, radius_km=RADIUS_KLASTER_KM, sel=0.1):
    """Pusat-pusat titik panas terpadat untuk diberi label di peta.

    Untuk tiap sel ~11 km dihitung jumlah titik panas dalam radius `radius_km`.
    Sel terpadat dipilih, lalu sekitarnya (1,8x radius) disingkirkan supaya label tidak
    menumpuk, dan diulang. Mengembalikan list dict: lat, lon (titik berat), n.
    """
    sel_isi = {}
    for t in titik:
        sel_isi.setdefault((math.floor(t["lat"] / sel), math.floor(t["lon"] / sel)), []).append(t)
    r = radius_km / 111.0
    jangkau = int(math.ceil(r / sel))

    def sekitar(c):
        hasil = []
        for di in range(-jangkau, jangkau + 1):
            for dj in range(-jangkau, jangkau + 1):
                hasil.extend(sel_isi.get((c[0] + di, c[1] + dj), []))
        pusat_lat, pusat_lon = (c[0] + 0.5) * sel, (c[1] + 0.5) * sel
        return [t for t in hasil if jarak_km(pusat_lat, pusat_lon, t["lat"], t["lon"]) <= radius_km]

    hitung = {c: len(sekitar(c)) for c in sel_isi}
    klaster = []
    for c in sorted(hitung, key=lambda c: -hitung[c]):
        # klaster kedua dst. hanya diberi label kalau cukup besar dibanding yang terbesar
        batas = max(minimal, 0.3 * klaster[0]["n"]) if klaster else minimal
        if len(klaster) >= maks or hitung[c] < batas:
            break
        lat, lon = (c[0] + 0.5) * sel, (c[1] + 0.5) * sel
        if any(jarak_km(lat, lon, k["lat"], k["lon"]) < 1.8 * radius_km for k in klaster):
            continue
        anggota = sekitar(c)
        klaster.append({"lat": sum(a["lat"] for a in anggota) / len(anggota),
                        "lon": sum(a["lon"] for a in anggota) / len(anggota), "n": len(anggota)})
    return klaster


# ---------------------------------------------------------------- status
def nilai_kota(kota, titik_baru, titik_lama, prakiraan, stasiun, radius_km, sekarang):
    n_baru = sum(1 for t in titik_baru if jarak_km(kota["lat"], kota["lon"], t["lat"], t["lon"]) <= radius_km)
    n_lama = sum(1 for t in titik_lama if jarak_km(kota["lat"], kota["lon"], t["lat"], t["lon"]) <= radius_km)

    alasan = []
    t_api = _tingkat_dari_ambang(n_baru, AMBANG_TITIK_API)
    if t_api:
        alasan.append(f"{n_baru} titik panas dalam {radius_km} km")

    t_prak, ispu_prak = 0, None
    if prakiraan:
        ispu_prak = ispu(prakiraan["rata24"])
        t_prak = ISPU_KE_TINGKAT[kategori_ispu(ispu_prak)]
        if t_prak:
            alasan.append(f"prakiraan asap {ISPU_NAMA[kategori_ispu(ispu_prak)].lower()}")

    t_st = 0
    st = None
    if stasiun and stasiun.get("lat") is not None:
        jarak = jarak_km(kota["lat"], kota["lon"], stasiun["lat"], stasiun["lon"])
        segar = True
        if stasiun.get("waktu_iso"):
            try:
                segar = (sekarang - datetime.fromisoformat(stasiun["waktu_iso"])).total_seconds() < 6 * 3600
            except ValueError:
                segar = False
        if jarak <= 30 and segar:
            st = dict(stasiun, jarak_km=jarak)
            t_st = _tingkat_dari_ambang(stasiun["aqi"], AMBANG_AQI)
            if t_st:
                alasan.append(f"stasiun {stasiun['nama']} AQI {stasiun['aqi']}")

    tingkat = max(t_api, t_prak, t_st)
    return {
        "nama": kota["nama"], "lat": kota["lat"], "lon": kota["lon"],
        "tingkat": tingkat, "titik_24j": n_baru, "titik_24j_sebelumnya": n_lama,
        "prakiraan": prakiraan, "ispu_prakiraan": ispu_prak, "stasiun": st,
        "alasan": alasan,
        # tanpa prakiraan dan tanpa stasiun, status hanya dari titik panas -> jangan ditampilkan sebagai "aman"
        "data_kurang": prakiraan is None and st is None,
    }


def nilai_provinsi(prov, geom, titik, prakiraan_per_kota, stasiun_per_kota, radius_km, sekarang):
    baru, lama = saring_titik(titik, sekarang)
    baru_prov = [t for t in baru if di_wilayah(t["lon"], t["lat"], geom)]
    lama_prov = [t for t in lama if di_wilayah(t["lon"], t["lat"], geom)]
    kota = [nilai_kota(k, baru, lama, prakiraan_per_kota.get(k["nama"]), stasiun_per_kota.get(k["nama"]),
                       radius_km, sekarang) for k in prov["kota"]]
    kota.sort(key=lambda k: (-k["tingkat"], -k["titik_24j"]))
    return {
        "id": prov["id"], "nama": prov["nama"],
        "waktu": sekarang,
        "titik_prov_24j": len(baru_prov), "titik_prov_24j_sebelumnya": len(lama_prov),
        "titik_peta": baru,  # termasuk sekitar perbatasan, untuk gambar
        "kota": kota,
        "tingkat": max((k["tingkat"] for k in kota), default=0),
        # pusat titik panas terpadat; radius sama dengan radius kota supaya angkanya sebanding
        "klaster": klaster_titik(baru, radius_km=radius_km),
        "radius_km": radius_km,
    }


def arah_ke(lat1, lon1, lat2, lon2):
    """Arah (derajat dari utara, searah jarum jam) dari titik 1 ke titik 2."""
    dx = (lon2 - lon1) * math.cos(math.radians((lat1 + lat2) / 2))
    return math.degrees(math.atan2(dx, lat2 - lat1)) % 360


def kota_searah_angin(hasil, angin, sudut=35, jarak_maks=250):
    """Kota pantauan terdekat yang berada searah angin dari pusat titik panas terbesar."""
    if not angin or angin["lemah"] or angin["berubah"] or not hasil.get("klaster"):
        return None
    c = hasil["klaster"][0]
    calon = []
    for k in hasil["kota"]:
        d = jarak_km(c["lat"], c["lon"], k["lat"], k["lon"])
        if d < 20 or d > jarak_maks:
            continue
        beda = abs((arah_ke(c["lat"], c["lon"], k["lat"], k["lon"]) - angin["arah_ke"] + 180) % 360 - 180)
        if beda <= sudut:
            calon.append((d, k["nama"]))
    return min(calon)[1] if calon else None
