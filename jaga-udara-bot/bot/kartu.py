"""Membuat gambar kartu harian (PNG lebar 1080, tinggi mengikuti bentuk provinsi) untuk Telegram dan WhatsApp.

Peta sengaja sederhana: setiap titik panas digambar sebagai titik merah, ditambah kota dan
arah angin. Titik panas adalah informasi utama, jadi tidak ada yang boleh menutupinya:
panah angin digambar DI BAWAH titik dan hanya di bagian yang kosong, dan nama kota
ditaruh di posisi yang paling sedikit menutup titik.
"""
import math
import os

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib import font_manager  # noqa: E402
import numpy as np  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402
from matplotlib.patches import Circle, FancyArrow, FancyBboxPatch, Polygon  # noqa: E402

from .analisis import TINGKAT, bbox_wilayah  # noqa: E402
from .pesan import angka, kalimat_angin, tanggal, tren  # noqa: E402

# huruf Inter disertakan di repo supaya kartu di GitHub sama dengan di komputer (lisensi: fonts/LICENSE-Inter.txt)
_FOLDER_HURUF = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "fonts")
for _nama in ("Inter-Regular.otf", "Inter-Bold.otf"):
    _path = os.path.join(_FOLDER_HURUF, _nama)
    if os.path.exists(_path):
        font_manager.fontManager.addfont(_path)
plt.rcParams["font.family"] = ["Inter", "DejaVu Sans"]

WARNA = ["#2E9E4F", "#E0A800", "#E8710A", "#C62828"]
INK, MUTED, BG, LAND, LAND_LAIN, GARIS = "#14201F", "#4D5E5A", "#FBFCFA", "#E4ECE9", "#F1F4F2", "#9FB3AE"
# Kekuatan api dari satelit (FRP, megawatt): makin besar makin panas/luas apinya saat satelit lewat.
# Warna dan ukuran sama-sama berubah, supaya tetap terbaca oleh penderita buta warna.
# Catatan: kebakaran gambut yang membara bisa ber-FRP kecil tapi asapnya sangat banyak.
KELAS_API = [  # (FRP minimal, nama, warna, ukuran titik)
    (0, "Api kecil", "#F7A541", 16),
    (5, "Api sedang", "#E0362C", 24),
    (20, "Api besar", "#7A0A0A", 42),
]
ANGIN = "#2B5C8A"
TAMBAH_PETA = 0.35  # derajat di sekeliling provinsi
LEBAR = 1080
PETA_ATAS = 310  # piksel dari atas
PETA_LEBAR_MAKS, PETA_TINGGI_MAKS = 1020, 980


def batas_peta(geom):
    """Batas peta (barat, selatan, timur, utara). Dipakai juga main.py untuk data titik panas dan angin.

    Provinsi yang bentuknya tinggi dilebarkan ke kiri-kanan (wilayah sekitarnya ikut tampil),
    supaya peta selalu penuh selebar kartu.
    """
    x0, y0, x1, y1 = bbox_wilayah(geom, tambah=TAMBAH_PETA)
    rasio_min = PETA_LEBAR_MAKS / PETA_TINGGI_MAKS
    if (x1 - x0) / (y1 - y0) < rasio_min:
        tambah = ((y1 - y0) * rasio_min - (x1 - x0)) / 2
        x0, x1 = x0 - tambah, x1 + tambah
    return x0, y0, x1, y1


def _poligon(ax, geom, **kw):
    polys = geom["coordinates"] if geom["type"] == "MultiPolygon" else [geom["coordinates"]]
    for poly in polys:
        ax.add_patch(Polygon(poly[0], closed=True, **kw))


