"""Mengirim pesan dan foto ke kanal Telegram lewat Bot API (gratis)."""
import json
import mimetypes
import os
import time
import urllib.error
import urllib.request
import uuid


class GagalKirim(Exception):
    pass


def _post(url, data, headers, tries=3):
    """Kirim ke Bot API. Semua jenis gagal (HTTP, koneksi putus, batas waktu) dijadikan GagalKirim.

    Gangguan sementara (koneksi putus, server 5xx, 429 terlalu sering) dicoba ulang dengan jeda,
    supaya satu gangguan jaringan tidak menghentikan seluruh putaran.
    """
    last = None
    for i in range(tries):
        req = urllib.request.Request(url, data=data, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                hasil = json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            isi = e.read().decode(errors="replace")[:200]
            last = GagalKirim(f"Telegram {e.code}: {isi}")
            if e.code == 429:
                # Telegram memberi tahu berapa detik harus menunggu
                try:
                    tunggu = int(json.loads(isi).get("parameters", {}).get("retry_after", 5))
                except (ValueError, AttributeError):
                    tunggu = 5
                time.sleep(min(tunggu, 60) + 1)
                continue
            if e.code >= 500:
                time.sleep(5 * (i + 1))
                continue
            raise last  # 400/401/403 dst.: salah isi/izin, tidak ada gunanya diulang
        except (OSError, ValueError) as e:
            # URLError, batas waktu, koneksi diputus server (RemoteDisconnected/ConnectionReset),
            # atau balasan yang bukan JSON
            last = GagalKirim(f"Telegram tidak terjangkau: {e!r}")
            time.sleep(5 * (i + 1))
            continue
        if not hasil.get("ok"):
            raise GagalKirim(f"Telegram: {hasil}")
        return hasil
    raise last


def kirim_teks(token, chat_id, teks):
    # Telegram membatasi 4096 karakter per pesan
    for i in range(0, len(teks), 4000):
        body = json.dumps({"chat_id": chat_id, "text": teks[i:i + 4000], "parse_mode": "HTML",
                           "disable_web_page_preview": True}).encode()
        _post(f"https://api.telegram.org/bot{token}/sendMessage", body, {"Content-Type": "application/json"})


def _kirim_file(token, metode, kolom, chat_id, path, keterangan, nama_file, tipe_bawaan):
    batas = uuid.uuid4().hex
    with open(path, "rb") as f:
        isi = f.read()
    tipe = mimetypes.guess_type(path)[0] or tipe_bawaan
    bagian = []
    for k, v in (("chat_id", str(chat_id)), ("caption", keterangan[:1000])):
        bagian.append(f"--{batas}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n".encode())
    bagian.append(f"--{batas}\r\nContent-Disposition: form-data; name=\"{kolom}\"; filename=\"{nama_file}\"\r\n"
                  f"Content-Type: {tipe}\r\n\r\n".encode() + isi + b"\r\n")
    bagian.append(f"--{batas}--\r\n".encode())
    return _post(f"https://api.telegram.org/bot{token}/{metode}", b"".join(bagian),
                 {"Content-Type": f"multipart/form-data; boundary={batas}"})


def kirim_foto(token, chat_id, path, keterangan):
    _kirim_file(token, "sendPhoto", "photo", chat_id, path, keterangan, "kartu.png", "image/png")


def kirim_dokumen(token, chat_id, path, keterangan):
    """Mengirim file (misalnya PDF panduan). Mengembalikan message_id."""
    hasil = _kirim_file(token, "sendDocument", "document", chat_id, path, keterangan,
                        os.path.basename(path), "application/octet-stream")
    return hasil["result"]["message_id"]


def sematkan(token, chat_id, message_id):
    """Menyematkan (pin) pesan. Di kanal, bot perlu izin admin untuk menyematkan/mengedit pesan."""
    body = json.dumps({"chat_id": chat_id, "message_id": message_id, "disable_notification": True}).encode()
    _post(f"https://api.telegram.org/bot{token}/pinChatMessage", body, {"Content-Type": "application/json"})
