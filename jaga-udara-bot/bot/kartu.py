"""Membuat gambar kartu harian (PNG 1080 x 1650) untuk Telegram dan WhatsApp.

Isi kartu, dari atas ke bawah:
  1. Judul, tanggal, dan pita status provinsi berisi kalimat utama + yang perlu dilakukan
  2. Peta: titik panas (kepadatan), prakiraan asap (bayangan coklat-abu), arah angin (panah),
     kota berwarna sesuai status, label pusat titik panas, skala km, dan kotak arah asap
  3. Keterangan peta
  4. Daftar kota dengan status, perubahan sejak kabar sebelumnya, dan angka pendukung
Ukuran huruf dipilih supaya tetap terbaca di layar HP (kartu tampil ±0,36x) setelah
dikompres WhatsApp. Huruf terkecil 14 pt (±19 px).
"""
import math
import os

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from matplotlib import patheffects as pe  # noqa: E402
from matplotlib.colors import LinearSegmentedColormap  # noqa: E402
from matplotlib.font_manager import FontProperties  # noqa: E402
from matplotlib.patches import Circle, FancyArrow, FancyBboxPatch, Polygon, Rectangle, RegularPolygon  # noqa: E402

from .analisis import ISPU_NAMA, TINGKAT, bbox_wilayah, kategori_ispu, klaster_titik, nama_arah  # noqa: E402
from .pesan import TINDAKAN_SINGKAT, angka, kalimat_angin, kalimat_status, tanggal  # noqa: E402

LEBAR, TINGGI = 1080, 1650
KIRI, KANAN = 54, 1026

# Warna status: biru - kuning - oranye - merah tua. Tidak memakai pasangan hijau-merah
# supaya tetap bisa dibedakan oleh penderita buta warna; status juga selalu ditulis dengan kata.
WARNA = ["#2F6FB0", "#F2B705", "#E8710A", "#B3261E"]
TEKS_DI_WARNA = ["white", "#1B1B1B", "white", "white"]
ABU_DATA = "#7F8B88"

INK, MUTED, BG = "#14201F", "#45544F", "#FBFCFA"
LAUT, DARAT_LAIN, DARAT, GARIS_LAIN = "#D6E5F0", "#ECEFEC", "#F7F3EA", "#B4C0BC"
PANEL = "#EEF2F0"
ANGIN = "#1D3557"

# kepadatan titik panas: kuning muda -> merah tua
API = LinearSegmentedColormap.from_list("api", ["#FFD27A", "#F28C28", "#C1121F", "#6A040F"])
# prakiraan asap (PM2.5 rata-rata 24 jam): hanya kategori ISPU tidak sehat ke atas
ASAP_BATAS = [55.4, 150.4, 250.4, 1e6]
ASAP_WARNA = ["#CDBFAA", "#A8977F", "#7A6A55"]
ASAP_ALPHA = 0.78
ASAP_LABEL = ["tidak sehat", "sangat tidak sehat", "berbahaya"]

# tata letak (piksel dari atas)
PITA_ATAS, PITA_BAWAH = 168, 404
PETA_ATAS, PETA_BAWAH = 424, 1034
KET_ATAS, KET_BAWAH = 1048, 1176
DAFTAR_ATAS = 1206
RASIO_PETA = (KANAN - KIRI) / (PETA_BAWAH - PETA_ATAS)
BADGE_W, BADGE_H = 300, 160


# ---------------------------------------------------------------- bantu
def batas_peta(geom):
    """Batas peta (barat, selatan, timur, utara) yang pas dengan kotak peta di kartu.

    Dipakai juga oleh main.py untuk menentukan grid angin dan asap yang diambil.
    """
    x0, y0, x1, y1 = bbox_wilayah(geom, tambah=0.3)
    w, h = x1 - x0, y1 - y0
    if w / h < RASIO_PETA:
        tambah = (h * RASIO_PETA - w) / 2
        x0, x1 = x0 - tambah, x1 + tambah
    else:
        tambah = (w / RASIO_PETA - h) / 2
        y0, y1 = y0 - tambah, y1 + tambah
    return x0, y0, x1, y1


def _poligon(ax, geom, **kw):
    polys = geom["coordinates"] if geom["type"] == "MultiPolygon" else [geom["coordinates"]]
    for poly in polys:
        ax.add_patch(Polygon(poly[0], closed=True, **kw))


def _lebar_px(kv, teks, pt, tebal="normal"):
    r = kv.figure.canvas.get_renderer()
    return r.get_text_width_height_descent(teks, FontProperties(size=pt, weight=tebal), ismath=False)[0]


