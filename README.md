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
| `L` | Ganti warna latar (Gelap → Abu → Terang → Papan catur → …) |
| `Shift+L` | On/off gambar latar (backdrop) |
| `F` | Fullscreen |
| `E` | Buka dialog export |
| `T` | Toggle timeline |
| `I` | Toggle inspektor |
| `P` | Toggle FPS meter |
| `R` | Toggle part picker |
| `X` | Ganti tampilan pustaka: daftar ↔ galeri |
| `Y` | Toggle nama slot (tooltip) |
| `Shift+E` | Toggle edit tulang |
| `V` `U` `J` | Toggle mode vertex / bounds / IK |
| `\` | Toggle sidebar |
| `,` `.` | Step keyframe (kalau timeline kebuka) |
| `1`–`9` | Lompat ke varian ke-N (kalau model ber-family) |
| `[` `]` | Varian sebelumnya / berikutnya (wrap-around) |
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

### Cherry Tale

Bundle-nya diacak, bukan dienkripsi betulan, dan **wajib** didekripsi dulu
(`tools/extract-cherrytale.py` melakukannya otomatis):

1. tukar `bytes[i] <-> bytes[len-i]` untuk `i` di `{0x3FB, 0xD99, 0x197C}`
2. ganti `2018.3.5f1\0` → `2020.3.41f1\0`, lalu **lewati satu byte** sesudahnya

Langkah 2 penting: string pengganti satu byte lebih panjang, jadi tanpa
lompatan itu semua field setelahnya bergeser dan UnityPy melapor
`signed integer is greater than maximum`.

Nama aset di index memuat path penuh
(`assets_resources_honly_baseassets_uiprefabs_simpleprefab_..._cg_spine`).
Dipakai apa adanya, satu model jadi 15 tingkat direktori — melewati batas
kedalaman pemindai (8), sehingga modelnya tidak pernah muncul. Extractor
memangkasnya jadi satu tingkat:
`assets/cherrytale/img_cg_dynamic_e004_02_teaching_cg_spine/`.

> Bundle `_gacha_` dan `rtcamera_` tidak memuat TextAsset (spine-nya
> dirujuk dari bundle lain), jadi memang dilewati — bukan gagal.

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

## Updater Health Dashboard

Tombol **denyut** di header pustaka (sebelah tombol log) membuka satu meja
untuk **semua 27 updater** sekaligus — nggak perlu masuk tile game satu-satu.
Sumbernya `GET /api/updaters/health`:

- `--check` dijalankan **paralel (10 worker)** dengan **timeout 30 detik
  per game**, jadi satu updater yang lambat nggak menggantung panel.
- Hasilnya di-cache 5 menit di `data/updaters-health.json` (diabaikan git).
  Buka panel → pakai cache (11 ms). **Cek semua** → `?refresh=1`.
  `?game=ivntight&refresh=1` menyegarkan satu baris saja.
- Kontrak `--check` **tidak seragam**: updater lama seperti
  `update-shoujoukaisen.py` tidak mengirim field `ok`, dan jumlah model bisa
  bernama `have` / `models_have` / `installed`. `healthRow()` menormalkannya —
  yang menandakan gagal itu field `error` dari `runUpdater` atau `ok:false`
  eksplisit, bukan "tidak ada `ok`".
- **Sumber tertinggal** (`mirrorLag`): sinyal CDN resmi (`cdnSha` /
  `dataCommit`) berubah tapi `version` dari mirror komunitas masih sama →
  game sudah patch, mirror belum sinkron. Muncul sebagai badge kuning.
- Titik kuning di tombol header menyala kalau ada `changed`, model baru,
  kegagalan, atau mirror tertinggal.

**Terapkan yang berubah** minta konfirmasi dulu, lalu memanggil endpoint
`/api/update/:game?mode=apply` yang **sudah ada** secara berurutan sambil
mengikuti `/api/update/:game/status` untuk log. Tidak ada jalur apply baru,
jadi aturan `rescan` / `forceModelRescan` tetap identik dengan tombol
per-game. Apply sengaja tidak pernah dijalankan otomatis.

Regresi: `node tools/check-updater-dashboard.cjs` (39 assertion), termasuk
bukti bahwa updater tanpa field `ok` tidak lagi dilaporkan gagal.

### Change log per game

Tombol jam di header pustaka (`#change-log-btn`) membuka **riwayat pembaruan**.
Di daftar game ia menampilkan ringkasan semua game yang punya riwayat; di dalam
satu game ia menampilkan entri terbaru-dulu dengan **tanggal**, jumlah model
baru, versi updater, status backup GDrive, dan **chip nama model yang bisa
diklik** untuk langsung membuka modelnya.

- Sumber: `src/change-log.js`, tersimpan di `data/change-logs.json` (di luar git).
- `GET /api/change-logs` → ringkasan `[{game,label,count,lastAt,newModels}]`.
  `GET /api/change-logs?game=<key>` → `{game,label,entries}` terbaru dulu.
- Entri **`apply`**: dibuat setiap `/api/update/:game?mode=apply` sukses.
  Server memotret himpunan id model sebelum dan sesudah apply, jadi yang
  tampil adalah model yang *benar-benar* baru muncul, bukan sekadar angka
  `new` dari skrip. Apply gagal tidak meninggalkan entri palsu.
- Entri **`restore`**: di-seed satu kali dari `data/new-models.json` (`flagged`
  = waktu model pertama kali terdeteksi), supaya riwayat tidak kosong sebelum
  apply pertama. Dikelompokkan per game per tanggal.
- Daftar id per entri dibatasi 40 chip ditambah `addedCount` penuh, jadi entri
  restore berisi puluhan ribu model tetap ringan. Maksimal 60 entri per game.
- Entri apply juga mencatat apakah upload GDrive berhasil (`gdrive`).

**Kenapa model di riwayat kadang "tidak ada di list"?** Entri riwayat dibaca
langsung dari server, tapi daftar pustaka memakai snapshot `/api/models` yang
dimuat sekali saat tab dibuka. Kalau apply dijalankan dari tab/perangkat lain
(atau lewat dashboard "Terapkan yang berubah"), tab ini tidak ikut `refresh()` —
modelnya ada di server dan di disk, tapi tidak ada di `models`, sehingga chip
riwayat tampil `sudah tidak ada` dan pencarian tidak menemukannya.

Saat panel riwayat dibuka, `ensureFreshModels()` melakukan `HEAD
/api/models?lean=1` (cuma header, bukan body 12 MB), membandingkan ETag dengan
indeks lokal, dan memanggil `refresh()` kalau berbeda. Jadi sumber data riwayat
dan pustaka selalu sama. Selain itu, klik chip kini menjalankan
`revealModelInLibrary()`: pindah ke game model, bersihkan filter pencarian/
favorit, lompat ke halaman yang memuat kartunya, dan sorot kartu itu.
Perhitungan halaman diulang **setelah** `loadModel()` karena `markSeen()`
membuang badge NEW dan model turun dari urutan "baru dulu" ke posisi
alfabetisnya (bisa beda halaman). Regresi:
`node tools/check-change-log-stale.cjs` (mensuntik indeks basi lewat route
Playwright, tidak bergantung isi `data/change-logs.json`).

Path bisa di-override lewat `CHANGE_LOG_FILE` / `NEW_MODELS_FILE` (dipakai
regresi `tools/check-change-log.cjs` supaya data produksi aman).

### Backup otomatis ke GDrive setelah apply

Setiap `/api/update/:game?mode=apply` yang **sukses** langsung mengunggah
hasilnya ke Shared Drive, masih di dalam job yang sama. Jadi tidak perlu
lagi ingat backup manual (kasus BD2 yang dulu kelewat saat diunduh ulang).

- Modul: `src/gdrive-upload.js`. Dipanggil setelah indeks model disegarkan,
  sebelum `updateJob.running` diturunkan, sehingga panel log menampilkan
  baris `[gdrive] …` dan klien baru memanggil `refresh()` setelah backup
  selesai. Hasilnya juga masuk ke `result.gdrive` di `/status`.
- Root yang diunggah = gabungan **peta statis per updater** (`STATIC_ROOTS`)
  dan **deteksi dinamis** berkas dengan mtime sejak apply dimulai (satu
  proses `find`). Deteksi dinamis menangkap folder yang baru pertama kali
  ada; peta statis menangkap unduhan yang mempertahankan timestamp lama.
- Per root dijalankan `rclone copy` ke `gdrive:<root>` atau
  `gdrive:thumbs/<root>` dengan `--drive-root-folder-id=1zRly3eeewcrgdIe3bOUQUmyWUXXIwnzo`.
  **`copy`, bukan `sync`**: tidak pernah menghapus berkas di remote. rclone
  membandingkan size + mtime, jadi root besar (mis. `assets/chaoszero` 9,3 GB)
  tetap murah — dry-run menunjukkan cuma 1 berkas yang perlu pindah.
- Kegagalan upload **tidak membatalkan apply** (aset sudah aman di disk),
  tapi wajib terlihat di log + `result.gdrive.ok = false`. Apply yang gagal
  tidak mengunggah apa pun.

Kredensial tetap di `~/.config/rclone/rclone.conf` (0600), tidak ada di repo.
Konfigurasi opsional via env: `GDRIVE_UPLOAD=0` (matikan), `GDRIVE_REMOTE`,
`GDRIVE_ROOT_ID`, `RCLONE_BIN`, `GDRIVE_UPLOAD_TIMEOUT_MS` (default 45 menit
**per root**), `GDRIVE_UPLOAD_GLOBAL_MS` (pagar total, default 90 menit).
Jatah per-root ini penting: sinkronisasi awal `public/audio/crosscore` berisi
3.638 berkas kecil, dan satu deadline global 30 menit habis dipakai root lain
sehingga root terakhir gagal.

Regresi lokal tanpa jaringan: `node tools/check-gdrive-upload.cjs`.

### Tombol updater & "Unexpected end of JSON input"

Gejala: klik **Perbarui aset** → toast `Gagal memeriksa pembaruan: Failed to
execute 'json' on 'Response': Unexpected end of JSON input`. Itu bukan bug
Python, tapi frontend memanggil `r.json()` pada **respons tanpa body**. Dua
sumbernya:

1. **304 dari ETag Express.** `res.json()` otomatis memberi ETag; browser yang
   revalidasi (`If-None-Match`) menerima `304 Not Modified` dengan **0 byte**.
   Endpoint `/api/update*` dan `/api/updaters*` sekarang membuang header
   conditional dan mengirim `Cache-Control: no-store`. Hasil `--check` memang
   selalu baru, jadi caching kondisional tidak masuk akal di sini.
2. **Request keburu putus.** `--check` Cat Shinobi mengekstrak APK 648 MB dan
   mem-parse semua bundle UnityPy **setiap kali** (~17–20 dtk), sehingga
   proxy/tunnel bisa memutus koneksi sebelum JSON terkirim.
   `tools/update-catshinobi.py` kini menyimpan daftar skeleton + jumlah
   tekstur di `scan-cache.json` dengan kunci **ukuran APK** (penanda versi
   yang sama dengan `version`). Tetap ada probe versi lewat HTTP Range ~3 MB,
   jadi rilis baru tetap ketahuan dan otomatis membatalkan cache.
   **20,7 dtk → 1,5 dtk.**

