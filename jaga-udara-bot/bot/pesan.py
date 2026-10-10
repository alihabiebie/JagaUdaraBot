"""Menyusun teks pesan: Telegram (HTML) dan WhatsApp (format *tebal*)."""
import html
from datetime import timedelta

from .analisis import TINGKAT, WIB, ISPU_NAMA, kategori_ispu

HARI = ["Senin", "Selasa", "Rabu", "Kamis", "Jumat", "Sabtu", "Minggu"]
BULAN = ["Jan", "Feb", "Mar", "Apr", "Mei", "Jun", "Jul", "Agu", "Sep", "Okt", "Nov", "Des"]
IKON = ["🟢", "🟡", "🟠", "🔴"]

TINDAKAN = [
    "Udara relatif aman. Tetap pantau kabar berikutnya.",
    "Bayi, anak, lansia, ibu hamil, dan penderita asma atau sakit jantung: kurangi kegiatan lama di luar. Siapkan masker N95 atau KN95.",
    "Kelompok rentan tetap di dalam rumah, di kamar yang ditutup rapat. Keluar rumah pakai masker N95 atau KN95. Kurangi kerja berat di luar.",
    "Semua orang sebisa mungkin di dalam rumah. Bayi, lansia, dan orang sakit di kamar bersih atau tempat berlindung. Segera ke puskesmas kalau sesak, bibir kebiruan, atau anak bernapas cepat.",
]

CATATAN = ("Titik api dari satelit NASA (bisa terlewat kalau tertutup awan atau asap tebal). "
           "Prakiraan asap dari model CAMS dan bisa lebih rendah dari kenyataan saat kebakaran gambut. "
           "Inisiatif warga Jaga Udara, bukan kanal resmi pemerintah.")

# PDF panduan dikirim ke kanal Telegram tepat setelah setiap pesan (lihat main.py).
# Saluran WhatsApp tidak bisa memuat file PDF, jadi baris ini hanya untuk Telegram.
PANDUAN = "📄 Panduan bergambar: buka file PDF di bawah pesan ini (juga disematkan di bagian atas kanal)."


def tanggal(dt):
    d = dt.astimezone(WIB)
    return f"{HARI[d.weekday()]}, {d.day} {BULAN[d.month - 1]} {d.year}, {d:%H.%M} WIB"


def jam_relatif(iso_lokal, sekarang):
    """'2026-10-11T07:00' -> 'besok 07.00' / 'hari ini 18.00'."""
    hari_ini = sekarang.astimezone(WIB).date()
    tgl = iso_lokal[:10]
    jam = iso_lokal[11:16].replace(":", ".")
    if tgl == str(hari_ini):
        return f"hari ini {jam}"
    if tgl == str(hari_ini + timedelta(days=1)):
        return f"besok {jam}"
    return f"{tgl[8:10]}/{tgl[5:7]} {jam}"


def tren(baru, lama):
    if lama == 0 and baru == 0:
        return "sama"
    if baru > lama * 1.2 + 2:
        return f"naik dari {lama}"
    if baru < lama * 0.8 - 2:
        return f"turun dari {lama}"
    return f"kemarin {lama}"


def _baris_kota(k, sekarang, wa=False):
    e = (lambda s: s) if wa else html.escape
    b = (lambda s: f"*{s}*") if wa else (lambda s: f"<b>{s}</b>")
    bagian = [f"{IKON[k['tingkat']]} {b(e(k['nama']))}: {TINGKAT[k['tingkat']]}"]
    rinci = [f"titik api {k['titik_24j']} ({tren(k['titik_24j'], k['titik_24j_sebelumnya'])})"]
    if k["ispu_prakiraan"] is not None:
        kat = ISPU_NAMA[kategori_ispu(k["ispu_prakiraan"])]
        p = k["prakiraan"]
        rinci.append(f"prakiraan asap {kat.lower()}, terpekat {jam_relatif(p['jam_puncak'], sekarang)}")
    if k["stasiun"]:
        rinci.append(f"stasiun {e(k['stasiun']['nama'])}: AQI {k['stasiun']['aqi']}")
    return bagian[0] + "\n   " + "; ".join(rinci)


def harian(hasil, radius_km, wa=False):
    s = hasil["waktu"]
    e = (lambda x: x) if wa else html.escape
    b = (lambda x: f"*{x}*") if wa else (lambda x: f"<b>{x}</b>")
    t = hasil["tingkat"]
    baris = [
        f"{IKON[t]} {b('Kabar asap ' + e(hasil['nama']))}",
        tanggal(s),
        "",
        f"Status provinsi: {b(TINGKAT[t])}",
        f"Titik api 24 jam terakhir: {hasil['titik_prov_24j']} ({tren(hasil['titik_prov_24j'], hasil['titik_prov_24j_sebelumnya'])})",
        "",
        b(f"Per kota (titik api dalam {radius_km} km):"),
    ]
    baris += [_baris_kota(k, s, wa) for k in hasil["kota"]]
    baris += ["", b("Yang perlu dilakukan:"), TINDAKAN[t]]
    if not wa:
        baris += ["", PANDUAN]
    baris += ["", ("_" + CATATAN + "_") if wa else f"<i>{html.escape(CATATAN)}</i>"]
    return "\n".join(baris)


def peringatan(hasil, naik, wa=False):
    """naik = list (nama_kota, tingkat_lama, tingkat_baru)."""
    s = hasil["waktu"]
    b = (lambda x: f"*{x}*") if wa else (lambda x: f"<b>{x}</b>")
    e = (lambda x: x) if wa else html.escape
    tmax = max(n for _, _, n in naik)
    baris = [f"{IKON[tmax]} {b('PERINGATAN ASAP: ' + e(hasil['nama']))}", tanggal(s), ""]
    for nama, lama, baru in naik:
        k = next(x for x in hasil["kota"] if x["nama"] == nama)
        alasan = ", ".join(k["alasan"]) or "kondisi memburuk"
        baris.append(f"{IKON[baru]} {b(e(nama))} naik ke {b(TINGKAT[baru])} (sebelumnya {TINGKAT[lama]})")
        baris.append(f"   Penyebab: {e(alasan)}")
    baris += ["", b("Yang perlu dilakukan:"), TINDAKAN[tmax]]
    if not wa:
        baris += ["", PANDUAN]
    return "\n".join(baris)


def keterangan_foto(hasil):
    t = hasil["tingkat"]
    return f"{IKON[t]} Kabar asap {hasil['nama']}: {TINGKAT[t]}. {tanggal(hasil['waktu'])}"
