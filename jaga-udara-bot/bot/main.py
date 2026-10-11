"""Bot Peringatan Asap Jaga Udara.

Cara pakai:
    python -m bot.main                 # mode otomatis: ringkasan harian pagi, selain itu hanya kalau status naik
    python -m bot.main --mode harian   # paksa kirim ringkasan
    python -m bot.main --mode cek      # hanya kirim kalau ada kota yang statusnya naik
    python -m bot.main --coba          # tidak mengirim apa pun, hanya membuat file di folder arsip/

Variabel lingkungan (di GitHub: Settings > Secrets and variables > Actions):
    FIRMS_MAP_KEY          kunci gratis dari https://firms.modaps.eosdis.nasa.gov/api/map_key/
    TELEGRAM_BOT_TOKEN     token dari @BotFather
    TELEGRAM_CHAT_KALTENG  ID kanal, misalnya @jagaudara_kalteng (nama secret sesuai config/provinsi.json)
    WAQI_TOKEN             opsional, token gratis dari https://aqicn.org/data-platform/token/
"""
import argparse
import csv
import hashlib
import json
import os
import sys
from datetime import datetime, timedelta, timezone

from . import analisis, kartu, pesan, sumber, telegram

AKAR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# Ringkasan + PDF dikirim tiap 3 jam pada putaran yang jatuh di jam 06.00-23.59 WIB
# (jadwal 06, 09, 12, 15, 18, 21). Putaran 00 dan 03 hanya mengirim kalau status naik.
JAM_HARIAN_WIB = range(6, 24)
# jarak antartitik grid peta (derajat): angin dan prakiraan asap
LANGKAH_GRID = {"angin": 1.0, "pm25": 0.5}


def _baca_json(path, bawaan):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, ValueError):
        return bawaan


def _tulis_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


LOG_JADWAL = os.path.join(AKAR, "state", "log-jadwal.csv")
KOLOM_LOG = ["mulai_wib", "pemicu", "slot_wib", "terlambat_menit", "mode", "pesan_terkirim"]


def _slot(dt):
    """Slot jadwal (06.00, 09.00, ... WIB) tempat waktu ini jatuh, sebagai teks 'YYYY-MM-DD HH.00'."""
    wib = dt.astimezone(analisis.WIB)
    return f"{wib:%Y-%m-%d} {wib.hour - wib.hour % 3:02d}.00"


def _pemicu():
    """jadwal = cron GitHub, eksternal = cron-job.org (workflow_dispatch dengan pemicu=eksternal), manual = tombol Run."""
    acara = os.environ.get("GITHUB_EVENT_NAME", "")
    if acara == "schedule":
        return "jadwal"
    if acara == "workflow_dispatch":
        return "eksternal" if os.environ.get("PEMICU") == "eksternal" else "manual"
    return "lain"


def _catat_jadwal(mulai, mode, terkirim):
    """Catat jam bot benar-benar mulai dibanding slot jadwalnya (06.00, 09.00, ... WIB).

    Hanya di GitHub Actions dan bukan saat uji, supaya log berisi jadwal asli.
    Dari log ini terlihat seberapa terlambat jadwal otomatis GitHub.
    """
    if os.environ.get("GITHUB_ACTIONS") != "true" or os.environ.get("FIXTURES"):
        return
    wib = mulai.astimezone(analisis.WIB)
    slot = wib.replace(hour=wib.hour - wib.hour % 3, minute=0, second=0, microsecond=0)
    pemicu = _pemicu()
    terjadwal = pemicu in ("jadwal", "eksternal")  # slot hanya bermakna untuk jalan terjadwal
    baris = {
        "mulai_wib": f"{wib:%Y-%m-%d %H.%M}",
        "pemicu": pemicu,
        "slot_wib": f"{slot:%Y-%m-%d %H.%M}" if terjadwal else "",
        "terlambat_menit": int((wib - slot) / timedelta(minutes=1)) if terjadwal else "",
        "mode": mode,
        "pesan_terkirim": terkirim,
    }
    baru = not os.path.exists(LOG_JADWAL)
    os.makedirs(os.path.dirname(LOG_JADWAL), exist_ok=True)
    with open(LOG_JADWAL, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=KOLOM_LOG)
        if baru:
            w.writeheader()
        w.writerow(baris)


