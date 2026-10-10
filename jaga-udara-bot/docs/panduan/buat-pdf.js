// Membuat panduan-asap-keluarga.pdf dari halaman panduan interaktif (panduan-asap-keluarga.html).
// Semua bagian yang di halaman harus diketuk (masker, cara pakai, kamar bersih, tanda bahaya)
// dibuka sekaligus supaya bisa dibaca dan dicetak.
//
// Jalankan dari folder ini:  node buat-pdf.js
// Perlu Playwright (npm i playwright) dan Chromium.
const path = require("path");
const { chromium } = require("playwright");

const SUMBER = path.join(__dirname, "panduan-asap-keluarga.html");
const HASIL = path.join(__dirname, "..", "panduan-asap-keluarga.pdf");

const CSS = `
  :root{--display:"Inter Display","Inter",sans-serif;--body:"Inter",sans-serif}
  body{font-size:15px;background:#fff}
  nav.top,.tick,.done,#dailyProg,#buildProg,.seg,.stepnav,.hslist{display:none!important}
  .wrap{max-width:none;padding:0}
  section{padding-block:22px;break-before:auto}
  .task,.mask,.bstep,.symp,.task[aria-pressed],.mask[aria-pressed],.bstep[aria-pressed],.symp[aria-pressed]{
    cursor:default;border-color:var(--line)!important;background:var(--paper)!important;box-shadow:none!important}
  .task,.mask,.bstep,.symp,.note,.opt,.rowc,.box,.verdict,.mat,.num,.dont,.person,.cetak-langkah,.cetak-titik,.result,.info{break-inside:avoid}
  .hs{animation:none!important;box-shadow:none!important}
  .hs[aria-pressed="true"]{background:#0B5563!important;color:#fff!important;transform:translate(-50%,-50%)!important}
  .cetak-verdict{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}
  .cetak-langkah-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px}
  .cetak-langkah{background:var(--paper);border:1px solid var(--line);border-radius:16px;padding:10px;display:flex;flex-direction:column;gap:8px}
  .cetak-langkah .plate{aspect-ratio:1;padding:4%}
  .cetak-langkah p{font-size:.9rem}
  .cetak-titik-list{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}
  .cetak-titik{min-height:0}
  h2{break-after:avoid}
`;