def _bungkus(kv, teks, pt, tebal, lebar_px):
    """Pecah teks menjadi beberapa baris berdasarkan lebar sebenarnya (piksel) di kartu."""
    baris, kini = [], ""
    for kata in teks.split():
        coba = (kini + " " + kata).strip()
        if kini and _lebar_px(kv, coba, pt, tebal) > lebar_px:
            baris.append(kini)
            kini = kata
        else:
            kini = coba
    if kini:
        baris.append(kini)
    return "\n".join(baris)


def _pas(kv, teks, pt, tebal, lebar_px, minimal):
    """Ukuran huruf terbesar (<= pt) yang membuat teks muat dalam lebar_px."""
    while pt > minimal and _lebar_px(kv, teks, pt, tebal) > lebar_px:
        pt -= 0.5
    return pt


def _perbesar(lats, lons, z, kali=6):
    """Haluskan grid kasar (interpolasi bilinear) supaya bayangan asap tidak kotak-kotak."""
    lats, lons = np.asarray(lats, float), np.asarray(lons, float)
    lat_b = np.linspace(lats[0], lats[-1], (len(lats) - 1) * kali + 1)
    lon_b = np.linspace(lons[0], lons[-1], (len(lons) - 1) * kali + 1)
    antara = np.array([np.interp(lon_b, lons, baris) for baris in z])
    halus = np.array([np.interp(lat_b, lats, antara[:, j]) for j in range(antara.shape[1])]).T
    return lat_b, lon_b, halus


class _Penempat:
    """Penempatan label sederhana: coba beberapa posisi, pilih yang tidak bertabrakan."""

    def __init__(self, kv, x0, y0, x1, y1):
        self.kv = kv
        self.batas = (x0, y0, x1, y1)
        self.dpx = (x1 - x0) / (KANAN - KIRI)  # derajat per piksel (sumbu x dan y sama)
        self.kotak = []
        # pusat sel titik panas: informasi utama peta, tidak boleh tertutup label/panah/kotak
        self.api = np.empty((0, 2))
        self.r_api = 0.0

    def kena_api(self, k):
        """Jumlah sel titik panas yang tertutup kotak k (barat, selatan, timur, utara)."""
        if not len(self.api):
            return 0
        r = self.r_api
        x, y = self.api[:, 0], self.api[:, 1]
        return int(((x > k[0] - r) & (x < k[2] + r) & (y > k[1] - r) & (y < k[3] + r)).sum())

    def api_dekat_garis(self, xa, ya, xb, yb, tambah):
        """Apakah ada sel titik panas dalam jarak (r_api + tambah) dari ruas garis a-b."""
        if not len(self.api):
            return False
        dx, dy = xb - xa, yb - ya
        L2 = dx * dx + dy * dy or 1e-12
        t = np.clip(((self.api[:, 0] - xa) * dx + (self.api[:, 1] - ya) * dy) / L2, 0, 1)
        jx, jy = xa + t * dx - self.api[:, 0], ya + t * dy - self.api[:, 1]
        return bool((np.hypot(jx, jy) < self.r_api + tambah).any())

    def ukuran(self, teks, pt, tebal="bold"):
        return (_lebar_px(self.kv, teks, pt, tebal) + 16) * self.dpx, (pt * 100 / 72 * 1.5) * self.dpx

    def bebas(self, k):
        x0, y0, x1, y1 = self.batas
        if k[0] < x0 or k[2] > x1 or k[1] < y0 or k[3] > y1:
            return False
        return not any(k[0] < b[2] and k[2] > b[0] and k[1] < b[3] and k[3] > b[1] for b in self.kotak)

    def tambah(self, k):
        self.kotak.append(k)

    def dekat(self, x, y, jarak):
        return any(b[0] - jarak < x < b[2] + jarak and b[1] - jarak < y < b[3] + jarak for b in self.kotak)

    def tempatkan(self, x, y, teks, pt, jarak_px=18):
        """Kembalikan (x_teks, y_teks, ha) untuk label di sekitar titik (x, y)."""
        w, h = self.ukuran(teks, pt)
        calon = []
        # dekat dulu, lalu makin jauh kalau posisi dekat menutup titik panas
        for jarak in (jarak_px, jarak_px * 2.2, jarak_px * 3.6):
            d = jarak * self.dpx
            calon += [(x + d, y + d * 0.3, "left"), (x - d, y + d * 0.3, "right"),
                      (x + d, y - d * 0.3 - h, "left"), (x - d, y - d * 0.3 - h, "right"),
                      (x, y + d * 1.3, "center"), (x, y - d * 1.3 - h, "center")]
        terbaik = None
        for cx, cy, ha in calon:
            kx0 = cx if ha == "left" else cx - w if ha == "right" else cx - w / 2
            k = (kx0, cy, kx0 + w, cy + h)
            if self.bebas(k):
                n = self.kena_api(k)
                if terbaik is None or n < terbaik[0]:
                    terbaik = (n, cx, cy, ha, k)
                if n == 0:
                    break
        if terbaik:
            _, cx, cy, ha, k = terbaik
            self.tambah(k)
            return cx, cy + h / 2, ha
        cx, cy, ha = calon[0]
        self.tambah((cx, cy, cx + w, cy + h))
        return cx, cy + h / 2, ha


