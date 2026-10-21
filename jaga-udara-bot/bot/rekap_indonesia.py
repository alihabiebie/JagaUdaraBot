"""Rekap titik panas NASA FIRMS untuk seluruh Indonesia, per provinsi dan per pulau.

Dipakai untuk memutuskan provinsi mana yang perlu kanal Telegram baru.
Jalankan lewat tombol Run di GitHub Actions dengan mode "rekap-indonesia"
(kunci FIRMS hanya ada di sana), atau di komputer sendiri:

    FIRMS_MAP_KEY=... python -m bot.rekap_indonesia --hari 7

Hasil: laporan/rekap-indonesia/<tanggal>.md, .json, dan .png
"""
import argparse
import json
import os
from datetime import datetime, timedelta, timezone

from . import analisis, sumber

AKAR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BBOX_INDONESIA = (94.5, -11.5, 141.5, 6.5)
FRP_BESAR = 20  # MW, sama dengan kelas "api besar" di kartu

# Batas 34/38 provinsi tidak disimpan di repo (besar); diunduh saat dijalankan.
SUMBER_BATAS = [
    "https://github.com/wmgeolab/geoBoundaries/raw/main/releaseData/gbOpen/IDN/ADM1/"
    "geoBoundaries-IDN-ADM1_simplified.geojson",
    "https://raw.githubusercontent.com/superpikar/indonesia-geojson/master/indonesia-province-simple.json",
]
KUNCI_NAMA = ("shapeName", "Propinsi", "PROVINSI", "provinsi", "NAME_1", "name", "nama")

PULAU = [  # (kata kunci nama provinsi, pulau)
    (("aceh", "sumatera", "sumatra", "riau", "jambi", "bengkulu", "lampung", "bangka"), "Sumatra"),
    (("kalimantan",), "Kalimantan"),
    (("jakarta", "jawa", "java", "banten", "yogyakarta"), "Jawa"),
    (("bali", "nusa tenggara", "nusatenggara"), "Bali & Nusa Tenggara"),
    (("sulawesi", "gorontalo"), "Sulawesi"),
    (("maluku",), "Maluku"),
    (("papua", "irian"), "Papua"),
]


def nama_pulau(provinsi):
    n = provinsi.lower()
    if "kepulauan riau" in n or n in ("kepri", "riau islands"):
        return "Sumatra"
    for kunci, pulau in PULAU:
        if any(k in n for k in kunci):
            return pulau
    return "Lainnya"


ARAH_INGGRIS = {"central": "Tengah", "west": "Barat", "east": "Timur", "south": "Selatan", "north": "Utara",
                "southeast": "Tenggara", "southwest": "Barat Daya", "northeast": "Timur Laut", "highland": "Pegunungan"}
NAMA_KHUSUS = {"riau islands": "Kepulauan Riau", "bangka belitung islands": "Kepulauan Bangka Belitung",
               "special region of yogyakarta": "DI Yogyakarta", "jakarta special capital region": "DKI Jakarta",
               "north sumatra": "Sumatera Utara", "west sumatra": "Sumatera Barat", "south sumatra": "Sumatera Selatan",
               "west java": "Jawa Barat", "central java": "Jawa Tengah", "east java": "Jawa Timur"}


def indonesiakan(nama):
    """'Central Kalimantan' -> 'Kalimantan Tengah'; 'KALIMANTAN TENGAH' -> 'Kalimantan Tengah'."""
    n = " ".join(nama.replace("_", " ").split())
    if n.lower() in NAMA_KHUSUS:
        return NAMA_KHUSUS[n.lower()]
    kata = n.split()
    if len(kata) >= 2 and kata[0].lower() in ARAH_INGGRIS:
        n = " ".join(kata[1:]) + " " + ARAH_INGGRIS[kata[0].lower()]
    if n.isupper() or n.islower():
        n = " ".join(w if w.upper() in ("DKI", "DI") else w.capitalize() for w in n.split())
    return n


