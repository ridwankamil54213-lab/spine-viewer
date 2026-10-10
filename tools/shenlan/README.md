# 深蓝终末录 (Deep Blue) — `youdianse.com/game/detail/761`

R18 舰娘卡牌 (Unity **2021.3**). Rilis v1.1 (2026-09); APK ~941 MB, terpasang ~2,9 GB.

## Sumber

Halaman `https://www.youdianse.com/game/detail/761` menyimpan URL APK di data
Nuxt (bukan <a href>), dan **CDN-nya pakai CloudFront signed URL** — tanpa tanda
tangan, CDN balas `403 MissingKey ... Key-Pair-Id`. Jadi harus ambil URL lengkap
(yang sudah memuat `?Expires=..&Signature=..&Key-Pair-Id=..`) dari HTML halaman;
URL mentah tanpa query tidak jalan.

```bash
# URL lengkap ada di HTML halaman (data JSON), sering di sekitar
#   "https://d7j2ofanssf00.cloudfront.net//20260930/<file>.apk?Expires=..&Signature=..&Key-Pair-Id=.."
curl -L -o shenlan.apk "<URL lengkap bertanda-tangan>"
```

Catatan: `content-length` = ukuran unduhan (~941 MB); 2,89 GB adalah ukuran
setelah terpasang (APK + aset runtime), bukan ukuran file.

## Format

```
assets/prefab/hero/herospines/hero_<id>/hero_<id>.unity3d      # model spine
assets/prefab/hero/herospines/hero_<id>/herocg_<id>_<n>.unity3d # CG (spine juga)
```

Tiap `.unity3d` = **UnityFS biasa, tanpa enkripsi**, satu model utuh:
`TextAsset <Name>.skel` + `TextAsset <Name>.atlas` + `Texture2D` (2048x2048).
Semua atlas `pma: true`.

Sisa APK (tekstur herobust, background, suara, VFX, FGUI) tidak ber-spine.

## Pakai

```bash
unzip -q shenlan.apk 'assets/prefab/hero/herospines/*' -d sl_h
/srv/venv-spine/bin/python tools/shenlan/extract-shenlan.py /opt/games/sl_h assets/shenlan
```

Keluaran: **77 model** — `hero_<id>` (model tempur) + `heroCG_<id>_<n>` (CG).
Di viewer: `assets/shenlan/<Nama>/`, `pmaDefault: true`.

## ⚠️ Terblokir: Spine **4.3.39-beta**

Semua 77 `.skel` memakai versi **4.3.39-beta** dari editor Spine *unreleased*.
Rilis runtime publik terakhir adalah **4.3.13** (npm `@esotericsoftware/spine-core`
& `spine-pixi-v7`), dan binary-nya **tidak** kompatibel:

- spine-core 4.3.13 → gagal baca header, `Bone name must not be null`.
- spine-core 4.2.120 (versi terdekat) → parse 256 nama benar (sampai region
  `Battleship_*`, `pom_L/R`, `arm_R3`) lalu melenceng di section **IK constraints**
  (`IK constraint data name must not be null`), yaitu di antara Bones dan Skins.
- Header 4.3.39-beta ter-parse sempurna dengan `BinaryInput` 4.3.13
  (`version=4.3.39-beta`, `refScale=100`, `imagesPath=./images/`), jadi
  divergensinya ada di **layout section constraints/attachments**, bukan header.

Ekstraksinya sendiri 100% benar — 77 model lengkap (`.skel` + `.atlas` + PNG).
Model tinggal dipakai begitu runtime 4.3.39 keluar, atau dengan viewer/editor
Spine resmi yang mendukung versi tersebut. Jangan buang waktu mencoba runtime
4.x lain: semuanya lebih tua dari 4.3.39.

Upaya yang sudah dicoba: npm `@esotericsoftware/spine-core` 4.3.2–4.3.13,
alias `spine-pixi-v7-42` (4.2.120), branch GitHub `4.3`/`4.4`/`5.0`, tag
`spine-ts-4.3.x` — tidak ada yang >= 4.3.39.

## Jebakan

- Tekstur 2048x2048 → stream ke disk (`_texcache/`), jangan tahan di RAM (OOM).
- URL APK harus yang **bertanda-tangan**; regex `\.apk` memotong query string —
  ambil sampai `Key-Pair-Id` ikut.