def _data_kurang(k):
    return bool(k.get("data_kurang")) and k["tingkat"] == 0


def _warna_kota(k):
    if _data_kurang(k):
        return ABU_DATA, "white"
    return WARNA[k["tingkat"]], TEKS_DI_WARNA[k["tingkat"]]


def _label_status(k):
    return "DATA KURANG" if _data_kurang(k) else TINGKAT[k["tingkat"]]


# ---------------------------------------------------------------- bagian-bagian kartu
def _kepala(kv, hasil):
    t = hasil["tingkat"]
    kv.text(KIRI, 44, "JAGA UDARA  ·  KABAR ASAP", fontsize=15, color=MUTED, weight="bold", va="center")
    kv.text(KIRI, 94, hasil["nama"], fontsize=34, color=INK, weight="bold", va="center")
    kv.text(KIRI, 142, tanggal(hasil["waktu"]), fontsize=18, color=MUTED, va="center")

    # pita status
    atas, bawah = PITA_ATAS, PITA_BAWAH
    warna, teks = WARNA[t], TEKS_DI_WARNA[t]
    kv.add_patch(FancyBboxPatch((KIRI, atas), KANAN - KIRI, bawah - atas,
                                boxstyle="round,pad=0,rounding_size=18", fc=warna, ec="none"))
    kv.text(KIRI + 26, atas + 36, "STATUS PROVINSI", fontsize=14, color=teks, weight="bold", va="center", alpha=0.9)
    kv.text(KIRI + 24, atas + 88, TINGKAT[t], fontsize=34, color=teks, weight="bold", va="center")
    n, n0 = hasil["titik_prov_24j"], hasil["titik_prov_24j_sebelumnya"]
    jml = f"{angka(n)} titik panas"
    kv.text(KIRI + 26, atas + 150, jml, fontsize=_pas(kv, jml, 19, "bold", 270, 15),
            color=teks, weight="bold", va="center")
    kv.text(KIRI + 26, atas + 184, "dalam 24 jam", fontsize=15, color=teks, va="center")
    kv.text(KIRI + 26, atas + 210, f"(kemarin {angka(n0)})", fontsize=15, color=teks, va="center")

    # garis pemisah dan kalimat utama
    x = KIRI + 330
    kv.plot([x - 24, x - 24], [atas + 24, bawah - 24], color=teks, alpha=0.35, lw=1.5)
    ka = kalimat_angin(hasil.get("angin"), hasil)
    if t == 0 and hasil["titik_prov_24j"] < 10 and ka and hasil["angin"]["lemah"]:
        ka = None  # tidak ada asap yang perlu dikabarkan arahnya
    if t == 0:
        aksi = "Yang perlu dilakukan: " + TINDAKAN_SINGKAT[0]
    else:
        aksi = f"Di kota berstatus {TINGKAT[t]}: " + TINDAKAN_SINGKAT[t]
    ruang = bawah - atas - 40
    for skala in (1.0, 0.95, 0.9, 0.85, 0.8):
        baris = [(kalimat_status(hasil), 19.5 * skala, "bold")]
        if ka:
            baris.append((ka, 17 * skala, "normal"))
        baris.append((aksi, 17 * skala, "bold"))
        susun = [(_bungkus(kv, isi, pt, tb, KANAN - 22 - x), pt, tb) for isi, pt, tb in baris]
        tinggi = sum((b.count("\n") + 1) * pt * 1.39 * 1.25 + 12 for b, pt, _ in susun) - 12
        if tinggi <= ruang:
            break
    y = atas + 20 + max(0, (ruang - tinggi) / 2)
    for isi, pt, tebal in susun:
        kv.text(x, y, isi, fontsize=pt, color=teks, weight=tebal, va="top", linespacing=1.25)
        y += (isi.count("\n") + 1) * pt * 1.39 * 1.25 + 12


