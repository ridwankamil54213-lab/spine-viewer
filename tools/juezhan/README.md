# 决战僵尸舞娘 (Zombie Dancer) — Cocos extraction

Game ini **Cocos Creator 3.x (JS)**, bukan Unity — jadi seluruh pipeline
蜜桃乌托邦 (Addressables/IDOLAB2) tidak berlaku. Kabar baiknya: **tidak ada
enkripsi** di jalur asetnya.

```bash
/srv/venv-spine/bin/python tools/juezhan/zhanjiang-download.py \
    --apk /opt/juezhan/game.apk --out /opt/juezhan/spine --textures
```

## Rantai (semua dari IL tool + `startup-config.json` di APK)

1. APK punya `assets/src/startup-config.json` → channel `18game`:
   `domainConfigUrls`, `mainDomains`, `resDomains` (`res-kaipao.bmmqga.com`,
   cadangan `res-kaipao.xjhwlgy.com`).
2. `GET {mainDomain}/config/26/18game.json?h5t={ms}` →
   `gameConfig.hotUpdateUrl = /18game/android/2.0.4.9/`, `resPath`.
   (`26` = `backstageCode`.)
3. `GET {resPath}{hotUpdateUrl}project.manifest` — manifest Cocos, 2720 aset.
4. `GET …/assets/resources/config.<hash>.json` → `paths`/`uuids`/`types`.
5. Untuk tiap `sp.SkeletonData`:
   - `import/<xx>/<uuid>.<hash>.json` — **self-contained**: `_name`,
     `_atlasText` (atlas lengkap), `textureNames`, `_skeletonJson`.
   - `native/<xx>/<uuid>.<hash>.png` — halaman atlas (polos).

## Jebakan yang sudah dipecahkan

- **Nama file pakai uuid ter-kompresi 22 char.** Perlu `decodeUuid()` Cocos
  (2 char pertama apa adanya, lalu tiap pasang char → 3 hex) untuk dapat uuid
  36-char yang dipakai nama file. UUID yang sama muncul di `d[1]` (dependency)
  DAN di `paths`/`uuids` — itu cara menemukan PNG halaman atlasnya.
- **`sp.SkeletonData` hanya ada di hot-update, TIDAK di APK.** APK cuma shell;
  versi APK (2.0.5.8) beda dari versi aset (2.0.4.9). Jangan buang waktu
  mencari spine di dalam APK.
- **Domain di tool basi.** `res.kaipaogames.com/18game/1.0.8.6` sudah 404 dan
  bucket `kaipaodomain.s3…` sudah dihapus (`NoSuchBucket`). Yang hidup:
  `res-kaipao.bmmqga.com` (+ `main.kaipaogames.com` untuk config).
- **Body XML di balik HTTP 200.** S3/CloudFront balikin `<Error>…` dengan
  status 200; `http_get()` menolaknya.

## Hasil

62 skeleton **Spine 3.8.99**, 297 MB. Semuanya di bawah
`tafang/role/roleN/{painting,battle,front,back,story,teach}` untuk role1..role23
(painting = splash art, battle = animasi tempur, front/back = pop-in/out,
teach = tutorial, story = CG cerita). Atlas-nya `format: RGBA8888` — straight
alpha, tanpa baris `pma:`, jadi mode PMA viewer dibiarkan Auto.

Masuk viewer sebagai `assets/juezhan/<role>_<kategori>/`.