def _nama_fitur(f):
    p = f.get("properties") or {}
    for k in KUNCI_NAMA:
        if p.get(k):
            return indonesiakan(str(p[k]).strip())
    return "Tanpa nama"


def ambil_batas():
    """Batas provinsi seluruh Indonesia: fixture (uji), lalu sumber daring berurutan."""
    teks = sumber._fixture("batas_indonesia.geojson")
    if teks is None:
        galat = []
        for url in SUMBER_BATAS:
            try:
                teks = sumber._get(url, timeout=90, tries=2)
                json.loads(teks)
                break
            except Exception as e:  # coba sumber berikutnya
                galat.append(f"{url}: {e}")
                teks = None
        if teks is None:
            raise sumber.GagalAmbil("batas provinsi tidak bisa diunduh: " + " | ".join(galat))
    fitur = json.loads(teks)["features"]
    hasil = []
    for f in fitur:
        g = f.get("geometry")
        if not g or g["type"] not in ("Polygon", "MultiPolygon"):
            continue
        hasil.append({"nama": _nama_fitur(f), "geom": g, "bbox": analisis.bbox_wilayah(g, tambah=0)})
    return hasil


def provinsi_titik(lon, lat, batas):
    for b in batas:
        x0, y0, x1, y1 = b["bbox"]
        if x0 <= lon <= x1 and y0 <= lat <= y1 and analisis.di_wilayah(lon, lat, b["geom"]):
            return b["nama"]
    return None


def saring(titik, sekarang, hari):
    """Buang keyakinan rendah dan luar rentang; deteksi beberapa satelit di sel ±1 km pada hari yang sama dihitung satu."""
    awal = sekarang - timedelta(days=hari)
    sel = {}
    for t in titik:
        if t["keyakinan"] in ("l", "low") or t["waktu"] < awal:
            continue
        k = (round(t["lat"] / analisis.SEL_DEDUP), round(t["lon"] / analisis.SEL_DEDUP), t["waktu"].date())
        if k not in sel or t["frp"] > sel[k]["frp"]:
            sel[k] = t
    return list(sel.values())


def rekap(titik, batas, sekarang, hari):
    batas24 = sekarang - timedelta(hours=24)
    prov = {}
    luar = 0
    for t in titik:
        n = provinsi_titik(t["lon"], t["lat"], batas)
        if n is None:
            luar += 1
            continue
        r = prov.setdefault(n, {"provinsi": n, "pulau": nama_pulau(n), "titik_24j": 0, "titik_periode": 0,
                                "api_besar_periode": 0, "frp_total": 0.0, "lokasi": []})
        r["titik_periode"] += 1
        r["frp_total"] += t["frp"]
        r["api_besar_periode"] += t["frp"] >= FRP_BESAR
        r["titik_24j"] += t["waktu"] >= batas24
        r["lokasi"].append((t["lon"], t["lat"]))
    for r in prov.values():
        r["rata_per_hari"] = round(r["titik_periode"] / hari, 1)
        # pusat terpadat (sel 0,5°) untuk tahu daerah mana di provinsi itu
        sel = {}
        for lon, lat in r.pop("lokasi"):
            k = (round(lon * 2) / 2, round(lat * 2) / 2)
            sel[k] = sel.get(k, 0) + 1
        r["pusat_terpadat"] = [{"lon": k[0], "lat": k[1], "titik": n}
                               for k, n in sorted(sel.items(), key=lambda x: -x[1])[:3]]
        r["frp_total"] = round(r["frp_total"], 1)
    urut = sorted(prov.values(), key=lambda r: (-r["titik_periode"], -r["titik_24j"]))
    pulau = {}
    for r in urut:
        p = pulau.setdefault(r["pulau"], {"pulau": r["pulau"], "titik_24j": 0, "titik_periode": 0, "api_besar_periode": 0})
        for k in ("titik_24j", "titik_periode", "api_besar_periode"):
            p[k] += r[k]
    return urut, sorted(pulau.values(), key=lambda p: -p["titik_periode"]), luar