def _tulis_asap(ax, pen, lo, la, zh, x0, y0, x1, y1):
    """Tulisan ASAP di bagian berasap tidak sehat yang masih kosong."""
    j, i = np.unravel_index(np.argmax(zh), zh.shape)
    w, h = pen.ukuran("ASAP", 14)
    for dy in (0, 0.5, -0.5, 1.0, -1.0):
        for dx in (0, 0.8, -0.8, 1.6, -1.6):
            cx, cy = lo[i] + dx, la[j] + dy
            if not (x0 < cx < x1 and y0 < cy < y1):
                continue
            if zh[np.abs(la - cy).argmin(), np.abs(lo - cx).argmin()] < ASAP_BATAS[0]:
                continue
            k = (cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2)
            if pen.bebas(k) and not pen.kena_api(k):
                pen.tambah(k)
                ax.text(cx, cy, "ASAP", fontsize=14, color="#4A3D2E", weight="bold", ha="center",
                        va="center", zorder=6, style="italic",
                        path_effects=[pe.withStroke(linewidth=3.5, foreground="white")])
                return


def _peta(fig, kv, hasil, geom_target, semua_fitur):
    x0, y0, x1, y1 = batas_peta(geom_target)
    ax = fig.add_axes([KIRI / LEBAR, 1 - PETA_BAWAH / TINGGI, (KANAN - KIRI) / LEBAR, (PETA_BAWAH - PETA_ATAS) / TINGGI])
    ax.set_facecolor(LAUT)
    for f in semua_fitur:
        _poligon(ax, f["geometry"], facecolor=DARAT_LAIN, edgecolor=GARIS_LAIN, linewidth=0.9, zorder=1)
    _poligon(ax, geom_target, facecolor=DARAT, edgecolor="none", zorder=1)

    pen = _Penempat(kv, x0, y0, x1, y1)

    # 1. prakiraan asap (di bawah titik panas)
    asap = hasil.get("asap_grid")
    ada_asap_buruk = False
    zh = None
    if asap:
        z = np.array([[np.nan if v is None else v for v in baris] for baris in asap["pm"]], float)
        if np.isfinite(z).any():
            z = np.where(np.isfinite(z), z, np.nanmin(z))
            la, lo, zh = _perbesar(asap["lats"], asap["lons"], z)
            if np.nanmax(zh) >= ASAP_BATAS[0]:
                ada_asap_buruk = True
                ax.contourf(lo, la, zh, levels=ASAP_BATAS, colors=ASAP_WARNA, alpha=ASAP_ALPHA, zorder=2)
                ax.contour(lo, la, zh, levels=[ASAP_BATAS[0]], colors=["#6B5B47"], linewidths=1.2,
                           linestyles="--", zorder=2.5)

    _poligon(ax, geom_target, facecolor="none", edgecolor=INK, linewidth=2.2, zorder=4)

    # 2. titik panas sebagai kepadatan (bukan ribuan titik yang terkesan sangat tepat)
    pts = hasil["titik_peta"]
    if pts:
        lebar_sel = 0.11  # derajat, sekitar 12 km
        nx = max(10, int((x1 - x0) / lebar_sel))
        ny = max(6, int((y1 - y0) / (lebar_sel * math.sqrt(3))))
        hb = ax.hexbin([p["lon"] for p in pts], [p["lat"] for p in pts], gridsize=(nx, ny),
                       extent=(x0, x1, y0, y1), mincnt=1, cmap=API, linewidths=0.3, zorder=3)
        c = hb.get_array()
        if len(c):
            hb.set_clim(1, max(4, float(np.percentile(c, 95))))
            hb.set_edgecolor("face")
            pen.api = np.asarray(hb.get_offsets(), float).reshape(-1, 2)
            pen.r_api = (x1 - x0) / nx * 0.55

    # Kotak arah asap, skala, dan tanda utara ditaruh di pojok yang paling sedikit titik panasnya
    # (dan tidak menutup kota). Urutan = pilihan utama kalau semua pojok sama-sama kosong.
    def _pojok(nama, w_px, h_px):
        w, h = w_px * pen.dpx, h_px * pen.dpx
        kx = x1 - w if nama[1] == "ka" else x0
        ky = y1 - h if nama[0] == "at" else y0
        return (kx, ky, kx + w, ky + h)

    def _skor_pojok(k):
        kota_tertutup = sum(k[0] < c["lon"] < k[2] and k[1] < c["lat"] < k[3] for c in hasil["kota"])
        return pen.kena_api(k) + 1000 * kota_tertutup

    pojok = {}
    sisa = [("at", "ka"), ("at", "ki"), ("ba", "ki"), ("ba", "ka")]
    for nama, w_px, h_px, urutan in (
            ("arah", BADGE_W + 26, BADGE_H + 26, [("at", "ka"), ("at", "ki"), ("ba", "ka"), ("ba", "ki")]),
            ("skala", 230, 70, [("ba", "ki"), ("ba", "ka"), ("at", "ki"), ("at", "ka")]),
            ("utara", 64, 100, [("at", "ki"), ("at", "ka"), ("ba", "ka"), ("ba", "ki")])):
        pilih = min((p for p in urutan if p in sisa), key=lambda p: _skor_pojok(_pojok(p, w_px, h_px)))
        sisa.remove(pilih)
        pojok[nama] = pilih
        pen.tambah(_pojok(pilih, w_px, h_px))
    for k in hasil["kota"]:
        r = 18 * pen.dpx
        pen.tambah((k["lon"] - r, k["lat"] - r, k["lon"] + r, k["lat"] + r))

    # 3. kota
    for k in hasil["kota"]:
        fc, tc = _warna_kota(k)
        ukuran = [170, 210, 260, 320][k["tingkat"]]
        r = 8 * pen.dpx
        if pen.kena_api((k["lon"] - r, k["lat"] - r, k["lon"] + r, k["lat"] + r)):
            # ada titik panas tepat di kota: cincin berwarna status, tengahnya kosong supaya titik panas terlihat
            ax.scatter([k["lon"]], [k["lat"]], s=ukuran + 60, facecolors="none", edgecolors=fc, linewidths=4.5,
                       zorder=8)
        else:
            ax.scatter([k["lon"]], [k["lat"]], s=ukuran, c=fc, edgecolors="white", linewidths=3, zorder=8)
        ax.scatter([k["lon"]], [k["lat"]], s=ukuran + 140, facecolors="none", edgecolors=INK, linewidths=1.1, zorder=7)
        tx, ty, ha = pen.tempatkan(k["lon"], k["lat"], k["nama"], 15)
        ax.text(tx, ty, k["nama"], ha=ha, va="center", fontsize=15, weight="bold", color=tc, zorder=9,
                bbox=dict(boxstyle="round,pad=0.28", fc=fc, ec="white", lw=2.2))

    # 4. label pusat titik panas
    klaster = hasil.get("klaster")
    if klaster is None:
        klaster = klaster_titik(pts, radius_km=hasil.get("radius_km", 50))
    garis = []  # garis penunjuk yang sudah digambar

    def _di_kotak(x, y, k):
        return k[0] < x < k[2] and k[1] < y < k[3]

    def _titik_garis(x0_, y0_, x1_, y1_):
        return [(x0_ + (x1_ - x0_) * i / 20, y0_ + (y1_ - y0_) * i / 20) for i in range(21)]

    def _garis_rapi(x, y, tx, ty, k):
        # garis baru tidak menembus label lain, dan label baru tidak menutup garis lama
        if any(_di_kotak(px, py, b) for px, py in _titik_garis(x, y, tx, ty) for b in pen.kotak):
            return False
        return not any(_di_kotak(px, py, k) for g in garis for px, py in _titik_garis(*g))

    calon = ((0, -0.4), (0, 0.4), (0.8, -0.4), (-0.8, -0.4), (0.8, 0.4), (-0.8, 0.4), (0, -0.75), (0, 0.75),
             (1.2, 0), (-1.2, 0), (1.2, -0.75), (-1.2, -0.75), (1.2, 0.75), (-1.2, 0.75), (0, -1.1), (0, 1.1))
    for kl in klaster:
        teks = f"±{angka(kl['n'])} titik panas"
        w, h = pen.ukuran(teks, 14)
        posisi = []
        for dx, dy in calon:
            tx, ty = kl["lon"] + dx, kl["lat"] + dy
            k = (tx - w / 2, ty - h / 2, tx + w / 2, ty + h / 2)
            if pen.bebas(k):
                posisi.append((pen.kena_api(k), not _garis_rapi(kl["lon"], kl["lat"], tx, ty, k), len(posisi),
                               tx, ty, k))
        if not posisi:
            continue
        # utamakan posisi yang tidak menutup titik panas, lalu yang garisnya rapi, lalu yang paling dekat
        *_, tx, ty, k = min(posisi)
        pen.tambah(k)
        # garis penunjuk di bawah semua label, supaya tidak menembus label pusat lain
        ax.plot([kl["lon"], tx], [kl["lat"], ty], color="#7A0F0F", lw=1.4, zorder=5.8)
        ax.text(tx, ty, teks, ha="center", va="center", fontsize=14, weight="bold", color="#7A0F0F",
                zorder=6.6, bbox=dict(boxstyle="round,pad=0.25", fc="white", ec="#C1121F", lw=1.2, alpha=0.95))
        # lingkaran kosong supaya sel titik panas di bawahnya tetap terlihat
        ax.scatter([kl["lon"]], [kl["lat"]], s=90, facecolors="none", edgecolors="#7A0F0F", linewidths=2.2,
                   zorder=6.5)
        garis.append((kl["lon"], kl["lat"], tx, ty))

    if ada_asap_buruk:
        _tulis_asap(ax, pen, lo, la, zh, x0, y0, x1, y1)

    # 5. panah angin: menunjuk ke arah asap terbawa. Tidak digambar di atas label.
    angin = hasil.get("angin")
    ada_panah = False
    if angin and not angin["lemah"]:
        xs, ys, us, vs = [], [], [], []
        for p in angin["titik"]:
            if not (x0 + 0.25 < p["lon"] < x1 - 0.25 and y0 + 0.25 < p["lat"] < y1 - 0.25):
                continue
            if pen.dekat(p["lon"], p["lat"], 0.3):
                continue
            laju = math.hypot(p["u"], p["v"])
            if laju < 1:
                continue
            panjang = 0.26 + 0.28 * min(laju / 20, 1)  # derajat
            ux, vy = p["u"] / laju * panjang / 2, p["v"] / laju * panjang / 2
            if pen.api_dekat_garis(p["lon"] - ux, p["lat"] - vy, p["lon"] + ux, p["lat"] + vy, 0.08):
                continue  # panah tidak boleh menutup titik panas
            xs.append(p["lon"])
            ys.append(p["lat"])
            us.append(p["u"] / laju * panjang)
            vs.append(p["v"] / laju * panjang)
        if xs:
            ada_panah = True
            ax.quiver(xs, ys, us, vs, angles="xy", scale_units="xy", scale=1, color=ANGIN,
                      width=0.0058, headwidth=3.6, headlength=3.8, headaxislength=3.4,
                      edgecolor="white", linewidth=1.1, zorder=5, pivot="middle")

    # 6. skala km dan arah utara
    bx0, by0, _, _ = _pojok(pojok["skala"], 230, 70)
    lat_skala = by0 + 35 * pen.dpx
    km_per_derajat = 111.32 * math.cos(math.radians(lat_skala))
    panjang_km = 100
    sx = bx0 + 22 * pen.dpx
    lebar_skala = panjang_km / km_per_derajat
    ax.add_patch(Rectangle((bx0, by0), 230 * pen.dpx, 70 * pen.dpx, fc="white", ec="none", alpha=0.85, zorder=9))
    ax.plot([sx, sx + lebar_skala], [lat_skala, lat_skala], color=INK, lw=5, solid_capstyle="butt", zorder=10)
    ax.text(sx + lebar_skala + 10 * pen.dpx, lat_skala, f"{panjang_km} km", fontsize=14, color=INK, va="center",
            weight="bold", zorder=10)
    nx0, _, _, ny1 = _pojok(pojok["utara"], 64, 100)
    ux, uy = nx0 + 34 * pen.dpx, ny1 - 70 * pen.dpx
    ax.annotate("U", xy=(ux, uy + 44 * pen.dpx), xytext=(ux, uy), ha="center", va="center", fontsize=15,
                weight="bold", color=INK, zorder=10,
                arrowprops=dict(arrowstyle="-|>", color=INK, lw=2.2),
                path_effects=[pe.withStroke(linewidth=3, foreground="white")])

    ax.set_xlim(x0, x1)
    ax.set_ylim(y0, y1)
    ax.set_aspect("equal", adjustable="box")
    ax.set_xticks([])
    ax.set_yticks([])
    for s in ax.spines.values():
        s.set_edgecolor(GARIS_LAIN)
        s.set_linewidth(1.2)
    return {"asap_ada": zh is not None, "asap_buruk": ada_asap_buruk, "panah": ada_panah, "pojok_arah": pojok["arah"]}


