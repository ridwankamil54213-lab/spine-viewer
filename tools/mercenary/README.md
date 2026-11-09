# Otherworld Mercenary Corps / 异世界佣兵团养成记

`com.Cryptect.Mercenary` — <https://play.google.com/store/apps/details?id=com.Cryptect.Mercenary>

Pipeline ekstraksi aset Spine untuk spine-viewer. Dua sumber:

| Sumber | Isi |
| --- | --- |
| XAPK Google Play (APKPure, `version=latest`) | 9 model Spine "lokal" + 85 ilustrasi slot + `assets/aa/catalog.json` |
| CDN Addressables `https://d2yyge1twff5nv.cloudfront.net/Product/Live/<versi>/Android/` | `catalog_Product.json` + 89 bundle `remote_prefab_spineillust_*.bundle` |

## Kenapa HTTP Range

XAPK 697 MB, tapi semua entri ZIP-nya `STORED` (tanpa kompresi).
`zip_central_directory()` membaca EOCD + central directory lewat 2 request
Range, lalu `fetch_entry()` mengambil hanya byte yang dibutuhkan. Total unduhan
~233 MB (3 bundle) + 1 katalog, bukan 697 MB.

`base_assets.apk` ada di dalam XAPK sebagai entri ZIP lain, jadi central
directory-nya di-parse dua kali: outer → `base_assets.apk` → inner.

## CDN Addressables

Path yang benar (bukan `Product/Android/...` atau `stc.utds...`):

```
https://d2yyge1twff5nv.cloudfront.net/Product/Live/3.0.1/Android/catalog_Product.json
https://d2yyge1twff5nv.cloudfront.net/Product/Live/3.0.1/Android/catalog_Product.hash
https://d2yyge1twff5nv.cloudfront.net/Product/Live/3.0.1/Android/remote_prefab_spineillust_assets_..._<hash>.bundle
```

`catalog_Product.json` (7,7 MB, `m_BuildResultHash` berbeda dengan katalog di
APK) berisi 21.027 `m_InternalIds`. Dari situ:

- 95 nama karakter kanonik: `Prefab/SpineIllust/<Nama>_Illust.prefab`
- 94 bundle `spineillust`; 89 di antaranya > 100 KB dan **self-contained**
  (`TextAsset` skeleton + `<nama>.atlas` + `Texture2D` 4096² + MonoBehaviour
  `SkeletonData`/`Atlas`). Lima sisanya cuma prefab `MonoBehaviour` — skeleton
  mereka memang sudah ikut di APK (Albedo, Ema, Karma, Kronos, Moa).

Ukuran dicek lewat `Range: bytes=0-0` → `Content-Range: bytes 0-0/<total>`,
jadi 94 probe cuma ~94 byte payload. Nama bundle memuat hash konten, sehingga
cache bersama di `/srv/spine-assets/mercenary/remote/bundles/` aman dipakai
lintas versi: versi baru → nama baru → unduh baru; versi sama → nol unduhan.

### Catatan atlas

Atlas menulis `size: 6959,6959` sementara `Texture2D` yang dikirim Unity
berukuran 4096×4096 (platform downscale). Ini juga terjadi pada 9 model
lokal. `src/viewer.js` sudah punya deteksi "region keluar dari berkas" dan
menskalakan ulang halaman, jadi tidak perlu menimpa `size:` di atlas.

Dua versi skeleton minor ditemukan: 4.0.64 (96 model), 4.0.62 (`albedo2`),
4.0.63 (`shoggoth`). `GAME_ROOTS` memakai `spineRuntime: "4.0"`.

## Keluaran

```
assets/mercenary/<slug>/<slug>.json | <slug>.atlas | <halaman>.png   × 98
assets/mercenary/_names.json                    95 karakter, 183 nama, 32 family
assets/mercenary-illust/<slug>.png                                    × 85
public/thumbs/mercenary/<slug>.webp + _manifest.json                 × 98
public/thumbs/_game/mercenary.png                                    ikon 128px
data/mercenary-update-state.json
```

Family dibentuk dari token terakhir nama karakter: `Bikini_Kronos` dan
`Adult_Kronos` bergabung ke `Kronos`. Rig alternatif lokal (`ema_alt`,
`kei_alt`) ikut family karakter masing-masing. Hasilnya 49 kartu root +
49 varian.

## Kontrak updater

`update.py` membungkus `refresh.py` sesuai kontrak `runUpdater()` di
`src/server.js`:

- `--check` → 1 HEAD XAPK + 1 GET 32 byte `catalog_Product.hash`.
  `changed` bila versi/ukuran XAPK berubah, jumlah model turun, **atau** hash
  katalog CDN berubah (developer bisa menambah karakter tanpa naik versi APK).
- `--apply` → unduh 3 bundle XAPK (cached lewat Range) + katalog CDN + 89
  bundle CDN (cached), ekstrak ke staging, validasi, swap atomik ke `assets/`,
  tulis state. Aman dijalankan ulang.

Semua progres ke **stderr**; **stdout** hanya blok JSON hasil (wajib
multi-baris — `runUpdater()` berhenti menyalin log saat menjumpai baris `{`).

Interpreter: `/srv/venv-spine/bin/python` (butuh `UnityPy` + `Pillow`).

## Regresi

```bash
node tools/check-mercenary.cjs
```

31 assertion: API (`98` Spine, `85` image), kelengkapan 98 folder
(json/atlas/PNG), `_names.json`, 98 thumbnail, updater idempoten + state,
dan Playwright headless (render `ada` / `moa` / `basilla` dari CDN, popup
Varian Ema, image stage, 0 aset 404, 0 JS error).