Lapisan ketiga: `fetchUpdateJSON()` di `src/viewer.js` membaca respons sebagai
teks dulu, memakai `cache: "no-store"`, dan kalau body kosong memberi pesan
`Server tidak mengirim JSON (HTTP …, body kosong). Coba lagi sebentar.`
Semua jalur updater (check, apply, polling status, dashboard) memakainya.
Server juga menggabungkan dua `--check` yang jalan barengan lewat
`checkInFlight`, jadi klik dobel tidak menyalakan dua proses berat.

Regresi: `node tools/check-update-json.cjs` (31 assertion) — termasuk uji
`If-None-Match: *` tidak lagi 304, kecepatan cache, dan **simulasi body
kosong di browser** yang harus menghasilkan toast yang jelas, bukan error
samar.

Regresi: `node tools/check-update-refresh.cjs` (21 assertion), termasuk uji
**model tiruan** yang ditambahkan ke `assets/` lalu harus langsung muncul
tanpa `?refresh=1` begitu apply selesai.

### Kenapa model baru dulu telat muncul setelah update

Gejala: apply selesai, tapi model baru baru tampil beberapa menit kemudian /
setelah reload berulang. Tiga lapis yang saling menumpuk:

1. `scanTree()` menyimpan signature `assets/` selama `SCAN_TREE_TTL_MS`
   (15 dtk), dan endpoint `/api/update/:game?mode=apply` **tidak pernah**
   memanggil `invalidateScan()` (padahal upload & delete sudah memanggilnya).
2. `forceModelRescan` hanya dinyalakan untuk updater berflag `rescan`
   (**18 dari 27**). Lebih parah, `getModels()` saat signature berubah
   sengaja mengembalikan `cache.models` **LAMA** sambil menjadwalkan
   `scheduleScan()` di latar — jadi perlu beberapa request lagi sebelum
   daftar benar-benar berganti.
3. Frontend cuma memanggil `refresh()` kalau hasil apply punya
   `new_models` atau `extracted` (banyak updater memakai field lain), dan
   `res.json()` pada `/api/models?lean=1` bisa meledak kalau server menjawab
   **304 ETag** tanpa body — refresh gagal diam-diam.

Perbaikannya: **server menyegarkan indeks SEBELUM menurunkan
`updateJob.running = false`**. `invalidateScan()` + `getModels({force:true})`
dijalankan untuk **semua** updater (semuanya menulis ke `assets/`), dengan
normalisasi `applyOk` karena sebagian `--apply` tidak mengirim field `ok`
(mis. Ark Re:Code). Jadi `refresh()` pertama yang dipicu frontend setelah
status "Selesai" sudah menerima daftar segar. Frontend sekarang **selalu**
refresh setelah apply sukses, toleran 304, dan apply-massal lewat dashboard
juga ikut memuat ulang pustaka.

Terukur: model baru tampil dalam **9–11 detik** (waktu apply + pindai ulang
~5 dtk), bukan beberapa menit. Konsekuensi jujur: pindai ulang itu sinkron,
jadi event loop server tertahan beberapa detik sekali saja per apply — itu
sebabnya polling `/status` bisa sempat terputus dan client perlu retry.

## Cat Shinobi: nama karakter, varian, thumbnail

596 model `catshinobi/` dulu cuma punya 260 nama, tanpa picker varian dan
tanpa thumbnail sama sekali. Sekarang semuanya dibangun **offline** dari APK
resmi yang sudah diekstrak (lihat `tools/catshinobi/README.md`):

| | Hasil | Sumber |
| --- | --- | --- |
| Nama karakter | **260 → 307** model | tabel Unity Localization game sendiri (`UI_CHARACTER_NAME_*`, `UI_COSTUME_NO_*`, en/id/ja) |
| Varian | **186 family / 519 anggota** | id numerik sama lintas bentuk (`Char_`, `Char_SD_`, `Char_LD_`, `cat_battle_mode_`, `cat_front_mode_`, `cat_ninja_`) |
| Thumbnail | **188 WebP / 517 model** | Sprite ilustrasi `CharThumb_*`, `CharInfoThumb_*`, `char_*`, `Icon_Profile_*` |

- **Thumbnail bukan halaman atlas.** Sprite yang dipilih berlatar transparan
  (semua WebP punya chunk `ALPH`; 0 gambar fully opaque), bukan `Texture2D`
  2048² yang dipakai skeleton. Ini sesuai preferensi gambar ilustrasi karakter.
- **Nama tidak dikarang.** `cat_*_mode_*` dan `monster_*` sengaja dibiarkan
  tanpa nama karena angkanya indeks animasi/musuh, bukan id karakter.
  Perbaikan `costume->base` membuat `Char_1003` → *Akari Mayoneko —
  Summer・Shinobis*, `Char_15002` → *Sena Kisaragi — Noble Frost*, dll.
- Tiap entri nama membawa `variant` (`Battle`, `SD (Chibi)`, `LD`,
  `Cat · Battle`, `Monster`, `· Skill`), diteruskan ke `m.character.variant`.
  Family dibaca loader umum di `src/server.js`, jadi picker varian yang sama
  dengan Arknights / Zone Nova / Stella Sora langsung jalan.

Regenerasi: `/srv/venv-spine/bin/python tools/catshinobi/refresh.py` (offline,
~4 detik) lalu `systemctl restart spine-viewer` + `/api/models?refresh=1`
karena server menyimpan cache model persisten. `public/thumbs/catshinobi/`
ada di luar git. Regresi `node tools/check-catshinobi.cjs` (37 assertion).

## Dukungan model 3D (glTF / GLB)

Bisa, tapi **bukan "tambah satu flag"**: PIXI 7 itu renderer 2D orthographic
(tanpa depth / lighting / skinning), jadi 3D butuh konteks WebGL terpisah.
Implementasinya sengaja **terpisah** supaya 43 ribu model 2D tidak tersentuh.

- **Runtime**: `three@0.187` + `GLTFLoader` + `OrbitControls` di
  **`public/dist/model3d.js` (645 KB)**, IIFE mandiri yang di-*lazy load* lewat
  `<script>` saat model 3D pertama dibuka. `viewer.js` tetap **4,1 MB**.
- **Format generik** `format: "model3d"`: `scanModels()` mendeteksi
  `model.glb` + `anims/*.glb` di root game mana pun. Tidak hardcode Stella Sora.
- **Pilot**: `stellasora-3d` dari `StellaSoraWiki/StellaSoraModels` —
  **59 model / 177 clip / 295 MB**, 19 family varian, 58 thumbnail.
  GLB utama berisi mesh+skin+tekstur tanpa clip; `AnimationMixer` me-retarget
  clip dari GLB terpisah berdasarkan nama node.
- **Thumbnail tetap gambar ilustrasi 2D** (potret AVG yang dipakai root
  Live2D), bukan potongan atlas dan bukan tangkapan 3D.
- Kanvas PIXI cuma disembunyikan; `dispose3D()` melepas renderer/controls/
  mixer saat kembali ke model 2D. HUD menampilkan `3D · glTF` + mesh/triangle.
  Export PNG memakai `Model3DStage.capture()`; ekspor video & A/B compare
  sengaja tidak didukung untuk 3D (ada pesan jelas, bukan crash).
- **Animasi langsung jalan saat model dibuka** (auto-play `idle`, bukan pose
  statis). Root motion clip seperti `Attack` dibuang supaya karakter tidak
  meleset keluar kamera; bind pose dipulihkan tiap ganti clip; tombol Play jadi
  jeda/lanjut `AnimationMixer`. Regresi `check-model3d.cjs` mengukur perubahan
  frame dari waktu ke waktu dan memastikan model tetap terlihat (0 piksel = gagal).

Regenerasi: `tools/model3d/update.py --check|--apply`, `refresh.py` untuk mode
offline, `npm run build` (dua bundle), lalu `?refresh=1`. Detail lengkap di
`tools/model3d/README.md`. Regresi `node tools/check-model3d.cjs` (37
assertion) membuktikan kanvas tidak blank, clip bisa diputar, dan kembali ke
Spine 2D tetap bersih.

## Ark Re:Code: model "bukan Spine"

`catalog_116031` membawa 20 bundle hero baru. 18 di antaranya (`H169`,
`H191`…`H210`, `H611`) ternyata **bukan model Spine** — isinya cuma prefab,
ikon, dan `ParticleSystem`, **0 `TextAsset`**. Bandingkan `H189` lama yang
punya halaman atlas `Assets/Game/Hero/H189/H189/H189.png`. Dua model
sisanya (`M001`, `M020`) memang Spine dan diekstrak jadi `M_001_1` /
`M_020_1`.

Log lama menulis `→ ? (tanpa atlas)`, yang terkesan seperti berkas rusak.
Sekarang: `→ bukan Spine (0 TextAsset)`.

Tiga perbaikan di `tools/update-arkrecode.py`:

1. **State disimpan SETELAH ekstraksi.** Versi lama menulis
   `state["processed"]` sebelum loop, jadi model yang gagal (berkas tak
   terunduh / extractor error) ikut dicatat "selesai" dan tidak pernah
   dicoba lagi.
2. **`processed_v2` menyimpan signature bundle** (SHA-1 dari relpath URL,
   yang mengandung hash konten), bukan id polos. Kalau game belakangan
   menambahkan skeleton ke `H191`, hash bundle-nya berubah → model itu
   otomatis muncul lagi sebagai "baru". Format lama `processed` dibuang.
3. **`stem_installed()` mengenali `M001` → `M_001_1`** (alias underscore).
   Tanpa ini `M001` diunduh ulang terus meski `M_001_2` sudah ada.

`--check` juga tidak lagi mencampur folder lama dengan model katalog:
`installed` kini dihitung dari model yang benar-benar punya folder, bukan
`len(installed | processed)` yang dulu menghasilkan `609/268` di dashboard.

Hasil sekarang: **268 model · 250 terpasang · 18 bukan Spine · 0 baru**,
idempoten. Regresi `node tools/check-arkrecode.cjs` (36 assertion) mencakup
unit signature, state, dashboard, 0 aset 404, dan render `M_001_1`.

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
| `GET /api/models` | Daftar model lengkap (bisa difilter `?game=`) |
| `GET /api/models?lean=1` | Indeks ringan untuk pustaka (tanpa field detail) |
| `GET /api/models/:id` | Satu entri model lengkap |
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
| `GET /api/updaters/health` | `--check` seluruh updater (paralel, cache 5 menit; `?refresh=1`, `?game=…`) |
| `GET /api/bd2-audio`, `/api/orisries-audio` | Audio game tertentu |

Catatan endpoint:

- `GET /api/models` dikirim terkompresi (puluhan MB → beberapa MB; terukur
  27 MB → 2,2 MB pada 38.280 model — angkanya ikut berubah kalau game
  ditambah/dihapus) dan memakai ETag,
  jadi muat-ulang yang tidak berubah dijawab `304` tanpa badan. Body, ETag,
  dan gzip dihitung sekali per signature pindai (`src/models-payload.js`),
  bukan tiap request. `?game=` mengembalikan satu game saja (lebih ringan
  kalau cuma butuh itu) dan tetap bisa digabung `&lean=1`.
  `?refresh=1` memaksa pindai ulang — masuk rate limit ketat (30/menit per
  IP), karena pindai ulang penuh itu berat. `GET /api/models/:id` sengaja
  **dikeluarkan** dari kuota itu: ia cuma membaca satu entri dari Map di
  memori, jadi membuka banyak model berurutan tidak boleh kena 429.
