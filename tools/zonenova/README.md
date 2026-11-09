# Zone Nova (禁域战姬, EROLABS) — Spine 4.1

Integrasi **murni dari CDN resmi**, tanpa APK / `adb pull` / login game.
Kredit algoritma ke komunitas [Live2DHub](https://live2dhub.com/t/topic/4502)
(topik 4502 & 4603) dan repo
[`boring877/zone-nova-extractor`](https://github.com/boring877/zone-nova-extractor)
untuk KDF AES dan format MasterMemory.

## Rantai sumber

```
1. CONFIG   zonenova.future-step.net:12000/ServerConfig/GetConfig
            ?appVersion=1.06&customAppIdentifier=EROLAB_ANDROID_RELEASE
   -> AssetBundlePath = https://d23odp11837l0m.cloudfront.net/amgameasset/Stg/AssetBundles/
   -> MasterDataDownloadPath = .../amgameasset/Prod/master-data.bytes
   -> MasterDataVersion

   PENTING: cuma appVersion=1.06 yang mengembalikan AssetBundlePath.
   Versi lain (1.00–1.05, 1.07+) mengembalikan string kosong. Domain lama
   asset.lecisxqw.com yang dipakai skrip komunitas sudah NXDOMAIN.

2. KATALOG  <AssetBundlePath>Android/9A188D7BF0BF119DE38B57A44DF3A917.ab
   Nama berkas = MD5("Android" + "version.json").upper() + ".ab"
   Dekrip      = XOR rolling: plain[i] = cipher[i] ^ (i % 63)
   Hasil       = {"version": 472,
                  "assetBundleMetadatas": {"<path>": {hash, fileSizeInMB, ...}}}
   -> 947 entri, 188 di antaranya prefab/characterspine/...

3. BUNDLE   <AssetBundlePath>Android/<MD5("Android"+path).upper()>.ab
   Prefix    "UtS\0 5.0." (fake header), lalu magic "UnityFS" di offset ~1–2 KB.
   Cara baca  cari "UnityFS" dalam 16 KB pertama, buang prefix, load UnityPy
              dengan FALLBACK_UNITY_VERSION = "2022.3.62f2" (versi Unity
              sengaja disembunyikan game, tanpa ini UnityPy menolak berkas).
   Isi        TextAsset "<n>.skel" (binary Spine 4.1.24) + "<n>.atlas"
              + Texture2D "<n>" (umumnya 2048×2048 RGBA).

4. NAMA     master-data.bytes: AES-256-CBC + PKCS7, KEY/IV konstan (lihat
            update.py). Dekrip lewat binary `openssl`, jadi tidak butuh
            pycryptodome saat runtime. Plaintext = MasterMemory
            (MessagePack + LZ4 ext type 99). Tabel `translation_ds` memuat
            ["CHARACTER_NAME_<id>", zh-CN, EN, ja, zh-TW] untuk 70 karakter.

5. GAMBAR   boring877/gacha-wiki-zone-nova/public/images/characters/*.jpg
            -> WebP 320×420 untuk thumbnail. BUKAN halaman atlas.
```

## Hasil

- **188 model**: 118 `prefab/characterspine/cg/<n>/<id>` + 70
  `prefab/characterspine/portrait/<id>`; `ui/icon/emojispine` sengaja dilewat.
- Folder `assets/zonenova/<cgN_id>` / `portrait_<id>`, semuanya ASCII.
- Nama Inggris + varian (`Naya — CG 1`, `Naya — Portrait`) di
  `data/zonenova-names.json`; `data/zonenova-family.json` mengelompokkan
  CG/portrait per karakter jadi picker varian.
- `public/thumbs/zonenova/_manifest.json` memetakan id model ke WebP ilustrasi.
  Cakupan ~30/70 karakter (wiki hanya punya 33 potret non-card); model tanpa
  potret sengaja dibiarkan tanpa thumbnail daripada menampilkan potongan atlas.
- `GAME_ROOTS.zonenova`: `spineRuntime: "4.1"`, `pmaDefault: false`
  (viewer komunitas memakai `premultipliedAlpha: false`; atlas tidak punya
  baris `pma:` dan teksturnya straight-alpha).

## Pemakaian

```sh
/srv/venv-spine/bin/python tools/zonenova/update.py --check    # ~1 dtk
/srv/venv-spine/bin/python tools/zonenova/update.py --apply     # ~400 MB, 188 .ab
/srv/venv-spine/bin/python tools/zonenova/refresh.py            # --apply --offline
node tools/check-zonenova.cjs                                   # regresi (:3000)
```

Cache di `/srv/spine-assets/zonenova/`: `config.json`, `version.ab`,
`version.json`, `master-data.bytes`, `wiki-images.json`, `bundles/*.ab`,
`state.json`. `--check` cuma mengambil config + katalog AB (≈160 KB) dan
menghitung versi dari sha1 keduanya; `changed` bertahan sampai `--apply`.
`--offline` benar-benar tidak menyentuh jaringan (termasuk daftar gambar
wiki) — berguna saat CDN down.

Dependensi: lihat `tools/zonenova/requirements.txt`. `openssl`, `UnityPy`,
`lz4.block`, `msgpack`, Pillow dipakai langsung.

`UPDATERS.zonenova` memakai `rescan: true`. `assets/zonenova/` dan
`public/thumbs/zonenova/` tidak masuk git.
