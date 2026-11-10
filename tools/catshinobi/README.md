# Cat Shinobi (ねこ親方 / com.cookapps.catshinobi) — asset updater

Cat Shinobi is a Unity **Addressables** game. Nothing lives on a separate CDN:
every Spine skeleton ships inside the 528 MB APK split
`split_UnityDataAssetPack.apk`, in one big bundle
`assets/aa/Android/defaultlocalgroup_assets_all_*.bundle` (492 MB) plus a small
`boot_assets_*.bundle`. So the "update" is: pull the split from the device
(redroid), scan the bundles, extract only the skeletons that are not in
`assets/catshinobi/` yet.

## Usage

```sh
# what's new?  (cheap on repeat: skips the 528 MB pull when the device split
# size matches the cached copy)
/srv/venv-spine/bin/python tools/update-catshinobi.py --check
# pull + extract only the new skeletons into assets/catshinobi/
/srv/venv-spine/bin/python tools/update-catshinobi.py --apply

# offline / already-pulled:
... --check --apk /opt/catshinobi/split_UnityDataAssetPack.apk
... --apply --bundles /opt/catshinobi/aa/assets/aa/Android
```

Env: `CS_OUT` (default `assets/catshinobi`), `CS_WORK` (default
`/srv/spine-assets/catshinobi-update`), `ADB`, `ADB_SERIAL` (default
`127.0.0.1:15555`).

## Output layout

```
assets/catshinobi/<Name>/<Name>.skel
assets/catshinobi/<Name>/<Name>.atlas
assets/catshinobi/<Name>/<page>.png
```

## Gotchas (learned the hard way)

- **TextAsset must be read raw.** `obj.read().m_Script` decodes to `str` and
  corrupts binary `.skel`; parse Unity's TextAsset layout manually from
  `get_raw_data()` (int32 name_len / padded name / int32 size / bytes).
- **Never `obj.read()` a Texture2D while scanning.** Decoding all 2584 textures
  costs minutes; read `m_Width`/`m_Height` via `read_typetree()` to rank
  duplicates, then decode ONLY the pages an atlas references.
- **Duplicate texture names**: keep the LARGEST (width×height); picking the
  first saves a small page whose coordinates don't match the atlas.
- A skeleton stem may be split on underscores (`02_Hino` + `Reona_Ingame`)
  while the atlas name is one token — that's a bundle quirk, not a bug.
- The Addressables catalog is local (`catalog.bin` in the split, `m_IsLocal…`
  false but no remote profile); there is no remote group to fetch.

> **Catatan:** paragraf di atas merangkum jalur lama (tarik split dari perangkat
> redroid lewat `adb`). Jalur aktif sekarang ada di `tools/update-catshinobi.py`
> yang mengunduh XAPK dari APKPure; lihat bagian berikut.

## Metadata: nama karakter, varian, thumbnail

Tiga hal yang sebelumnya belum lengkap untuk 596 model `assets/catshinobi/`:
nama karakter cuma 260, tidak ada picker varian, dan tidak ada thumbnail.
Semuanya dibangun **offline** dari APK yang sudah diekstrak.

| Berkas | Sumber | Keluaran |
| --- | --- | --- |
| `../catshinobi-names.py` | bundle `localization-string-tables-*` | `data/catshinobi-names.json` |
| `enrich.py` | `Sprite` di `defaultlocalgroup_*` | `public/thumbs/catshinobi/*.webp` + `_manifest.json`, `data/catshinobi-family.json` |
| `refresh.py` | — | jalankan dua-duanya, offline (~4 dtk) |

### Thumbnail = ilustrasi, bukan atlas

Bundle berisi 3.562 `Texture2D`; mayoritas adalah halaman atlas Spine
(`Char_LD_11011`, `sactx-…`) berukuran 2048² dan **fully opaque**. Yang dipakai
adalah **Sprite ilustrasi** berlatar transparan: `CharThumb_<id>` (168),
`CharInfoThumb_<id>`, `char_<nama>_<id>`, `Icon_Profile_*_Full_<id>`.
`enrich.py` menyaring rasio 0,30–1,25 & tinggi ≥160 px lalu memilih satu
gambar terbaik per id. Hasil: **233 ilustrasi → 188 WebP (3,3 MB) → 517 model
ber-thumbnail**. Semua WebP punya kanal alpha (rata-rata 56–172); 0 gambar
fully opaque, jadi bukan potongan atlas.

### Nama karakter

`tools/catshinobi-names.py` membaca tabel lokalisasi **milik game sendiri**
(`UI_CHARACTER_NAME_*`, `UI_COSTUME_NO_*`; en/id/ja), bukan wiki. Aturannya
sengaja ketat supaya tidak mengarang nama: `exact-char`, `costume->base`, atau
`base(<id>)` (tiga angka depan sama dengan karakter dasar berakhir `01`,
mis. `10003` → `10001` Mei Kaminari). `cat_*_mode_*` dan `monster_*` sengaja
tidak dinamai karena angkanya indeks animasi/musuh, bukan id karakter.

Perbaikan: cabang `costume-only` dulu langsung berhenti sehingga `Char_1003`
(Summer Shinobis), `Char_2004`, `Char_6002`, … tidak pernah mencoba
`shared_base`. Sekarang **260 → 307 model bernama**, lengkap dengan kostum asli
(`Noble Frost`, `May Marry Me`, `Soccerholic`, …) dan field `variant`
(`Battle`, `SD (Chibi)`, `LD`, `Cat · Battle`, `Monster`, `· Skill`).

### Varian (family)

Model dikelompokkan per **id numerik yang sama** lintas bentuk:
`Char_32001`, `Char_SD_32001`, `Char_LD_32001`, `cat_battle_mode_32001`,
`cat_front_mode_32001`, `cat_ninja_32001` = satu family. Root diutamakan
`Char_<id>`; nama family dari tabel lokalisasi, atau penanda jujur `Set <id>`
kalau tidak ada. Hasil **186 family / 519 anggota**. Server membacanya lewat
daftar `family` umum di `src/server.js`, jadi picker varian yang sama dengan
Arknights / Zone Nova / Stella Sora langsung bekerja.

### Regenerasi

```bash
# sesudah update-catshinobi.py mengekstrak APK baru:
/srv/venv-spine/bin/python tools/catshinobi/enrich.py   # isi cache sprite
/srv/venv-spine/bin/python tools/catshinobi/refresh.py  # offline
systemctl restart spine-viewer
node tools/check-catshinobi.cjs
```

`enrich.py --offline` cuma membaca `…/catshinobi-update/sprites/` (PNG +
`_index.json`), tidak membuka bundle 648 MB. Cache dan
`public/thumbs/catshinobi/` ada di luar git.