- **Indeks dua tingkat:** UI boot memakai `?lean=1` (terukur 541 KB gzip
  vs 2,2 MB penuh pada 38.280 model),
  lalu `GET /api/models/:id` mengambil field yang cuma dipakai saat model
  dibuka (skeleton/atlas, daftar animasi, skin, …). Detailnya digabung ke
  objek yang sama supaya `switchVariant()`, A/B, dan permalink yang mencari
  model berdasarkan id tetap bekerja. Respons penuh default **tidak berubah** —
  `tools/check-cherrytale.cjs` dan klien lama masih dapat semua field.
  Id boleh memuat `/` dan `#`; kirim dengan `encodeURIComponent()`.
- `DELETE /api/models/:id` menerima id persis seperti di daftar model
  (`game/model`, variannya `game/model#varian`) dan menghapus **foldernya**.
  Id yang bukan sebuah model dibalas `404`, bukan sukses palsu.
- Upload menolak folder apa pun yang keluar dari `assets/`, dan dibatasi
  6 per menit per IP.

## Chaos Zero Nightmare (CZN)

Model CZN sekarang memakai **aset game-side di `assets/chaoszero/`** (1.527
model Spine 3.8, dipulihkan dari GDrive). Pustaka komunitas `czn-rigs` dan
cut-ins `czn-cutins-cg` sudah diarsipkan ke `/srv/spine-assets/`. Repo dan wiki
di bawah tetap dipakai sebagai **sumber metadata** (nama, roster, kartu,
thumbnail, ikon), bukan sebagai sumber model.

Rig komunitas itu dulu diiris supaya pustakanya isi **cuma karakter yang
benar-benar ada di wiki**:

| Sumber | Isi |
| --- | --- |
| [`BenNoSleep/czn-animation-viewer`](https://github.com/BenNoSleep/czn-animation-viewer) `rigs/` | 1.171 rig Spine 3.8 (`skeleton.json` gzip + `.atlas` + `.webp`) |
| [wiki e7bot](https://wiki.e7bot.top/#/czn/combatant) + [Partner](https://wiki.e7bot.top/#/czn/partner) | 89 karakter: 39 `CHAR_COMBATANT` + 50 `CHAR_SUPPORTER` |

Irisannya **322 rig / 89 karakter / ~343 MB**. Yang terbuang itu monster, NPC,
god, event umum, dan portrait karakter yang tidak dirilis. Tiap karakter dapat
beberapa rig (`model_`, `portrait_`, `liveevent_`, `_battle_ready`, skin), dan
`attachCznFamilies()` di server menggabungkannya jadi **satu kartu + dropdown
varian** — bukan 322 kartu terpisah.

Daftar karakter wiki dikirim terenkripsi AES-256-CBC (`{data, encrypted}`);
kuncinya ada di bundle JS mereka, 16 byte pertama payload adalah IV.
`tools/czn/refresh.py` mendekripnya, mencocokkan `id` rig dengan id karakter,
mengunduh **hanya** file yang perlu, lalu mengubah nama file ke format yang
dikenal pemindai (`<slug>.json` / `<slug>.atlas` + halaman tekstur sesuai
yang disebut atlas). Nama tampilan kartu diambil dari wiki, bukan dari repo.

Thumbnail **disalin persis dari web**: `capture-thumbs.cjs` membuka halaman
Combatant dan Partner dengan Playwright lalu menycreenshot elemen kartu
aslinya (latar slot, badge job/ego, frame rarity, nama) pada ukuran native
**260×460** — bukan rekreasi manual. Satu thumbnail per karakter dipakai
bersama oleh semua rig variannya lewat `_manifest.json`.

Refresh ulang (idempoten, tidak menghapus apa pun di luar `assets/czn-rigs`):

```bash
python3 tools/czn/refresh.py            # roster + unduh + konversi + manifest
python3 tools/czn/fetch-icons.py        # ikon filter dari wiki (public/thumbs diabaikan git)
python3 tools/czn/refresh-cards.py      # kartu skill dari /api/czn/cards/list
node tools/czn/capture-thumbs.cjs       # 89 thumbnail dari web (+ normalisasi)
curl 'http://127.0.0.1:3000/api/models?refresh=1' >/dev/null
node tools/check-czn.cjs                # verifikasi render & thumbnail
```

Butuh `cryptography` (Python), `ffmpeg` (sudah dipakai server untuk export),
dan `playwright-core` (Node). Normalisasi thumbnail sengaja tidak memakai
Pillow: interpreter systemd (`/usr/bin/python3`) tidak memilikinya.

### Tampilan & filter pustaka

Pustaka model **default-nya galeri (grid)** — thumbnail 260×460 jauh lebih
berguna daripada baris 44px. Tombol **Daftar / Galeri** di header tetap bisa
mengganti, pilihan terakhir diingat di `localStorage` (`spine-stage:layout`),
dan shortcut `X` men-toggle keduanya.

Saat membuka game **Chaos Zero Nightmare**, muncul panel filter khusus:

- **Tab `Semua` / `Combatants` / `Partner`** dengan jumlah kartu langsung
  (89 / 39 / 50). Mengikuti `char_type` dari wiki, bukan tebakan dari nama.
- **Filter ikon Ego / Job / Rarity** meniru baris filter wiki: badge ego
  berlatar gradien, badge job, dan deretan bintang — bukan dropdown teks.
  Klik ikon = aktif, klik lagi = matikan. Opsinya diisi otomatis dari atribut
  model, jadi karakter baru di wiki langsung muncul tanpa edit kode.
- Semua filter bisa dikombinasikan dengan **pencarian** dan **Favorit**, dan
  angka di tab ikut menyesuaikan. **↺** mengembalikan ke semua.
- **Urutan kartu CZN: rarity tertinggi dulu** (5★ → 4★ → 3★), lalu nama.
  Game lain tetap memakai urutan badge NEW + alfabet seperti sebelumnya.

Aset ikon ada di `public/thumbs/czn-ui/` dan **tidak ikut ke-commit**
(`public/thumbs/*` diabaikan git). `tools/czn/fetch-icons.py` mengambilnya lagi
dari wiki, termasuk bintang CZN yang di-embed di chunk `GradeFilter` — nama
chunk-nya di-resolve dinamis karena hash Vite berubah tiap deploy. Job
`vanguard` tidak punya ikon sendiri; wiki memetakannya ke `icon_job_knight`.

Atribut `charType`/`ego`/`job`/`rarity` ditempelkan server di
`applyCznNames()` dan ikut ke indeks ringan, jadi filter bekerja **tanpa**
memuat detail 322 model satu-satu. Panelnya otomatis hilang saat kembali ke
daftar game.

### Kartu skill

`tools/czn/refresh-cards.py` memakai **indeks resmi** `/api/czn/cards/list`
wiki (juga terenkripsi AES, kunci sama), bukan lagi menebak nama berkas
`start_<id>_01..12` seperti `tools/download-czn-cards.py` lama. Dari situ
didapat `sct_name` (nama berkas pasti), `base_combatant.id` (pemilik),
`animation`, `name`, `ego`, `rarity`, `cost`, dan `sort`. `sct_name` bisa
berulang (varian epiphany) jadi dideduplikasi per karakter.

Hasil: **39 karakter / 456 ilustrasi unik / 168 animasi `.webm`** (~120 MB) di
`assets/czn-cards/<charid>/` + `index.json`. Partner memang tidak punya kartu
di wiki. Tombol **Kartu** (shortcut `K`) muncul otomatis untuk model CZN yang
bisa dipetakan ke id karakter; panelnya menampilkan petak ilustrasi dengan
bingkai yang mengikuti **ego + rarity asli dari wiki**.

**Deskripsi skill** ikut dari `desc_display` wiki: **1.391 deskripsi** (456
primer + 935 varian epiphany) untuk 456 ilustrasi — satu gambar bisa dipakai
beberapa kartu dengan teks berbeda. Markup wiki (`<color_orange>`, `<cc>`,
`<color_ego_*>`, `<u>`, `<br>`, `</>`) diterjemahkan `refresh-cards.py` jadi
HTML aman (semua teks di-escape, cuma `<span style>`, `<u>`, `<br>` yang
dikeluarkan) dengan warna persis `descriptionFormatter` wiki. Tiap kartu
menampilkan nama, cost, dan deskripsi dasar; kalau ada varian epiphany muncul
tombol **+N varian** yang membuka panel berisi semua deskripsinya. Teks polos
juga jadi tooltip dan `aria-label`.

Tool lama (`download-czn-cards.py`, `download-czn-card-videos.py`,
`probe-czn-cards.py`) dibiarkan sebagai referensi, tapi bukan jalur utama lagi.

### Pembaru (tombol "Perbarui aset")

`tools/czn/update.py` adalah **satu updater untuk `chaoszero`** (kunci game
yang dipakai sekarang). Tombol di header pustaka otomatis muncul saat membuka
Chaos Zero Nightmare; titik merah muncul kalau ada yang berubah.

Model Spine **tidak diunduh updater ini**: `assets/chaoszero/` berisi aset
game-side yang dipulihkan dari GDrive. Yang disegarkan cuma metadata wiki:
ikon filter, kartu skill, potret/thumbnail, dan `public/thumbs/chaoszero/
_manifest.json` yang memetakan tiap model (root maupun varian) ke potret
karakternya. Pustaka komunitas `czn-rigs` / `czn-cutins-cg` sudah diarsipkan;
`tools/czn/refresh.py` **tidak pernah dijalankan sebagai skrip** oleh updater
(ia cuma dipakai sebagai modul untuk `wiki_roster()`).

- `--check` (cepat, tanpa unduh aset): bandingkan tanda tangan tiga sumber —
  `index.json` + commit `main` GitHub, roster wiki, dan daftar kartu wiki —
  serta himpunan id dan jumlah berkas di disk terhadap
  `data/chaoszero-update-state.json` (diabaikan git). Check pertama melakukan
  *bootstrap* supaya tidak langsung melapor "semua baru".
- `--apply` (background, ada panel log): jalankan berurutan `fetch-icons.py` →
  `refresh-cards.py` → `capture-thumbs.cjs` → `normalize-thumbs.py` →
  `build-thumb-manifest.py`, lalu simpan state. `refresh-cards.py` adalah data
  utama; ikon & thumbnail bersifat kosmetik dan boleh dilewati kalau wiki /
  Chromium sedang rewel, tanpa menggagalkan apply.
- Server menandai `forceModelRescan` setelah apply sukses, jadi `/api/models`
  berikutnya (dipicu `refresh()` klien) langsung pindai ulang. Cache
  `index.json` kartu juga di-reset.

Interpreter updater sengaja `python3` (`/usr/bin/python3`, punya
`cryptography` untuk mendekrip payload wiki), bukan venv build. Di dashboard,
`have` bisa lebih besar dari `expected`: `expected` adalah jumlah kartu unik
di daftar wiki saat ini, sementara `have` menghitung semua `.webp` di disk —
`refresh-cards.py` melakukan **merge** (kartu lama yang tidak lagi terdaftar
tetap disimpan), jadi data yang sudah terunduh tidak pernah hilang.

`normalize-thumbs.py` butuh `ffmpeg`. Kalau binary-nya tidak ada di PATH
systemd, skrip itu cuma memperingatkan dan keluar 0 supaya
`capture-thumbs.cjs` tidak ikut gagal; pasang/symlink ffmpeg ke
`/usr/local/bin/ffmpeg` untuk normalisasi 260x460 yang sebenarnya.

Cek manual:

```bash
python3 tools/czn/update.py --check
curl 'http://127.0.0.1:3000/api/update/chaoszero?mode=check'
curl 'http://127.0.0.1:3000/api/update/chaoszero?mode=apply'   # background
curl 'http://127.0.0.1:3000/api/update/chaoszero/status'
```

## Epic Seven (E7)

Sumber tunggal: **https://e7codex.com/**. Data lama (ekstraksi game-side,
`epic7-v3` / SCSP v3) sudah dihapus; sekarang satu katalog `units.json` yang
jadi acuan untuk semuanya. `tools/update-epic7.py` menyatukan EMPAT sumber
yang harus tetap sinkron:

| Sumber | Endpoint | Isi | Folder |
| --- | --- | --- | --- |
| Lobby | `e7codex.com/data/units.json` → `spine[]` | 855 rig pose lobby | `assets/epic7/<id>/` |
| Combat | `assets.e7codex.com/<id>/combat/` | 466 rig animasi skill (~20 animasi) | `assets/epic7-combat/<id>/` |
| Skill | `units.json` → `skills[]` | 426 animated WebP | `assets/epic7-skill/<id>_skill<n>/` |
| Wallpaper | `e7codex.com/data/lobby_anims.json` | 24 video VP9 WebM (0,88 GB) | `assets/epic7-wallpaper/<id>/` |

Nama, rarity (bintang), elemen, kelas, slug, dan tanggal rilis ditulis ke
`assets/epic7/_names.json`; `applyEpic7Names()` memetakannya ke `name` +
`character`. Rig combat dan animasi skill **tidak muncul sebagai game
terpisah** — keduanya dilampirkan ke kartu karakter lewat `family`, jadi satu
karakter punya dropdown `Lobby / Combat / Skill 1 …`. Keempat game pembantu
ditandai `hiddenGame: true` tapi tetap dikirim ke klien, karena
`switchVariant()` mencari model berdasarkan id.

### Thumbnail & performa

`thumb` dari e7codex berukuran **2075×3120 / ~4,4 MB** per potret. Untuk 855
model itu ~3,4 GB yang harus dikirim ke galeri, jadi `update-epic7.py`
menormalisasinya lewat `ffmpeg` ke lebar **300 px** (proporsi dipertahankan,
~136 KB). Sengaja tanpa Pillow: interpreter systemd `/usr/bin/python3` tidak
memilikinya, sementara ffmpeg sudah dipakai server untuk export. Transport
unduh memakai `curl` karena `urllib` kadang nge-stall 5–33 detik kena
Cloudflare — `--check` turun dari **134 dtk jadi 0,3 dtk**.

### Pembaru

- `--check`: bandingkan hash `units.json` + `lobby_anims.json` dan jumlah
  berkas di disk terhadap `data/epic7-update-state.json` (diabaikan git),
  plus daftar berkas yang belum lengkap. Check pertama bootstrap baseline.
- `--apply`: unduh yang belum lengkap, bangun ulang `_names.json` +
  thumbnail + `_manifest.json`, simpan state. Kegagalan combat/skill/wallpaper
  cuma jadi `warnings`; yang menggagalkan rescan cuma rig lobby.
- `UPDATERS.epic7` punya `rescan: true`, jadi `/api/models` berikutnya
  langsung dipindai ulang tanpa refresh manual.

Kelengkapan model dicek dari **tiga berkas** (`<id>.json` + `<id>.atlas` +
halaman tekstur), bukan cuma `.json`: dulu kalau unduhan halaman atlas gagal,
model dianggap sudah ada selamanya dan tidak pernah dicoba ulang.

Cek manual:

```bash
python3 tools/update-epic7.py --check
curl 'http://127.0.0.1:3000/api/update/epic7?mode=check'
curl 'http://127.0.0.1:3000/api/update/epic7?mode=apply'   # background
```

Tool unduh lama (`download-e7codex.py`, `fetch-e7codex-meta.py`,
`download-e7combat.py`, `download-e7skills.py`, `download-e7wallpapers.py`)
masih ada sebagai referensi, tapi masing-masing cuma menangani satu sumber
dan tidak punya state/rescan — yang dipanggil server adalah updater di atas.

## CrossCore (交错战线)

Sumber tunggal sekarang: **https://crosscore.art/** ("Cross Core L2D Viewer",
134 karakter / 421 kostum / 486 scene). Seluruh aset lama dari ArtHub
(`github.com/Talors1225/arthub-viewer-web`), mirror komunitas, dan pohon
`crosscore-interaction/` sudah **diarsipkan** ke
`/srv/spine-assets/archive-crosscore-<waktu>/`, bukan dihapus.

