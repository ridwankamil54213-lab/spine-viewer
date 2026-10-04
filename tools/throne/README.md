# Divine Throne: Idle RPG — Cocos Creator 2.x extraction

Paket: `com.luckystargame.jdxy.gp` (LUCKYSTAR / MAGIC NETWORK). Engine = **Cocos
Creator 2.x** (JS, `libcocos2djs.so`) lagi, tapi aset spine-nya disimpan berbeda
dari contoh Cocos 2.x lain.

Ringkas: **tidak ada dekripsi**, tapi setiap bagian ada di tempat berbeda:

| Bagian | Tempat | Bentuk |
|---|---|---|
| Skeleton | `native/<xx>/<uuid>.bin` | **Spine BINER 3.8.99** (bukan JSON) |
| Atlas | inline di `import/<xx>/*.json` | teks atlas lengkap |
| Tekstur | `native/<xx>/<uuid>.astc` | ASTC header kustom |

## Sumber

Semua ada di dalam APK **Play Asset Delivery**:
`/data/app/.../split_install_time_asset_pack.apk` (1.74 GB) — bukan di
`data.pack` atau folder eksternal (game belum pernah jalan di perangkat).

```bash
adb -s 127.0.0.1:15555 pull <path>/split_install_time_asset_pack.apk /opt/throne/apk/
unzip -q /opt/throne/apk/split_install_time_asset_pack.apk -d /opt/throne/pack
/srv/venv-spine/bin/python tools/throne/extract-throne.py \
    --pack /opt/throne/pack --out /opt/spine-viewer/assets/throne
```

Struktur di dalam pack: `assets/assets/<paket>/{config.<hash>.json, import/, native/}`
untuk 11 paket (`activity, assist, battle, chapter, city, common, corps, hero,
playerInfo, resources, wild`). Hanya **common** (353) dan **resources** (16) yang
memuat `sp.SkeletonData`.

## Format

**config.<hash>.json** — Cocos: `{types, uuids, paths}`. Untuk tiap nama spine ada
dua entri:
```
spine/<kategori>/<Nama>  -> sp.SkeletonData  (uuid A, skeleton .bin)
spine/<kategori>/<Nama>  -> cc.Texture2D     (uuid B, uuid BERBEDA, .astc)
```

**import/<xx>/*.json** — serialisasi Cocos (bukan objek JSON biasa). Record yang
dicari ada di `d[5]`, bentuknya:
```
[<id>, "<Nama>", ".bin", "<atlasText LENGKAP>", ["<Nama>.png"], [<textures>]]
```
`atlasText` memuat header atlas + SEMUA region (hal yang sama yang biasanya ada
di file `.atlas` terpisah). Jadi atlas tidak perlu dicari ke mana-mana.

**native .bin** — benar-benar Spine **binar** biasa (hash skeleton + string
`3.8.99` + tabel). Karena viewer spine-viewer sudah memuat `.skel` dan
mendeteksi versi runtime dari byte, cukup disalin sebagai `<Nama>.skel`; tidak
perlu konverter apa pun.

**ASTC kustom** (header 16 byte):
```
0  4  magic 13 AB A1 5C
4  1  block_x        (5, 4, 8, …)
5  1  block_y
6  1  dim_z (1)
7  3  width   (little-endian)
10 3  height  (little-endian)
13 3  reservasi
16 .. data ASTC (tanpa header 16 byte standar)
```
Decode `texture2ddecoder.decode_astc(data, w, h, bx, by)` lalu **tukar kanal
R/B** (hasilnya BGRA). `.astc` bisa satu halaman atau lebih; `textureNames`
menentukan nama tiap halaman (mis. `X.png`, `X2.png`).

## Jebakan

- Record SkeletonData dikenali dari `o[2] == ".bin"` + `"size:" in o[3]`.
  Mencocokkan `o[0]` dengan index kelas **gagal** — di `d[5]` nilai itu bukan
  index kelas, jadi harus dideteksi dari isinya.
- Satu nama spine bisa muncul beberapa kali di `paths` (tipe aset berbeda:
  `sp.SkeletonData`, `cc.Texture2D`, `cc.Asset`, `cc.SpriteFrame`) — pisahkan
  berdasarkan tipe.
- Texture2D **selalu** punya uuid berbeda dari SkeletonData; jangan anggap sama.

## Hasil

**369 skeleton, 0 gagal, ~349 MB** — `common/` 353 + `resources/` 16
(`spine/roleshow`, `spine/roleatk`, `spine/effect`, `spine/bottomTabBar`, dll).
Spine **3.8.99**. Di viewer: `assets/throne/<paket>/<Nama>/`.