def _penunjuk_angin(kv, hasil, pojok=("at", "ka")):
    """Kotak di pojok peta (biasanya kanan atas): ke mana asap terbawa."""
    angin = hasil.get("angin")
    w, h = BADGE_W, BADGE_H
    x = KANAN - w - 12 if pojok[1] == "ka" else KIRI + 12
    y = PETA_ATAS + 12 if pojok[0] == "at" else PETA_BAWAH - h - 12
    tepi = ANGIN if angin else ABU_DATA
    kv.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0,rounding_size=14",
                                fc="white", ec=tepi, lw=1.8, alpha=0.96, zorder=20))
    cx, cy, r = x + 56, y + h / 2 + 4, 40
    kv.add_patch(Circle((cx, cy), r, fc="#E8EEF5" if angin else "#EEF0EF", ec=tepi, lw=1.5, zorder=21))
    kv.text(cx, cy - r - 3, "U", fontsize=12, color=tepi, ha="center", va="bottom", weight="bold", zorder=22)
    if not angin:
        kv.text(cx, cy, "?", fontsize=30, color=ABU_DATA, ha="center", va="center", weight="bold", zorder=22)
        judul, isi, warna_isi = "ARAH ANGIN", "data belum\ntersedia", ABU_DATA
    elif angin["lemah"] or angin["berubah"]:
        kv.text(cx, cy, "~", fontsize=32, color=ANGIN, ha="center", va="center", weight="bold", zorder=22)
        judul, isi = ("ANGIN LEMAH", "asap lambat\nmenyebar") if angin["lemah"] else ("ARAH ANGIN", "berubah-ubah")
        warna_isi = ANGIN
    else:
        a = math.radians(angin["arah_ke"])
        dx, dy = math.sin(a) * r * 0.78, -math.cos(a) * r * 0.78  # sumbu y kanvas terbalik
        kv.add_patch(FancyArrow(cx - dx, cy - dy, 2 * dx, 2 * dy, width=8, head_width=24, head_length=20,
                                length_includes_head=True, fc=ANGIN, ec=ANGIN, zorder=22))
        judul = "ASAP TERBAWA KE"
        isi = f"{nama_arah(angin['arah_ke']).upper()}\n±{angin['laju']:.0f} km/jam"
        warna_isi = ANGIN
    tx = x + 110
    kv.text(tx, y + 38, judul, fontsize=_pas(kv, judul, 13, "bold", w - 122, 11), color=MUTED, weight="bold",
            va="center", zorder=22)
    baris1 = max(isi.split("\n"), key=len)
    kv.text(tx, y + 98, isi, fontsize=_pas(kv, baris1, 17, "bold", w - 122, 13), color=warna_isi, weight="bold",
            va="center", zorder=22, linespacing=1.3)