| Sumber | Isi | Folder |
| --- | --- | --- |
| `/` → `app.<hash>.js` → `catalog-all.<hash>.js` | 486 scene, `coverage.v2357` | `data/crosscore-art-catalog.json` |
| `/api/art/...`, `/api/legacy-art/...`, `/game-clips/...` | 408 rig Spine (4.2.20 / 4.2.38 / 3.8.99, PMA) | `assets/crosscore/<slug>/` |
| `/api/art/<hash>/illustration.webp` | 78 ilustrasi statis | `assets/crosscore-cg/<slug>/` |
| katalog `roster` + `skins` | nama Tionghoa, outfit, rarity | `assets/crosscore/_names.json` |
| ilustrasi statis | 79 thumbnail + `_manifest.json` | `public/thumbs/crosscore/` |

`tools/crosscore/import-art.py` mengunduh semuanya (idempoten, 8 worker,
skip berkas yang sudah ada). Tiga hal yang mudah menjebak:

- Halaman tekstur **selalu** hidup di direktori yang sama dengan `.atlas`.
  Katalog punya tiga bentuk URL (`/api/art/<sha256>/`, `/api/legacy-art/<sha1>/<subdir>/`,
  `/game-clips/<sha256>/`), jadi jangan pernah menebak prefix tetap.
- Beberapa nama berkas mengandung spasi (`Gondul _character.json`) → path
  harus di-URL-encode.
- Baris nama halaman di `.atlas` ditulis ulang ke `<slug>.png` agar cocok
  dengan konvensi scanner (nama folder = stem).

Semua model jatuh ke game **`crosscore`** (`resolveGame` cocokkan awalan,
`crosscore-cg` ikut masuk). `applyCrosscoreNames()` memasang nama karakter,
`characterId`, `outfit`, dan `sceneLabel` dari `_names.json` plus `_extras.json`;
lalu `attachCrosscoreFamilies()` menyatukan **semua scene satu karakter** jadi
satu kartu dengan dropdown Varian: **713 model → 134 kartu** (130 family / 709
model ber-varian). Root selalu rig UTAMA (`rank: 0`), efek `rank: 1`, ilustrasi
statis `rank: 2`; label varian memakai `outfit · sceneLabel`, root diberi label
`Utama`. Regresi: `node tools/check-crosscore-variants.cjs`.

### Efek, zona sentuh, dan suara

`tools/crosscore/import-extras.py` menambahkan tiga lapisan lagi dari situs
yang sama:

- **Efek** (`characters[].effects`, 227 rig `front`/`back`): tiap rig jadi model
  varian `assets/crosscore/<slug>_effF|effB/`. Skeleton-nya punya attachment
  yang **sama persis** dengan atlas scene induk, jadi atlas dan halaman
  teksturnya disalin (hardlink untuk hemat disk) dan nama halamannya ditulis
  ulang. Hasilnya efek bisa dibuka dari dropdown Varian walau viewer kita
  merender satu rig sekali.
- **Zona sentuh** (`/official-zones.js` 225 prefab + `/touch-zones.js` 17):
  `data/cc-interaction.json` dibangun ulang jadi **225 model / 1.554 aksi**
  dengan `prefab` = slug model, sehingga mesin CCI lama langsung aktif lagi.
  `areas` memakai format `[cx, cy, w, h, derajat]` yang sama.
- **Suara** (`/audio/catalog.json`, `entrances.json`, `subtitles.json`):
  **3.638 klip WebM** (236 MB) ke `public/audio/crosscore/clips/`, disajikan
  statis di `/audio/crosscore/clips/<nama>`. **188 model** dapat `audio.tracks`
  (tombol audio bawaan `renderAudio()`), dan aksi sentuh membawa nama klip
  sehingga `cciApplyEvent()` memutar voice saat area disentuh. 3.638 subtitle
  tersimpan di `_extras.json`.

`_extras.json` sengaja terpisah dari `_names.json` supaya `import-art.py`
tidak menimpanya saat apply berikutnya. Regresi:
`node tools/check-crosscore-extras.cjs`.

### Thumbnail

Situsnya cuma menyediakan **79 ilustrasi statis**, jadi 635 rig awalnya tanpa
gambar. `tools/crosscore/render-thumbs.cjs` membuka tiap rig lewat permalink
`?v=<base64url {"m":id}>`, menycreenshot canvas WebGL (1200×800 — di bawah
~1000px layout berubah jadi stack dan clip screenshot gagal), lalu
`tools/crosscore/normalize-thumbs.py` memotong ke subjek memakai **persentil
2%/98%** piksel terang (bukan min/max, supaya satu piksel UI di pojok tidak
membuat crop melar) dan menyimpan WebP ≤256px.

- **408 rig utama** dirender jadi potret ~200×256 (8–18 KB).
- **227 rig efek** tidak dirender sendiri (isinya cuma lapisan partikel);
  mereka memakai thumbnail rig induknya.
- **78 model `crosscore-cg`** tetap memakai 79 ilustrasi WebP lama.

Hasilnya **713/713 model** punya thumbnail. Outputnya sengaja di folder
`public/thumbs/crosscore-render/` dengan `_manifest.json` sendiri supaya
`import-art.py` tidak menimpanya saat apply; `thumbManifest()` menggabungkan
semua folder `public/thumbs/*` sehingga tidak ada kunci yang bentrok. Tool-nya
**idempoten** (WebP yang sudah ada dilewati), jadi jalankan ulang setelah impor
scene baru:

```sh
node tools/crosscore/render-thumbs.cjs --workers 3   # butuh server hidup + Playwright
node tools/check-crosscore-thumbs.cjs
```

`normalize-thumbs.py` butuh Pillow; tool mencari interpreter yang memilikinya
(`THUMB_PYTHON`, venv proyek, `/usr/bin/python3`, lalu `python3`).

### Pembaru

`tools/crosscore/update.py` sekarang memantau katalog crosscore.art, bukan lagi
tiga katalog ArtHub:

- `--check`: ambil HTML → `app.<hash>.js` → `catalog-all.<hash>.js`, bandingkan
  signature + himpunan 486 scene + isi disk terhadap
  `data/crosscore-art-state.json`. Check pertama bootstrap. `have`/`expected`
  diisi untuk dashboard (486/486).
- `--apply`: jalankan `import-art.py` lalu `import-extras.py` (keduanya
  idempoten), tulis ulang `_names.json`, `_extras.json`, thumbnail,
  `_manifest.json`, `cc-interaction.json`, dan state. Kalau efek/touch/suara
  belum pernah diimpor, `--check` menawarkan apply walau katalog utama tidak
  berubah. `rescan: true` memaksa `/api/models` dipindai ulang; apply sukses
  juga otomatis mengunggah ke GDrive lewat `src/gdrive-upload.js` (termasuk
  root `public/audio/crosscore`).
