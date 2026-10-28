# Legacy tests

Script pemeriksaan ad-hoc yang dulu menumpuk di root repo. Dipindah ke sini
tanpa diubah isinya — semuanya masih jalan (`node tools/legacy-tests/<nama>.js`),
tapi tidak ada yang otomatis dan tidak ada yang dirujuk oleh kode aplikasi.

Butuh server jalan di port 3000 dan `playwright-core` (devDependency).

## Isi

| Berkas | Untuk apa |
| --- | --- |
| `smoke-test.js` | Smoke test headless: buka viewer, pilih `spineboy`, pastikan render + animasi jalan. Catatan: tidak bisa pixel-sample kanvas WebGL, jadi pengecekannya lewat state. |
| `verify-multi.js` | Beberapa model sekaligus, memakai ulang alur `smoke-test.js`. |
| `nikke-sample-test.js` | Sampel model Nikke; varian (`c010/aim`, `c010/cover`) dicapai lewat dropdown "Varian". |
| `verify-bd2-autoplay.js` | BD2: autoplay voice + alur audio. |
| `verify-bd2-media.js` | BD2: media (ikon/voice) terpasang benar. Dipanggil dari `verify-bd2-autoplay.js`. |
| `verify-bd2-variants.js` | BD2: dropdown varian. |
| `verify-stream.js` | Pemuatan stream / potongan besar. |
| `test-export-http.js` | Export lewat HTTP langsung ke endpoint server. |
| `test-export-live.js` | Export lewat UI sungguhan di browser. |
| `adbkit-check.js` | Diagnostik ADB (`adbkit`) untuk ws-scrcpy — bukan soal Spine, tapi butuh `adbkit` terpasang. |

## Kenapa tidak digabung ke `tools/check-*.cjs`

Yang di `tools/check-*.cjs` adalah pemeriksaan yang masih dipakai dan
didokumentasikan di README (`npm`-nya cuma `node tools/check-*.cjs`). Isi
folder ini sebaliknya: sekali pakai untuk satu penyelidikan pada satu waktu,
dan sebagian bergantung pada aset atau host tertentu. Kalau ada yang mau
dipakai rutin, promosikan ke `tools/check-*.cjs` dan masukkan ke README.
