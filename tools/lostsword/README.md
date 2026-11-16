# Lost Sword (`lostsword` + `lostsword-video`)

Sumber tunggal sekarang LIVE dari **`https://lost-sword-l2d-viewer.pages.dev/`**, menggantikan pipeline ekstraksi XAPK mentah (`tools/extract-lostsword.py` + `tools/extract-lostsword-video.py`) yang sebelumnya mencampur 868 model berduplikat kapitalisasi (`Anessa` vs `anessa`), ratusan monster/prop mentah, video High/Low dobel, dan nol thumbnail.

## Arsitektur & Sumber Data

1. **Resolusi bundle Vite dinamis**:
   `tools/lostsword/refresh.py` mengunduh HTML utama `https://lost-sword-l2d-viewer.pages.dev/`, menemukan `<script type="module" src="/assets/index-<hash>.js">`, lalu mengekstrak array katalog karakter `jl=[{...}]` (**147 entri** per 2026-11-16) menggunakan parser tokenizer murni Python tanpa dependensi eksternal.
2. **285 folder Spine / 297 skeleton** di `assets/lostsword/{standing,chibi,pet}/<folder>/`:
   - `standing/` — 164 model (ilustrasi L2D/Spine karakter, kostum `Bikini`/`Bunny`/`Daily`/`Lingerie`/`Special`/`Memorial`, serta folder `Lobby_*` multi-layer `#_F` dan `#_B`).
   - `chibi/` — 81 model Battle Mode.
   - `pet/` — 52 model Pet + kostum `Ps_*`.
3. **88 video cutscene MP4** di `assets/lostsword-video/`:
   - `skill-videos/Pc_*.mp4` dan `memorial-videos/Pc_*_Memorial.mp4`.
   - `lostsword-video` memakai `hiddenGame: true` di `GAME_ROOTS` sehingga tidak tampil sebagai tile game terpisah; seluruh 88 klip terhubung langsung ke dropdown **Varian** karakter masing-masing dengan badge `Video`.
4. **87 family karakter (`assets/lostsword/_names.json`)**:
   - Mengelompokkan 147 entri katalog (385 item = 297 model Spine + 88 video) ke dalam **87 kartu karakter root** tanpa tabrakan aset maupun label.
   - Urutan anggota di popup Varian: `Model` (`Utama`, `Lobby`, `Lobby (Back)`), `Aksi` (`Battle Mode`, `Skill Cutscene`, `Cutscene — Memorial`), dan `Varian` (kostum `Daily — Silent Shadow`, `Special — Bunny Girl`, `Bikini`, `Lingerie`, `Memorial — First Love`, serta `Pet — <petName>`).
   - Sub-judul kostum dan kategori disimpan di `character.squad` sehingga pencarian `"First Love"`, `"Silent Shadow"`, `"Bunny"`, `"Bikini"`, `"Lingerie"`, atau `"Memorial"` langsung menemukan kartu karakter.
5. **Thumbnail spesifik per varian (`public/thumbs/lostsword/` + `_manifest.json`)**:
   - 277 berkas WebP unik resmi yang memetakan **385/385** item (`char_*.webp` 256×340 untuk standing/video, `small_*.webp` untuk Battle Mode chibi, dan `pet_*.webp` untuk Pet).
6. **Jumlah di atas mengikuti katalog live**, bukan konstanta: `_names.json`
   menyimpan `entries`, `families`, `models`, `bundle`, dan `sig`.
   `tools/check-lostsword.cjs` membaca berkas itu untuk menurunkan ekspektasi,
   sehingga rilis situs tidak membuat regresi palsu merah.

## Penggantian penuh (`--replace`)

Kalau pohon aset masih bercampur dengan sisa ekstraksi XAPK lama, `refresh.py`
mendeteksinya dari keberadaan `assets/lostsword/lobbyunit/` atau
`assets/lostsword-video/High/`. Mode ini juga bisa dipaksa dengan `--replace`:

```bash
python3 tools/lostsword/refresh.py --replace
```

Alurnya aman (bukan `rm -rf`):
1. Bangun `staging-models/` + `staging-videos/` di `STATE_DIR` **hanya** dari
   folder yang disebut katalog live. Berkas yang namanya cocok di pohon lama
   di-**hardlink** (hemat disk), sisanya diunduh dari situs.
2. Validasi staging: kalau ada folder gagal, skrip berhenti **sebelum** menyentuh
   pohon produksi.
3. `shutil.move` seluruh `assets/lostsword/`, `assets/lostsword-video/`, dan
   `cache/lostsword/` ke `/srv/spine-assets/lostsword/apk-backup-<waktu>/`,
   lalu swap staging ke tempatnya.
4. Tulis ulang `_names.json` dan `_manifest.json` thumbnail.

Pada 2026-11-16 ini membuang 732 model sisa XAPK (`unit/` 411 + `lobbyunit/` 321)
dan 223 video `High/`/`Low/`; pustaka turun dari 1.120 ke **297 model + 88 video**
dan ukuran aset dari 2,3 GB ke **622 MB**. Arsip lama tetap tersimpan di luar repo.
Root GDrive (`lostsword`, `lostsword-video`, `thumbs/lostsword`) perlu di-`rclone
sync` sekali setelah replace, karena jalur auto-upload memakai `rclone copy` yang
tidak pernah menghapus berkas lama di remote.

## Pembaruan & Verifikasi

```bash
# Sinkronkan model, video, nama, family, dan thumbnail dari situs
python3 tools/lostsword/refresh.py

# Kontrak updater untuk tombol "Periksa pembaruan" di UI
python3 tools/lostsword/update.py --check
python3 tools/lostsword/update.py --apply

# Verifikasi end-to-end (API + disk + Playwright render Spine, varian & video)
node tools/check-lostsword.cjs
```

Backup pohon aset XAPK lama disimpan di luar repo pada `/srv/spine-assets/lostsword/apk-backup-*/` dan state versi disimpan di `/srv/spine-assets/lostsword/state.json`.
