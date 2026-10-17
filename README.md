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
| `EXPORT_MAX_FRAMES` | `600` | Batas jumlah frame sekali export |
| `EXPORT_MAX_MB` | `96` | Batas ukuran total frame per job export |
| `EXPORT_TMP_TTL_HOURS` | `2` | Sisa frame (`data/exports/`) yang ditinggalkan dibersihkan otomatis |
| `EXPORT_OUT_TTL_HOURS` | `168` | Umur video hasil export sebelum dibersihkan |
| `UPLOAD_LIMIT_MAX` | `6` | Unggahan per menit per IP |
| `RATE_LIMIT_MAX` | `30` | Permintaan ketat (`/api/models`, `/api/update`, `/finish`) per menit per IP |
| `FRAME_LIMIT_MAX` | `3000` | Frame export per menit (satu request per frame, jadi langkahnya sendiri) |
| `SCAN_TREE_TTL_MS` | `15000` | Seberapa sering isi `assets/` dicek ulang (di worker thread) |
| `UPDATE_TIMEOUT_MS` | `1800000` | Batas waktu satu pembaruan game |
| `BD2_MEDIA` | `/srv/spine-assets/bd2-media` | Audio/ikon BD2 |
| `OR_AUDIO_DIR` | `/srv/spine-assets/orisries/audio` | Soundtrack OrisRies |

> **Keamanan.** Server ini tidak punya akun sama sekali: siapa pun yang
> bisa menembus port-nya bisa mengunggah, menghapus model, menjalankan
> pembaruan (spawn proses), dan memakai export. Ada rate limit per IP
> dan penjaga path, tapi itu menahan *hammering*, bukan pengunjung yang
> sengaja. Untuk akses dari luar, taruh di belakang reverse proxy
> bertoken — atau set `HOST=127.0.0.1`.

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
- **Banding A/B di panggung** — di tab inspektor *Bandingkan*, tombol
  **"A/B di panggung"** memuat model B di sebelah model A yang sedang
  dibuka. **Keduanya memakai kanvas terpisah**, jadi tiap panel punya
  kamera sendiri (scroll untuk zoom panel B tidak menyentuh panel A) —
  perlu karena ukuran kanvas Spine sangat bervariasi (3839×6715 vs
  1136×2260 pada satu pasang yang diuji; median pustaka 947×1334).
  Geser model B dengan **tombol kanan**. Drag kiri dan roda di atas sebuah
  panel menggerakkan kamera panel ITU (di mode tumpang tindih, keduanya
  sekaligus), jadi A dan B bisa di-zoom dan dipan sendiri-sendiri.
  pakai **Reset posisi** untuk mengembalikan, dan **Kunci** bila ingin
  A ikut bergerak supaya hanya posisi relatifnya yang berubah.
  Klik-kanan sebuah kartu model menggantikan B saat mode A/B aktif. Keduanya digerakkan oleh **satu clock**, dan seek-nya memakai
  *proporsi siklus* bukan detik mentah — durasi A dan B hampir selalu beda
  (mis. 5,33 s vs 2,5 s), jadi meneruskan detik yang sama membuat B berputar
  dua kali lebih cepat dan perbandingannya menyesatkan. Pilih tata letak
  **Berdampingan** atau **Tumpang tindih**. Klik-kanan sebuah kartu model
  (saat mode A/B aktif) menggantikan B dengan model itu.
- **Onion skin** — di panel yang sama, 1–3 frame: pose N frame sebelumnya
  digambar lebih redup di belakang pose saat ini, untuk memeriksa timing
  antar frame. Hanya menyalin pose, bukan piksel.
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

Catatan endpoint:

- `GET /api/models` dikirim terkompresi (27 MB → ~2,3 MB) dan memakai ETag,
  jadi muat-ulang yang tidak berubah dijawab `304` tanpa badan. `?game=`
  mengembalikan satu game saja (lebih ringan kalau cuma butuh itu).
  `?refresh=1` memaksa pindai ulang — masuk rate limit ketat, karena
  pindai ulang penuh itu berat.
- `DELETE /api/models/:id` menerima id persis seperti di daftar model
  (`game/model`, variannya `game/model#varian`) dan menghapus **foldernya**.
  Id yang bukan sebuah model dibalas `404`, bukan sukses palsu.
- Upload menolak folder apa pun yang keluar dari `assets/`, dan dibatasi
  6 per menit per IP.

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
