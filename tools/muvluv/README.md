# マブラヴ ガールズガーデンX (Muv-Luv Girls Garden X) — spine

Game browser DMM/FANZA (EXNOA × KMS), **Unity WebGL**. Model spine di-Addressables.

## Cara akses (butuh login DMM)

Halaman `play.games.dmm.co.jp/game/muvluv_ggx_538269` butuh login DMM (R18).
Cookie sesi disuntik dari file; tanpa itu halaman kosong.

## Arsitektur

```
api-game.muvluv-girls-garden.com/Content/Atom            (entry game)
  -> assets.muvluv-girls-garden.com/production-public/<ver>/WebGL/Desktop/Build/
       Desktop.loader.js / Desktop.data/.wasm/.framework.js  (Unity WebGL)
  -> .../WebGL/Desktop/StreamingAssetsMobile/aa/            (katalog utama)
  -> .../BundleAssets/X/WebGL/ASTC/                         (bundle aset, ASTC)
```

Katalog Addressables: `spine_catalog.bin` (juga `ui_/vfx_/sound_catalog.bin`).
`<ver>` = mis. `a13f7627-175c-4f2a-b6b6-77bef89011ad`.

## Bundle spine

`spine_catalog.bin` memetakan **1485** bundle (`rlp/<hash>.bundle`) ke aset
berkategori: `SBM/` (752), `SCS/` (240), `SBSX/` (148), `SBCV/` (142),
`SBES/` (87), `SBC/` (84), `SCBS/`, `SSD/`, `SAS/`…
(`SBM` = model TSF/mecha, `SCS` = karakter).

**URL bundle** (pola ditemukan dari log request live):
```
.../BundleAssets/X/WebGL/ASTC/<hash>.bundle
```
TANPA subfolder `rlp/`. Tiap bundle = UnityFS, satu model spine lengkap:
`TextAsset <name>.atlas` + `TextAsset <name>` (skeleton **JSON 4.2.33**) +
`Texture2D`. (Beberapa bundle = objek non-spine: UI/particle.)

## Pakai

```bash
# 1. ambil katalog (butuh URL katalog; lihat catatan)
# 2. jalankan pipeline: baca katalog -> unduh 1485 bundle -> ekstrak
/srv/venv-spine/bin/python /opt/mlv/fetch-extract.py all
```

Keluaran: `assets/muvluv/<name>/{<name>.skel, <name>.atlas, <name>.png}`.
Di viewer: root `muvluv`, label "マブラヴ ガールズガーデンX".

## Catatan

- Skeleton = **JSON**, bukan `.skel` biner (viewer menanganinya; format 4.2).
- Beberapa bundle tidak mengandung spine (particle/UI) — otomatis dilewati.
- Bundle di-cache di `/opt/mlv/bundles`; hapus untuk memaksa unduh ulang.

## CG / illust (galeri gambar, bukan spine)

Gambar CG **TIDAK** ada di `spine_catalog.bin` — semuanya di `ui_catalog.bin`,
satu bundle UnityFS per gambar berisi satu `Texture2D`. Keluarga yang dipakai:

| Prefix | Isi | Resolusi | Jumlah |
|---|---|---|---|
| `TMB/` | CG karakter | 1920x1080 | 168 |
| `TCBX/` | **CG H eksplisit** | 1920x1080 | 118 |
| `TFB/` | CG cerita | 1920x1080 | 28 |
| `TMCB/` | CG episode / foto (galeri ep.) | 1920x1080 | 76 |
| `TMGIB/` | ilustrasi mecha / TSF | 1920x1080 | 26 |
| `ICV/` | portrait illustrasi karakter | 360x640 | 754 |

Ekstrak:

```bash
/srv/venv-spine/bin/python tools/muvluv/extract-muvluv-cg.py
```

Keluaran: **1170 PNG** di `assets/muvluv-cg/` (nama = `<tag>_<id>.png`, mis.
`cg_h_c111302.png`). Hash bundle diambil dari dependency katalog
(`rlp/<hash>.bundle`), URL unduh sama seperti model spine. Di viewer: game
**`muvluv-cg`** ("マブラヴ ガールズガーデンX — CG", entri GAME_ROOTS sebelum
`muvluv`), dirender oleh jalur `format: "image"`.

Sisa prefix `ui_catalog` yang **bukan** CG (jangan dimasukkan): `ICS`/`TMET`/
`TAIT`/`TII` = ikon item/karakter (188–300px), `TAB`/`TMGIT`/`TQTB` = background
& banner, `TSST` = banner langganan, `TCNP` = kartu nama.

## Thumbnail untuk rig Spine

1243 model di `assets/muvluv/` tidak punya thumbnail. `refresh-thumbs.py`
memasangkannya dengan CG di atas dan menulis
`public/thumbs/muvluv/<id>.webp` + `_manifest.json` (1107 pasangan, 136 model
tanpa CG tetap fallback huruf). Prioritas: `illust_portrait_` → `cg_chara_` →
`cg_h_` → `cg_episode_` → `cg_mecha_` → `cg_story_`. Semua keluarga dipakai
(termasuk CG H eksplisit, sesuai keputusan user 2026-11-07).

Bentuk **utuh tanpa crop**: diperkecil agar muat 300×300 dengan aspect ratio
dijaga (`scale=300:300:force_original_aspect_ratio=decrease`), CSS kartu
`object-fit: contain` yang menangani sisi kosong. Konversi `libwebp` lewat
`/usr/bin/ffmpeg` — interpreter systemd tidak punya Pillow.

```bash
/usr/bin/python3 tools/muvluv/refresh-thumbs.py --limit 3   # uji
/usr/bin/python3 tools/muvluv/update.py --check
/usr/bin/python3 tools/muvluv/update.py --apply
```

`update.py` menyimpan state di `data/muvluv-update-state.json` dan terdaftar di
`UPDATERS["muvluv"]` (`rescan: true`). Peta audit model → CG ada di
`data/muvluv-thumb-sources.json`. Regresi: `tools/check-muvluv-thumbs.cjs`.