def _keterangan(kv, hasil, info):
    atas, bawah = KET_ATAS, KET_BAWAH
    kv.add_patch(FancyBboxPatch((KIRI, atas), KANAN - KIRI, bawah - atas, boxstyle="round,pad=0,rounding_size=10",
                                fc=PANEL, ec="none"))
    y1, y2, y3 = atas + 26, atas + 64, atas + 102
    x = KIRI + 18
    tx = x + 100
    lebar = KANAN - 16 - tx
    pt = 14.5
    # titik panas
    for i, f in enumerate([0.05, 0.35, 0.7, 1.0]):
        kv.add_patch(RegularPolygon((x + 11 + i * 22, y1), numVertices=6, radius=11, fc=API(f), ec="none"))
    teks = f"Titik panas 24 jam: sedikit → banyak.  Angka = jumlah dalam {hasil.get('radius_km', 50)} km."
    kv.text(tx, y1, teks, fontsize=_pas(kv, teks, pt, "normal", lebar, 13), color=INK, va="center")
    # angin
    angin = hasil.get("angin")
    if info["panah"]:
        kv.add_patch(FancyArrow(x, y2, 82, 0, width=5, head_width=16, head_length=14,
                                length_includes_head=True, fc=ANGIN, ec="white", lw=0.8))
        teks, warna, xt = f"Arah angin {angin['jam']} jam ke depan. Asap ikut terbawa ke arah panah.", INK, tx
    elif angin and angin["lemah"]:
        teks, warna, xt = "Angin lemah: tidak ada panah angin, asap lambat menyebar.", INK, x
    elif angin and angin["berubah"]:
        teks, warna, xt = "Arah angin berubah-ubah: asap bisa menyebar ke segala arah.", INK, x
    elif angin:
        teks, warna, xt = "Arah angin: lihat kotak \"Asap terbawa ke\" di peta.", INK, x
    else:
        teks, warna, xt = "Arah angin: data belum tersedia saat ini.", MUTED, x
    kv.text(xt, y2, teks, fontsize=_pas(kv, teks, pt, "normal", KANAN - 16 - xt, 13), color=warna, va="center")
    # asap
    judul = "Prakiraan asap 24 jam:"
    kv.text(x, y3, judul, fontsize=pt, color=INK, va="center")
    x += _lebar_px(kv, judul, pt) + 18
    if info["asap_buruk"]:
        for warna, label in zip(ASAP_WARNA, ASAP_LABEL):
            kv.add_patch(Rectangle((x, y3 - 10), 28, 20, fc=DARAT, ec="none"))
            kv.add_patch(Rectangle((x, y3 - 10), 28, 20, fc=warna, alpha=ASAP_ALPHA, ec=MUTED, lw=0.6))
            kv.text(x + 36, y3, label, fontsize=pt, color=INK, va="center")
            x += 36 + _lebar_px(kv, label, pt) + 22
    elif info["asap_ada"]:
        kv.text(x, y3, "tidak ada daerah dengan udara tidak sehat", fontsize=pt, color=INK, va="center")
    else:
        kv.text(x, y3, "data belum tersedia saat ini", fontsize=pt, color=MUTED, va="center", style="italic")


