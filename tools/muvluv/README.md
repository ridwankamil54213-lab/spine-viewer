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