- `UPDATERS.crosscore` memakai `python3` dan `rescan: true`.

Cek manual:

```bash
python3 tools/crosscore/update.py --check
python3 tools/crosscore/import-extras.py --workers 8
curl 'http://127.0.0.1:3000/api/update/crosscore?mode=check' 
curl 'http://127.0.0.1:3000/api/update/crosscore?mode=apply'   # background
```

`tools/update-crosscore*.py` dan `tools/crosscore/refresh-meta.py` masih ada
sebagai referensi pipeline lama, tetapi tidak dipanggil server lagi.

## Brown Dust 2

Sumber tunggal: **https://github.com/Zormolo/Brown-Dust-2-Assets** (repo ~5 GB,
biner lewat Git-LFS — tapi `raw.githubusercontent.com` mengembalikan byte asli,
jadi tidak perlu `git-lfs`).

| Sumber | Isi | Folder |
| --- | --- | --- |
| `assets/spine/<kategori>/…` | 2.365 berkas → 517 model | `assets/bd2-char/`, `assets/bd2/` |
| `assets/ui/costume_face/` (216) + `costume_icon/` (208) | 369 thumbnail | `public/thumbs/bd2/` |
| `data/bd2-names.json` (395 entri) | nama karakter + kostum | sudah di-commit |

`update-browndust.py` menulis langsung ke tata letak viewer:
`bd2-char/<Karakter>/<Kostum>/` untuk model utama, subfolder
`Skill-Cutscene` / `Interaction` / `Light-Novel-Talk` untuk varian, dan
`bd2/<id>/` untuk miscellaneous/special animation. Hasilnya **370 family**
(dropdown Varian) dan 177 varian Skill-Cutscene. `applyBd2Names()` memetakan
nama karakter + kostum lewat `bd2AssetKey()` dari nama berkas `.skel`:
**388 dari 517** model punya nama, sisanya memang tidak ada di
`CharInfo(Dropped).json`.

### Thumbnail

`refresh-thumbs.py` memetakan stem skeleton ke `illust_inven_<stem>.png`
(costume_face), lalu fallback ke `icon_costume<costumeId>.png` lewat
`bd2-names.json` — kunci `cutscene_*` juga terindeks, jadi varian skill
cutscene ikut dapat gambar. 369 berkas jadi **376 kunci manifest** karena 7
folder berisi beberapa skeleton dan `scanModels()` memberi id
`<folder>#<stem>`. Daftar berkas UI di-cache per commit SHA di
`data/bd2-ui-thumbs-state.json` supaya tidak boros kuota GitHub API anonim
(60/jam).

### Pembaru

`tools/browndust/update.py` menyatukan dua langkah: `update-browndust.py`
(model, tiap berkas diverifikasi terhadap SHA git-blob dari Trees API) dan
`refresh-thumbs.py`.

- `--check`: commit SHA + jumlah berkas disk terhadap
  `data/bd2-update-state.json`, plus tanya updater model berapa yang belum ada.
- `--apply`: unduh yang baru, bangun ulang thumbnail, simpan state. Kegagalan
  thumbnail cuma jadi peringatan; yang menggagalkan rescan cuma berkas model.
- `UPDATERS.bd2` memakai `python3` dan `rescan: true`.
- State lama `/srv/spine-assets/bd2-update/state.json` tetap dipakai skrip
  model untuk cache pohon GitHub (commit SHA + daftar blob). Kalau kuota API
  anonim habis (60/jam) dan SHA tidak terbaca, skrip memakai SHA tersimpan —
  rate limit **bukan** perubahan repo, jadi titik merah tidak menyala palsu.
- Smoke test tidak menggantungkan `changed:false` pada upstream: commit baru
  yang sah memang boleh bikin `changed:true`. Yang diwajibkan cuma `ok:true`
  dan `new:0` (tidak ada model yang belum terpasang).

Catatan: skrip model menampung blob unduhan di memori sebelum menulis ke disk.
Restore penuh 2.365 berkas sempat makan ~3 GB RSS; pembaruan harian cuma
memuat delta sehingga aman.

Cek manual:

```bash
python3 tools/browndust/update.py --check
curl 'http://127.0.0.1:3000/api/update/bd2?mode=check'
curl 'http://127.0.0.1:3000/api/update/bd2?mode=apply'   # background
```

Popup **Varian** di tepi kanan stage awalnya WIP khusus BD2; sekarang sudah
dijadikan komponen bersama untuk semua game (lihat section **Variant picker**).
Pembaru aset di atas tidak menyentuh UI itu.

## Make Drama

Sumber sekarang LIVE dari **`https://mad.altterisk.cc/viewer/`** (penerus
katalog MAD Viewer). Pipeline lama yang bergantung clone git
`/opt/re-targets/mad-viewer` + `git fetch` sudah diarsipkan — lihat
`tools/mad-drama.md`.

Empat katalog yang dipakai `tools/mad-drama/refresh.py`:

| Berkas | Isi |
| --- | --- |
| `/data/skin_list.json` | 145 skin (`key`, `kind`, `character`, `stores`, `animations`) |
| `/data/cdn.json` | `unit -> bucket repo` (`anyabot/MAD-assets-1/2`, jsDelivr + fallback raw.githubusercontent) |
| `/data/characters.json` | 202 karakter + `types`: nama EN/KO, rarity, elemen, peran, posisi, divisi, faksi, artis, CV, deskripsi |
| `/data/icons.json` | daftar resmi 88 ikon skin & 180 ikon karakter |

Hasil: **143 model** (dari 131 → +12; 2 skin `drama` cuma PNG tanpa skeleton
memang dilewati), **145 entri `_names.json`**, **134 thumbnail** WebP +
manifest, **63 family** (root 101 kartu).

Beda dengan versi lama:

- Metadata karakter **kaya**, bukan cuma nama: `m.character` bawa `rarity`
  (`★★★`), `element` (`Reason`), `class` (`DPS`), `position`, `division`,
  `faction`, `artist`, `cv`, `desc`, dan `source: "mad.altterisk.cc"`.
- Thumbnail lokal sebelumnya **kosong**; sekarang diunduh dari
  `/icons/skin/Thumbnail_<KEY>.webp`, varian `Thumbnail_Icon_*`, fallback
  `/icons/char/Icon_<CODE>.webp`. Kunci drama sengaja tidak dibuat supaya
  manifest tidak punya entri yatim.
- Satu updater `tools/mad-drama/update.py` + state
  `data/mad-drama-update-state.json`, `rescan: true` di `UPDATERS`.
  `--check` membandingkan hash 4 katalog + jumlah berkas disk; skin `drama`
  dikecualikan dari hitungan "model belum ada" supaya tidak jadi titik merah
  palsu selamanya.

```bash
python3 tools/mad-drama/refresh.py --limit 3   # uji, tidak menimpa metadata
python3 tools/mad-drama/update.py --check
python3 tools/mad-drama/update.py --apply
```

**Bug yang ketemu sekalian:** `thumbManifest()` di `src/server.js` tadinya
memakai satu cache global dengan satu `mtime` maksimum untuk SEMUA manifest
per-game. Akibatnya entri thumbnail yang dihapus tidak pernah hilang (Make
Drama sempat kebaca 136 padahal 134). Cache sekarang **per-game**, jadi
perubahan manifest langsung terbaca tanpa restart.

## Gambar latar (backdrop)

Tombol **Backdrop** di baris kontrol menyalakan/mematikan gambar suasana di
belakang model; dropdown di sebelahnya milih **Aurora** / **Studio** / **Malam**.
Bedanya dengan tombol **Latar**: itu cuma mengganti WARNA polos untuk diagnostik
tepi & PMA, sedangkan Backdrop adalah pemandangan penuh. Kanvas Pixi memakai
`backgroundAlpha: 0`, jadi lapisan CSS di `z-index: 0` langsung terlihat di
belakang skeleton tanpa mengubah rendering sedikit pun.

- Asetnya 3 SVG lokal di `public/backgrounds/` (tanpa CDN/unduhan runtime),
  `background-size: cover`, jadi aman di layar lebar maupun fullscreen.
- Keadaan `on/off` + scene terakhir disimpan di `localStorage` (`stageBackdrop`)
  dan ikut ke permalink sebagai `bk` — tautan tanpa `bk` berarti mati, supaya
  tampilan yang dibagikan tidak mewarisi preferensi sesi sebelumnya.
- Shortcut **`Shift+L`**; `L` tanpa Shift tetap mengganti warna latar.
- Mematikan Backdrop mengembalikan warna latar polos yang terakhir dipilih.

`tools/check-backdrop-fullscreen.cjs` menguji 17 hal: toggle, ganti scene,
shortcut, persist setelah reload, kunci permalink, dan regresi fullscreen di
bawah.

### Bintang jatuh di Aurora

Scene **Aurora** punya lapisan bintang animasi: 18 bintang berkedip ditambah
**18 bintang jatuh** (meteor) yang melintang turun ke kiri. Delay negatif,
durasi, panjang lintasan, dan sudutnya dibedakan satu sama lain sehingga
beberapa meteor terlihat bersamaan di langit tanpa jadi hujan yang seragam;
tiap meteor tetap punya jeda panjang sebelum muncul lagi. Bintangnya **tidak**
digambar di `aurora.svg` — CSS animation tidak bisa menyentuh isi
`background-image`, jadi semuanya berupa elemen DOM `.starfield` di dalam
`#stage-backdrop` (`public/index.html` + `public/styles.css`). Scene Studio dan
Malam sengaja tetap statis. Animasi otomatis mati saat
`prefers-reduced-motion: reduce`; meteornya hilang, bintangnya jadi redup.

`tools/check-aurora-stars.cjs` menguji 28 hal: animasi benar-benar berjalan
(`currentTime` maju), lintasan meteor ke kiri-bawah lalu memudar saat jeda,
beberapa meteor aktif bersamaan, isolasi antar scene, `prefers-reduced-motion`,
dan tidak ada 404 aset.

### Bug fullscreen blank hitam (diperbaiki)

Gejala: begitu masuk fullscreen, seluruh layar jadi hitam walau model masih
termuat. Akarnya **bukan** WebGL, melainkan tabrakan spesifisitas CSS:
`.layout.is-gallery.sidebar-hidden` (3 kelas) imbang dengan
`:root:fullscreen .layout` (3) dan ditulis belakangan, sehingga grid tetap dua
kolom `0 1fr`. Karena `.sidebar` di-`display:none` saat fullscreen, satu-satunya
item grid (`.stage`) jatuh ke kolom **pertama yang lebarnya 0** → kanvas
berukuran 0 → layar hitam (tinggal ~2% piksel non-hitam).

Aturan fullscreen sekarang menyebut varian `.sidebar-hidden` / `.is-gallery`
(4–5 kelas) sehingga menang dan grid benar-benar satu kolom `1fr`. Regresi
diuji dengan **pengukuran lebar stage + analisis kecerahan screenshot** lewat
ffmpeg, bukan cuma "tidak error": sesudah perbaikan stage 1400 px dan piksel
non-hitam kembali normal.

## Mitao Utopia — updater pindah ke pipeline iOS

`UPDATERS["mitao-utopia"]` menunjuk `tools/update-mitao.py` (interpreter
`/srv/venv-spine/bin/python`, `rescan: true`). Audit menemukan tiga masalah dan
semuanya diperbaiki:

- **`ASSET_DIR` salah**: default `/opt/spine-viewer/assets/mitao-utopia` tidak
  ada, padahal service jalan dari `/root/spine-viewer`. Akibatnya `--check`
  melapor `have: 0` (padahal 252 model) dan `--apply` menulis ke pohon yang
  tidak dipindai server. Sekarang `ROOT/assets/mitao-utopia` relatif repo.
- **`--check` bohong**: tanpa state, `previous: null` menyalakan titik merah
  selamanya dan tidak ada field `ok`. Sekarang bootstrap baseline, `_ver_eq()`,
  dan `have` dari direktori asli.
- **Android v3 / iOS v2 tidak kompatibel**: forum `live2dhub.com/t/topic/6410`
  post #15 mengonfirmasi. Empat container dipetakan lewat HTTP Range tanpa
  unduh APK 198 MB:
  - bundle Android `IDOLNAB3` → **XChaCha20-Poly1305 terpecahkan** di
    `tools/mitao/idol_rs_v3.py` (Ghidra atas `libidol_resource_guard.so`);
  - manifest Android `IDOLRS1` → wrapper 24 byte + `IDOLAB2` v2 + tanda tangan
    RSA-3072 384 byte, kunci master dirotasi di **Obfuz VM** (468 kandidat
    kunci dari metadata IL2CPP + 240 label KDF tetap gagal);
  - manifest iOS 1.6.2 → v2 dengan kunci `13db410d…`, **kebuka**: 3226 bundle,
    1038 skeleton; kunci ini gagal membuka HMAC manifest Android;
  - `global-metadata.dat` → `IDOLMD1`, kunci `3d7900c1…` membuka 17.736.188
    byte metadata IL2CPP plaintext.

Karena isi manifest kedua platform identik (`plain_len` cuma beda 1 byte =
panjang string versi), updater **dialihkan ke iOS**: manifest diambil dari CDN
`ios_cn_release` (bukan APK 198 MB), didekrip `tools/mitao/idol_v2.py`, lalu
bundle skeleton diunduh + didekrip + diekstrak. Berkas bundle tetap spesifik
platform — `FileHash` iOS ditolak endpoint Android — jadi seluruh alur
(endpoint, kunci, dekripsi) ikut iOS, tidak dicampur.

`--apply --manifest-only` menyegarkan manifest tanpa mengunduh bundle (aman
untuk verifikasi); `--apply --replace` mengekstrak ke staging, memvalidasi
minimal 50 model lengkap, lalu menukar seluruh `assets/mitao-utopia` dengan
hasil iOS (pohon Android lama dibackup ke
`/srv/spine-assets/mitao/android-backup-<waktu>/`). `--apply` biasa menambah
model baru tanpa menimpa yang ada. Dekripsi Android v3 tetap disimpan sebagai
referensi RE. Detail struktur header, KDF, dan primitif ada di
`tools/mitao/README.md`.

**Thumbnail + varian (2026-11-08)**: semua 3226 bundle diekstrak
`tools/mitao/extract-all.py` ke `/srv/spine-assets/mitao/extracted/` (13.334
berkas, path mirip `AssetPath` asli) dan bisa dibrowse lewat File Browser
(`filebrowser.service`, port 8080). Thumbnail diambil dari folder
`DynamicSingleTextures/HeroSelectDisplay` — 35 sprite jadi WebP 300px, dipakai
bersama 116 model lewat `public/thumbs/mitao-utopia/_manifest.json`
(`tools/mitao/refresh-thumbs.py`, dipanggil otomatis `--apply`). Varian:
`front_<id>` jadi kartu root, `back/hfront/common/skill/hspecial_<id>` jadi baris picker
`attachMitaoFamilies()`. Seluruh 43 model `equip_*` dihapus permanen. Nama
karakter dari `HEROINFO_Name_<id>` di tabel lokalisasi bundle (`refresh-names.py`
→ `data/mitao-names.json` → `applyMitaoNames()`): 143 model dapat nama asli
Jepang, id tetap dicantumkan supaya bisa dicari. Hasil akhir **214 model /
136 kartu root / 78 varian**.

Regresi: `tools/check-mitao.cjs` (15 assertion: endpoint HTTP asli,
`--apply --manifest-only`, self-test solver v2 dan v3) +
`tools/check-mitao-variants.cjs` (26 assertion API + UI Playwright).

## Poker Fate — updater XENC terpasang di UI

`UPDATERS["pokerfate"]` (`rescan: true`) menjalankan
`tools/pokerfate/update-pokerfate.py`. Sebelumnya updater ini cuma skrip manual
tanpa `--check`/`--apply` dan tidak terdaftar, jadi tombol "Perbarui aset"
untuk game ini mati. Sekarang: `--check` 0,6 dtk (1 `HEAD` + state
`data/pokerfate-update-state.json`), `--apply` idempoten, `--probe` memverifikasi
konstanta `S=0xAF3E40196CB07413` / `C=0x61C8864680B583EB` dari
`live2dhub.com/t/topic/6530` ke APK live lewat HTTP Range tanpa unduh 1,61 GiB.
Progres ke stderr, stdout murni JSON; dekripsi big-int; preflight UnityPy
menolak "dekripsi palsu"; staging divalidasi sebelum swap (backup di luar repo).
Regresi `tools/check-pokerfate.cjs` (21 assertion). Detail:
`tools/pokerfate/README.md`.

## Lost Sword — migrasi ke `lost-sword-l2d-viewer.pages.dev`

Sumber tunggal sekarang LIVE dari **`https://lost-sword-l2d-viewer.pages.dev/`**,
menggantikan ekstraksi XAPK mentah (`tools/extract-lostsword.py` +
`tools/extract-lostsword-video.py`) yang sebelumnya mencampur 868 model
berduplikat kapitalisasi (`Anessa` vs `anessa`), ratusan monster/prop mentah,
video High/Low dobel, dan nol thumbnail. Pohon lama dibackup ke
`/srv/spine-assets/lostsword/apk-backup-*/`.

- `tools/lostsword/refresh.py` mengunduh HTML utama, me-resolve dinamis
  `/assets/index-<hash>.js`, lalu mengekstrak katalog `jl=[{...}]` (**147 entri**
  per 2026-11-16) dengan tokenizer murni Python.
- **285 folder Spine / 297 skeleton** di `assets/lostsword/{standing,chibi,pet}/`
  (164 model standing termasuk folder `Lobby_*` multi-layer `#_F`/`#_B`,
  81 chibi Battle Mode, 52 pet).
- **88 video cutscene MP4** di `assets/lostsword-video/{skill-videos,memorial-videos}/`
  (`hiddenGame: true`, seluruhnya menempel ke family karakter di `lostsword`).
- **87 family karakter** di `assets/lostsword/_names.json` (`attachLostSwordFamilies()`
  di `src/server.js`): 385 item (297 Spine + 88 video) digabung menjadi **87 kartu
  root** tanpa tabrakan aset maupun label, lengkap dengan pencarian sub-judul
  kostum (`"First Love"`, `"Silent Shadow"`, `"Bunny"`, `"Bikini"`, `"Lingerie"`).
- **385/385 thumbnail WebP** (277 berkas unik) di `public/thumbs/lostsword/` +
  `_manifest.json` (`char_*.webp` 256×340 untuk standing/video, `small_*.webp`
  untuk Battle Mode, dan `pet_*.webp` untuk Pet).
- Semua angka di atas **mengikuti katalog live** dan tersimpan di
  `assets/lostsword/_names.json`; `tools/check-lostsword.cjs` membacanya sebagai
  sumber ekspektasi, jadi rilis situs tidak membuat regresi palsu merah.

**Penggantian penuh (2026-11-16).** Pohon lama ternyata masih menyimpan sisa
ekstraksi XAPK (`unit/` 411 + `lobbyunit/` 321 model, plus video `High/` & `Low/`)
sehingga pustaka membaca 1.120 model campuran. `refresh.py --replace` mendeteksi
layout legacy itu, membangun staging **hanya** dari katalog situs (hardlink dari
pohon lama bila cocok, unduh sisanya), lalu mengarsipkan seluruh pohon lama ke
`/srv/spine-assets/lostsword/apk-backup-<waktu>/` sebelum swap. Hasilnya
`assets/lostsword/` cuma berisi `standing/`, `chibi/`, `pet/` (463 MB, dari
1,7 GB) dan `assets/lostsword-video/` cuma `skill-videos/` + `memorial-videos/`
(159 MB, dari 599 MB). Root GDrive yang bersesuaian juga di-`rclone sync`
supaya restore tidak mengembalikan model lama.
- `UPDATERS["lostsword"]` & `UPDATERS["lostsword-video"]` (`rescan: true`)
  menjalankan `tools/lostsword/update.py` (`--check` / `--apply`). Regresi:
  `tools/check-lostsword.cjs` (33 assertion API + disk + Playwright). Detail:
  `tools/lostsword/README.md`.

## Otherworld Mercenary Corps — `com.Cryptect.Mercenary`

Sumber ganda: **XAPK Google Play** (lewat APKPure) untuk aset bawaan + **CDN
Addressables resmi** untuk konten unduhan:
`https://d2yyge1twff5nv.cloudfront.net/Product/Live/<versi>/Android/`.
XAPK-nya 697 MB tapi seluruh entri `STORED`, jadi `tools/mercenary/refresh.py`
cukup 2–3 request HTTP Range untuk membaca central directory lalu mengunduh
**hanya 3 bundle** (~233 MB), bukan paket penuh.

- **98 model Spine 4.0.x** di `assets/mercenary/`: 9 dari 3 bundle lokal
  (`duplicateassetisolation_*`, `local_assets_all_*`) + 89 dari bundle
  `remote_prefab_spineillust_*.bundle` di CDN. Tiap bundle remote
  self-contained (TextAsset skeleton + `.atlas` + Texture2D 4096²).
  Nama berkas memuat hash konten ⇒ cache `/srv/spine-assets/mercenary/remote/`
  aman dipakai lintas versi dan `--apply` ulang tidak mengunduh ulang.
- `catalog_Product.json` di CDN (hash `m_BuildResultHash` berbeda dengan
  `assets/aa/catalog.json` di APK) dipakai untuk daftar 95 karakter kanonik
  dan 94 bundle `SpineIllust`. Bundle < 100 KB cuma berisi prefab MonoBehaviour
  (skeleton-nya sudah ada di APK) ⇒ dilewati.
- **85 ilustrasi slot** `UI_Slot_Illust_*` → `assets/mercenary-illust/` yang
  diindeks sebagai galeri `format: "image"` (pemindai galeri menerima akhiran
  `-illust` selain `-cg` / `-skill`).
- **49 kartu root + 49 varian** dalam **32 family**: varian kostum
  (`Bikini_Kronos`, `Masquerade_Ema`, …) dan rig alternatif (`ema_alt`,
  `kei_alt`) disatukan lewat picker Varian. Nama + family ditulis ke
  `assets/mercenary/_names.json` lalu diterapkan `attachMercenaryNames()`.