def _daftar_kota(kv, hasil, status_lama):
    radius_km = hasil.get("radius_km", 50)
    y = DAFTAR_ATAS
    kv.text(KIRI, y, "Per kota", fontsize=18, color=INK, weight="bold", va="center")
    if status_lama:
        kv.text(KANAN, y, "▲ memburuk   ▼ membaik", fontsize=14.5, color=MUTED, ha="right", va="center")
    teks = f"Status dihitung dari titik panas dalam {radius_km} km dan kualitas udara (prakiraan & stasiun)"
    kv.text(KIRI, y + 30, teks, fontsize=_pas(kv, teks, 14, "normal", KANAN - KIRI, 12.5), color=MUTED, va="center")
    y += 76
    x_nama, x_info = KIRI + 232, KIRI + 470
    for k in hasil["kota"][:6]:
        fc, tc = _warna_kota(k)
        kv.add_patch(FancyBboxPatch((KIRI, y - 19), 190, 38, boxstyle="round,pad=0,rounding_size=9", fc=fc, ec="none"))
        lbl = _label_status(k)
        kv.text(KIRI + 95, y, lbl, fontsize=_pas(kv, lbl, 15, "bold", 176, 12), color=tc, weight="bold",
                ha="center", va="center")
        lama = (status_lama or {}).get(k["nama"])
        if lama is not None and not _data_kurang(k):
            if k["tingkat"] > lama:
                kv.text(KIRI + 200, y, "▲", fontsize=16, color="#B3261E", va="center")
            elif k["tingkat"] < lama:
                kv.text(KIRI + 200, y, "▼", fontsize=16, color="#2F6FB0", va="center")
        kv.text(x_nama, y, k["nama"], fontsize=_pas(kv, k["nama"], 19, "bold", x_info - x_nama - 12, 15),
                color=INK, weight="bold", va="center")
        info = f"{angka(k['titik_24j'])} titik panas"
        if k["ispu_prakiraan"] is not None:
            info += f" · udara {ISPU_NAMA[kategori_ispu(k['ispu_prakiraan'])].lower()}"
        elif _data_kurang(k):
            info += " · data udara belum ada"
        kv.text(x_info, y, info, fontsize=_pas(kv, info, 16, "normal", KANAN - x_info, 13), color=MUTED, va="center")
        y += 48
    return y