(async () => {
  const browser = await chromium.launch({ executablePath: process.env.CHROMIUM || undefined });
  const page = await browser.newPage({ colorScheme: "light", reducedMotion: "reduce" });
  // font Google tidak dipakai; halaman memakai font Inter yang terpasang di komputer
  await page.route(/fonts\.(googleapis|gstatic)\.com/, (r) => r.abort());
  await page.goto("file://" + SUMBER, { waitUntil: "load" });
  await page.addStyleTag({ content: CSS });

  await page.evaluate(() => {
    const $ = (s) => document.querySelector(s);
    const ganti = (el, teks) => { if (el) el.textContent = teks; };
    const hapus = (el) => el && el.remove();

    // teks "Ketuk ..." tidak berlaku di kertas
    ganti($(".hero .head p.muted"),
      "Disusun 7 Oktober 2026 dari panduan Kemenkes, dokter anak, dokter paru, WHO, dan US EPA.");
    hapus($("#harian .head p.muted"));
    ganti($("#masker .head p.muted"), "Garis abu-abu di gambar adalah asap yang masuk.");
    ganti($("#kamar .head p.muted"),
      "Satu kamar yang ditutup rapat dan diberi alat penyaring udara. Arti angka di gambar ada di bawahnya.");
    document.querySelectorAll("#rakit p.muted.small").forEach((p) => { if (/Ketuk/.test(p.textContent)) p.remove(); });
    ganti($("#bahaya .head p.muted"), "Kalau ada SATU saja tanda di bawah ini pada diri sendiri atau keluarga:");

    // masker: tampilkan keempat penjelasan sekaligus
    const V = [
      ["ok", "N95 dengan dua tali di kepala: paling baik", "Menempel rapat di wajah, jadi asap halus tersaring. Ada tulisan N95 di maskernya. Beli di apotek."],
      ["mid", "KN95 tali telinga: pakai kalau N95 tidak ada", "Bahannya menyaring, tapi tali telinga membuatnya lebih sering bocor di pipi. Tekan sampai rapat."],
      ["no", "Masker medis tipis: tidak menyaring asap halus", "Longgar di pipi dan hidung, jadi asap masuk dari samping. Menurut dokter paru, masker ini tidak mampu menyaring asap halus."],
      ["no", "Masker kain: tidak menyaring asap halus", "Asap halus menembus kain. Saputangan dan kain basah juga sama."],
    ];
    const vd = document.createElement("div");
    vd.className = "cetak-verdict";
    V.forEach(([c, h, p]) => {
      const d = document.createElement("div");
      d.className = "verdict " + c;
      d.innerHTML = "<h3></h3><p></p>";
      d.firstChild.textContent = h;
      d.lastChild.textContent = p;
      vd.appendChild(d);
    });
    $("#verdict").replaceWith(vd);

    // cara pakai masker: keempat langkah berjajar
    const STEPS = ["Tutup hidung sampai dagu.", "Tekan kawat di hidung dengan dua tangan sampai mengikuti bentuk hidung.",
      "Pastikan tidak ada celah di pipi. Kalau rapat, asap tetap di luar.",
      "Boleh dipakai berulang. Ganti kalau sudah kotor, rusak, atau terasa berat untuk bernapas. Jangan dicuci."];
    const pics = [...document.querySelectorAll("#stepSrc > div")].map((d) => d.innerHTML);
    const lg = document.createElement("div");
    lg.className = "cetak-langkah-grid";
    STEPS.forEach((t, i) => {
      const d = document.createElement("div");
      d.className = "cetak-langkah";
      d.innerHTML = '<div class="plate"></div><span class="eyebrow"></span><p></p>';
      d.querySelector(".plate").innerHTML = pics[i];
      d.querySelector(".eyebrow").textContent = "Langkah " + (i + 1);
      d.querySelector("p").textContent = t;
      lg.appendChild(d);
    });
    $(".steps").replaceWith(lg);

    // kamar bersih: semua angka dijelaskan
    const H = [
      ["Jendela dan pintu ditutup rapat", "Kalau udara luar membaik, walau sementara, buka jendela untuk mengganti udara. Tutup lagi begitu asap datang."],
      ["Handuk digulung di bawah pintu", "Sumbat celah bawah pintu supaya asap tidak merembes. Jangan sampai pintu sulit dibuka dari dalam."],
      ["Alat penyaring udara (air purifier)", "Pilih yang ada tulisan HEPA. Nyalakan terus di kecepatan paling tinggi. Cek saringannya setiap hari."],
      ["Colok langsung ke dinding", "Jangan pakai kabel rol untuk alat penyaring udara."],
      ["Kipas angin supaya tetap sejuk", "Kamar yang ditutup rapat cepat panas. Pakai kipas angin atau AC."],
      ["Dahulukan yang rentan", "Bayi, lansia, ibu hamil, dan orang sakit tinggal di kamar ini. Raba badan bayi sesering mungkin. Kalau panas atau banyak berkeringat, longgarkan bajunya dan pindah ke tempat yang lebih sejuk."],
      ["Air minum dan obat di dekat Anda", "Sediakan air putih. Penderita asma: letakkan inhaler di tempat yang mudah diambil."],
    ];
    document.querySelectorAll("#scene .hs").forEach((b) => b.setAttribute("aria-pressed", "false"));
    const tl = document.createElement("div");
    tl.className = "cetak-titik-list";
    H.forEach(([h, p], i) => {
      const d = document.createElement("div");
      d.className = "info cetak-titik";
      d.innerHTML = '<span class="n"></span><div><h3></h3><p></p></div>';
      d.querySelector(".n").textContent = i + 1;
      d.querySelector("h3").textContent = h;
      d.querySelector("p").textContent = p;
      tl.appendChild(d);
    });
    $("#info").replaceWith(tl);

    // tanda bahaya: tampilkan tindakannya
    $("#result").className = "result alarm";
    ganti($("#resH"), "Segera ke puskesmas atau rumah sakit");
    ganti($("#resP"), "Jangan menunggu. Kalau tidak ada kendaraan, hubungi 119 atau 112, atau minta tolong tetangga. Kalau ragu, tetap periksakan.");

    document.querySelectorAll("details").forEach((d) => (d.open = true));
    document.querySelectorAll('[aria-pressed="true"]').forEach((b) => b.setAttribute("aria-pressed", "false"));
  });

  await page.pdf({
    path: HASIL, format: "A4", printBackground: true,
    margin: { top: "12mm", bottom: "14mm", left: "12mm", right: "12mm" },
    displayHeaderFooter: true, headerTemplate: "<span></span>",
    footerTemplate: '<div style="font-size:8px;color:#4D5E5A;width:100%;text-align:center;font-family:Inter,sans-serif">' +
      'Jaga Udara · Panduan keluarga saat kabut asap · inisiatif warga, bukan kanal resmi pemerintah · hal. <span class="pageNumber"></span>/<span class="totalPages"></span></div>',
  });
  await browser.close();
  console.log("PDF dibuat:", HASIL);
})();