def _kirim_panduan(token, chat, path, sha_lama, prov, selalu=False):
    """Kirim PDF panduan ke kanal.

    selalu=True: dikirim bersama setiap pesan. Selain itu hanya kalau belum pernah dikirim atau isinya berubah.
    PDF disematkan (pin) hanya kalau isinya baru, supaya kanal tidak penuh sematan yang sama.
    Mengembalikan sha PDF yang sudah disematkan (sha lama kalau gagal, supaya dicoba lagi di putaran berikutnya).
    """
    try:
        with open(path, "rb") as f:
            sha = hashlib.sha256(f.read()).hexdigest()
    except FileNotFoundError:
        print(f"[{prov['id']}] PDF panduan tidak ditemukan: {path}")
        return sha_lama
    baru = sha != sha_lama
    if not (baru or selalu):
        return sha_lama
    try:
        mid = telegram.kirim_dokumen(token, chat, path, f"📄 Panduan keluarga menghadapi kabut asap ({prov['nama']}). "
                                     "Simpan dan teruskan ke keluarga. Bisa dicetak untuk ditempel atau dibacakan.")
    except telegram.GagalKirim as e:
        print(f"[{prov['id']}] GAGAL kirim PDF panduan: {e}")
        return sha_lama
    print(f"[{prov['id']}] PDF panduan dikirim ke kanal")
    if not baru:
        return sha_lama
    try:
        telegram.sematkan(token, chat, mid)
    except telegram.GagalKirim as e:
        print(f"[{prov['id']}] PDF panduan terkirim, tapi gagal disematkan (beri bot izin admin 'Pin/Edit messages'): {e}")
    return sha


