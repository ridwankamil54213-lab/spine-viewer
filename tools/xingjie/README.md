# 性界大战 (Xingjie Dazhan) — Cocos 2.x H5 extraction

Game ini **Cocos Creator 2.x** dengan build **H5 web**, bukan Unity dan bukan
Cocos 3.x. Karena versi H5 resminya ada, **tidak perlu APK** — seluruh aset
dilayani langsung lewat HTTP dan sisa kerja cuma HTTP + base64.

```bash
# 1. ambil settings + konf serta map aset (butuh node)
./tools/xingjie/fetch-settings.sh            # -> /opt/xingjie/{settings.js,map.json,...}
# 2. ekstrak semua skeleton
/srv/venv-spine/bin/python tools/xingjie/extract-xjdz.py \
    --out /opt/spine-viewer/assets/xingjie
```

## Rantai

1. `GET https://h5.spj2web.com/` → `index.html` menyebut
   `src/settings.<hash>.js` (semua hash build bisa dibaca dari sini; jangan
   di-hardcode) + `main.<hash>.js`.
2. `settings.js` = `window._CCSettings`:
   - `assetTypes` — array tipe, `sp.SkeletonData` menandai berkas spine.
   - `rawAssets.assets` — `id -> [path, tipeIdx]` (path gaya `roleSpine/H30090/body.json`).
   - `uuids` — `id -> uuid 22-char` (ter-kompres).
   - `md5AssetsMap` — `{import:[uuid,hash,uuid,hash,…], "raw-assets":[…]}`.
   - Dari `main.js`: `libraryPath:'res/import'`, `rawAssetsBase:'res/raw-'`.
3. URL aset = `<base>/res/import/<xx>/<uuid36>.<hash>.json` untuk metadata, dan
   `<base>/res/raw-assets/<xx>/<uuid36>.<hash>.png` untuk tekstur.
4. `sp.SkeletonData` JSON **self-contained**: `_skeletonJson`, `_atlasText`,
   `textures[].__uuid__` (22-char → harus `decodeUuid()`), `textureNames`.

## Enkripsi tekstur (JSON polos, PNG dibungkus)

`GET /src/assets/plugin_conf.js` memberi:

```js
window.assets_cfg = { encriptType:"0",
  encriptKey:"u40DCSu5hsL3AVfl3QS1",
  encriptSign:"zOm6SMaxvsiBo4WcR0m5xYVEgZ5Lloq4NgB47cnW" };
```

File `raw-assets` (PNG) datang sebagai:

```
"assets-encrypt-2022" + encriptSign  +  base64(PNG)  +  "="  +  encriptKey + ekor
```

Dekode: buang 59 byte header, ambil base64 sampai karakter `=` pertama,
tambahkan padding seperlunya, `base64.b64decode()` → PNG utuh. (Bukan
XOR/XXTEA: `loaderplugin.js` yang di-obfuscate isinya hanya registrasi download
handler + `checkIsEncripted`; untuk web build ini berkas raw-nya murni base64.)

## Jebakan

- **Hash build berubah tiap rilis** (`settings.c1e23.js`,
  `project.4a5e6.js`). Selalu baca dari `index.html`, jangan hardcode.
- **`textures[].__uuid__` = uuid 22-char** — wajib `decodeUuid()` dulu, kalau
  tidak URL-nya 404 (ini penyebab "tex HTTPError" pertama).
- **URL 200 palsu**: nginx H5 ini mengembalikan `index.html` (200) untuk path
  apa pun yang tidak ada. Cek magic byte (`\x89PNG`) / parse JSON, jangan andalkan
  status code saja.
- **CDN di balik `spj2-domains.s3.ap-east-1.amazonaws.com/domains.json`**
  (berisi `["spj2cloud.com"]`) — dipakai game untuk domain cadangan; h5.spj2web.com
  sendiri sudah cukup.
- Nama folder hasil = path dengan `/`→`_` (`roleSpine/H30090/body.json` →
  `roleSpine_H30090_body`).

## Hasil

**876 skeleton, 0 gagal, ~595 MB (di disk 817 MB)** — 25 detik dengan 16 worker.
`roleSpine/*` 164, `r18/{interaction,plotSpineNew}/*` 58, `commonSpine/*` 27,
`mainCitySpine` 15, `relic` 13, plus 579 `skillEffect/*` + efek lain.

Spine **3.8.99** (849), sisanya 3.5.49 / 3.8.75 / 3.6.53 / 3.8.82 (efek lama).
Atlas `format: RGBA8888`, tanpa baris `pma:` → mode PMA viewer biarkan **Auto**.