- **98 thumbnail WebP** di `public/thumbs/mercenary/` — **semua dari gambar
  ilustrasi karakter, bukan halaman atlas** (kumpulan potongan badan).
  Prioritas: `UI_Slot_Illust_*` → potret `UI_Emoticon_*` → art NPC
  `Citizen_*` → splash art lobby CDN `UI_Bg_Lobby_*_Title_*` → halaman atlas
  sebagai fallback terakhir. Varian kostum mewarisi ilustrasi karakter utama
  lewat family picker; nama beda eja/akhiran (`ninetails-roselin`,
  `bikini-eventdaphne`, `albedo2`, …) dipetakan lewat `ILLUST_ALIASES`.
  Asal tiap thumbnail tercatat di `public/thumbs/mercenary/_sources.json`.
- `UPDATERS["mercenary"]` (`rescan: true`) menjalankan
  `tools/mercenary/update.py` (`--check` / `--apply`). `--check` cuma 1 HEAD
  XAPK + 1 GET 32 byte `catalog_Product.hash`; perubahan katalog CDN tanpa
  naik versi APK tetap terdeteksi. State: `data/mercenary-update-state.json`.
- Regresi: `tools/check-mercenary.cjs` (36 assertion, termasuk asal thumbnail
  ilustrasi dan render Playwright untuk model lokal & CDN). Detail: `tools/mercenary/README.md`.

## 欲洛降临 (EroEra) — `youdianse.com/game/detail/456`

Diambil langsung dari **Unity GameFramework hotupdate CDN**
(`https://res-01.eepgames.com/buildCfg/0_1_64/Android/Version.txt` →
`GameFrameworkVersion.<hash8>.dat` berformat `GFU\x02`), tanpa perlu mengunduh
APK 641 MB:

- `tools/eroera/refresh.py` menyinkronkan 75 bundle `Spine/*`, `TbData/TbDatas`
  (`LoadType = 2` QuickDecrypt 220 byte XOR `hash_code`), dan
  `SpriteAtlas/Packs/Hero` ke `/srv/spine-assets/eroera/bundles/`.
- **174 model Spine (4.1.23 / 4.1.24)** di `assets/eroera/` yang dikelompokkan
  ke **43 kartu root** (30 Hero `hero_10001..10030` + 10 Pet `pet_*` + 3 Extra
  `role_c010/t001/t002`) dan **131 varian** (`Utama`, `H Scene — Base (初级)`,
  `H Scene — Adv (高级)`, `Interaction (调教)`, `Activity`, `Aim`, `Cover`,
  `Skill Cut`).
- Nama asli karakter & pet di-parse dari tabel binary `ByteBuf` Luban
  (`hero_tbheroshowgirl` & `pet_tbpetcharacter`); potret kartu bertingkat
  (`card_1_1`..`card_30_3`, `p_kp41001`..`p_kp45002`) diekstrak dari
  `SpriteAtlas/Packs/Hero` menjadi 64 berkas WebP di `public/thumbs/eroera/`
  (menutup 165/174 model).
- `UPDATERS["eroera"]` (`rescan: true`) menjalankan `tools/eroera/update.py`
  (`--check` / `--apply`). Regresi: `tools/check-eroera.cjs` (27 assertion).
  Detail: `tools/eroera/README.md`.

## Nikke — unduh ulang dari ArtHub

Data lama (3416 model / 11 GB) punya banyak model dobel: 313 dari 321
karakter `cNNN` muncul berkali-kali. Atas permintaan user, `assets/nikke/`
**diarsipkan** ke `/srv/spine-assets/nikke-old-20261107/` (bukan `rm -rf`, jadi
bisa dibalik) lalu diunduh **dari nol** dari
`https://github.com/Talors1225/arthub-viewer-web/tree/main/nikki`.

Repo itu menyimpan **katalog + viewer**, bukan berkas model. Aset aslinya ada
di bucket R2 yang dipakai `arthub-cos.js` (`/nikki/spine/` di-rewrite jadi
`/nikki/spine_carved/`):

| Berkas | Isi |
| --- | --- |
| `nikki/nikki_chars.json` | 2104 karakter, tiap satu `{dir, skel, atlas}` + `characterCode`, `resourceType`, `typeLabel` |
| `nikki/character-names.json` | 131 profil nama karakter |
| `pub-bdd986c6ec274f53b01df62ac49e02e2.r2.dev/nikki/spine_carved/<folder>/` | `.skel` (Spine **4.1.20** binary), `.atlas` (`pma:true`), halaman PNG |

`tools/nikke/refresh.py` mengunduh 2104 folder, **mengganti nama skel + atlas
ke `<id>`** supaya id stabil, dan **membiarkan nama halaman PNG apa adanya**
(karena atlas memanggilnya persis). Beberapa atlas diawali BOM UTF-8 — parser
memakai `utf-8-sig` supaya halaman pertama tidak jadi 404. Hasil: **2104 model,
2104 id unik, 0 duplikat**, 6,1 GB, `_names.json` 2104 entri.

- `applyNikkiNames()` di `src/server.js` membaca `_names.json` **setelah**
  `attachCharacters()`, jadi **nama NKAS menang** atas peta lama
  (`data/nikke-*.json`) yang kuncinya sudah tidak cocok.
- `UPDATERS["nikke"]` menunjuk `tools/nikke/update.py` + state
  `data/nikke-update-state.json`, `rescan: true`. Updater ini berpusat ke
  NKAS (lihat "Updater berbasis NKAS" di bawah). **`tools/update-nikke.py`
  (repo Nikke-db) sudah USANG** — jangan dipakai, ia mengembalikan duplikat.
  Skripnya sengaja dibiarkan sebagai arsip.
- Manifest 3416 id lama tersimpan di `/tmp/nikke-deleted-ids-2026-11-07.json`.

```bash
python3 tools/nikke/refresh.py --limit 3     # uji
python3 tools/nikke/update.py --check
python3 tools/nikke/update.py --apply
```

`tools/check-nikke.cjs` menguji 39 hal: jumlah & keunikan id, kelengkapan
setiap folder (skel + atlas + semua halaman atlas), nama Inggris dari NKAS
(tanpa aksara Tionghoa), varian, thumbnail, updater berbasis NKAS, render 3
model (tanpa 404), dan `--check` lewat endpoint HTTP asli.

### Updater berbasis NKAS

`tools/nikke/update.py` memantau **NKAS sebagai sumber kanonik**; ArtHub cuma
sumber berkas model. State `data/nikke-update-state.json` menyimpan tiga sidik
terpisah (`sig` gabungan, `arthubSig`, `nkasSig`), daftar 206 kode `cNNN`,
dan jumlah nama NKAS yang terpakai.

- `--check` laporkan blok `nkas`: `{sumber, karakter, kode, sig, baru,
  belumAdaDiArtHub, namaTerpakai}`. Alasannya spesifik — "sumber nama NKAS
  berubah" atau "NKAS: 1 karakter baru (c121 Anne: Miracle Fairy)" — bukan
  lagi selalu "katalog ArtHub berubah".
- Karakter baru dideteksi dari selisih `nkasCodes` state; state format lama
  di-upgrade diam-diam supaya 206 karakter tidak salah dibilang baru.
- `belumAdaDiArtHub` = kode yang sudah ada di NKAS tapi belum punya rig di
  katalog ArtHub (saat ini `c019`).
- `--apply` jalankan **`refresh.py --names-only` lebih dulu** (segarkan nama
  dari NKAS), baru unduh model + thumbnail dari ArtHub. Kalau NKAS mati,
  `namaOk: false` jadi peringatan, `_names.json` lama dipertahankan, dan
  unduh model tetap dianggap sukses.
- Endpoint NKAS opsional di `source_state()`: kalau mati, `--check` tetap
  jalan (field `nkas.karakter` jadi 0), tidak bikin server error.

Response `/api/update/nikke?mode=check` meneruskan blok `nkas` apa adanya
(server melakukan `{...result, log}`), jadi UI bisa menampilkannya.

### Nama karakter (NKAS)

Katalog ArtHub menyimpan `characterName` berbahasa Tionghoa (`安妮`, `尤妮`) dan
label tipe seperti `剧情 / 过场` — 88 nama + 1055 label tadinya lolos ke UI.
`build_names()` di `tools/nikke/refresh.py` sekarang mengambil nama dari
**https://nkas.pages.dev/nikkes/**:

- Endpoint yang dipakai halaman itu: `/nk_data/nikkegg/characters.json`
  (206 karakter; `img: si_c102_00_s` → kode `c102`, `name` sudah Inggris).
- Kode `characterCode` → nama: `c121` → `Anne: Miracle Fairy`, `c160` → `Yuni`.
- Tanpa kode: cocokkan **url terpanjang** NKAS di dalam id, dan **hanya untuk
  entri yang punya `characterName`** (22 model: `EventScene_staranis_03` →
  `Anis`, `azxservicetime_character_diesel` → `Diesel`). Tanpa pembatas ini
  url `eve` nyangkut di prefix `EventScene_*` (123 kartu salah jadi "EVE"),
  `ade` di `madeinrush_*`, `mica` di `chemical`.
- NPC yang tak ada di 206 entri utama dijaring dari situs saudara NKAS
  `nkas-l2d.pages.dev/characters.json` (571 entri, `c013_00` → `Marian`).
- Label tipe Tionghoa diganti `resourceType` yang sudah Inggris
  (`Cutscene`, `Catalog`, `Battle`, `Lobby`, `Skill`, …).

Hasil: **2104 nama, 0 aksara Tionghoa**, 1625 di antaranya langsung dari NKAS.
`--names-only` meregenerasi `_names.json` tanpa mengunduh ulang 2104 model;
`update.py --check` ikut mengawasi hash kedua endpoint NKAS.

### Varian aim / cover / skillcut

`attachNikkiFamilies()` di `src/server.js` mengelompokkan rig sekarakter jadi
satu kartu: `c010_00` = **Utama**, `c010_aim_*` = **Aim NN**,
`c010_cover_*` = **Cover NN**, `c010_00_skillcut` = **Skill Cut**, dan
`catalog-*` = **Katalog · …**. Hasil: **391 family / 1406 model jadi varian**,
pustaka turun dari 2104 jadi **1089 kartu root**. Picker bersama yang sudah ada
dipakai apa adanya — ≤3 varian jadi tab segmented, >3 jadi popup dengan
thumbnail per baris.

### Thumbnail

`tools/nikke/refresh-thumbs.py` menarik **2104 poster WebP** dari
`posters/nikki/<id>--<variant>.webp` di repo yang sama (`variant` diambil dari
`cutscenes[0].variant`, nilainya `0` atau `Catalog` — cocok persis dengan suffix
berkas). Ditulis ke `public/thumbs/nikke/<id>.webp` + `_manifest.json`, 38 MB,
tanpa crop (maks 300 px, aspect utuh, `object-fit: contain`).

- 2 model tanpa poster sendiri (`c330_aim_00`, `c550_aim_00`) fallback ke
  poster root karakternya.
- 3 poster berupa WebP **animasi** yang decoder ffmpeg tak bisa baca disimpan
  apa adanya (tetap valid untuk `<img>`), jadi tetap 2104/2104.
- `update.py` sekarang menjalankan **model + thumbnail** sekaligus dan
  menyertakan jumlah keduanya di state `--check`.

## Thumbnail MuvLuv dari game CG

1243 rig Spine di game **マブラヴ ガールズガーデンX** sebelumnya cuma punya badge
huruf. Thumbnailnya sekarang diturunkan **lokal** dari game
**マブラヴ ガールズガーデンX — CG** (1170 PNG di `assets/muvluv-cg/`) — tidak ada
unduhan jaringan. Galeri CG sendiri tidak perlu thumbnail terpisah: model
`format: "image"` langsung memakai `imageFile`-nya sebagai kartu.

