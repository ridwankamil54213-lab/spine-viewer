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

Model CZN diambil dari dua sumber yang sengaja diiris, jadi pustakanya isi
**cuma karakter yang benar-benar ada di wiki**:

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

`tools/czn/update.py` menyatukan keempat tool di atas jadi **satu updater**
untuk `czn-rigs` dan `czn-cutins-cg`. Tombol di header pustaka otomatis muncul
saat membuka game CZN; titik merah muncul kalau ada yang berubah.

- `--check` (cepat, tanpa unduh aset): bandingkan tanda tangan tiga sumber —
  `index.json` + commit `main` GitHub, roster wiki, dan daftar kartu wiki —
  serta himpunan id dan jumlah berkas di disk terhadap
  `data/czn-update-state.json` (diabaikan git). Check pertama melakukan
  *bootstrap* supaya tidak langsung melapor "semua baru".
- `--apply` (background, ada panel log): jalankan berurutan `refresh.py` →
  `fetch-icons.py` → `refresh-cards.py` → `capture-thumbs.cjs`, lalu simpan
  state. Ikon & thumbnail bersifat kosmetik: kalau wiki sedang rewel mereka
  cuma diperingatkan, tidak menggagalkan model/kartu.
- Server menandai `forceModelRescan` setelah apply sukses, jadi `/api/models`
  berikutnya (dipicu `refresh()` klien) langsung pindai ulang tanpa request
  tambahan yang menghabiskan kuota rate limit. Cache `index.json` kartu juga
  di-reset.

`tools/update-czn.py` lama **tidak dipakai lagi**: ia butuh clone git
`/opt/re-targets/czn-repo` dan akan menimpa `_names.json` / `_manifest.json`
dengan metadata lama (tanpa `charType`/`ego`/`rarity`). Interpreter updater
sengaja `python3`, bukan `/srv/venv-spine/bin/python` yang tidak punya
`cryptography`.

Cek manual:

```bash
python3 tools/czn/update.py --check
curl 'http://127.0.0.1:3000/api/update/czn-rigs?mode=check'
curl 'http://127.0.0.1:3000/api/update/czn-rigs?mode=apply'   # background
curl 'http://127.0.0.1:3000/api/update/czn-rigs/status'
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

Sumber tunggal: **https://github.com/Talors1225/arthub-viewer-web**. Data lama
dari mirror komunitas (`kmou424/Crosscore_Anti_Hexie_Assets`,
`R2iCecho/Crosscore_Assets_curr_1`) ditinggalkan — indeks ArtHub lebih baru
dan asetnya disajikan lewat Cloudflare R2 yang bisa diakses langsung.

| Sumber | Isi | Folder |
| --- | --- | --- |
| `crosscore/crosscore_chars.json` | 502 entri → 495 folder unik (Spine 4.2.20 / 4.2.38) | `assets/crosscore/` |
| `crosscore-interaction/catalog/catalog.json` (R2) | 324 prefab → 325 model/layer | `assets/crosscore-interaction/` |
| `thumbs/index.json` + `thumbs/crosscore/*.webp` | 761 potret WebP 400 px (23 MB) | `public/thumbs/crosscore*/` |

Kedua pohon aset jatuh ke game **`crosscore`** (`resolveGame` mencocokkan
awalan). `attachCrosscoreFamilies()` lalu menggabungkan folder yang sama dari
kedua pohon jadi satu family "Spine / Interaksi": **827 model tetap dikirim ke
klien, tapi cuma 502 kartu root** yang tampil di pustaka (324 pasangan +
beberapa folder ber-skeleton ganda). Lihat section **Variant picker** di bawah.
`_names.json` dikunci oleh **id model penuh** supaya keduanya tidak tabrak;
`applyCrosscoreNames()` memetakannya ke `name` + `character`. 55 prefab
interaksi tidak punya entri di `models[]` katalog, jadi model itu tetap
memakai nama folder — memang tidak ada nama di sumbernya. Panel interaksi
sendiri memakai `data/cc-interaction.json` (270 model) lewat
`/api/interaction/crosscore`.

### Gotcha sumber

- Path prefab menulis `/crosscore-interaction/spine/...`, tapi objeknya ada di
  `/crosscore/spine/...` (lihat `PATH_REWRITES` di `arthub-cos.js`).
- Nama kategori non-ASCII (`角色动态`, `剧情CG`) sudah percent-encoded di
  prefab: harus `unquote` dulu, baru `quote` utuh — kalau di-quote dua kali
  hasilnya 404.
- Beberapa atlas memakai kapitalisasi berbeda dari indeks
  (`60320_skin_Dainslef03.atlas` vs `..._dainslef03...`). Skrip unduh mencoba
  varian kapital per token, bukan cuma lower/upper.
- **7 folder berisi beberapa skeleton** → `scanModels()` memberi id
  `<folder>#<stem>`. Manifest thumbnail di-expand per stem (768 kunci untuk
  761 berkas) dan `applyCrosscoreNames()` fallback ke id dasar.
- 236 kunci thumbnail berasal dari katalog lama (555 entri, varian "effect")
  dan tidak punya model lagi; dilewati.

### Pembaru

