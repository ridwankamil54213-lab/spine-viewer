# Ark Re:Code — updater resmi (CDN terbuka)

Sumber: `https://erdpu.gzxhcjz.com/GamePatch/Android/`
Ditemukan dari string table `二游资源工具.exe` (lihat `eryou-endpoints.md`).

## Yang terbuka

| File | Isi |
|---|---|
| `catalog_112681.json` | **25 MB** Addressables catalog, 72.590 internal id, 5.504 bundle |
| `{namabundle}_{md5}.bundle` | 200 OK, tanpa login, tanpa enkripsi |

Pola nama bundle: `<namabundle>_<md5 32 hex>.bundle`.
Internal id di catalog memakai placeholder `http://PatchDomain/Android/…` —
ganti dengan `https://erdpu.gzxhcjz.com/GamePatch/Android/` lalu ambil
nama file paling kanan.

## Hasil: 7 model H-scene (CG interaktif)

Bukan model karakter biasa — ini **H-scene** yang di game diputar lewat
sistem CG. Semua **Spine 4.1.23**, atlas bertanda **`pma:true`**.

| Model | .skel | Atlas | PNG | Tulang | Animasi |
|---|---|---|---|---|---|
| H006 | 273 KB | 3,7 KB | 2048² | 140 | 17 |
| H006_S | 304 KB | 4,4 KB | 2048² | — | — |
| H009_S | 181 KB | 4,5 KB | 2048² | — | — |
| H016 | 224 KB | 4,1 KB | 2048² | — | — |
| H016_S | 384 KB | 7,6 KB | 2048² | 335 | 3 |
| H019 | 184 KB | 3,7 KB | 2048² | — | — |
| H060_S | 283 KB | 7,0 KB | 2048² | 275 | 3 |

Terverifikasi render di browser: runtime 4.1, Spine 4.1.23, 275 tulang,
3 animasi, PMA aktif, 0 error konsol.

## Aturan penting

**Selector bundle**: di catalog, bundle yang benar-benar berisi Spine punya
`skeletondata` atau `.skel` di namanya — hanya **7 dari 5.504**. Bundle
`defaultduplicategroup_*` (668 buah) isinya cuma prefab/shader; contohnya
`..._spine-skeleton-pma-screen_*.bundle` hanya berisi 1 Shader, bukan model.

**UnityPy + .skel**: `TextAsset.m_Script` untuk file biner dikembalikan
sebagai `str` dengan surrogateescape (`0xc8` → `\udcc8`). Encode dengan
**`latin-1`** (bukan utf-8) supaya byte aslinya pulih utuh 1:1.

## Isi viewer

`assets/arkrecode-h/<MODEL>/` + entri `GAME_ROOTS`:

```js
{ match: "arkrecode-h", key: "arkrecode-h",
  label: "Ark Re:Code — CG H-Scene", spineRuntime: "4.1", pmaDefault: true }
```

Entri ini **harus sebelum** `arkrecode` (prefix match).

Skrip: `/opt/arkupd/check-skel.py`, `/opt/arkupd/extract-ark.py`.

## Catatan pembaruan (catalog_116031)

`tools/update-arkrecode.py` adalah jalur updater yang **aktif** sekarang
(dokumen di atas merangkum riset awal untuk `arkrecode-h`). 20 bundle hero
baru di catalog ini: 18 di antaranya (`H169`, `H191`…`H210`, `H611`) cuma
berisi prefab/ikon/`ParticleSystem` tanpa `TextAsset`, jadi **bukan Spine**;
hanya `M001`/`M020` yang menghasilkan `M_001_1`/`M_020_1`.

State `processed_v2` menyimpan signature hash bundle, bukan id polos, supaya
model yang belum punya skeleton tetap bisa muncul lagi kalau game menambahkannya.
State ditulis **setelah** ekstraksi. Detail lengkap + regresi
`tools/check-arkrecode.cjs` ada di `README.md` → "Ark Re:Code: model bukan Spine".

## Catatan

Ark Re:Code yang sudah ada di viewer (597 model, `arkrecode/`) mencakup
karakter + CG biasa. Catalog punya 585 model Spine dari 589 `.skel.bytes` —
jadi model karakter di viewer **sudah lengkap**; yang belum ada hanya
7 H-scene ini.
