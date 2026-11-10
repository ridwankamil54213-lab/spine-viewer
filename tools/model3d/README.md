# Model 3D (glTF / GLB) — Stella Sora

Dukungan **format `model3d`** yang benar-benar terpisah dari jalur 2D.
Sumber aset: [`StellaSoraWiki/StellaSoraModels`](https://github.com/StellaSoraWiki/StellaSoraModels)
(public, ~349 MB, 2.003 `.glb`).

## Kenapa terpisah

Viewer ini berbasis **PIXI 7** = renderer 2D orthographic sprite batch. Tidak
ada perspective camera, depth buffer, lighting, atau skinning. Menambah 3D
"di dalam PIXI" bukan pilihan; dibutuhkan konteks WebGL kedua.

| | |
| --- | --- |
| Runtime | `three@0.187` + `GLTFLoader` + `OrbitControls` |
| Bundle | **`public/dist/model3d.js` (645 KB)**, IIFE terpisah, di-*lazy load* lewat `<script>` saat model 3D pertama dibuka |
| `viewer.js` | tetap **4,1 MB** — 43 ribu model Spine/Live2D tidak menanggung three.js |
| Stage | `src/model3d-stage.js`: kanvas `.model3d-canvas` ditumpuk di `#canvas-wrap`, pola sama dengan `image-stage.js` / `video-stage.js` |
| Deteksi | `scanModels()` melihat `model.glb` di sebuah folder → `format: "model3d"` |

Karena kanvas PIXI hanya **disembunyikan** (bukan dicabut), ticker/state viewer
tetap utuh. `dispose3D()` melepas renderer, controls, mixer, geometri dan
tekstur saat pengguna kembali ke model 2D.

## Struktur aset

```
assets/stellasora-3d/<id>/
    model.glb            mesh + skin + tekstur, TANPA AnimationClip
    anims/<clip>.glb     AnimationClip terpisah (maks 3 per model)
    _meta.json           karakter, variant, charId, daftar clip
```

Retarget animasi: `AnimationMixer` memakai `gltf.scene` sebagai root; track di
GLB animasi resolve berdasarkan **nama node** (data Unityyang sama), jadi clip
dari berkas terpisah bisa langsung diputar. Model dipusatkan lewat `Group`
pembungkus — bukan menggeser `gltf.scene` — supaya binding track tidak rusak.

## Yang dihasilkan `tools/model3d/update.py`

| Berkas | Isi |
| --- | --- |
| `assets/stellasora-3d/` | 59 model + 177 clip (295 MB), di luar git |
| `data/stellasora-3d-names.json` | 59 nama karakter + label kostum |
| `data/stellasora-3d-family.json` | 19 family varian (40 model ber-family) |
| `public/thumbs/stellasora-3d/_manifest.json` | 58 kunci → 37 WebP |
| `public/thumbs/_game/stellasora-3d.png` | ikon game |

**Thumbnail = gambar ilustrasi 2D**, bukan potongan atlas dan bukan tangkapan
3D. Diambil dari `public/thumbs/stellasora/` (potret AVG yang dipakai root
Live2D), dipetakan lewat `data/stellasora-l2d-names.json` memakai nama
karakter. 55/59 karakter langsung cocok; 4 nama kostum ber-prefix
(`Firstlight_Noya`, `Snowish_Laru`, `Springseek_Coronis`, `Suntide_Willow`)
dinormalisasi ke karakter dasarnya. Satu model tanpa ilustrasi sengaja
dibiarkan tanpa thumbnail.

## Format generik

`format: "model3d"` tidak hardcode Stella Sora. `scanModels()` mendeteksi
`model.glb` di root game mana pun, membaca `_meta.json` (opsional) dan
`anims/*.glb`, lalu mengirim `modelFile` + `animationFiles`. Loader nama/family
umum di `src/server.js` sudah mendaftarkan `stellasora-3d`. Menambah game 3D
lain cukup: taruh `.glb`, daftarkan `GAME_ROOTS`, sediakan `*-names.json`.

Cabang khusus di `src/viewer.js`: `is3D()`, `load3DModel()`, `dispose3D()`
di teardown, dropdown animasi, HUD (`3D · glTF`, jumlah mesh/triangle), dan
export PNG lewat `Model3DStage.capture()`. Ekspor video frame-by-frame dan
A/B compare **sengaja tidak didukung** untuk 3D (ada pesan jelas, tidak crash).

## Cara pakai

```bash
# cek rilis / hitung yang belum ada (GitHub tree API, tanpa token)
/srv/venv-spine/bin/python tools/model3d/update.py --check
# unduh + bangun metadata (idempoten, 10 worker, ~33 dtk untuk 295 MB)
/srv/venv-spine/bin/python tools/model3d/update.py --apply
# regenerasi metadata dari aset lokal, TANPA jaringan (~0,3 dtk)
/srv/venv-spine/bin/python tools/model3d/refresh.py

npm run build            # menghasilkan viewer.js + model3d.js
systemctl restart spine-viewer
curl 'http://127.0.0.1:3000/api/models?refresh=1' >/dev/null
node tools/check-model3d.cjs
```

`--check` memakai SHA-1 dari daftar `path:size` GLB utama sebagai `version`;
`version` hanya disimpan saat `--apply`, jadi titik merah tetap muncul sampai
di-apply. Cache tree ada di `/srv/spine-assets/stellasora-3d/tree.json`.

`assets/stellasora-3d/` dan `public/thumbs/stellasora-3d/` **di luar git**
(besar & bisa diregenerasi). Yang masuk git: skrip, `data/*-3d-*.json`, ikon
game, dan `package.json` (dependency `three`).
