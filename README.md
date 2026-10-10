# Spine Stage

Viewer buat skeleton Spine2D dan model Live2D yang diekstrak dari game mobile.
Aset disajikan oleh server Express ini sendiri dan dirender di browser dengan
pixi-spine.

> **Catatan soal istilah.** Nama paketnya `spine-stage`, folder/nama repo-nya
> `spine-viewer`. Keduanya merujuk ke proyek yang sama.

## Jalanin

```bash
npm install
npm run build     # bundle src/viewer.js -> public/dist/viewer.js
npm start         # http://localhost:3000
```

Buat development, `npm run dev` = build + start. Kalau mau auto-rebuild saat
ngedit, jalankan `npm run watch` di terminal terpisah — server menyajikan
`public/dist/` apa adanya, jadi rebuild langsung kelihatan tinggal refresh.

Butuh Node.js 18+ (dikembangkan dan diuji di v20).

### Konfigurasi

Semua lewat environment variable, semuanya opsional:

| Variabel | Default | Fungsi |
| --- | --- | --- |
| `PORT` | `3000` | Port HTTP |
| `HOST` | `0.0.0.0` | Interface bind. Set `127.0.0.1` kalau cuma mau akses lokal |
| `MAX_UPLOAD_MB` | `64` | Batas upload lewat `/api/upload` |
| `FFMPEG_PATH` | `ffmpeg` di `$PATH` | Untuk export video |
| `EXPORT_MAX_FRAMES` | — | Batas jumlah frame sekali export |
| `EXPORT_MAX_MB` | — | Batas ukuran hasil export |

## Cara pakai

Kiri ada library: pilih **game**, lalu **model**. Kanan ada stage. Model
langsung dimuat dan diputar.

### Fitur

- **Multi-runtime** — Spine 3.8 / 4.0 / 4.1 / 4.2 dideteksi dari isi file,
  bukan dari ekstensi atau konfigurasi manual.
- **Favorit** — klik bintang di model, lalu filter pakai tombol "Favorit".
  Disimpan di `localStorage`; ada mirror server-side lewat `/api/favorites`
  supaya daftar ikut lintas browser.
- **Timeline & scrubbing** — buka panel timeline buat lihat dan geser
  playhead, lengkap dengan step per keyframe.
- **Inspektor** — hierarki bone, daftar skin, dan attachment.
- **Export PNG** — resolution native, ukurannya diprediksi sebelum render.
- **Part picker** — overlay bounding box per part (pakai `SkeletonBounds`);
  hover buat highlight, klik buat inspect.
- **FPS meter** — rate live + min/avg + grafik.
- **Live2D** — model Cubism (`.moc3`) juga didukung selain Spine.
- **Tautan (permalink)** — tombol 🔗 di header (atau `Ctrl/Cmd-Shift-C`)
  menghasilkan URL yang memuat ulang persis tampilan sekarang: model, animasi,
  skin/varian, waktu di playhead, dan status play/pause, plus seluruh kamera
  (zoom/geser/balik), kecepatan, latar, dan panel yang terbuka. URL di address
  bar juga ikut diperbarui (debounced) setiap kali tampilan berubah, jadi kamu
  bisa langsung salin dari sana. Payload-nya JSON base64url di `?v=`, jadi
  bisa dibaca balik tanpa server. Lihat `docs/permalink.md`.

### Shortcut

