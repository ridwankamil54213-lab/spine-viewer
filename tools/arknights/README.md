# 明日方舟 (Arknights) — Spine 3.8

Integrasi dari tiga repositori publik (tanpa auth):

| Sumber | Isi |
|---|---|
| [`isHarryh/Ark-Models`](https://github.com/isHarryh/Ark-Models) | 3.112 folder `.skel` + `.atlas` + `.png`, `models_data.json` (3.200 entri) |
| [`ArknightsAssets/ArknightsGameData`](https://github.com/ArknightsAssets/ArknightsGameData) `en/gamedata/excel/` | `skin_table.json` (nama skin Inggris), `enemy_handbook_table.json` (nama musuh Inggris) |
| [`yuanyan3060/ArknightsGameResource`](https://github.com/yuanyan3060/ArknightsGameResource) | `portrait/`, `avatar/`, `enemy/`, `skin/` → thumbnail ilustrasi WebP |

## Kenapa foldernya di-sanitasi

Nama asli banyak mengandung `#` (**589 folder**, mis. `002_amiya_epoque#4`).
Server membuat id dengan `rel.replace(/[^\w.\-/]+/g, "-")` dan viewer
menyusun URL aset dari `/assets/<id>/<skeletonFile>`, sehingga folder like itu
akan menghasilkan id `002_amiya_epoque-4` → **semua aset 404**. Selain itu `#`
di dalam URL adalah penanda fragment.

`update.py` menulis ulang **nama folder + nama berkas + baris halaman di
`.atlas`** ke ASCII (`#` / `$` → `_`), dengan md5 pendek kalau sanitasi
membuat tabrakan. Id model tetap stabil dan tidak mengandung `#` kecuali
pemisah varian bawaan server untuk folder yang punya beberapa `.skel`.

## Format

- **Spine 3.8** binary `.skel` → runtime `@pixi-spine/runtime-3.8` yang sudah
  ada di viewer (`spineRuntime: "3.8"` di `GAME_ROOTS`).
- Repo sumber memaksa **Premultiplied Alpha** pada semua tekstur walau
  `.atlas` tidak memuat baris `pma:true` → `pmaDefault: true`.
- 953 operator (termasuk 521 skin), 2.063 folder musuh, 96 dynamic illust.
  `models_data.json` punya 3.200 entri; 109 di antaranya tidak punya folder
  (beberapa gaya musuh berbagi folder) dan 21 folder tidak punya metadata —
  keduanya tetap diekstrak dengan nama fallback ASCII.

## Nama & family

- Operator: `displaySkin.modelName` (Inggris) + `displaySkin.skinName` untuk
  skin; fallback `appellation` dari `models_data.json`.
- Musuh: `enemyData[enemy_<id>].name` dari handbook EN; sisanya fallback
  ke id yang dipretty-print. **0 aksara Tionghoa** di nama tampilan.
- `data/arknights-names.json` (leaf folder → `{name, character, skin, type,
  rarity, source}`) dan `data/arknights-family.json` mengelompokkan skin per
  `charId` jadi picker varian di UI. Keduanya dibaca `src/server.js`.

## Thumbnail

Bukan halaman atlas. `resolve_art()` mencari berurut:
`portrait/char_<key>_1.png` → `...png` → `avatar/` → `enemy/enemy_<key>.png`
→ `skin/`. Gambar diunduh lewat jsDelivr (fallback `raw.githubusercontent.com`),
di-resize ke 320×420 dan disimpan WebP di `public/thumbs/arknights/`.
`#` pada nama berkas di-encode jadi `%23`. Manifest `_manifest.json`
memetakan **id model lengkap** (termasuk varian `#<stem>`) ke file WebP.
Cakupan ~2.776/3.112 folder; musuh yang tak punya ilustrasi dibiarkan tanpa
thumbnail daripada menampilkan potongan atlas.

## Pemakaian

```sh
/srv/venv-spine/bin/python tools/arknights/update.py --check    # ~1 dtk, 3 JSON kecil
/srv/venv-spine/bin/python tools/arknights/update.py --apply     # zip 1,1 GB + 2.776 gambar
/srv/venv-spine/bin/python tools/arknights/refresh.py            # --apply --offline, dari cache

node tools/check-arknights.cjs   # regresi (server :3000)
```

Cache di `/srv/spine-assets/arknights/`: `models_data.json`, `skin_table.json`,
`enemy_handbook_table.json`, `art-tree.json`, `Ark-Models-main.zip`, `state.json`.
`--check` mengambil 3 metadata JSON dari CDN dan menghitung versi dari
sha1 gabungannya; selisih versi = titik merah sampai Apply. `--apply` hanya
mengunduh ulang zip kalau versi berubah, dan melewati thumbnail yang sudah ada.

`UPDATERS.arknights` memakai `rescan: true` karena Apply menulis folder model
baru. `assets/arknights/` dan `public/thumbs/arknights/` tidak masuk git.