def jalankan(mode="otomatis", coba=False, sekarang=None, hanya=None):
    mulai = datetime.now(timezone.utc)
    sekarang = sekarang or mulai
    if os.environ.get("WAKTU_UJI"):
        sekarang = datetime.fromisoformat(os.environ["WAKTU_UJI"])
    cfg = _baca_json(os.path.join(AKAR, "config", "provinsi.json"), {})
    batas = _baca_json(os.path.join(AKAR, "data", "batas-provinsi.geojson"), {"features": []})
    fitur = {f["properties"]["kode"]: f for f in batas["features"]}
    status_path = os.path.join(os.environ.get("STATE_DIR") or os.path.join(AKAR, "state"), "status.json")
    status = _baca_json(status_path, {})

    map_key = os.environ.get("FIRMS_MAP_KEY", "")
    tg_token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    waqi = os.environ.get("WAQI_TOKEN", "")
    radius = cfg.get("radius_kota_km", 50)
    panduan_pdf = os.path.join(AKAR, cfg["panduan_pdf"]) if cfg.get("panduan_pdf") else ""

    jam_wib = sekarang.astimezone(analisis.WIB).hour
    # Pencegah kirim dobel: cron-job.org dan cron GitHub (cadangan) bisa sama-sama jalan untuk slot yang sama.
    # Pada mode otomatis, provinsi yang slot ini sudah selesai dikirim akan dilewati.
    otomatis = mode == "otomatis"
    slot = _slot(sekarang)
    dilewati = []
    if mode == "otomatis":
        mode = "harian" if jam_wib in JAM_HARIAN_WIB else "cek"

    def _sudah_dikirim(prov):
        return otomatis and not coba and status.get(prov["id"], {}).get("slot", "") == slot

    # Grid angin dan asap diambil SEKALI untuk gabungan wilayah semua provinsi yang diproses
    # (peta antarprovinsi saling tumpang tindih), lalu dipotong per provinsi. Ini menghemat
    # kuota gratis Open-Meteo: ±800 lokasi per putaran, bukan ±1.250.
    kotak_peta = {}
    for prov in cfg.get("provinsi", []):
        f = fitur.get(prov.get("kode_bps"))
        if prov.get("aktif") and f and (not hanya or prov["id"] in hanya) and not _sudah_dikirim(prov):
            kotak_peta[prov["id"]] = kartu.batas_peta(f["geometry"])
    grid = {}

    def _grid(jenis):
        if jenis not in grid:
            k = kotak_peta.values()
            bb = (min(b[0] for b in k), min(b[1] for b in k), max(b[2] for b in k), max(b[3] for b in k))
            nama = f"grid_{jenis}_{'-'.join(kotak_peta)}.json"
            try:
                grid[jenis] = (sumber.angin_grid(bb, LANGKAH_GRID[jenis], nama) if jenis == "angin"
                               else sumber.pm25_grid(bb, LANGKAH_GRID[jenis], nama))
            except (sumber.GagalAmbil, KeyError, ValueError, TypeError) as e:
                print(f"grid {jenis} gagal, peta tanpa lapisan {jenis}: {e}")
                grid[jenis] = None
        return grid[jenis]

    ringkasan = []
    galat = 0
    terkirim = 0
    for prov in cfg.get("provinsi", []):
        if not prov.get("aktif"):
            continue
        if hanya and prov["id"] not in hanya:
            continue
        slot_lama = status.get(prov["id"], {}).get("slot", "")
        if _sudah_dikirim(prov):
            dilewati.append(prov["id"])
            continue
        f = fitur.get(prov["kode_bps"])
        if not f:
            print(f"[{prov['id']}] batas wilayah tidak ditemukan, dilewati")
            continue
        geom = f["geometry"]
        try:
            # ambil titik panas seluas peta di kartu (lebih lebar dari provinsi), supaya tidak terpotong garis lurus
            b1, b2 = analisis.bbox_wilayah(geom), kartu.batas_peta(geom)
            titik = sumber.titik_api((min(b1[0], b2[0]), min(b1[1], b2[1]), max(b1[2], b2[2]), max(b1[3], b2[3])),
                                     map_key)
        except sumber.GagalAmbil as e:
            print(f"[{prov['id']}] GAGAL ambil titik panas: {e}")
            galat += 1
            continue
        prak, stas = {}, {}
        for k in prov["kota"]:
            kunci = k["nama"].lower().replace(" ", "_")
            try:
                prak[k["nama"]] = analisis.ringkas_prakiraan(sumber.prakiraan_pm25(k["lat"], k["lon"], kunci), sekarang)
            except (sumber.GagalAmbil, KeyError, ValueError) as e:
                print(f"[{prov['id']}] prakiraan {k['nama']} gagal: {e}")
            stas[k["nama"]] = sumber.stasiun_terdekat(k["lat"], k["lon"], waqi, kunci)

        hasil = analisis.nilai_provinsi(prov, geom, titik, prak, stas, radius, sekarang)

        # lapisan peta tambahan; kalau gagal, kartu tetap dibuat tanpa lapisan ini
        bbox_peta = kartu.batas_peta(geom)
        try:
            hasil["angin"] = analisis.ringkas_angin(
                sumber.potong_grid(_grid("angin"), bbox_peta, LANGKAH_GRID["angin"]), sekarang)
        except (KeyError, ValueError, TypeError) as e:
            print(f"[{prov['id']}] data angin gagal, peta tanpa panah angin: {e}")
            hasil["angin"] = None
        try:
            hasil["asap_grid"] = analisis.ringkas_asap_grid(
                sumber.potong_grid(_grid("pm25"), bbox_peta, LANGKAH_GRID["pm25"]), sekarang)
        except (KeyError, ValueError, TypeError) as e:
            print(f"[{prov['id']}] grid asap gagal, peta tanpa bayangan asap: {e}")
            hasil["asap_grid"] = None

        lama = status.get(prov["id"], {}).get("kota", {})
        # peringatan di luar jadwal hanya kalau ada kota yang naik ke SIAGA atau BAHAYA,
        # supaya pelanggan tidak kebanjiran pesan
        naik = [(k["nama"], lama.get(k["nama"], 0), k["tingkat"]) for k in hasil["kota"]
                if k["tingkat"] > lama.get(k["nama"], 0) and k["tingkat"] >= 2]

        # arsip
        cap = sekarang.astimezone(analisis.WIB)
        folder = os.path.join(os.environ.get("ARSIP_DIR") or os.path.join(AKAR, "arsip"), f"{cap:%Y}", f"{cap:%m}")
        os.makedirs(folder, exist_ok=True)
        dasar = os.path.join(folder, f"{cap:%d-%H%M}-{prov['id']}")
        try:
            png = kartu.buat(hasil, geom, [x for x in batas["features"] if x is not f], dasar + ".png", radius,
                             status_lama=lama or None)
        except Exception as e:  # kartu gagal dibuat: pesan teks tetap dikirim
            print(f"[{prov['id']}] GAGAL membuat kartu, hanya teks yang dikirim: {e!r}")
            png = None
            galat += 1
        uji = "[CONTOH, DATA UJI]\n" if os.environ.get("FIXTURES") else ""
        teks_tg = uji + pesan.harian(hasil, radius)
        teks_wa = uji + pesan.harian(hasil, radius, wa=True)
        with open(dasar + "-whatsapp.txt", "w", encoding="utf-8") as fh:
            fh.write(teks_wa)
        with open(dasar + "-telegram.html", "w", encoding="utf-8") as fh:
            fh.write(teks_tg)

        kirim = []
        if mode == "harian":
            kirim = [("foto", png, pesan.keterangan_foto(hasil)), ("teks", teks_tg)] if png else [("teks", teks_tg)]
        elif naik:
            teks_al = uji + pesan.peringatan(hasil, naik)
            with open(dasar + "-peringatan-whatsapp.txt", "w", encoding="utf-8") as fh:
                fh.write(uji + pesan.peringatan(hasil, naik, wa=True))
            kirim = [("teks", teks_al)] + ([("foto", png, pesan.keterangan_foto(hasil))] if png else [])

        chat = os.environ.get(prov.get("chat_env", ""), "")
        panduan_lama = status.get(prov["id"], {}).get("panduan_sha", "")
        panduan_sha = panduan_lama
        gagal_kirim = False
        if kirim and not coba:
            if not (tg_token and chat):
                print(f"[{prov['id']}] TELEGRAM_BOT_TOKEN atau {prov.get('chat_env')} belum diisi, pesan tidak dikirim")
            else:
                try:
                    for item in kirim:
                        if item[0] == "foto":
                            telegram.kirim_foto(tg_token, chat, item[1], item[2])
                        else:
                            telegram.kirim_teks(tg_token, chat, item[1])
                        terkirim += 1
                except telegram.GagalKirim as e:
                    print(f"[{prov['id']}] GAGAL kirim: {e}")
                    galat += 1
                    gagal_kirim = True
        # PDF panduan ikut setiap pesan; tanpa pesan pun tetap dikirim kalau isinya baru
        if panduan_pdf and not coba and tg_token and chat:
            panduan_sha = _kirim_panduan(tg_token, chat, panduan_pdf, panduan_lama, prov, selalu=bool(kirim))

        status[prov["id"]] = {
            "waktu": sekarang.isoformat(),
            "tingkat": hasil["tingkat"],
            "titik_prov_24j": hasil["titik_prov_24j"],
            "kota": {k["nama"]: k["tingkat"] for k in hasil["kota"]},
            "panduan_sha": panduan_sha,
            # slot ditandai selesai hanya kalau semua pesan terkirim, supaya pemicu cadangan bisa mengulang
            "slot": slot if (otomatis and not coba and not gagal_kirim) else slot_lama,
        }
        if not coba:
            _tulis_json(status_path, status)  # simpan tiap provinsi, supaya yang sudah terkirim tidak dikirim ulang
        ringkasan.append(f"[{prov['id']}] {analisis.TINGKAT[hasil['tingkat']]}, {hasil['titik_prov_24j']} titik panas, "
                         f"mode {mode}, {'kirim ' + str(len(kirim)) + ' pesan' if kirim else 'tidak ada pesan'}"
                         f"{' (uji coba, tidak dikirim)' if coba and kirim else ''} -> {os.path.relpath(dasar, AKAR)}")

    semua_dilewati = bool(dilewati) and not ringkasan
    if dilewati:
        ringkasan.append(f"Slot {slot} WIB sudah dikirim sebelumnya untuk {', '.join(dilewati)}, dilewati supaya tidak dobel")
    if not coba:
        _tulis_json(status_path, status)
    keterangan = mode + (" (coba)" if coba else "") + (" (dilewati, slot sudah dikirim)" if semua_dilewati else "")
    _catat_jadwal(mulai, keterangan, terkirim)
    print("\n".join(ringkasan) or "Tidak ada provinsi aktif.")
    return 1 if galat else 0


def main():
    ap = argparse.ArgumentParser(description="Bot Peringatan Asap Jaga Udara")
    ap.add_argument("--mode", choices=["otomatis", "harian", "cek"], default="otomatis")
    ap.add_argument("--coba", action="store_true", help="jangan kirim apa pun, hanya buat file arsip")
    ap.add_argument("--provinsi", default="", help="hanya provinsi ini, dipisah koma (mis. kalbar,kalsel). Kosong = semua yang aktif")
    a = ap.parse_args()
    hanya = {x.strip().lower() for x in a.provinsi.split(",") if x.strip()} or None
    sys.exit(jalankan(a.mode, a.coba, hanya=hanya))


if __name__ == "__main__":
    main()
