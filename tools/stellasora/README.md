# Stella Sora (Yostar) — Spine 4.2 + Live2D Cubism 4

Satu updater menulis **dua root**:

| Root | Isi | Runtime |
|---|---|---|
| `assets/stellasora/` | 36 model Spine dari event | `spineRuntime: "4.2"` (4.2.43) |
| `assets/stellasora-l2d/` | 252 varian Live2D (234 entri karakter) | `format: "live2d"` / Cubism 4 |

## Kenapa sumber ini

Pencarian kesegaran per 2026-11-09:

| Sumber | Update | Catatan |
|---|---|---|
| `nova-static.stellasora.global/meta/win.html` | **real-time** | CDN RESMI game. 2,9 MB, bisa didekrip `openssl enc -d -aes-128-cbc -K <key> -iv 0`. Berisi 12.170 nama `.unity3d`, tapi pola URL `/res/win/` belum terbuka |
| `AutumnVN/StellaSoraData` | hari ini, cron **5 menit** | 5.041 JSON tabel data game |
| `AutumnVN/ssassets` | cron tiap jam | 12.401 WebP, ditarik dari CDN di atas |
| **R2 + `morphthemoth/Stella-Sora-Live2d`** | 2 hari (`Patch 2.0.1`) | **aset model siap pakai**: `.moc3`, `.model3.json`, `.skel`, `.atlas`, tekstur |
| `StellaSoraWiki/StellaSoraLive2Ds` | 20 hari | 113 ZIP Live2D, lebih usang |
| `StellaSoraWiki/StellaSoraModels` | 17 hari | 3D `.glb`, bukan untuk viewer ini |

**Keputusan:** model diambil dari R2 (paling segar yang langsung bisa dipakai,
tanpa dekripsi/manifest Unity). `AutumnVN/StellaSoraData` + CDN resmi Yostar
dipakai sebagai **sinyal kesegaran** di `--check` (`cdnSha`, `dataCommit`),
jadi ketahuan kalau game baru patch walau repo komunitas belum sync.

## Rantai data

```
R2  https://pub-fc0f3c90b1b34cacb1ce80b771ca4b08.r2.dev/
  chars/<skin>/<variant>/<name>.model3.json   -> FileReferences
      Moc, Textures[], Physics, DisplayInfo, Motions{}, Expressions[]
  events/<ref>/spine/<name>.{skel,atlas,png}
  avg/<id>/<pose>.png                          -> thumbnail ilustrasi

GitHub raw  morphthemoth/Stella-Sora-Live2d/master/data/
  models.json (234 entri: 252 varian `.model3.json` + 36 `.skel` + 5
              `body.png`; yang `.skel` sama dengan events.json dan yang
              `.png` statis, jadi keduanya dilewat di root Live2D)
  events.json (32 event / 36 Spine)
  avg.json (216 potret karakter)
  characterid.json (id 3-digit -> nama)
```

`version` = sha1 dari 4 data JSON. `--check` cuma mengambil 4 JSON + manifest
CDN + 1 commit API; `--apply` menulis model, nama, family, dan thumbnail.

## Penyesuaian format Live2D

Server (`src/server.js`) mendeteksi Live2D dari **`.moc3` di root folder**,
tekstur juga di root, `motions/` dan `expressions/` di subfolder, dan
mensintesis `.model3.json` di browser. Karena aset R2 aslinya bertingkat
(`textures/texture_00.png`, `motions/idle.motion3.json`, …), updater
**meratakan** berkas:

```
assets/stellasora-l2d/10301_l/
  10301_L.moc3
  texture_00.png  texture_01.png
  10301_L.physics3.json
  10301_L.cdi3.json
  motions/idle.motion3.json ...
  expressions/<...>.exp3.json   (kalau ada)
```

Spine event 4.2.43 memakai runtime `spine-pixi-v7-42`; teksturnya
straight-alpha (`pmaDefault: false`).

## Thumbnail

Bukan halaman atlas: potret karakter dari `avg/<id>/<pose>.png` di R2,
di-resize 320×420 jadi WebP di `public/thumbs/stellasora/`. Manifest
`_manifest.json` memetakan **id model lengkap** (kedua root) ke
`<charId>.webp`. Karakter tanpa potret dibiarkan tanpa thumbnail.

## Nama & family

`data/stellasora{,-l2d}-names.json` (leaf folder → `{name, character,
variant, source}`) dan `...-family.json`. `attachCharacters()` di server
sudah digeneralisasi untuk membaca keduanya; family mengelompokkan varian
per karakter jadi picker varian di UI. Semua nama Inggris, 0 aksara Tionghoa.

## Pemakaian

```sh
/srv/venv-spine/bin/python tools/stellasora/update.py --check    # ~2 dtk
/srv/venv-spine/bin/python tools/stellasora/update.py --apply     # prefetch paralel R2
/srv/venv-spine/bin/python tools/stellasora/refresh.py            # --apply --offline
node tools/check-stellasora.cjs                                   # regresi (:3000)
```

Cache: `/srv/spine-assets/stellasora/` (`data-*.json`, `assets/`, `state.json`,
`win.html`). Prefetch dua ronde (model3 dulu, lalu semua referensi) dengan 16
worker supaya ~3.800 berkas tidak diunduh satu-satu. Setelah prefetch, sisa
proses murni lokal & deterministik.

`UPDATERS.stellasora` memakai `rescan: true` dan melayani **dua** tile
(`UPDATABLE.stellasora` + `UPDATABLE["stellasora-l2d"]`).
`assets/stellasora*/` dan `public/thumbs/stellasora/` tidak masuk git.

Dependensi: stdlib + Pillow (lihat `requirements.txt`).