`tools/crosscore/update.py` menyatukan tiga langkah: dua skrip unduh
(`update-crosscore-arthub.py`, `update-crosscore-interaction.py`) lalu
`refresh-meta.py` (nama + thumbnail + manifest).

- `--check`: hash `crosscore_chars.json`, `thumbs/index.json`, katalog R2 +
  jumlah berkas disk terhadap `data/crosscore-update-state.json`, plus tanya
  kedua skrip unduh berapa model yang belum ada. Check pertama bootstrap.
- `--apply`: unduh yang belum ada, bangun ulang metadata, simpan state.
  Kegagalan thumbnail cuma jadi peringatan; yang menggagalkan rescan cuma
  kegagalan model.
- `UPDATERS.crosscore` memakai `python3` dan `rescan: true`.

Cek manual:

```bash
python3 tools/crosscore/update.py --check
curl 'http://127.0.0.1:3000/api/update/crosscore?mode=check'
curl 'http://127.0.0.1:3000/api/update/crosscore?mode=apply'   # background
```

`tools/update-crosscore.py` (mirror lama) masih ada sebagai referensi tapi
tidak dipanggil server lagi.

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
  `/assets/index-<hash>.js`, lalu mengekstrak katalog `jl=[{...}]` (143 entri:
  130 `Playable` + 13 `NPC`) dengan tokenizer murni Python.
- **276 folder Spine / 287 skeleton** di `assets/lostsword/{standing,chibi,pet}/`
  (147 folder standing termasuk 11 folder `Lobby_*` multi-layer `#_F`/`#_B`,
  78 folder chibi Battle Mode, 51 folder pet).
- **87 video cutscene MP4** di `assets/lostsword-video/{skill-videos,memorial-videos}/`
  (`hiddenGame: true`, seluruhnya menempel ke family karakter di `lostsword`).
- **84 family karakter** di `assets/lostsword/_names.json` (`attachLostSwordFamilies()`
  di `src/server.js`): 374 item (287 Spine + 87 video) digabung menjadi **84 kartu
  root** tanpa tabrakan aset maupun label, lengkap dengan pencarian sub-judul
  kostum (`"First Love"`, `"Silent Shadow"`, `"Bunny"`, `"Bikini"`, `"Lingerie"`).
- **374/374 thumbnail WebP** di `public/thumbs/lostsword/` + `_manifest.json`
  (`char_*.webp` 256×340 untuk standing/video, `small_*.webp` untuk Battle Mode,
  dan `pet_*.webp` untuk Pet).
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

`attachCrosscoreFamilies()` di `src/server.js` mengelompokkan
`crosscore/<folder>` dan `crosscore-interaction/<folder>` yang berbagi nama
jadi satu family berlabel `Spine` / `Interaksi` — pola sama seperti
`attachEpic7CombatFamilies()`. 324 dari 325 folder interaksi punya pasangan,
jadi **827 model → 502 kartu root**, 649 model ber-family. `family.label`
diisi per model supaya `<select>` memilih opsi yang benar. Model interaksi
tanpa pasangan dibiarkan berdiri sendiri.

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
node tools/check-crosscore.cjs   # CrossCore: ArtHub, 827 model, nama, render
node tools/check-bd2.cjs         # BD2: Zormolo, 517 model .skel, family, render
node tools/check-mad-drama.cjs   # Make Drama: 143 model, metadata, 134 thumb, render
node tools/check-backdrop-fullscreen.cjs # backdrop on/off + regresi fullscreen blank hitam
node tools/check-aurora-stars.cjs  # Aurora: bintang kedip + bintang jatuh (meteor)
node tools/check-muvluv-thumbs.cjs # MuvLuv: 1107 thumbnail dari game CG
node tools/check-nikke.cjs        # Nikke: 2104 model ArtHub, 0 duplikat, render
node tools/check-mitao.cjs        # Mitao: solver iOS v2, manifest, updater
node tools/check-mitao-variants.cjs # Mitao: varian front_*, nama JP, thumbnail
node tools/check-pokerfate.cjs    # Poker Fate: updater XENC, probe HTTP Range
node tools/check-lostsword.cjs    # Lost Sword: 287 model, 87 video, 84 family, thumb
node tools/check-eroera.cjs       # 欲洛降临 (EroEra): 174 model, 43 family, Luban, thumb
node tools/check-mercenary.cjs    # Mercenary: 98 model (89 CDN), 85 ilustrasi, 32 family
node tools/check-ivntight.cjs     # IV-N-Tight: hash katalog live, 84 model, 0 404, render
node tools/check-arknights.cjs    # Arknights: 3112 Spine 3.8, nama EN, 2777 ilustrasi, render
node tools/check-zonenova.cjs     # Zone Nova: 188 Spine 4.1 CDN, katalog XOR, ilustrasi, render
node tools/check-stellasora.cjs   # Stella Sora: 36 Spine 4.2 + 252 Live2D, ilustrasi, render
node tools/check-updater-dashboard.cjs # 27 updater: health paralel, cache, mirror lag, UI
node tools/check-arkrecode.cjs    # Ark Re:Code: processed_v2 signature, 18 bukan Spine, render
node tools/check-variant-picker.cjs # picker bersama: 4 game, thumbnail, switch
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
