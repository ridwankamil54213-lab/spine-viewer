# Lost Sword — updater

Game: **Lost Sword** (로스트 소드), Wemade Connect (`com.wemadeconnect.aos.lostdgl`).

## Sumber: XAPK resmi (selalu versi terbaru)

Bukan repo komunitas — repo semacam itu tidak ikut ter-update. Sumbernya APK
resmi di APKPure:

```
https://d.apkpure.net/b/XAPK/com.wemadeconnect.aos.lostdgl?version=latest
```

Redirect-nya membawa nama berkas yang memuat versi (`Lost+Sword_1.591.1_...`),
jadi **`--check` cukup satu permintaan 1 byte** (`Range: bytes=0-0`)
untuk tahu versi terbaru, dan langsung balik kalau sudah sama. Unduhan penuh
(2,6 GB) hanya terjadi saat versi berubah; XAPK-nya di-cache di
`cache/lostsword/lostsword.xapk`.

## Pipeline

```
XAPK (2.6 GB)
  └─ UnityStreamingAssetsPack.apk        (split, 1.0 GB)
       └─ assets/aa/Android/*.bundle     (468 bundle)
            └─ UnityPy get_raw_data()    → TextAsset (.skel/.atlas) + Texture2D (.png)
```

**Kenapa `get_raw_data()`, bukan `obj.read()`:** untuk bundle ini UnityPy
mendekode `TextAsset.m_Script` menjadi `str`, dan itu merusak `.skel` biner
(byte ≥ 0x80 tidak bisa bolak-balik lewat encoding teks apa pun). `get_raw_data()`
memberi byte apa adanya; layout TextAsset di-parse manual:

```
int32 name_len | char[] name (pad 4) | int32 data_len | byte[] data
```

Texture2D tetap lewat `obj.read().image` (Pillow).

### Skeleton JSON tanpa ekstensi

Sebagian model (mis. `Iris`, `mordred`, `Mercedes`, `Grand_Commander`) menyimpan
skeleton sebagai **Spine JSON tanpa ekstensi sama sekali** — TextAsset-nya
bernama `Iris`, `mordred`, dst., jadi filter berbasis ekstensi `.skel` akan
**membuangnya** dan modelnya hilang tanpa jejak. Deteksi skeleton dari
**isinya** (`{"skeleton"...`) — bukan dari nama berkas — lalu tulis ulang
sebagai `<stem>.json` (viewer memilih runtime Spine dari field versi di JSON-nya;
inilah sumber versi campur 4.1.06–4.1.24).

## Tata letak keluaran (yang dibaca viewer)

```
assets/lostsword/<grup>/<folder>/<stem>.{skel,atlas,png}
```

- `grup` = `lobbyunit` | `unit` | `pet` | `atlas`, diturunkan dari prefiks nama
  bundle. **`prefabs_map_*` (72 bundle, layer peta/langit/bangunan) sengaja
  dilewati** — ratusan skeleton latar yang akan membanjiri library karakter.
- `folder` = **daun nama bundle** (mis. `prefabs_lobbyunit_cristina_bikini01` →
  `cristina_bikini01`), **bukan stem skeleton**. Stem tidak unik secara global
  (banyak unit memakai `ef`, `Back`, `Skill`), jadi folder berbasis stem akan
  menggabungkan model berbeda atau bertabrakan. Nama bundle unik + enak dibaca.
- Satu bundle = satu folder, walau isinya beberapa skeleton: karakter dengan
  layer kabut/efek (`Abyss` + `Abyss_Fog_B/F` + `Eff_1/2/3`) tetap satu model,
  dan viewer menampilkannya sebagai satu model **dengan dropdown varian**.

## Perintah

```
python tools/update-lostsword.py --check          # probe versi; 1 byte kalau sudah terbaru
python tools/update-lostsword.py --apply          # unduh (kalau berubah) + ekstrak yang baru
python tools/update-lostsword.py --check  --force --xapk <path>   # offline: pindai semua bundle
python tools/update-lostsword.py --apply --changed --xapk <path>  # tulis ulang hanya bundle yg berubah
python tools/update-lostsword.py --apply --only unit              # batasi ke satu grup
```

- **`--force`** mengabaikan cap versi dan memindai semua bundle (untuk uji).
- **`--changed`** memindai semua bundle tapi hanya menulis ulang yang berkas
  bundle-nya lebih baru dari folder terpasang (pakai stempel waktu di dalam zip;
  nama bundle memuat hash konten sehingga aset yang berubah jadi entri baru).
- **`--xapk`** memakai XAPK yang sudah ada, jadi bisa jalan offline.
- **`--only <grup>`** membatasi ke `lobbyunit`/`unit`/`pet`/`atlas`.

Idempoten: `--check --force` mengembalikan `new: 0` saat semua sudah terpasang.

## Hasil (v1.591.1)

- 468 bundle → **392 folder / 449 model** (72 bundle peta dilewati, 20 bundle
  bukan-spine).
- 156 lobby (kartu lobby + memorial/daily/bikini), 224 unit (karakter + monster
  + boss + efek), 69 pet.
- **422 skeleton biner + 19 skeleton JSON tanpa ekstensi** (19 terakhir inilah
  yang tadinya hilang: `iris`, `mordred`, `mercedes`, `grand_commander`,
  `imperial_giant_soldie`, `nimue`, `lilith`, `roy`, `urien`, `igraine`,
  `beirin`, `gawain_lobby`, `goblin_s_boss`, `dummy`, `merry`, `enya_ultimate`,
  `worlddragon_01`, `cristina_bikini`, …).
- **90 model punya varian** (dropdown), mis. `unit/isabel` → `Isabel` +
  `Isabel_Throne`; `lobbyunit/elizabeth` → `Elizabeth` + `Elizabeth_Special`.
- Spine **4.1.06–4.1.24** (versi campur); atlas PMA (`pma:true`) — viewer
  mendeteksi PMA dari atlas.
- Sisa yang tak bisa render (memang tak lengkap di APK): 11 skeleton tanpa atlas
  (`enya_ultimate`, `worlddragon_01`, `skull_*`, `goblin_carriage` b_05/b_06,
  `cristina_bikini`, …) dan 16 atlas tanpa skeleton (kartu lobby diam yang
  atlas-nya dipakai ulang, mis. `mordred`/`iris` lobby).

## Catatan

- Model karakter menyimpan "skin" di dalam skeleton (mis. `unit/crassa` punya
  `default`, `Memorial`, `None`) — itu yang muncul di dropdown **Skin**.
- `atlas/` (equipment/weapon atlas) berisi 1 PNG saja tanpa skeleton, jadi
  memang tidak menghasilkan model.
