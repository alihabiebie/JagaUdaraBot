"""Menyusun teks pesan: Telegram (HTML) dan WhatsApp (format *tebal*)."""
import html
from datetime import timedelta

from .analisis import TINGKAT, WIB, ISPU_NAMA, kategori_ispu, kota_searah_angin, nama_arah

HARI = ["Senin", "Selasa", "Rabu", "Kamis", "Jumat", "Sabtu", "Minggu"]
BULAN = ["Jan", "Feb", "Mar", "Apr", "Mei", "Jun", "Jul", "Agu", "Sep", "Okt", "Nov", "Des"]
IKON = ["🔵", "🟡", "🟠", "🔴"]  # sama dengan warna kartu: biru, kuning, oranye, merah

TINDAKAN = [
    "Udara relatif aman. Tetap pantau kabar berikutnya.",
    "Bayi, anak, lansia, ibu hamil, dan penderita asma atau sakit jantung: kurangi kegiatan lama di luar. Siapkan masker N95 atau KN95.",
    "Kelompok rentan tetap di dalam rumah, di kamar yang ditutup rapat. Keluar rumah pakai masker N95 atau KN95. Kurangi kerja berat di luar.",
    "Semua orang sebisa mungkin di dalam rumah. Bayi, lansia, dan orang sakit di kamar bersih atau tempat berlindung. Segera ke puskesmas kalau sesak, bibir kebiruan, atau anak bernapas cepat.",
]

# versi pendek untuk kartu gambar
TINDAKAN_SINGKAT = [
    "Udara relatif aman. Tetap pantau kabar berikutnya.",
    "Bayi, anak, lansia, ibu hamil, penderita asma: kurangi kegiatan lama di luar.",
    "Kelompok rentan tetap di kamar tertutup. Keluar rumah pakai masker N95/KN95.",
    "Semua orang sebisa mungkin di dalam rumah. Sesak napas? Segera ke puskesmas.",
]

CATATAN = ("Titik panas = panas tinggi yang terdeteksi satelit NASA, belum tentu kebakaran; "
           "api bisa terlewat kalau tertutup awan atau asap tebal. "
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


def _gabung(nama):
    return nama[0] if len(nama) == 1 else ", ".join(nama[:-1]) + " dan " + nama[-1]


def kalimat_status(hasil):
    """Satu kalimat: di mana kondisi paling buruk."""
    t = hasil["tingkat"]
    if t == 0:
        return "Hari ini tidak ada kota pantauan yang perlu waspada."
    terburuk = [k["nama"] for k in hasil["kota"] if k["tingkat"] == t]
    if len(terburuk) > 3:
        return f"{len(terburuk)} kota berstatus {TINGKAT[t]}, termasuk {_gabung(terburuk[:2])}."
    return f"Status {TINGKAT[t]} di {_gabung(terburuk)}."


def angka(n):
    """1234 -> '1.234' (pemisah ribuan Indonesia)."""
    return f"{n:,}".replace(",", ".")


def kalimat_angin(angin, hasil=None):
    """Ke mana asap terbawa angin, dalam bahasa sehari-hari. None kalau data angin tidak ada."""
    if not angin:
        return None
    tujuan = kota_searah_angin(hasil, angin) if hasil else None
    if tujuan:
        return (f"Angin membawa asap ke arah {nama_arah(angin['arah_ke'])} (±{angin['laju']:.0f} km/jam), "
                f"menuju {tujuan}.")
    if angin["lemah"]:
        return "Angin lemah: asap cenderung mengendap di sekitar sumber api."
    if angin["berubah"]:
        return f"Angin berubah-ubah arah (±{angin['laju']:.0f} km/jam): asap bisa menyebar ke segala arah."
    return f"Angin membawa asap ke arah {nama_arah(angin['arah_ke'])} (±{angin['laju']:.0f} km/jam)."


def _baris_kota(k, sekarang, wa=False):
    e = (lambda s: s) if wa else html.escape
    b = (lambda s: f"*{s}*") if wa else (lambda s: f"<b>{s}</b>")
    bagian = [f"{IKON[k['tingkat']]} {b(e(k['nama']))}: {TINGKAT[k['tingkat']]}"]
    rinci = [f"titik panas {k['titik_24j']} ({tren(k['titik_24j'], k['titik_24j_sebelumnya'])})"]
    if k["ispu_prakiraan"] is not None:
        kat = ISPU_NAMA[kategori_ispu(k["ispu_prakiraan"])]
        p = k["prakiraan"]
        rinci.append(f"prakiraan asap {kat.lower()}, terpekat {jam_relatif(p['jam_puncak'], sekarang)}")
    if k["stasiun"]:
        rinci.append(f"stasiun {e(k['stasiun']['nama'])}: AQI {k['stasiun']['aqi']}")
    if k.get("data_kurang"):
        rinci.append("data kualitas udara belum ada, status hanya dari titik panas")
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
        f"Titik panas 24 jam terakhir: {angka(hasil['titik_prov_24j'])} ({tren(hasil['titik_prov_24j'], hasil['titik_prov_24j_sebelumnya'])})",
    ]
    ka = kalimat_angin(hasil.get("angin"), hasil)
    if ka:
        baris.append(ka)
    baris += [
        "",
        b(f"Per kota (titik panas dalam {radius_km} km):"),
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
    ka = kalimat_angin(hasil.get("angin"), hasil)
    for nama, lama, baru in naik:
        k = next(x for x in hasil["kota"] if x["nama"] == nama)
        alasan = ", ".join(k["alasan"]) or "kondisi memburuk"
        baris.append(f"{IKON[baru]} {b(e(nama))} naik ke {b(TINGKAT[baru])} (sebelumnya {TINGKAT[lama]})")
        baris.append(f"   Penyebab: {e(alasan)}")
    if ka:
        baris += ["", ka]
    baris += ["", b("Yang perlu dilakukan:"), TINDAKAN[tmax]]
    if not wa:
        baris += ["", PANDUAN]
    return "\n".join(baris)


def keterangan_foto(hasil):
    t = hasil["tingkat"]
    return f"{IKON[t]} Kabar asap {hasil['nama']}: {TINGKAT[t]}. {tanggal(hasil['waktu'])}"
