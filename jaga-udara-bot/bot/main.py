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
import hashlib
import json
import os
import sys
from datetime import datetime, timezone

from . import analisis, kartu, pesan, sumber, telegram

AKAR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
JAM_HARIAN_WIB = (5, 6, 7)  # ringkasan dikirim pada putaran yang jatuh di jam ini


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


def _kirim_panduan(token, chat, path, sha_lama, prov):
    """Kirim PDF panduan ke kanal lalu sematkan, hanya kalau belum pernah dikirim atau isinya berubah.

    Mengembalikan sha PDF yang sudah terkirim (sha lama kalau gagal, supaya dicoba lagi di putaran berikutnya).
    """
    try:
        with open(path, "rb") as f:
            sha = hashlib.sha256(f.read()).hexdigest()
    except FileNotFoundError:
        print(f"[{prov['id']}] PDF panduan tidak ditemukan: {path}")
        return sha_lama
    if sha == sha_lama:
        return sha_lama
    try:
        mid = telegram.kirim_dokumen(token, chat, path, f"📄 Panduan keluarga menghadapi kabut asap ({prov['nama']}). "
                                     "Simpan dan teruskan ke keluarga. Bisa dicetak untuk ditempel atau dibacakan.")
    except telegram.GagalKirim as e:
        print(f"[{prov['id']}] GAGAL kirim PDF panduan: {e}")
        return sha_lama
    try:
        telegram.sematkan(token, chat, mid)
    except telegram.GagalKirim as e:
        print(f"[{prov['id']}] PDF panduan terkirim, tapi gagal disematkan (beri bot izin admin 'Pin/Edit messages'): {e}")
    print(f"[{prov['id']}] PDF panduan dikirim ke kanal")
    return sha


def jalankan(mode="otomatis", coba=False, sekarang=None):
    sekarang = sekarang or datetime.now(timezone.utc)
    if os.environ.get("WAKTU_UJI"):
        sekarang = datetime.fromisoformat(os.environ["WAKTU_UJI"])
    cfg = _baca_json(os.path.join(AKAR, "config", "provinsi.json"), {})
    batas = _baca_json(os.path.join(AKAR, "data", "batas-provinsi.geojson"), {"features": []})
    fitur = {f["properties"]["kode"]: f for f in batas["features"]}
    status_path = os.path.join(AKAR, "state", "status.json")
    status = _baca_json(status_path, {})

    map_key = os.environ.get("FIRMS_MAP_KEY", "")
    tg_token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    waqi = os.environ.get("WAQI_TOKEN", "")
    radius = cfg.get("radius_kota_km", 50)
    panduan_pdf = os.path.join(AKAR, cfg["panduan_pdf"]) if cfg.get("panduan_pdf") else ""

    jam_wib = sekarang.astimezone(analisis.WIB).hour
    if mode == "otomatis":
        mode = "harian" if jam_wib in JAM_HARIAN_WIB else "cek"

    ringkasan = []
    galat = 0
    for prov in cfg.get("provinsi", []):
        if not prov.get("aktif"):
            continue
        f = fitur.get(prov["kode_bps"])
        if not f:
            print(f"[{prov['id']}] batas wilayah tidak ditemukan, dilewati")
            continue
        geom = f["geometry"]
        try:
            titik = sumber.titik_api(analisis.bbox_wilayah(geom), map_key)
        except sumber.GagalAmbil as e:
            print(f"[{prov['id']}] GAGAL ambil titik api: {e}")
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
        png = kartu.buat(hasil, geom, [x for x in batas["features"] if x is not f], dasar + ".png", radius)
        uji = "[CONTOH, DATA UJI]\n" if os.environ.get("FIXTURES") else ""
        teks_tg = uji + pesan.harian(hasil, radius)
        teks_wa = uji + pesan.harian(hasil, radius, wa=True)
        with open(dasar + "-whatsapp.txt", "w", encoding="utf-8") as fh:
            fh.write(teks_wa)
        with open(dasar + "-telegram.html", "w", encoding="utf-8") as fh:
            fh.write(teks_tg)

        kirim = []
        if mode == "harian":
            kirim = [("foto", png, pesan.keterangan_foto(hasil)), ("teks", teks_tg)]
        elif naik:
            teks_al = uji + pesan.peringatan(hasil, naik)
            with open(dasar + "-peringatan-whatsapp.txt", "w", encoding="utf-8") as fh:
                fh.write(uji + pesan.peringatan(hasil, naik, wa=True))
            kirim = [("teks", teks_al), ("foto", png, pesan.keterangan_foto(hasil))]

        chat = os.environ.get(prov.get("chat_env", ""), "")
        panduan_lama = status.get(prov["id"], {}).get("panduan_sha", "")
        panduan_sha = panduan_lama
        if panduan_pdf and not coba and tg_token and chat:
            panduan_sha = _kirim_panduan(tg_token, chat, panduan_pdf, panduan_lama, prov)
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
                except telegram.GagalKirim as e:
                    print(f"[{prov['id']}] GAGAL kirim: {e}")
                    galat += 1

        status[prov["id"]] = {
            "waktu": sekarang.isoformat(),
            "tingkat": hasil["tingkat"],
            "titik_prov_24j": hasil["titik_prov_24j"],
            "kota": {k["nama"]: k["tingkat"] for k in hasil["kota"]},
            "panduan_sha": panduan_sha,
        }
        ringkasan.append(f"[{prov['id']}] {analisis.TINGKAT[hasil['tingkat']]}, {hasil['titik_prov_24j']} titik api, "
                         f"mode {mode}, {'kirim ' + str(len(kirim)) + ' pesan' if kirim else 'tidak ada pesan'}"
                         f"{' (uji coba, tidak dikirim)' if coba and kirim else ''} -> {os.path.relpath(dasar, AKAR)}")

    if not coba:
        _tulis_json(status_path, status)
    print("\n".join(ringkasan) or "Tidak ada provinsi aktif.")
    return 1 if galat else 0


def main():
    ap = argparse.ArgumentParser(description="Bot Peringatan Asap Jaga Udara")
    ap.add_argument("--mode", choices=["otomatis", "harian", "cek"], default="otomatis")
    ap.add_argument("--coba", action="store_true", help="jangan kirim apa pun, hanya buat file arsip")
    a = ap.parse_args()
    sys.exit(jalankan(a.mode, a.coba))


if __name__ == "__main__":
    main()