def _panah_angin(ax, angin, xy, x0, y0, x1, y1):
    """Panah kecil arah asap terbawa, hanya di tempat yang tidak ada titik panas di dekatnya."""
    if not angin or angin["lemah"] or angin["berubah"]:
        return False
    jarak_aman = 0.22  # derajat (~25 km) dari titik panas terdekat
    ada = False
    rata = math.hypot(angin["u"], angin["v"]) or 1
    for p in angin["titik"]:
        if not (x0 + 0.3 < p["lon"] < x1 - 0.3 and y0 + 0.3 < p["lat"] < y1 - 0.3):
            continue
        laju = math.hypot(p["u"], p["v"])
        if laju < 1:
            continue
        # panah yang berlawanan dengan arah umum (lebih dari 60°) tidak digambar, supaya tidak membingungkan
        if (p["u"] * angin["u"] + p["v"] * angin["v"]) / (laju * rata) < 0.5:
            continue
        panjang = 0.32 + 0.22 * min(laju / 20, 1)
        dx, dy = p["u"] / laju * panjang, p["v"] / laju * panjang
        xa, ya = p["lon"] - dx / 2, p["lat"] - dy / 2
        if len(xy):
            # jarak tiap titik panas ke ruas panah
            t = np.clip(((xy[:, 0] - xa) * dx + (xy[:, 1] - ya) * dy) / (dx * dx + dy * dy), 0, 1)
            if (np.hypot(xa + t * dx - xy[:, 0], ya + t * dy - xy[:, 1]) < jarak_aman).any():
                continue
        ax.add_patch(FancyArrow(xa, ya, dx, dy, width=0.035, head_width=0.13, head_length=0.12,
                                length_includes_head=True, fc=ANGIN, ec="none", alpha=0.55, zorder=2))
        ada = True
    return ada


def _label_kota(ax, fig, k, xy, terpakai, semua_kota):
    """Nama kota di posisi yang paling sedikit menutup titik panas dan tidak menimpa nama lain."""
    calon = [(9, 7, "left", "bottom"), (-9, 7, "right", "bottom"), (9, -7, "left", "top"),
             (-9, -7, "right", "top"), (0, 13, "center", "bottom"), (0, -13, "center", "top"),
             (22, 18, "left", "bottom"), (-22, 18, "right", "bottom"), (22, -18, "left", "top"),
             (-22, -18, "right", "top"), (0, 30, "center", "bottom"), (0, -30, "center", "top")]
    r = fig.canvas.get_renderer()
    inv = ax.transData.inverted()
    terbaik = None
    for urut, (dx, dy, ha, va) in enumerate(calon):
        t = ax.annotate(k["nama"], (k["lon"], k["lat"]), xytext=(dx, dy), textcoords="offset points",
                        ha=ha, va=va, fontsize=13, weight="bold", color=INK, zorder=6,
                        bbox=dict(boxstyle="round,pad=0.2", fc="white", ec="none", alpha=0.85))
        bb = t.get_window_extent(r).expanded(1.08, 1.15)
        (bx0, by0), (bx1, by1) = inv.transform([(bb.x0, bb.y0), (bb.x1, bb.y1)])
        t.remove()
        tutup = int(((xy[:, 0] > bx0) & (xy[:, 0] < bx1) & (xy[:, 1] > by0) & (xy[:, 1] < by1)).sum()) if len(xy) else 0
        tabrak = any(bx0 < b[2] and bx1 > b[0] and by0 < b[3] and by1 > b[1] for b in terpakai)
        keluar = bb.x0 < ax.bbox.x0 or bb.x1 > ax.bbox.x1 or bb.y0 < ax.bbox.y0 or bb.y1 > ax.bbox.y1
        # label tidak boleh lebih dekat ke bulatan kota lain daripada ke kotanya sendiri
        cx, cy = (bx0 + bx1) / 2, (by0 + by1) / 2
        sendiri = math.hypot(cx - k["lon"], cy - k["lat"])
        rancu = any(math.hypot(cx - o["lon"], cy - o["lat"]) < sendiri for o in semua_kota if o is not k)
        skor = (tabrak or keluar or rancu, tutup, urut)
        if terbaik is None or skor < terbaik[0]:
            terbaik = (skor, dx, dy, ha, va, (bx0, by0, bx1, by1))
        if not tabrak and not keluar and not rancu and tutup == 0:
            break
    _, dx, dy, ha, va, kotak = terbaik
    terpakai.append(kotak)
    garis = dict(arrowstyle="-", color=INK, lw=0.8) if abs(dx) > 12 or abs(dy) > 14 else None
    ax.annotate(k["nama"], (k["lon"], k["lat"]), xytext=(dx, dy), textcoords="offset points", ha=ha, va=va,
                fontsize=13, weight="bold", color=INK, zorder=6, arrowprops=garis,
                bbox=dict(boxstyle="round,pad=0.2", fc="white", ec="none", alpha=0.85))