def _kaki(kv):
    baris = ["Titik panas = panas tinggi terdeteksi satelit NASA (VIIRS), belum tentu kebakaran.",
             "Asap dan angin = prakiraan Open-Meteo/CAMS, bisa lebih ringan dari kenyataan.",
             "Inisiatif warga Jaga Udara, bukan kanal resmi pemerintah. Batas wilayah: BAKOSURTANAL."]
    pt = min(_pas(kv, b, 14, "normal", KANAN - KIRI, 12) for b in baris)
    kv.text(KIRI, TINGGI - 58, "\n".join(baris), fontsize=pt, color=MUTED, va="center", linespacing=1.4)


# ---------------------------------------------------------------- utama
def buat(hasil, geom_target, semua_fitur, path, radius_km=None, status_lama=None):
    if radius_km is not None:
        hasil.setdefault("radius_km", radius_km)
    fig = plt.figure(figsize=(LEBAR / 100, TINGGI / 100), dpi=100, facecolor=BG)
    # kanvas dengan koordinat piksel (0,0 = kiri atas) untuk semua yang di luar peta
    kv = fig.add_axes([0, 0, 1, 1], zorder=0)
    kv.set_xlim(0, LEBAR)
    kv.set_ylim(TINGGI, 0)
    kv.axis("off")

    _kepala(kv, hasil)
    info = _peta(fig, kv, hasil, geom_target, semua_fitur)
    # kanvas kedua di atas peta untuk kotak arah asap
    atas = fig.add_axes([0, 0, 1, 1], zorder=5)
    atas.set_xlim(0, LEBAR)
    atas.set_ylim(TINGGI, 0)
    atas.axis("off")
    atas.patch.set_alpha(0)
    _penunjuk_angin(atas, hasil, info["pojok_arah"])
    _keterangan(kv, hasil, info)
    _daftar_kota(kv, hasil, status_lama)
    _kaki(kv)

    if os.environ.get("FIXTURES"):
        atas.text(LEBAR / 2, 760, "CONTOH DATA UJI", fontsize=66, color="#C62828", alpha=0.16, weight="bold",
                  ha="center", va="center", rotation=25, zorder=30)
    fig.savefig(path, dpi=100, facecolor=BG)
    plt.close(fig)
    return path
