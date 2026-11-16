# Nikke — unduh ulang dari ArtHub `nikki`

Menggantikan pipeline lama `tools/update-nikke.py` (repo Nikke-db) yang
menghasilkan model dobel. Data lama diarsipkan di
`/srv/spine-assets/nikke-old-20261107/`; `assets/nikke/` sekarang berisi
**2104 model, satu per folder, tanpa duplikat**.

## Sumber

| Berkas | Isi |
| --- | --- |
| `https://github.com/Talors1225/arthub-viewer-web/tree/main/nikki` | katalog + viewer (bukan berkas model) |
| `nikki/nikki_chars.json` | 2104 karakter: `id`, `cutscenes[].{dir,skel,atlas}`, `characterCode`, `resourceType`, `typeLabel` |
| `nikki/character-names.json` | 131 profil nama (opsional) |
| `arthub-cos-config.js` + `arthub-cos.js` | `root` = `pub-bdd986c6ec274f53b01df62ac49e02e2.r2.dev`; `PATH_REWRITES` `/nikki/spine/` → `/nikki/spine_carved/` |
| `https://nkas.pages.dev/nikkes/` | sumber nama Inggris (halaman Astro; JSON di `/nk_data/nikkegg/characters.json`) |
| `https://nkas-l2d.pages.dev/characters.json` | 571 nama `cNNN_NN`, fallback NPC/enemy |
| `https://raw.githubusercontent.com/Talors1225/arthub-viewer-web/main/posters/nikki/<id>--<variant>.webp` | 2102 poster thumbnail |

URL final:
`https://pub-bdd986c6ec274f53b01df62ac49e02e2.r2.dev/nikki/spine_carved/<folder>/<file>`.

## Bentuk aset

Satu karakter = satu cutscene. `.skel` = Spine **binary 4.1.20**, `.atlas`
memiliki `pma:true`, dan halaman tekstur PNG disebut di baris pertama atlas
(serta baris-baris sebelum `size:` lainnya untuk multi-halaman).

Aturan penulisan (sama seperti `tools/mad-drama/refresh.py`):

- skel + atlas di-rename ke `<id>.skel` / `<id>.atlas` → id model stabil;
- **nama halaman PNG tidak boleh diubah** — atlas memanggilnya persis;
- beberapa atlas diawali **BOM UTF-8**. Parser memakai `decode("utf-8-sig")`
  + `lstrip("\ufeff")`, kalau tidak halaman pertama jadi `%EF%BB%BF*.png` → 404;
- tidak ada dekripsi / UnityFS / FakeHeader: berkas R2 sudah bersih.

## Pakai

```bash
/usr/bin/python3 tools/nikke/refresh.py --limit 3     # uji ke NIKKE_OUT=/tmp/...
/usr/bin/python3 tools/nikke/update.py --check
/usr/bin/python3 tools/nikke/update.py --apply
```

`refresh.py` idempoten (folder lengkap dilewati) dan menulis
`assets/nikke/_names.json`. `update.py` **berpusat ke NKAS**: jalankan
`refresh.py --names-only` (segarkan nama), lalu `refresh.py` (model) +
`refresh-thumbs.py`, dan menyimpan state di
`data/nikke-update-state.json`. Terdaftar di `UPDATERS["nikke"]` dengan
`rescan: true`. `applyNikkiNames()` di `src/server.js` membaca `_names.json`
setelah `attachCharacters()`.

## Nama karakter: NKAS /nikkes/

Sumber: **https://nkas.pages.dev/nikkes/** → `/nk_data/nikkegg/characters.json`
(206 entri, `img: si_c102_00_s` → kode `c102`, `name` sudah Inggris). Halaman
Astro itu memuatnya lewat `_astro/nikkes.js` (`Promise.all` dengan
`/nk_data/aliases.json`); bukan `/api/` dan bukan file statis bernama
`characters.json` di root — semua path yang nggak ada dibalikin sebagai HTML
200, jadi cek `content-type` kalau nebak endpoint.

Urutan `build_names()`:

1. `c<characterCode>` → nama NKAS (1430 model).
2. `cNNN_NN` → `nkas-l2d.pages.dev/characters.json` (173; nutup NPC kayak
   `c013_00` → `Marian` yang absen dari 206 entri utama).
3. Url NKAS **terpanjang** yang terkandung di id — TAPI cuma kalau entri
   punya `characterName` (22 model; `staranis` → `Anis`). Tanpa pembatas ini
   url `eve` nyangkut di `EventScene_*` (123 kartu jadi "EVE"), `ade` di
   `madeinrush_*`, `mica` di `chemical`. Url 1 huruf juga diabaikan.
4. Profil `character-names.json` (0), lalu bagian ASCII `displayName` (479).
5. Jangkar terakhir: buang sisa aksara Tionghoa (mis. `角色 C013`), kalau
   hasilnya cuma kode polos `C013`/`C907` cari lagi ke peta NKAS
   (`Marian` / `Shifty`), baru fallback ke id model.

Label tipe Tionghoa (`剧情 / 过场`, `目录素材`, …) **jangan dipakai**: ganti
dengan `resourceType` lewat `TYPE_LABEL` → `Cutscene`, `Catalog`, `Battle`,
`Lobby`, `Skill`. Hasil 2104 nama, **0 CJK**.