def _baris_angin(fig, hasil, Y):
    """Satu baris di atas peta: ke mana asap terbawa angin, dengan kompas kecil."""
    angin = hasil.get("angin")
    ax = fig.add_axes([54 / LEBAR, Y(293), 54 / LEBAR, Y(239) - Y(293)])
    ax.set_xlim(-1, 1)
    ax.set_ylim(-1, 1)
    ax.set_aspect("equal")
    ax.axis("off")
    ax.add_patch(Circle((0, 0), 0.95, fc="#E8EEF5", ec=ANGIN if angin else MUTED, lw=1.5))
    if angin and not angin["lemah"] and not angin["berubah"]:
        a = math.radians(angin["arah_ke"])
        dx, dy = math.sin(a) * 0.7, math.cos(a) * 0.7
        ax.add_patch(FancyArrow(-dx, -dy, 2 * dx, 2 * dy, width=0.16, head_width=0.5, head_length=0.45,
                                length_includes_head=True, fc=ANGIN, ec=ANGIN))
    else:
        ax.text(0, 0, "~" if angin else "?", fontsize=20, color=ANGIN if angin else MUTED, ha="center",
                va="center", weight="bold")
    teks = kalimat_angin(angin, hasil) or "Arah angin: data belum tersedia saat ini."
    fig.text(121 / LEBAR, Y(266), teks, fontsize=15 if len(teks) < 85 else 13.5, color=INK, va="center")


