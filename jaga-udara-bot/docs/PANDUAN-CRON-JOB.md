# Memasang pemicu tepat waktu dengan cron-job.org

Jadwal bawaan GitHub sering terlambat atau terlewat. Pada pengamatan 10–11 Okt 2026, hanya 2 dari 6 jadwal yang jalan. Karena itu bot dinyalakan dari luar oleh **cron-job.org** (gratis, tanpa kartu kredit). Layanan ini menekan tombol "Run workflow" tepat pukul 00.01, 03.01, 06.01, 09.01, 12.01, 15.01, 18.01, dan 21.01 WIB.

Jadwal GitHub tetap ada sebagai cadangan pada menit :20. Kalau slot itu sudah dikirim lewat cron-job.org, bot melewatinya, jadi pesan tidak terkirim dua kali.

Waktu yang dibutuhkan sekitar 15 menit. Ada dua bagian: membuat token GitHub, lalu membuat jadwal di cron-job.org.

---

## Bagian A. Membuat token GitHub (5 menit)

Token ini semacam "kunci" yang hanya bisa dipakai untuk menekan tombol Run bot di repo JagaUdaraBot. Token ini **tidak bisa** membaca secrets (token Telegram, kunci NASA) dan **tidak bisa** mengubah kode.

1. Buka https://github.com/settings/personal-access-tokens/new (pastikan sudah masuk ke akun GitHub `alihabiebie`).
2. Isi:
   - **Token name:** `cron-job jaga udara`
   - **Expiration:** pilih **1 year** atau **Custom** (paling lama yang tersedia). Catat tanggalnya di kalender. GitHub juga akan mengirim email sebelum token kedaluwarsa.
   - **Resource owner:** `alihabiebie`
   - **Repository access:** pilih **Only select repositories**, lalu pilih **JagaUdaraBot**.
3. Di bagian **Permissions → Repository permissions**, cari **Actions**, lalu ubah menjadi **Read and write**. Izin lain biarkan seperti semula ("Metadata: Read" otomatis ikut).
4. Klik **Generate token**, lalu **salin** token yang diawali `github_pat_...`.
   Token hanya ditampilkan sekali. Simpan sementara di catatan HP. **Jangan dikirim ke grup, chat, atau orang lain.**

---

## Bagian B. Membuat jadwal di cron-job.org (10 menit)

1. Daftar di https://console.cron-job.org/signup dengan email Anda, lalu konfirmasi lewat email.
2. Setelah masuk, klik **CREATE CRONJOB**.

### Tab "COMMON"

- **Title:** `Jaga Udara – peringatan asap`
- **URL:**
  ```
  https://api.github.com/repos/alihabiebie/JagaUdaraBot/actions/workflows/peringatan-asap.yml/dispatches
  ```
- **Enable job:** aktif.
- **Execution schedule:** pilih **Custom** (atau "User-defined"), lalu atur:
  - **Days of month:** semua (Every day)
  - **Days of week:** semua
  - **Months:** semua
  - **Hours:** 0, 3, 6, 9, 12, 15, 18, 21
  - **Minutes:** 1
- **Time zone:** **Asia/Jakarta**. Kalau pilihan ini tidak ada di halaman job, aturlah di **Settings** akun.
- **Notify me when…:** centang **execution of the cronjob fails** dan **the cronjob will be disabled because of too many failures**. Supaya Anda dapat email kalau ada masalah.

### Tab "ADVANCED"

- **Request method:** `POST`
- **Headers** (klik tambah header, satu per baris):

  | Key | Value |
  |---|---|
  | `Accept` | `application/vnd.github+json` |
  | `Authorization` | `Bearer github_pat_...` (tempel token dari Bagian A, didahului kata `Bearer` dan satu spasi) |
  | `X-GitHub-Api-Version` | `2022-11-28` |
  | `Content-Type` | `application/json` |

- **Request body:** untuk **uji coba dulu**, isi:
  ```json
  {"ref":"main","inputs":{"mode":"otomatis","coba":"ya","pemicu":"eksternal"}}
  ```
- **Save responses in job history:** aktifkan kalau ada, supaya pesan error GitHub terlihat.

### Uji coba

1. Klik **TEST RUN**, lalu **START TEST RUN**.
2. Hasil yang benar adalah **HTTP 204 No Content**. Di tab Actions GitHub akan muncul run baru "Peringatan asap". Karena `coba` = `ya`, run uji ini tidak mengirim pesan ke kanal.
3. Kalau hasilnya:
   - **401 / 403:** token salah atau izin "Actions: Read and write" belum diberikan. Periksa header Authorization (harus `Bearer ` + token).
   - **404:** URL salah, atau token tidak diberi akses ke repo JagaUdaraBot.
   - **422:** isi body salah ketik.

### Pakai sungguhan

Setelah uji berhasil, ubah **Request body** menjadi:
```json
{"ref":"main","inputs":{"mode":"otomatis","pemicu":"eksternal"}}
```
Lalu klik **SAVE**. Selesai.

---

## Cara memantau

- **Riwayat cron-job.org:** setiap pemicu tercatat beserta status HTTP-nya (204 = berhasil).
- **`jaga-udara-bot/state/log-jadwal.csv` di repo:** setiap kali bot jalan, tercatat jam mulai, pemicunya (`eksternal` = cron-job.org, `jadwal` = cadangan GitHub, `manual` = tombol Run), dan keterlambatannya. Kalau cron-job.org sudah mengirim, run cadangan GitHub tercatat dengan keterangan "dilewati, slot sudah dikirim".

## Kalau token kedaluwarsa atau bocor

1. Buat token baru (Bagian A).
2. Di cron-job.org, ganti nilai header `Authorization` dengan token baru.
3. Hapus token lama di https://github.com/settings/personal-access-tokens.

Kalau Anda curiga token bocor, segera hapus token itu. Selama token belum diganti, bot tetap berjalan lewat jadwal cadangan GitHub.
