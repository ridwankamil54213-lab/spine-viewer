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
- **`sp.SkeletonData` di APK?** Awalnya dikira tidak ada, ternyata **ADA** — di
  paket bawaan APK sendiri (`assets/assets/resources` + `assets/assets/startup`),
  terpisah dari hot-update. APK shell versi 2.0.5.8 lebih baru dari aset server
  2.0.4.9, jadi isinya bukan duplikat: lihat bagian "Isi APK" di bawah.
- **Domain di tool basi.** `res.kaipaogames.com/18game/1.0.8.6` sudah 404 dan
  bucket `kaipaodomain.s3…` sudah dihapus (`NoSuchBucket`). Yang hidup:
  `res-kaipao.bmmqga.com` (+ `main.kaipaogames.com` untuk config).
- **Body XML di balik HTTP 200.** S3/CloudFront balikin `<Error>…` dengan
  status 200; `http_get()` menolaknya.

## Isi APK (bukan cuma shell) — `tools/juezhan/zhanjiang-apk.py`

Server hot-update cuma 2.0.4.9; APK bawa paket sendiri di 2.0.5.8. Hasil:
APK punya **67** skeleton vs **62** di server. Yang tidak ada di server:

- **role15** — karakter utuh (painting, battle, teach, teach1).
- Versi **lebih baru** `role5/8/10/14 teach` + `role8 teachBg`.
- `startup/skeleton` — skeleton layar boot.

Cara (tanpa jaringan, semua dari APK):

```bash
unzip -o /opt/juezhan/game.apk "assets/assets/resources/import/*" \
      "assets/assets/resources/native/*" "assets/assets/startup/*" -d apk-res
/srv/venv-spine/bin/python tools/juezhan/zhanjiang-apk.py \
      --apk /opt/juezhan/game.apk --out /opt/spine-viewer/assets/juezhan
```

Jebakan khusus jalur APK:

- Config APK **"packed"**: `paths` per-pack, index bisa ≥ `len(uuids)` — ulangi
  `uuids` (offset global Cocos) saat lookup.
- Sebuah uuid `sp.SkeletonData` bisa **tidak ada di `resources/config`**: ia
  milik paket `startup`. Pakai uuid sebagai nama folder kalau path tak dikenal.
- Atlas **multi-halaman**: ambil SEMUA dependency texture (`d[1]`) dan salin ke
  nama halaman atlas secara berurutan, bukan hanya yang pertama.
- File native ada di `assets/<paket>/native/<xx>/<uuid>.<hash>.<ext>` — coba
  beberapa base path (`<scan>/assets/…` dan `<scan>/assets/assets/…`).

## Hasil

67 skeleton **Spine 3.8.99**, 304 MB (62 dari server + 5 baru/lebih-baru dari
APK). Semuanya di bawah
`tafang/role/roleN/{painting,battle,front,back,story,teach}` untuk role1..role23
(painting = splash art, battle = animasi tempur, front/back = pop-in/out,
teach = tutorial, story = CG cerita). Atlas-nya `format: RGBA8888` — straight
alpha, tanpa baris `pma:`, jadi mode PMA viewer dibiarkan Auto.

Masuk viewer sebagai `assets/juezhan/<role>_<kategori>/`.
