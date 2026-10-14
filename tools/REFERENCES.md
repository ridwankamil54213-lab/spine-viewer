# Referensi: violet-wdream/.Scripts

Koleksi script unpack game (Cina). Di-clone ke `/srv/spine-assets/_tools/vw`.
Repo ini muncul di "Special Thanks" E7SpineAssetConverter.

**PERINGATAN README (diterjemahkan):** "Sebelum dipakai, minta saran LLM atau
baca komentar kode" dan "coba dulu dengan sedikit file dan backup sumbernya".
Sebagian besar script punya path absolut `D:\...` yang HARUS diganti.

## Yang sudah divalidasi

### Games/Orisries/DecryptOrisries.py
Logikanya IDENTIK dengan `tools/decrypt-orisries.py` punya kita:
key `b'wiki is transfer'`, AES-CBC, IV 16 byte di ekor + panjang IV (LE u32),
file `UnityFS` dilewatkan begitu saja. Validasi silang bagus — implementasi
kita sudah benar.

Perbedaan: script repo menulis ke subdirektori `decrypted/` dan memakai
`assert` (berhenti di file pertama yang bukan bundle), sedangkan punya kita
mencatat error dan lanjut — itulah sebabnya 3 file manifest teks
(`art_2026090201.json`, `.info`, `filelistdata.txt`) tidak menggagalkan
seluruh proses.

## Yang relevan tapi BELUM dipakai

### Games/BrownDustII/{FetachCatalog,GenURLs}.py
- `FetachCatalog.py`: ambil versi terbaru + catalog BD2 dari
  `mt.bd2.pmang.cloud/MaintenanceInfo` (butuh `httpx` + `blackboxprotobuf`).
- `GenURLs.py`: ubah catalog jadi daftar URL unduhan. BASE_URL =
  `https://cdn.bd2.pmang.cloud/ServerData/StandaloneWindows64/HD/<VERSION>/`,
  filter kata kunci default `["skeleton", "idcardbgcutscene"]`.

Ini jalan untuk menambah bundle BD2 yang belum terunduh (65 `cha_*` +
169 `banner` menurut perbandingan catalog vs filelistdata).

### Utils/DownLoad/UrlsDownLoader.py + CheckUrlsValid.py
Pengunduh + pemeriksa validitas URL — berguna kalau daftar URL sudah ada.

### SpineFileProcess/
- `CheckSpineFiles.py`: audit kelengkapan atlas/skeleton/gambar.
- `Png_resize_by_atlas.py`: samakan ukuran PNG dengan deklarasi atlas
  (masalah yang sama dengan 20 model OrisRies yang texture-nya dipadding).
- `Converter/TheMoonlitOath/Skel2Json.py`: konversi .skel **3.8** -> .json,
  Python murni 1529 baris, CLI `python Skel2Json.py in.skel out.json`.
  TIDAK cocok untuk Project QT: game itu Spine **2.1.27**, bukan 3.8.

### Decrypt/
`DecryptXOR.py` (deteksi jenis XOR bundle Unity), `UnityCN_Key_Brute_force.py`,
`YooAssetUnpacker.py` (YooAsset — dipakai Haze Reverb).

## Game di repo (39) yang belum ada di viewer
CounterSide, DestinyChild, GirlCafeGun2, IronSaga, OmniHeroes, Starward,
TheMoonlitOath, illusionConnectRe, dll. Kandidat kalau mau tambah game baru.

## Sumber aset Nikke (updater)

Repo **github.com/Nikke-db/Nikke-db.github.io** — mirror lengkap aset spine
NIKKE (1544 .skel, 1544 .atlas, 3392 .png) yang layout-nya SAMA dengan viewer:
`l2d/<folder>/<folder>_00.{skel,atlas,png}` + subfolder varian `aim/` & `cover/`.
Dipakai oleh `tools/update-nikke.py` (`--check` = recursive tree, `--apply` =
unduh berkas yang belum ada secara file-level). Viewer sudah memperlakukan
`<folder>/aim` & `<folder>/cover` sebagai varian (aturan family lama).
