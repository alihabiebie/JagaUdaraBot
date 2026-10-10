"""Membuat gambar kartu harian (PNG 1080 x 1350) untuk Telegram dan WhatsApp."""
import os

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import FancyBboxPatch, Polygon  # noqa: E402

from .analisis import TINGKAT, bbox_wilayah  # noqa: E402
from .pesan import tanggal, tren  # noqa: E402

WARNA = ["#2E9E4F", "#E0A800", "#E8710A", "#C62828"]
INK, MUTED, BG, LAND, LAND_LAIN, GARIS = "#14201F", "#4D5E5A", "#FBFCFA", "#E4ECE9", "#F1F4F2", "#9FB3AE"


def _poligon(ax, geom, **kw):
    polys = geom["coordinates"] if geom["type"] == "MultiPolygon" else [geom["coordinates"]]
    for poly in polys:
        ax.add_patch(Polygon(poly[0], closed=True, **kw))


def buat(hasil, geom_target, semua_fitur, path, radius_km):
    fig = plt.figure(figsize=(10.8, 13.5), dpi=100, facecolor=BG)
    t = hasil["tingkat"]

    # --- judul
    fig.text(0.05, 0.955, "Jaga Udara", fontsize=17, color=MUTED, weight="bold")
    fig.text(0.05, 0.915, f"Kabar asap {hasil['nama']}", fontsize=34, color=INK, weight="bold")
    fig.text(0.05, 0.885, tanggal(hasil["waktu"]), fontsize=17, color=MUTED)
    chip = FancyBboxPatch((0.05, 0.835), 0.40, 0.038, boxstyle="round,pad=0.006,rounding_size=0.015",
                          transform=fig.transFigure, facecolor=WARNA[t], edgecolor="none")
    fig.patches.append(chip)
    fig.text(0.065, 0.846, f"Status provinsi: {TINGKAT[t]}", fontsize=19, color="white", weight="bold")
    fig.text(0.50, 0.846, f"{hasil['titik_prov_24j']} titik api dalam 24 jam "
             f"({tren(hasil['titik_prov_24j'], hasil['titik_prov_24j_sebelumnya'])})",
             fontsize=16, color=INK)

    # --- peta
    ax = fig.add_axes([0.05, 0.40, 0.90, 0.42])
    ax.set_facecolor("#DCE8F6")
    x0, y0, x1, y1 = bbox_wilayah(geom_target, tambah=0.35)
    for f in semua_fitur:
        _poligon(ax, f["geometry"], facecolor=LAND_LAIN, edgecolor=GARIS, linewidth=0.8)
    _poligon(ax, geom_target, facecolor=LAND, edgecolor=INK, linewidth=1.6)
    pts = hasil["titik_peta"]
    if pts:
        ax.scatter([p["lon"] for p in pts], [p["lat"] for p in pts], s=10, c="#D2352F",
                   alpha=0.75, linewidths=0, zorder=3, label="Titik api 24 jam terakhir")
    for k in hasil["kota"]:
        ax.scatter([k["lon"]], [k["lat"]], s=230, c=WARNA[k["tingkat"]], edgecolors="white",
                   linewidths=2.5, zorder=5)
        ax.annotate(k["nama"], (k["lon"], k["lat"]), xytext=(9, 7), textcoords="offset points",
                    fontsize=13, weight="bold", color=INK, zorder=6,
                    bbox=dict(boxstyle="round,pad=0.2", fc="white", ec="none", alpha=0.8))
    ax.set_xlim(x0, x1)
    ax.set_ylim(y0, y1)
    ax.set_aspect("equal")
    ax.set_xticks([])
    ax.set_yticks([])
    for s in ax.spines.values():
        s.set_edgecolor(GARIS)
    if pts:
        ax.legend(loc="lower left", fontsize=12, frameon=True, framealpha=0.9, markerscale=2.5)

    # --- daftar kota
    y = 0.36
    fig.text(0.05, y, f"Per kota (titik api dalam {radius_km} km, 24 jam terakhir)", fontsize=16, color=MUTED, weight="bold")
    y -= 0.045
    for k in hasil["kota"][:7]:
        fig.patches.append(FancyBboxPatch((0.05, y - 0.006), 0.16, 0.032, boxstyle="round,pad=0.004,rounding_size=0.01",
                                          transform=fig.transFigure, facecolor=WARNA[k["tingkat"]], edgecolor="none"))
        fig.text(0.13, y + 0.004, TINGKAT[k["tingkat"]], fontsize=14, color="white", weight="bold", ha="center")
        fig.text(0.235, y + 0.004, k["nama"], fontsize=17, color=INK, weight="bold")
        info = f"{k['titik_24j']} titik api"
        if k["ispu_prakiraan"] is not None:
            info += f" · prakiraan ISPU {k['ispu_prakiraan']}"
        fig.text(0.56, y + 0.004, info, fontsize=14, color=MUTED)
        y -= 0.042

    # --- kaki
    fig.text(0.05, 0.035, "Sumber: NASA FIRMS (titik api), Open-Meteo/CAMS (prakiraan), WAQI (stasiun). Batas: BAKOSURTANAL.\n"
             "Inisiatif warga, bukan kanal resmi pemerintah. Prakiraan bisa lebih rendah dari kenyataan.",
             fontsize=11.5, color=MUTED, linespacing=1.5)
    if os.environ.get("FIXTURES"):
        fig.text(0.5, 0.6, "CONTOH DATA UJI", fontsize=70, color="#C62828", alpha=0.18, weight="bold",
                 ha="center", va="center", rotation=25)
    fig.savefig(path, dpi=100, facecolor=BG)
    plt.close(fig)
    return path