`refresh.py --names-only` regenerasi nama tanpa unduh model. `update.py`
memantau NKAS lewat `source_state()`: hash terpisah untuk ArtHub dan NKAS,
daftar 206 kode `cNNN` di state, deteksi karakter baru, dan jumlah nama NKAS
yang terpakai. Endpoint NKAS opsional — kalau mati, `--check` tetap jalan.

## Varian aim / cover / skillcut

`attachNikkiFamilies()` mengelompokkan berdasarkan kode karakter + indeks
kostum (`c010_00`). Label: `Utama`, `Aim NN`, `Cover NN`, `Skill Cut`, dan
`Katalog · …` untuk id berawalan `catalog-`. 391 family / 1406 model jadi
varian → pustaka 1089 kartu root. Urutan: Utama → Aim → Cover → Skill Cut →
Katalog.

## Thumbnail

`refresh-thumbs.py` mengunduh poster dari
`posters/nikki/<id>--<variant>.webp` di repo yang sama. `variant` =
`cutscenes[0].variant` dari katalog (`0` atau `Catalog`). Keluaran
`public/thumbs/nikke/<id>.webp` + `_manifest.json` (2104 entri, 38 MB),
tanpa crop, maks 300 px.

Jebakan:
- 2 model tanpa poster sendiri → fallback ke poster root (`c330_00`, `c550_00`).
- 3 poster WebP **animasi** gagal didekode ffmpeg → disimpan apa adanya;
  jangan dianggap error,`<img>` tetap menampilkannya.
- Host poster BUKAN bucket R2 (`pub-bdd986c6...`), melainkan
  `raw.githubusercontent.com/.../posters/nikki/`. `K.stagePosterPath()` di
  viewer ArtHub memakai path relatif situsnya, bukan URL absolut.

Regresi: `tools/check-nikke.cjs` (39 assertion, termasuk nama NKAS tanpa CJK,
anti-false-positive "EVE", updater berbasis NKAS, family, thumbnail,
render 3 model dan 0 aset 404).

## Potret & filter Prydwen

```sh
python3 tools/nikke/import-prydwen.py
- Regresi: `node tools/check-nikke-prydwen.cjs`.

## Reset penuh saat pohon tercampur

Kalau jumlah model jauh di atas katalog (debug: `find assets/nikke -mindepth 1
-maxdepth 1 -type d | wc -l`), jangan hapus manual. Pakai:

```sh
python3 tools/nikke/replace.py --apply --workers 12
node tools/check-nikke-clean.cjs
```

`replace.py` mengunduh ke staging, memvalidasi, lalu **memindahkan** pohon lama
ke `/srv/spine-assets/nikke-before-replace-<stamp>` sebelum swap. Ia juga
menangani entri `bursts/` lewat `nativeBurst` dan cached 403 R2 dengan
cache-buster. `--stage /srv/spine-assets/nikke-stage-<stamp>` bisa dipakai
untuk melanjutkan staging yang gagal di tengah.

## Potret NKAS

```sh
python3 tools/nikke/import-nkas-thumbs.py
node tools/check-nikke-nkas.cjs
```

Daftar kode dari `https://nkas-l2d.pages.dev/characters.json` (571 entri,
termasuk NPC `c9000_*`), potret dari `https://nkas.pages.dev/characters/
mi_<kode>_s.png`. Server NKAS menolak request tanpa UA browser; importer
memakai `Mozilla/5.0` + retry cache-buster untuk 403 sesekali. Potret
disimpan sebagai WebP 256×496 dan dipasang sebagai overlay manifest paling
akhir, jadi menimpa Prydwen tanpa mengubah metadata filter.

Semua varian `skillcut` kini dinormalisasi di `nikkiVariantOf()` dan
dimasukkan ke family karakter: tidak ada kartu skillcut mandiri. Regresi
`check-nikke-nkas.cjs` memastikan 0 skillcut tampil di grid.
```

Mengambil 227 karakter dari `https://www.prydwen.gg/nikke/characters` (blob
JSON di HTML SSR, bukan API), mengunduh potret `*_card.webp` + ikon ke
`public/thumbs/nikke-prydwen/`, dan menulis `data/nikke-prydwen.json`
(`byCode` kode `cNNN` → atribut, `models` id model → kode). Pencocokan lewat
`data/nikke-characters.json`: `slug`/`name` Prydwen → `url`/`name` katalog →
`img` (`si_c010_00_s`) → `c010`. Idempoten; daftar id model diambil dari
`/api/models?game=nikke&lean=1` dengan fallback ke `assets/nikke/_names.json`.

Server menempelkan field `nkRarity`/`nkClass`/`nkElement`/`nkWeapon`/
`nkManufacturer`/`nkBurst` (ikut ke indeks lean), dan `thumbManifest()`
menerapkan manifest `nikke-prydwen` paling akhir. Filter bar `#nk-filters`
dan kartu 262:358 ada di `src/viewer.js` / `public/styles.css`.

## Arsip

- `tools/update-nikke.py` — **USANG**, jangan dipakai (sumber Nikke-db,
  mengembalikan duplikat). Dibiarkan sebagai referensi.
- `tools/fetch-thumbs.js` / `fetch-thumbs-legacy.py` — tool thumbnail lama
  (`nkas.pages.dev`), path tujuannya `/srv/spine-viewer/...` yang sudah tidak
  ada. Butuh `sharp` yang tidak terpasang.
- `data/nikke-*.json` — peta nama lama, kuncinya tidak lagi cocok; dibiarkan
  karena tidak berbahaya.
- Manifest 3416 id lama: `/tmp/nikke-deleted-ids-2026-11-07.json`.
