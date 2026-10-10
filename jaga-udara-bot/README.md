# Bot Peringatan Asap Jaga Udara

Bot otomatis yang memantau titik api dan asap di Kalimantan dan Sumatera, lalu mengirim kabar berbahasa sederhana ke kanal Telegram per provinsi. Setiap kirim, bot juga membuat gambar kartu dan teks siap salin untuk Saluran WhatsApp.

Inisiatif warga, bukan kanal resmi pemerintah. Biaya: Rp 0.

![Contoh kartu harian](docs/contoh/kartu-harian.png)

## Apa yang dikerjakan bot

Setiap 6 jam (06.00, 12.00, 18.00, 00.00 WIB) bot:

1. **Mengambil data**
   - Titik api 3 hari terakhir dari satelit VIIRS (NASA FIRMS)
   - Prakiraan PM2.5 per jam untuk tiap kota (Open-Meteo, model CAMS)
   - Angka stasiun pemantau terdekat (WAQI), kalau token diisi
2. **Menentukan status tiap kota**: AMAN, WASPADA, SIAGA, atau BAHAYA (aturannya di bawah)
3. **Mengirim**
   - Pukul 06.00 WIB: ringkasan harian (gambar kartu + pesan) ke kanal Telegram
   - Putaran lain: hanya mengirim peringatan kalau ada kota yang naik ke SIAGA atau BAHAYA
4. **Menyimpan** gambar, teks Telegram, dan teks WhatsApp di folder `arsip/`, serta status terakhir di `state/status.json`

Contoh pesan: [harian](docs/contoh/pesan-harian-whatsapp.txt), [peringatan](docs/contoh/pesan-peringatan-whatsapp.txt). Semua contoh di folder `docs/contoh/` memakai **data uji buatan**, bukan data asli.

## Cara status ditentukan

Status kota = tingkat **tertinggi** dari tiga penilaian berikut.

| Penilaian | AMAN | WASPADA | SIAGA | BAHAYA |
|---|---|---|---|---|
| Prakiraan PM2.5 rata-rata 24 jam ke depan (kategori ISPU) | Baik | Sedang | Tidak Sehat | Sangat Tidak Sehat / Berbahaya |
| Titik api dalam 50 km, 24 jam terakhir | 0–9 | 10–49 | 50–199 | 200 ke atas |
| Stasiun terdekat ≤30 km, data ≤6 jam (AQI skala AS) | 0–100 | 101–150 | 151–200 | 201 ke atas |

- Batas ISPU mengikuti Permen LHK No. 14/2020.
- **Ambang titik api adalah ambang awal** dan perlu disesuaikan setelah beberapa minggu dipakai. Ubah di `bot/analisis.py` (`AMBANG_TITIK_API`).
- Titik api berkeyakinan rendah dibuang. Deteksi dari beberapa satelit di sel ±1 km yang sama dihitung satu.

## Memasang (sekali saja, sekitar 30 menit)

### 1. Repo GitHub
Buat repo baru (Public, supaya GitHub Actions gratis), lalu unggah seluruh isi folder ini.

File jadwal harus ada tepat di `.github/workflows/peringatan-asap.yml` di akar repo (bukan di dalam folder `jaga-udara-bot/`). Nama folder tidak boleh mengandung spasi: `.github` dan `workflows`, bukan `.github ` atau ` workflows `. Kalau ada spasi, tab Actions tetap menampilkan "Get started".

### 2. Kunci data NASA FIRMS (gratis)
Buka https://firms.modaps.eosdis.nasa.gov/api/map_key/ , masukkan email, lalu salin MAP_KEY yang dikirim.

### 3. Bot dan kanal Telegram
1. Di Telegram, buka **@BotFather**, kirim `/newbot`, beri nama (misalnya "Jaga Udara Bot"), lalu salin **token**-nya.
2. Buat **kanal** baru (New Channel), misalnya `Jaga Udara – Kalteng`, jenis Public, dengan alamat misalnya `@jagaudara_kalteng`.
3. Tambahkan bot sebagai **admin** kanal itu, dengan izin "Post messages".

### 4. Simpan rahasia di GitHub
Buka repo, lalu **Settings > Secrets and variables > Actions > New repository secret**:

| Nama | Isi |
|---|---|
| `FIRMS_MAP_KEY` | kunci dari langkah 2 |
| `TELEGRAM_BOT_TOKEN` | token dari @BotFather |
| `TELEGRAM_CHAT_KALTENG` | alamat kanal, misalnya `@jagaudara_kalteng` |
| `WAQI_TOKEN` | opsional, token WAQI |

### 5. Coba jalankan
Buka tab **Actions > Peringatan asap > Run workflow**:
- isi `coba` = `ya` untuk uji tanpa mengirim (hasilnya ada di folder `jaga-udara-bot/arsip/`)
- isi `mode` = `harian` untuk langsung mengirim ringkasan ke kanal

Setelah itu bot berjalan sendiri sesuai jadwal.

## Menambah provinsi

Di `config/provinsi.json`, ubah `"aktif": false` menjadi `true` untuk provinsi yang diinginkan (Kalbar, Kalsel, Riau, Jambi, Sumsel sudah disiapkan), lalu buat kanal dan secret `TELEGRAM_CHAT_...` yang sesuai. Kota bisa ditambah dengan nama dan koordinatnya.

## Menjalankan di komputer sendiri

```bash
pip install -r requirements.txt
python tests/buat_fixture.py                  # buat data uji
FIXTURES=tests/fixtures WAKTU_UJI=2026-10-10T23:00:00+00:00 python -m bot.main --coba
python -m unittest discover tests             # uji dasar
```

Dengan data asli: isi variabel `FIRMS_MAP_KEY` (dan lainnya), lalu `python -m bot.main --coba`.

## Batasan yang perlu diketahui

- **Satelit:** satelit VIIRS lewat beberapa kali sehari dengan jeda data sekitar 3 jam. Titik api bisa terlewat kalau tertutup awan atau asap tebal, dan satu titik api belum tentu kebakaran.
- **Prakiraan:** model CAMS beresolusi sekitar 45 km dan bisa jauh lebih rendah dari kenyataan saat kebakaran gambut. Pakai untuk melihat tren.
- **Hitungan per kota:** titik api di sekitar kota dihitung dalam lingkaran 50 km, termasuk yang berada di provinsi tetangga.
- **Jadwal GitHub:** bisa terlambat 5–30 menit. Bot menyimpan arsip setiap putaran supaya repo tetap aktif, karena jadwal otomatis berhenti kalau repo 60 hari tanpa perubahan.
- **Tanpa pengujian lapangan:** bot belum diuji dengan data asli karena dibuat di lingkungan tanpa akses ke NASA dan Open-Meteo. Lakukan langkah 5 dengan `coba = ya` dulu.

## Sumber data dan lisensi

- Titik api: NASA FIRMS (VIIRS 375 m NRT)
- Prakiraan: Open-Meteo Air Quality API (CC BY 4.0), berbasis Copernicus Atmosphere Monitoring Service
- Stasiun: World Air Quality Index Project dan badan pemantau asal, termasuk BMKG. Wajib dicantumkan; tidak boleh dijual.
- Batas provinsi: Peta Dasar BAKOSURTANAL 1:250.000, via github.com/ans-4175/peta-indonesia-geojson. Cek lisensinya sebelum dipakai lebih luas.
- Kategori ISPU: Permen LHK No. 14/2020