`tools/muvluv/refresh-thumbs.py` memasangkan lewat prioritas sumber:
`illust_portrait_` (potret 360×640) → `cg_chara_` → `cg_h_` → `cg_episode_` →
`cg_mecha_` → `cg_story_`. Id model punya varian (`e124105_F`, `100201_B`,
`100001c`, `a10001`…), jadi kandidat dasarnya = id utuh, tanpa akhiran
`_F/_B/_S/_A`, tanpa `c`, lalu tanpa prefiks huruf; satu potret dipakai bersama
semua varian karakter.

Hasil: **1107 thumbnail** WebP (15 MB) + `_manifest.json`, 136 model tanpa CG
tetap fallback huruf. Sesuai keputusan user, **semua keluarga CG dipakai
termasuk `cg_h_` eksplisit**, dan gambar **tidak di-crop** — cuma diperkecil
agar muat 300×300 dengan aspect ratio utuh (360×640 → 169×300). CSS kartu sudah
`object-fit: contain`, jadi sisi kosongnya memang disengaja. Konversi lewat
`/usr/bin/ffmpeg` (`libwebp`), bukan Pillow.

Peta model → berkas CG disimpan di `data/muvluv-thumb-sources.json` buat audit.
Satu updater `tools/muvluv/update.py` terdaftar di `UPDATERS["muvluv"]`
(`rescan: true` supaya klien memuat ulang `/api/thumbnails`):

```bash
python3 tools/muvluv/refresh-thumbs.py --limit 3   # uji, tidak menimpa manifest
python3 tools/muvluv/update.py --check
python3 tools/muvluv/update.py --apply
```

`tools/check-muvluv-thumbs.cjs` menguji 20 hal: jumlah, kunci manifest valid,
rasio aspek utuh, distribusi sumber, render kartu di browser, fallback model
tanpa CG, dan `--check` lewat endpoint HTTP asli.

## Variant picker (semua game)

Picker varian dipakai **semua game yang punya `family`**, bukan lagi khusus
Brown Dust 2. Dua bentuk tergantung jumlah saudara:

- **≤3 varian → tab segmented** di atas stage. Selalu terlihat, satu klik
  langsung ganti model, tanpa popup. Ini yang dipakai mayoritas model
  (BD2 2-3, E7 2-3, CrossCore 2).
- **>3 varian → popup** di tepi kanan stage. CZN sampai 7 saudara, E7 bisa 5
  (Lobby / Combat / Skill 1..3), jadi dropdown inline terlalu sempit.

Rincian:

- `<select id="variant-select">` **tetap diisi** walau disembunyikan. Dia state
  holder: `permalinkState()` menulis `s.va` dari `dataset.id`-nya, restore
  permalink dan handler `change` membacanya. Jadi tautan & keyboard nggak rusak.
- Tiap baris popup bawa **thumbnail 44×44** dari `/api/thumbnails` (sudah
  dimuat saat boot, tanpa request tambahan) + badge kecil untuk format bukan
  Spine (`Video` / `Gambar`) atau rig dengan ≥5 animasi (`"23 animasi"` untuk
  Combat E7). Kalau nggak ada potret, fallback huruf pertama label.
- **Header grup** (`Model` / `Aksi` / `Potret` / `Latar` / `Varian`) muncul di
  popup panjang supaya 7 baris CZN nggak jadi deretan teks seragam. BD2
  sengaja tidak digrup agar urutan karakter › skin-nya tidak berubah.
- **Preview hover**: arahkan kursor ke baris → panel gambar besar di kiri popup,
  tanpa mengganti model. Hilang saat popup ditutup atau layar <1100 px.
- **Chip "N varian"** di kartu pustaka (daftar & galeri). `family.members`
  sudah ada di payload lean, jadi gratis. Klik chip memuat model dan langsung
  membuka pickernya — pengguna tahu ada varian sebelum model kebuka.
- **Keyboard**: `1`–`9` lompat ke varian ke-N, `[` / `]` siklus (wrap-around).
  Cuma aktif kalau model ber-family dan fokus bukan di input.
- Klik baris/tab → `switchVariant()`, popup tertutup, `<select>` tersinkron.
  Esc / klik di luar menutup popup; `pointerdown` di-stop di popup, tombol,
  dan tab supaya drag-to-pan canvas tidak mencuri klik.

### CrossCore ikut rapi

`attachCrosscoreFamilies()` di `src/server.js` mengelompokkan **semua scene
satu karakter** (rig Spine maupun ilustrasi statis) memakai `characterId`
dari `_names.json` crosscore.art. Hasilnya **486 scene → 134 kartu**, dengan
label varian `outfit · sceneLabel` dan label `Utama` untuk root. Ini
menggantikan grouping lama `Spine` / `Interaksi` yang memasangkan dua pohon
aset ArtHub yang sudah diarsipkan.

`tools/check-variant-picker.cjs` menguji picker di BD2, E7, CZN, dan
CrossCore (50 assertion): tab vs popup, chip di kartu, `<select>` state holder,
header grup, thumbnail & preview hover, klik ganti model, keyboard `1`/`]`,
0 JS error.

## Smoke test

```bash
node tools/check-controls.cjs    # tombol & toggle masih jalan
node tools/check-toolbar.cjs     # layout toolbar
node tools/check-fps.cjs         # FPS meter
node tools/check-mad-ports.cjs   # export PNG, clock, part picker
node tools/check-permalink.cjs   # tautan: tulis, dialog, pulihkan, payload rusak
node tools/check-cherrytale.cjs  # model Cherry Tale benar-benar tergambar
node tools/check-lean-library.cjs # indeks ringan + detail + A/B + shortcut
node tools/check-czn.cjs         # CZN: roster wiki, thumbnail, render Spine 3.8
node tools/check-czn-cards.cjs   # CZN: kartu skill, frame, shortcut K
node tools/check-epic7.cjs       # E7: 4 sumber e7codex, nama, varian, render
node tools/check-crosscore.cjs   # CrossCore: 713 model crosscore.art, integritas, render
node tools/check-bd2.cjs         # BD2: Zormolo, 517 model .skel, family, render
node tools/check-mad-drama.cjs   # Make Drama: 143 model, metadata, 134 thumb, render
node tools/check-backdrop-fullscreen.cjs # backdrop on/off + regresi fullscreen blank hitam
node tools/check-aurora-stars.cjs  # Aurora: bintang kedip + bintang jatuh (meteor)
node tools/check-muvluv-thumbs.cjs # MuvLuv: 1107 thumbnail dari game CG
node tools/check-nikke.cjs        # Nikke: 2104 model ArtHub, 0 duplikat, render
node tools/check-mitao.cjs        # Mitao: solver iOS v2, manifest, updater
node tools/check-mitao-variants.cjs # Mitao: varian front_*, nama JP, thumbnail
node tools/check-pokerfate.cjs    # Poker Fate: updater XENC, probe HTTP Range
node tools/check-lostsword.cjs    # Lost Sword: model/video/family dari _names.json
node tools/check-eroera.cjs       # 欲洛降临 (EroEra): 174 model, 43 family, Luban, thumb
node tools/check-mercenary.cjs    # Mercenary: 98 model (89 CDN), 85 ilustrasi, 32 family
node tools/check-ivntight.cjs     # IV-N-Tight: hash katalog live, 84 model, 0 404, render
node tools/check-arknights.cjs    # Arknights: 3112 Spine 3.8, nama EN, 2777 ilustrasi, render
node tools/check-zonenova.cjs     # Zone Nova: 188 Spine 4.1 CDN, katalog XOR, ilustrasi, render
node tools/check-stellasora.cjs   # Stella Sora: 36 Spine 4.2 + 252 Live2D, ilustrasi, render
node tools/check-updater-dashboard.cjs # 27 updater: health paralel, cache, mirror lag, UI
node tools/check-arkrecode.cjs    # Ark Re:Code: processed_v2 signature, 18 bukan Spine, render
node tools/check-update-json.cjs  # updater: no 304/body kosong, cache scan Cat Shinobi, toast
node tools/check-catshinobi.cjs   # Cat Shinobi: 307 nama, 186 family, 517 ilustrasi, render
node tools/check-update-refresh.cjs # apply: model baru langsung muncul, tanpa reload
node tools/check-model3d.cjs    # 3D glTF: 59 model, render, clip, balik ke 2D
node tools/check-variant-picker.cjs # picker bersama: 4 game, thumbnail, switch
node tools/check-update-log.cjs     # log pembaruan tidak hilang sebelum selesai
node tools/check-gdrive-upload.cjs   # peta root backup GDrive, tanpa jaringan
node tools/check-change-log.cjs        # riwayat per game: tanggal + model baru
node tools/check-change-log-stale.cjs  # riwayat vs indeks pustaka basi
node tools/check-crosscore-variants.cjs # 713 model -> 134 kartu karakter
node tools/check-crosscore-extras.cjs   # efek, zona sentuh, dan suara crosscore.art
node tools/check-crosscore-thumbs.cjs   # 713 model punya thumbnail, <img> ke-load
```

Benchmark pustaka (keluaran JSON di baris terakhir, buat diff before/after):

```bash
BENCH_RUNS=3 node tools/bench-library.cjs
```

Butuh `playwright-core` dan server jalan di port 3000. Tes backdrop/fullscreen
juga memakai `ffmpeg` buat mengukur kecerahan screenshot. Semuanya bisa
dijalankan sekaligus dengan `npm run test:smoke`.

Tombol lanjutan (FPS, Bagian, Tulang, Kisi, …) sekarang ada di dalam popover
**Alat**, jadi tes yang mengkliknya memakai `openTools()` dari
`tools/smoke-helpers.cjs` untuk membuka menu lebih dulu — termasuk lagi
setiap setelah `reload()`, karena status menu tidak ikut tersimpan.

## Catatan pengembangan

- Bundle frontend harus di-rebuild (`npm run build`) setelah ngedit
  `src/viewer.js` — yang disajikan itu `public/dist/viewer.js`, bukan source.
- Beberapa fitur niru **MAD Viewer** (export PNG native, clock deterministik,
  part picker). `tools/check-mad-ports.cjs` khusus ngecek hasil port-nya.
- Model legacy (Spine 2.1.27, mis. Project QT) render di iframe terpisah
  dengan loop sendiri, jadi FPS meter dimatikan di situ — angkanya nggak
  menggambarkan yang sebenarnya.
- **Pustaka puluhan ribu model:** tiga modul yang sengaja dipisah biar `viewer.js` dan
  `server.js` nggak makin gemuk:
  - `src/models-payload.js` — menyusun body full/lean + ETag + gzip + indeks
    `id → model` (server).
  - `src/library-index.js` — grup game, daftar akar per game, jumlah varian,
    dan teks pencarian yang dihitung **sekali** per array `models` (klien,
    cache `WeakMap`; `refresh()` ganti array = invalidasi alami).
  - `src/viewer.js` — `ensureModelDetail()` menghidrasi satu entri lewat
    `GET /api/models/:id` tepat sebelum model dibuka / dipakai sebagai B.
  Render pustaka tinggal menerapkan state dinamis (favorit, badge NEW, query)
  di atas indeks itu. Ukur dengan `node tools/bench-library.cjs`.
