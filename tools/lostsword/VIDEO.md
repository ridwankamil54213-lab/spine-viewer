# Lost Sword — video (skill / summon / quest cutscenes)

Game: **Lost Sword** (`com.wemadeconnect.aos.lostdgl`).

## Di mana videonya

Video **tidak** muncul lewat pencarian ekstensi apa pun:

- Tidak ada `.mp4`/`.usm`/`.webm` di dalam XAPK.
- Bundle `UnityStreamingAssetsPack.apk` hanya berisi skeleton/peta (468 bundle).
- Yang menyimpan video adalah **`UnityDataAssetPack.apk`** (1,4 GB, ~19,6k
  serialized file) sebagai objek **Unity `VideoClip`** — 224 objek, 87 nama unik.

Setiap `VideoClip` cuma ~350 byte (metadata) dan menunjuk blob eksternal:

```
m_ExternalResources.m_Source -> "<hash>.resource"   (berkas di pack yang sama)
m_ExternalResources.m_Offset -> offset byte di .resource
m_ExternalResources.m_Size   -> panjang byte
m_OriginalPath               -> "Assets/Resources/Video/High/Skill/<Nama>.mp4"
```

Jadi byte videonya = potongan `assets/bin/Data/<hash>.resource` pada
`[offset, offset+size)`. Nama & ekstensi diambil dari `m_OriginalPath`
(pack memuat versi **High `.mp4`** dan **Low `.m4v`** dari klip yang sama).

## Ekstraktor

```
python tools/extract-lostsword-video.py          # pakai XAPK yang di-cache
python tools/extract-lostsword-video.py --xapk <path>
python tools/extract-lostsword-video.py --list   # inventaris saja (tanpa tulis)
```

CPU-only; scan ~19,6k berkas lalu menulis ke `assets/lostsword-video/`
mengikuti pohon `Video/<Quality>/<Category>/`. Idempotent (melewati berkas yang
sudah ada dengan ukuran sama). Menulis `data/lostsword-videos.json` (daftar klip).

## Hasil (v1.591.1)

- **224 klip / 378,7 MB** — High 141 (`.mp4`), Low 83 (`.m4v`), H.264 1920×1080.
- Kategori: `Skill/` (per karakter), `Summon/` + `Summon/PickUp/`,
  `MemorialPick/`, `Quest/` (mis. `Prologue.mp4` 52 MB, `Summon_1/3.mp4`).
- 87 nama unik (High + Low = 2 varian per klip).

## Penting: codec H.264

File-nya H.264 standar (`ffprobe`: h264 Main/Constrained Baseline, yuv420p).
**Chromium headless bawaan Playwright di host ini TIDAK punya codec H.264**
(`canPlayType('video/mp4; codecs="avc1..."')` = ""; VP9 = "probably"), jadi
render-test otomatis tidak akan memutar `.mp4` — itu batasan browser uji, bukan
berkasnya. Di Chrome/Firefox/Safari user, videonya jalan normal. Untuk menguji
jalur pemutar tanpa codec H.264, transcode dulu ke VP9:

```
ffmpeg -y -i <klip>.mp4 -t 6 -an -c:v libvpx-vp9 -b:v 900k -vf scale=480:-2 t.webm
```

## Viewer

- `src/server.js` `attachLostSwordFamilies()` menyatukan **satu karakter = satu
  kartu**, dengan semua yang berhubungan masuk ke dropdown **Varian**:
  - model `unit/<base>` (root = "Utama"),
  - kostum/nampan `lobbyunit/<base>[_kostum]`, pet `pet/<base>_01`,
  - dan **video cutscene** karakter itu (`lostsword-video/.../Pc_<Char>_NN`).
  Penggabungan hanya terjadi kalau ada folder unit bernama persis `<base>`,
  supaya kata depan yang sama antar monster berbeda (`goblin_archer`,
  `goblin_king`, `dragon_gold`, `dragon_green`) tidak ikut tergabung. Folder
  unit berisi banyak skeleton (Abyss + kabut + efek, Goblin_Carriage b/u,
  Kraken Far/Mid/Front) juga digabung, dinamai dari stem-nya.
  Hasil: 91 keluarga, 61 di antaranya punya varian video; label duplikat 0.
- `scanVideos()` tetap memindai `assets/lostsword-video/` dan menambah satu model
  ber-`format: "video"` per berkas; berkas disajikan di `/lostsword-video/`
  (range request → bisa di-scrub). Video yang tak punya karakter (`Prologue`,
  `Summon_*`) tetap muncul sebagai entri di tile "Lost Sword — Video".
- `src/video-stage.js` memasang `<video controls>` overlay di `#canvas-wrap`
  dan menambah kelas `is-video` (canvas PIXI disembunyikan — tak ada skeleton).
  `disposeVideo()` melepas + menghentikan unduhan; **wajib** dipanggil saat
  keluar game (`backToGames()`), kalau tidak video 52 MB terus mengunduh dan
  render library tersendat.
- HUD video (`renderHud`) ditangani **sebelum** guard `!spine` — model video
  tidak punya objek `spine`, jadi guard itu akan menyembunyikan HUD-nya.
- Tombol update: `UPDATERS["lostsword-video"]` dengan `noCheck: true` (ekstraktor
  tak punya `--check`); endpoint check mengembalikan `{ok, extractor:true, new:0}`.
