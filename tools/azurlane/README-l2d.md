# Azur Lane (碧蓝航线) — Live2D

263 model Live2D Cubism 4 milik Azur Lane. (Untuk spine skin, lihat `README.md`
di folder ini.)

## Sumber (resmi)

Pakai **[azlassets](https://github.com/nobbyfix/AzurLane-AssetDownloader)**
(`pip install azlassets`) yang menarik AssetBundle **langsung dari CDN game**
(semua server: EN/JP/KR/TW/CN). Versi diambil via gate TCP game.

```bash
# config: batasi unduhan ke Live2D saja (hemat bandwidth)
#   config/userconfig.toml:
#     [filepaths]
#     asset-directory = "/opt/games/azurlane/ClientAssets"
#     [download.filters]
#     whitelist = ["live2d/"]
#     [extract.filters]
#     use-download-filters = true
azl download JP          # JP = paling banyak L2D (v1293, 266 bundle, ~2.9 GB)
```

Jebakan: gate **CN** (`line1-login-bili-blhx.bilibiligame.net`) TCP-timeout dari
host ini (blok China). EN/JP/KR/TW semua OK.

Hasil: `<asset-dir>/<CLIENT>/AssetBundles/live2d/<nama>` — 1 bundle per model
(266 file; 263 berisi Live2D, 3 (`junhe_5`, `lafei`, `tiancheng_cv_2`) bukan).

## Struktur bundle

Tiap bundle = **Cubism SDK for Unity**, bukan file Cubism lepas:

- `MonoBehaviour` (`CubismMoc`) → menyimpan **`.moc3` mentah** (magic `MOC3`).
- `Texture2D` → halaman tekstur (1–7 per model, 2048²).
- `TextAsset` `<nama>.physics3` → physics3 JSON.
- `AnimationClip` (`idle`, `home`, `login`, `touch_*`, …) → data motion.

## Ekstrak

```bash
/srv/venv-spine/bin/python tools/azurlane/extract-azurlane-l2d.py \
  /opt/games/azurlane/ClientAssets/JP/AssetBundles/live2d \
  /opt/spine-viewer/assets/azurlane-l2d
```

Mengeluarkan per model: `<nama>.moc3` (potong dari offset `MOC3` di raw
MonoBehaviour), `<nama>.physics3.json`, `texture_NN.png`, dan
`<nama>.model3.json` (sintetis).

Hasil: **263 model**, ~3.8 GB. Viewer mendeteksi ini sebagai `format: "live2d"`
/ `runtime: "cubism4"` (folder berisi `.moc3`) dan merendernya lewat
`pixi-live2d-display`.

Di viewer: `assets/azurlane-l2d/<nama>/`, root `azurlane-l2d`
(label "Azur Lane — Live2D").

## Nama kapal

`data/azurlane-l2d-names.json` memetakan folder → nama kapal Tionghoa, dari
`SHIP_NAME_MAP` (pinyin→Tionghoa) di
[MrKLLM/azurlane-assetbundle-toolkit](https://github.com/MrKLLM/azurlane-assetbundle-toolkit)
`scripts/ship_name_map.py` (256/263 cocok). Suffix `_hx` = versi HQ/detail.

Contoh: `abeikelongbi_3` → 「阿贝克隆比 — varian 3」.

## Update

Jalankan ulang `azl download JP` lalu extractor di atas. `.model3.json` viewer
disintesis ulang tiap scan, jadi tak perlu disunting.

## Catatan / TODO

- **Motion** (`idle`, `touch_*`, …) belum dikonversi: klip animasi ada di bundle
  sebagai `AnimationClip` Unity dan perlu dipetakan ke `motion3.json` (lihat
  `extract_motions.py` di repo MrKLLM — mapping berbasis crc32 genericBindings).
  Saat ini model tampil statis (tetap bisa di-zoom/geser), dropdown animasi kosong.
- 3 bundle tanpa `MOC3` (bukan Live2D) dilewati.