def _n(x):
    return f"{x:,}".replace(",", ".")


def tulis_md(path, urut, pulau, luar, sekarang, hari, sumber_batas, aktif):
    wib = sekarang.astimezone(analisis.WIB)
    b = [f"# Rekap titik panas Indonesia, {hari} hari terakhir",
         "",
         f"Diambil {wib:%d %b %Y %H.%M} WIB dari NASA FIRMS (VIIRS S-NPP, NOAA-20, NOAA-21). "
         "Keyakinan rendah dibuang; deteksi beberapa satelit di titik ±1 km pada hari yang sama dihitung satu. "
         f"Api besar = FRP ≥ {FRP_BESAR} MW. Batas provinsi: {sumber_batas}.",
         "",
         "## Per pulau", "",
         f"| Pulau | Titik {hari} hari | Titik 24 jam | Api besar |", "|---|---:|---:|---:|"]
    b += [f"| {p['pulau']} | {_n(p['titik_periode'])} | {_n(p['titik_24j'])} | {_n(p['api_besar_periode'])} |"
          for p in pulau]
    b += ["", "## Per provinsi", "",
          "Kanal: ✅ sudah ada kanal aktif, ○ belum.", "",
          f"| # | Provinsi | Pulau | Titik {hari} hari | Rata-rata/hari | Titik 24 jam | Api besar | Pusat terpadat (lintang, bujur: jumlah) | Kanal |",
          "|---:|---|---|---:|---:|---:|---:|---|:-:|"]
    for i, r in enumerate(urut, 1):
        pusat = "; ".join(f"{c['lat']:.1f}, {c['lon']:.1f}: {c['titik']}" for c in r["pusat_terpadat"])
        kanal = "✅" if any(a in r["provinsi"].lower() for a in aktif) else "○"
        b.append(f"| {i} | {r['provinsi']} | {r['pulau']} | {_n(r['titik_periode'])} | {r['rata_per_hari']} | "
                 f"{_n(r['titik_24j'])} | {_n(r['api_besar_periode'])} | {pusat} | {kanal} |")
    b += ["", f"Titik di luar daratan provinsi Indonesia (laut, Malaysia, Timor Leste, PNG): {_n(luar)}.",
          "", "Catatan: titik panas belum tentu kebakaran. Gambut membara bisa tampak sebagai api kecil tetapi asapnya pekat; "
          "kebakaran sabana (mis. Nusa Tenggara) bisa banyak titik tetapi asapnya cepat hilang."]
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(b) + "\n")


