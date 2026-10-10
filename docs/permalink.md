# Tautan tampilan (permalink)

Satu tombol 🔗 di header (juga `Ctrl`/`Cmd`-`Shift`-`C`) menghasilkan URL yang
memuat ulang persis tampilan yang sedang dilihat. Berguna buat berbagi satu
pose/animasi ke orang lain, menempel di laporan bug, atau menyimpan penanda ke
model favorit tanpa mengandalkan `localStorage` yang cuma lokal.

## Kenapa URL, bukan cuma localStorage

Sebagian preferensi (latar, visibilitas panel) memang sudah disimpan per
browser, tapi `localStorage` tidak bisa dibagikan dan tidak ikut saat pindah
perangkat. Permalink memindahkan seluruh state ke URL supaya bisa disalin,
dikirim, dan di-bookmark — dan server tidak perlu menyimpan apa pun.

## Bentuk URL

State di-encode sebagai JSON lalu base64url (aman untuk URL, tanpa padding),
lalu ditempel sebagai query `?v=`:

```
https://<host>/?v=eyJ2IjoxLCJnIjoib3Jpc3JpZXMiLCJtIjoib3Jpc3JpZXMvMDAwMCIsImEiOiJJZGxlX0x2MiJ9
```

`?v=` jujur soal niat: kalau saat link dibuat animasinya sedang **pause**
(atau baru di-scrub), link akan membuka dalam keadaan pause di detik itu; kalau
sedang main, link membuka dalam keadaan main.

## Kunci payload

Semua opsional — yang tidak relevan dengan default tidak ditulis, supaya URL
tetap pendek. Kunci satu huruf karena payload ikut panjang.

| Kunci | Arti | Nilai |
| --- | --- | --- |
| `v` | versi format | selalu `1` |
| `g` | game yang dibuka | key game (mis. `girlwars-l2d`) |
| `m` | id model | id persis dari `/api/models` (boleh mengandung `#`) |
| `a` | animasi/motion aktif | nama animasi |
| `k` | skin (Spine) atau ekspresi (Live2D) | nama |
| `va` | varian terpilih | **id** model varian (bukan label) |
| `r` | kecepatan putar | angka (default `1`) |
| `p` | sedang pause | `0` kalau pause (default main) |
| `t` | posisi playhead | detik (default `0`) |
| `z` `x` `y` | zoom, geser X, geser Y | angka; kalau tidak ada, sisi terima menjalankan *fit* |
| `f` | balik horizontal | `1` kalau aktif |
| `b` | tulang | `1` kalau tampil (default sembunyi) |
| `gr` | kisi | `0` kalau disembunyikan |
| `fps` | meter FPS | `1` kalau tampil |
| `pt` | part picker | `1` kalau aktif |
| `bg` | warna latar | `dark`/`grey`/`light`/`checker`/`magenta`/`green` |
| `tl` | timeline | `1` kalau terbuka |
| `insp` | inspektor | `1` kalau terbuka, atau `"slots"` / `"compare"` untuk tab |
| `sb` | sidebar | `0` kalau disembunyikan |

Catatan: `b` ditulis hanya saat tulang **tampil** (`1`); kunci bisa juga
berupa JSON boolean — sisi terima menerima keduanya.

## Cara restorasi

`bootPermalink()` dipanggil setelah `refresh()` (daftar model harus ada dulu,
karena `m` di-resolve lewat daftar itu). Urutannya penting:

1. Toggle instan (latar, panel, kamera, rate, flip) — tidak butuh model.
2. `loadModel(model)`.
3. Bit yang butuh skeleton hidup: **varian dulu** (mengganti varian = memuat
   ulang skeleton, jadi kalau animasi/skin dipasang sebelum ini akan tertimpa),
   baru animasi, skin, lalu playhead dan status play/pause.
4. `history.replaceState` menulis ulang URL sesuai hasil akhir (mis. kalau
   animasi di link sudah tidak ada, URL yang tertulis ikut bersih).

Kalau model di link sudah tidak ada di pustaka, halaman tetap memuat normal dan
menampilkan toast pemberitahuan. Payload rusak / bukan JSON apa pun diabaikan
diam-diam — halaman sekadar memuat seperti kunjungan biasa.

## Keterbatasan

- Kamera bersifat relatif terhadap ukuran viewport. Link dibuka di jendela
  dengan ukuran perangkat berbeda akan tetap mencoba zoom dan geser yang sama,
  bukan mem-"fit" ulang ke ukuran baru.
- Satu tab = satu link. Ada `Ctrl/Cmd-Shift-C` buat menyalin link tampilan
  sekarang tanpa membuka dialog; dialognya sendiri punya tombol **Salin
  tautan** dan **Segarkan URL** (menulis ulang URL agar cocok dengan tampilan
  saat ini).