| Tombol | Aksi |
| --- | --- |
| `Space` | Play / pause |
| `←` `→` | Ganti animasi |
| `+` `-` | Zoom |
| `0` | Fit model ke layar |
| `B` | Toggle bone |
| `G` | Toggle grid |
| `L` | Toggle background |
| `F` | Fullscreen |
| `E` | Buka dialog export |
| `T` | Toggle timeline |
| `I` | Toggle inspektor |
| `P` | Toggle FPS meter |
| `R` | Toggle part picker |
| `\` | Toggle sidebar |
| `,` `.` | Step keyframe (kalau timeline kebuka) |
| `Esc` | Tutup dialog / keluar fullscreen |
| `Ctrl/Cmd-Shift-C` | Salin tautan tampilan |

## Nambahin aset

Tiap game punya folder sendiri di `assets/<game>/<model>/` yang isinya skeleton
(`.skel` / `.json`), atlas (`.atlas`), dan tekstur (`.png`).

Game dikenali dari nama foldernya — lihat `GAME_ROOTS` di `src/server.js`.
Nambah game baru = tambah entry di situ:

```js
{ match: "namafolder", key: "namafolder", label: "Nama Game-nya" }
```

Entry yang lebih spesifik harus ditaruh **sebelum** yang lebih umum:
`match`-nya substring match dan yang pertama menang, makanya
`azurlane-chibi` ditaruh di atas `azurlane`.

Script ekstraksi ada di `tools/` (dan `tools/REFERENCES.md` buat catatan
sumber eksternal). Tiap game beda format bundle, jadi script-nya juga beda —
lihat `tools/extract-*.py` yang udah ada buat contoh.

### Upload manual

Model tunggal bisa diunggah lewat `POST /api/upload` (maksimal
`MAX_UPLOAD_MB`), atau tinggal taruh foldernya di `assets/`.

## Yang perlu diketahui soal aset

**`assets/` dan `public/thumbs/` tidak ikut ke-commit** — isinya hasil
ekstraksi, bukan source. Besar, binary, dan bisa diregenerasi dari script di
`tools/`. Yang dikecualikan cuma tiga model demo kecil (`raptor`, `spineboy`,
`coin`) dan ikon game di `public/thumbs/_game/`.

Jadi clone baru itu kosong: jalankan script ekstraksi dulu, atau
pakai tombol **"Perbarui aset"** di UI buat game yang punya updater
(Ark Re:Code, Shoujou Kaisen).

`data/favorites.json` juga diabaikan — isinya daftar favorit lokal satu
orang, bukan punya repo.

## Deteksi runtime

Bukan cuma `.skel` vs `.json`. `src/spine-version.cjs` membaca bytes header
(`detectFromBinary`) atau field `skeleton.version` (`detectFromJson`), lalu
`pickRuntime()` milih runtime yang cocok.

Ini penting karena runtime yang salah **nggak selalu error** — kadang cuma
baca dari offset yang keliru dan balikin string sampah. Versi 4.2 butuh
runtime asli (`spine-pixi-v7-42`), karena 4.1 lahir sebelum formatnya ada dan
4.3 baca float `referenceScale` di header yang nggak dipunya file 4.2.

## API

| Endpoint | Fungsi |
| --- | --- |
| `GET /api/models` | Daftar model (bisa difilter `?game=`) |
| `DELETE /api/models/:id` | Hapus model |
| `GET /api/thumbnails` | Manifest thumbnail |
| `GET /api/game-icons` | Ikon per game |
| `GET`/`PUT /api/favorites` | Mirror daftar favorit |
| `POST /api/upload` | Unggah model |
| `GET /api/export/capabilities` | Apa yang bisa diexport |
| `POST /api/export/frame` | Kirim satu frame |
| `POST /api/export/finish` | Selesaikan export |
| `POST /api/export/cancel` | Batalkan export |
| `GET /api/update/:game` | Jalankan updater game |
| `GET /api/update/:game/status` | Status updater |
| `GET /api/bd2-audio`, `/api/orisries-audio` | Audio game tertentu |

## Smoke test

```bash
node tools/check-controls.cjs    # tombol & toggle masih jalan
node tools/check-toolbar.cjs     # layout toolbar
node tools/check-fps.cjs         # FPS meter
node tools/check-mad-ports.cjs   # export PNG, clock, part picker
node tools/check-permalink.cjs   # tautan: tulis, dialog, pulihkan, payload rusak
```

Butuh `playwright-core` dan server jalan di port 3000.

## Catatan pengembangan

- Bundle frontend harus di-rebuild (`npm run build`) setelah ngedit
  `src/viewer.js` — yang disajikan itu `public/dist/viewer.js`, bukan source.
- Beberapa fitur niru **MAD Viewer** (export PNG native, clock deterministik,
  part picker). `tools/check-mad-ports.cjs` khusus ngecek hasil port-nya.
- Model legacy (Spine 2.1.27, mis. Epic Seven) render di iframe terpisah
  dengan loop sendiri, jadi FPS meter dimatikan di situ — angkanya nggak
  menggambarkan yang sebenarnya.