def buat(hasil, geom_target, semua_fitur, path, radius_km=None, status_lama=None):
    radius_km = radius_km or hasil.get("radius_km", 50)
    t = hasil["tingkat"]

    # --- tata letak (piksel): peta selebar mungkin, tinggi kartu mengikuti bentuk provinsi
    x0, y0, x1, y1 = batas_peta(geom_target)
    rasio = (x1 - x0) / (y1 - y0)
    peta_w = PETA_LEBAR_MAKS
    peta_h = peta_w / rasio
    if peta_h > PETA_TINGGI_MAKS:
        peta_h = PETA_TINGGI_MAKS
        peta_w = peta_h * rasio
    peta_bawah = PETA_ATAS + peta_h
    kota = hasil["kota"][:7]
    daftar_atas = peta_bawah + 45
    tinggi = int(daftar_atas + 61 + 57 * max(len(kota) - 1, 0) + 158)
    W = LEBAR

    def X(px):
        return px / W

    def Y(px):  # piksel dari atas -> pecahan figur dari bawah
        return 1 - px / tinggi

    fig = plt.figure(figsize=(W / 100, tinggi / 100), dpi=100, facecolor=BG)

    # --- judul
    fig.text(X(54), Y(61), "Jaga Udara", fontsize=17, color=MUTED, weight="bold")
    fig.text(X(54), Y(115), f"Kabar asap {hasil['nama']}", fontsize=34, color=INK, weight="bold")
    fig.text(X(54), Y(155), tanggal(hasil["waktu"]), fontsize=17, color=MUTED)
    chip = FancyBboxPatch((X(54), Y(223)), X(432), Y(172) - Y(223), boxstyle="round,pad=0,rounding_size=0.012",
                          transform=fig.transFigure, facecolor=WARNA[t], edgecolor="none")
    fig.patches.append(chip)
    fig.text(X(70), Y(198), f"Status provinsi: {TINGKAT[t]}", fontsize=19, color="white", weight="bold", va="center")
    fig.text(X(540), Y(198), f"{angka(hasil['titik_prov_24j'])} titik panas dalam 24 jam "
             f"({tren(hasil['titik_prov_24j'], hasil['titik_prov_24j_sebelumnya'])})",
             fontsize=16, color=INK, va="center")
    _baris_angin(fig, hasil, Y)

    # --- peta
    kiri = (W - peta_w) / 2
    ax = fig.add_axes([X(kiri), Y(peta_bawah), X(peta_w), Y(PETA_ATAS) - Y(peta_bawah)])
    ax.set_facecolor("#DCE8F6")
    for f in semua_fitur:
        _poligon(ax, f["geometry"], facecolor=LAND_LAIN, edgecolor=GARIS, linewidth=0.8)
    _poligon(ax, geom_target, facecolor=LAND, edgecolor=INK, linewidth=1.6)
    ax.set_xlim(x0, x1)
    ax.set_ylim(y0, y1)
    ax.set_aspect("equal")
    ax.set_xticks([])
    ax.set_yticks([])
    for s in ax.spines.values():
        s.set_edgecolor(GARIS)

    pts = hasil["titik_peta"]
    xy = np.array([(p["lon"], p["lat"]) for p in pts], float).reshape(-1, 2)
    ada_panah = _panah_angin(ax, hasil.get("angin"), xy, x0, y0, x1, y1)
    if len(xy):
        # titik panas di atas panah dan batas wilayah, supaya tidak pernah tertutup;
        # api besar digambar paling atas
        frp = np.array([p.get("frp") or 0 for p in pts], float)
        for i, (bawah, _, warna, ukuran) in enumerate(KELAS_API):
            atas = KELAS_API[i + 1][0] if i + 1 < len(KELAS_API) else np.inf
            m = (frp >= bawah) & (frp < atas)
            if m.any():
                ax.scatter(xy[m, 0], xy[m, 1], s=ukuran, c=warna, alpha=0.85, edgecolors="white",
                           linewidths=0.4, zorder=4 + i * 0.1)
    for k in hasil["kota"]:
        ax.scatter([k["lon"]], [k["lat"]], s=230, c=WARNA[k["tingkat"]], edgecolors="white",
                   linewidths=2.5, zorder=5)
    fig.canvas.draw()  # ukuran teks baru bisa diukur setelah digambar sekali
    terpakai = []
    for k in hasil["kota"]:
        _label_kota(ax, fig, k, xy, terpakai, hasil["kota"])

    tanda = []
    if len(xy):
        for _, nama, warna, ukuran in KELAS_API:
            tanda.append(Line2D([], [], ls="none", marker="o", ms=math.sqrt(ukuran) * 1.1, color=warna,
                                markeredgecolor="white", markeredgewidth=0.4, label=nama))
    if ada_panah:
        tanda.append(Line2D([], [], ls="none", marker=r"$\rightarrow$", ms=22, color=ANGIN, alpha=0.7,
                            label="Arah angin (asap ikut terbawa)"))
    if tanda:
        # sudut legenda dipilih yang paling sedikit menutup titik panas
        def _isi(px, py):
            w, h = (x1 - x0) * 0.42, (y1 - y0) * 0.16
            bx = x0 if px == 0 else x1 - w
            by = y0 if py == 0 else y1 - h
            return int(((xy[:, 0] > bx) & (xy[:, 0] < bx + w) & (xy[:, 1] > by) & (xy[:, 1] < by + h)).sum())
        pojok = min([(0, 0, "lower left"), (1, 0, "lower right"), (0, 1, "upper left"), (1, 1, "upper right")],
                    key=lambda p: _isi(p[0], p[1]) if len(xy) else 0)
        ax.legend(handles=tanda, loc=pojok[2], fontsize=12, frameon=True, framealpha=0.9,
                  title="Titik panas 24 jam (kekuatan api)" if len(xy) else None, title_fontsize=12,
                  alignment="left")

    # --- daftar kota
    y = daftar_atas
    fig.text(X(54), Y(y), f"Per kota (titik panas dalam {radius_km} km, 24 jam terakhir)", fontsize=16,
             color=MUTED, weight="bold", va="center")
    y += 61
    for k in kota:
        fig.patches.append(FancyBboxPatch((X(54), Y(y + 21)), X(173), Y(y - 21) - Y(y + 21),
                                          boxstyle="round,pad=0,rounding_size=0.008",
                                          transform=fig.transFigure, facecolor=WARNA[k["tingkat"]], edgecolor="none"))
        fig.text(X(140), Y(y), TINGKAT[k["tingkat"]], fontsize=14, color="white", weight="bold", ha="center",
                 va="center")
        fig.text(X(254), Y(y), k["nama"], fontsize=17, color=INK, weight="bold", va="center")
        info = f"{angka(k['titik_24j'])} titik panas"
        if k["ispu_prakiraan"] is not None:
            info += f" · prakiraan ISPU {k['ispu_prakiraan']}"
        fig.text(X(605), Y(y), info, fontsize=14, color=MUTED, va="center")
        y += 57

    # --- kaki
    fig.text(X(54), Y(tinggi - 28), "Kekuatan api = panas yang terukur satelit. Gambut yang membara bisa tampak \"api kecil\" tapi asapnya pekat.\n"
             "Sumber: NASA FIRMS (titik panas, belum tentu kebakaran), Open-Meteo/CAMS (prakiraan dan angin),\n"
             "WAQI (stasiun). Batas: BAKOSURTANAL. Inisiatif warga, bukan kanal resmi pemerintah.",
             fontsize=11.5, color=MUTED, linespacing=1.5, va="bottom")
    if os.environ.get("FIXTURES"):
        fig.text(0.5, Y(PETA_ATAS + peta_h / 2), "CONTOH DATA UJI", fontsize=70, color="#C62828", alpha=0.18, weight="bold",
                 ha="center", va="center", rotation=25)
    fig.savefig(path, dpi=100, facecolor=BG)
    plt.close(fig)
    return path