def gambar(path, titik, batas, urut, hari, sekarang):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np
    from matplotlib.patches import Polygon

    from . import kartu  # mendaftarkan huruf Inter dan kelas kekuatan api

    fig = plt.figure(figsize=(16, 11), dpi=100, facecolor=kartu.BG)
    ax = fig.add_axes([0.02, 0.36, 0.96, 0.56])
    ax.set_facecolor("#DCE8F6")
    for b in batas:
        g = b["geom"]
        for poly in (g["coordinates"] if g["type"] == "MultiPolygon" else [g["coordinates"]]):
            ax.add_patch(Polygon(poly[0], closed=True, fc=kartu.LAND, ec=kartu.GARIS, lw=0.5))
    if titik:
        xy = np.array([(t["lon"], t["lat"]) for t in titik])
        frp = np.array([t["frp"] for t in titik])
        for i, (bawah, nama, warna, ukuran) in enumerate(kartu.KELAS_API):
            atas = kartu.KELAS_API[i + 1][0] if i + 1 < len(kartu.KELAS_API) else np.inf
            m = (frp >= bawah) & (frp < atas)
            ax.scatter(xy[m, 0], xy[m, 1], s=ukuran / 3, c=warna, alpha=0.85, linewidths=0, zorder=3 + i,
                       label=f"{nama} ({int(m.sum()):,})".replace(",", "."))
        ax.legend(loc="lower left", fontsize=12, framealpha=0.9, markerscale=2)
    ax.set_xlim(BBOX_INDONESIA[0], BBOX_INDONESIA[2])
    ax.set_ylim(BBOX_INDONESIA[1], BBOX_INDONESIA[3])
    ax.set_aspect("equal")
    ax.set_xticks([])
    ax.set_yticks([])
    wib = sekarang.astimezone(analisis.WIB)
    fig.text(0.02, 0.965, f"Titik panas Indonesia, {hari} hari terakhir (NASA FIRMS VIIRS)", fontsize=24,
             weight="bold", color=kartu.INK)
    fig.text(0.02, 0.935, f"s.d. {wib:%d %b %Y %H.%M} WIB · {len(titik):,} titik".replace(",", "."), fontsize=15,
             color=kartu.MUTED)

    bx = fig.add_axes([0.25, 0.04, 0.70, 0.28])
    atas = urut[:15][::-1]
    bx.barh([r["provinsi"] for r in atas], [r["titik_periode"] for r in atas], color="#E0362C")
    bx.barh([r["provinsi"] for r in atas], [r["api_besar_periode"] for r in atas], color="#7A0A0A",
            label="di antaranya api besar")
    for i, r in enumerate(atas):
        bx.text(r["titik_periode"], i, f"  {r['titik_periode']:,}".replace(",", "."), va="center", fontsize=11)
    bx.set_title(f"15 provinsi dengan titik panas terbanyak ({hari} hari)", fontsize=15, loc="left", color=kartu.INK)
    bx.legend(loc="lower right", fontsize=11)
    for s in ("top", "right"):
        bx.spines[s].set_visible(False)
    bx.tick_params(labelsize=11)
    fig.savefig(path, facecolor=kartu.BG)
    plt.close(fig)


def jalankan(hari=7, sekarang=None):
    sekarang = sekarang or datetime.now(timezone.utc)
    if os.environ.get("WAKTU_UJI"):
        sekarang = datetime.fromisoformat(os.environ["WAKTU_UJI"])
    batas = ambil_batas()
    sumber_batas = "data uji" if os.environ.get("FIXTURES") else "geoBoundaries / superpikar (diunduh saat dijalankan)"
    titik = saring(sumber.titik_api(BBOX_INDONESIA, os.environ.get("FIRMS_MAP_KEY", ""), hari=hari), sekarang, hari)
    urut, pulau, luar = rekap(titik, batas, sekarang, hari)

    cfg = json.load(open(os.path.join(AKAR, "config", "provinsi.json"), encoding="utf-8"))
    aktif = [p["nama"].lower() for p in cfg.get("provinsi", []) if p.get("aktif")]

    folder = os.path.join(os.environ.get("LAPORAN_DIR") or os.path.join(AKAR, "laporan"), "rekap-indonesia")
    os.makedirs(folder, exist_ok=True)
    dasar = os.path.join(folder, f"{sekarang.astimezone(analisis.WIB):%Y-%m-%d-%H%M}")
    tulis_md(dasar + ".md", urut, pulau, luar, sekarang, hari, sumber_batas, aktif)
    with open(dasar + ".json", "w", encoding="utf-8") as fh:
        json.dump({"waktu": sekarang.isoformat(), "hari": hari, "provinsi": urut, "pulau": pulau,
                   "di_luar_provinsi": luar}, fh, ensure_ascii=False, indent=1)
    gambar(dasar + ".png", titik, batas, urut, hari, sekarang)
    print(f"Rekap Indonesia {hari} hari: {len(titik)} titik, {len(urut)} provinsi -> {os.path.relpath(dasar, AKAR)}")
    for r in urut[:20]:
        print(f"  {r['provinsi']:<28} {r['pulau']:<20} {r['titik_periode']:>6} titik, 24 jam {r['titik_24j']:>5}, "
              f"api besar {r['api_besar_periode']}")
    return dasar


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--hari", type=int, default=7, help="rentang hari ke belakang (1-10, batas API FIRMS)")
    a = ap.parse_args()
    jalankan(max(1, min(10, a.hari)))


if __name__ == "__main__":
    main()
