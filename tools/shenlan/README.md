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
assets/prefab/hero/herospines/hero_<id>/hero_<id>.unity3d       # model spine
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

## Spine 4.3.39-beta — perlu patch spine-core

Semua 77 `.skel` memakai versi **4.3.39-beta**. Rilis runtime JS publik terakhir
adalah **4.3.13** (npm `@esotericsoftware/spine-core` / `spine-pixi-v7`), dan
binary-nya **tidak kompatibel** (gagal baca dari `Bone name must not be null`).

Format 4.3.39-beta diambil dari **`skeletonViewer-4.3.39-beta.jar`** (libgdx,
runtime resmi yang mendukung versi ini) — di-*decompile* untuk membaca
`com/esotericsoftware/spine/SkeletonBinary.java`:

```bash
curl -Lo sv439.jar https://esotericsoftware.com/files/sv/skeletonViewer-4.3.39-beta.jar
curl -Lo cfr.jar https://repo1.maven.org/maven2/org/benf/cfr/0.152/cfr-0.152.jar
java -jar cfr.jar sv439.jar --outputdir sv_src   # -> com/esotericsoftware/spine/*.java
```

Perbedaan 4.3.39-beta vs 4.3.13 yang ditemukan & dipatch ke spine-core
(`patches/@esotericsoftware+spine-core+4.3.13.patch`):

1. **Bones** (nonessential): 4.3.39 tidak punya `iconSize`/`iconRotation`.
2. **Weighted vertices**: tanpa leading total-entry count.
3. **Mesh**: tanpa `slotCount`/`timelineSlots`.
4. **LinkedMesh**: satu index saja (tanpa `skinIndex`).
5. **Draw order folder timelines**: tidak ada.
6. **Animasi**: sebagian layout timeline 4.3.39 belum terpetakan; parser dibuat
   **toleran** — bones/slots/skins tetap terpakai (model dirender), animasi yang
   desync dilewati sampai patch dilengkapi.
7. BoundingBox/Point/Path/Clipping: `nonessential` = int biasa (bukan bool).

Tambah patch API runtime 4.3: `slot.getAttachment()` → `slot.pose.getAttachment()`
(helper `slotAttachment()` di `src/viewer.js`).

Terapkan setelah `npm install` (otomatis via `"postinstall"`):
```bash
npx patch-package
```

**Hasil**: **76/77 model ter-render** (bones+slots+skins), mis. `hero_11000101`
(40 slot, 72 tulang, Spine 4.3.39, runtime 4.3). Satu model (`hero_31200101`)
masih gagal parse skins (belum terpetakan).

## Jebakan

- Tekstur 2048x2048 → stream ke disk (`_texcache/`), jangan tahan di RAM (OOM).
- URL APK harus yang **bertanda-tangan**; regex `\.apk` memotong query string —
  ambil sampai `Key-Pair-Id` ikut.
- `slot.attachment` pindah ke `slot.pose.attachment` di runtime 4.2/4.3.
