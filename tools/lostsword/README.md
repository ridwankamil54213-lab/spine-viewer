# Lost Sword (`lostsword` + `lostsword-video`)

Sumber tunggal sekarang LIVE dari **`https://lost-sword-l2d-viewer.pages.dev/`**, menggantikan pipeline ekstraksi XAPK mentah (`tools/extract-lostsword.py` + `tools/extract-lostsword-video.py`) yang sebelumnya mencampur 868 model berduplikat kapitalisasi (`Anessa` vs `anessa`), ratusan monster/prop mentah, video High/Low dobel, dan nol thumbnail.

## Arsitektur & Sumber Data

1. **Resolusi bundle Vite dinamis**:
   `tools/lostsword/refresh.py` mengunduh HTML utama `https://lost-sword-l2d-viewer.pages.dev/`, menemukan `<script type="module" src="/assets/index-<hash>.js">`, lalu mengekstrak array katalog karakter `jl=[{...}]` (143 entri: 130 `Playable` + 13 `NPC`) menggunakan parser tokenizer murni Python tanpa dependensi eksternal.
2. **276 folder Spine / 287 skeleton** di `assets/lostsword/{standing,chibi,pet}/<folder>/`:
   - `standing/` — 147 folder (158 skeleton: ilustrasi L2D/Spine karakter, kostum `Bikini`/`Bunny`/`Daily`/`Lingerie`/`Special`/`Memorial`, serta 11 folder `Lobby_*` multi-layer `#_F` dan `#_B`).
   - `chibi/` — 78 folder (78 skeleton Battle Mode).
   - `pet/` — 51 folder (51 skeleton Pet + kostum `Ps_*`).
3. **87 video cutscene MP4** di `assets/lostsword-video/`:
   - `skill-videos/Pc_*.mp4` (82 klip skill cutscene).
   - `memorial-videos/Pc_*_Memorial.mp4` (5 klip memorial).
   - `lostsword-video` memakai `hiddenGame: true` di `GAME_ROOTS` sehingga tidak tampil sebagai tile game terpisah; seluruh 87 klip terhubung langsung ke dropdown **Varian** karakter masing-masing dengan badge `Video`.
4. **84 family karakter (`assets/lostsword/_names.json`)**:
   - Mengelompokkan 143 entri katalog (374 item = 287 model Spine + 87 video) ke dalam **84 kartu karakter root** tanpa tabrakan aset maupun label.
   - Urutan anggota di popup Varian: `Model` (`Utama`, `Lobby`, `Lobby (Back)`), `Aksi` (`Battle Mode`, `Skill Cutscene`, `Cutscene — Memorial`), dan `Varian` (kostum `Daily — Silent Shadow`, `Special — Bunny Girl`, `Bikini`, `Lingerie`, `Memorial — First Love`, serta `Pet — <petName>`).
   - Sub-judul kostum dan kategori disimpan di `character.squad` sehingga pencarian `"First Love"`, `"Silent Shadow"`, `"Bunny"`, `"Bikini"`, `"Lingerie"`, atau `"Memorial"` langsung menemukan kartu karakter.
5. **Thumbnail spesifik per varian (`public/thumbs/lostsword/` + `_manifest.json`)**:
   - 270 berkas WebP resmi yang memetakan **374/374** item (`char_*.webp` 256×340 untuk standing/video, `small_*.webp` untuk Battle Mode chibi, dan `pet_*.webp` untuk Pet).

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
