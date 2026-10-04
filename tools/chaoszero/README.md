# Chaos Zero Nightmare (卡厄斯梦境) — Yuna engine extraction

Smilegate **Yuna engine** (sama seperti 第七史诗 / Epic Seven), bukan Unity/Cocos.
Aset Android ada di dalam **SSRArchive** — bukan `data.pack` (itu versi PC):

```
/sdcard/Android/data/com.smilegate.chaoszero.stove.google/files/gameres/
    manifest.ssra          (~7.5 MB, indeks 87.529 file)
    chunks/*.ssrc          (~8.1 GB, konten terpotong)
```

Spine di sini bukan Spine biasa:
- Skeleton = **`.scsp`** (binari kustom Yuna, dibungkus LZ4), bukan `.skel`/`.json`.
- Halaman tekstur = **`.sct`/`.sct2`** (LZ4 + ASTC/ETC2), bukan PNG.
- `.atlas` standar, tapi menyebut halaman `.sct` (bukan `.png`).

Ketiganya dikonversi offline oleh tool di folder ini, jadi viewer hanya melihat
`.json` + `.atlas` + `.png` biasa.

## Alur

```bash
# 0. tarik data dari perangkat (adb, non-root; ~8 GB dari localhost cepat)
adb -s 127.0.0.1:15555 pull \
  /sdcard/Android/data/com.smilegate.chaoszero.stove.google/files/gameres /opt/czn/gameres

# 1. bangun scsp2json (SCSPParser.cpp + nlohmann json; tanpa SDL/astc)
bash tools/chaoszero/build-scsp2json.sh        # -> /opt/czn-work/scsp2json

# 2. ekstrak (SSRA -> scsp/atlas/sct -> json/atlas/png)
/srv/venv-spine/bin/python tools/chaoszero/extract-czn.py \
    --manifest /opt/czn/gameres/manifest.ssra --convert /opt/czn-work/scsp2json \
    --out /opt/spine-viewer/assets/chaoszero --filter model/ --workers 8
# ... ulangi dgn --filter face/portrait/ (dan kategori lain bila perlu)
```

`--filter` adalah prefix path arsip; hasil ditulis `<out>/<prefix><nama>/`.

## Format

**SSRA** (`ssra.py`): header 64 B (`"SSRA"`, versi, jumlah chunk/file, offset
tabel). Chunk table 32 B, file table 40 B (`is_compressed`, `is_encrypted`).
Tabel string + blok **GRPS** (nama grup: `base`, `lang_en`, `bin_arm64`, …).
Konten chunk dipakai sebagai ruang virtual per grup; `chunk_file_off` = offset
global dalam grup.

**SCSP** (`SCSPParser.cpp`): LZ4-blok (prefix `[u32 dec_len][u32 comp_len]`) →
header 0x62 B dengan magic `scsp`, tabel string, lalu bones/slots/IK/skins/
animations dalam layout binari Yuna. Dikonversi ke JSON Spine 3.8.79.

**SCT** (`sct.py`): SCT2 header 36 B; `data_offset`; data LZ4-blok (prefix sama)
→ piksel: `40`=ASTC 4x4, `47`=ASTC 8x8, `44`=ASTC 6x6, `19`=ETC2_RGBA8,
`17..26`=RGBA, `4/16`=RGB565, `6`=RGB, `102`=L8. ASTC lewat `texture2ddecoder`
(`decode_astc`), lalu **tukar kanal R/B**.

## Jebakan

- **Chunk fisik TIDAK 1:1 dengan `chunk_id` manifest.** Game memecah chunk besar
  (`base_b13_0` + `…_1`) dan menggeser nama entri berikutnya. Pasangan yang benar:
  urutkan chunk manifest per grup (menurut `chunk_id`) dan file `.ssrc` per grup
  (natural sort), lalu zip posisi demi posisi.
- Nama grup wajib dibaca dari blok **GRPS**; tanpa itu file `.ssrc` tak bisa
  dipetakan (dan hanya cocok lewat ukuran, yang ambigu).
- Aset bahasa (`local/<kode>/…`) berada di grup lain (`lang_*`) sehingga butuh
  chunk bahasa; untuk model/efek cukup grup `base`.
- `texture2ddecoder.decode_astc` mengembalikan BGRA → swap R/B.
- SCT tidak selalu LZ4 (cek ukuran vs harapan; kalau sama, datanya mentah).

## Hasil

`model/` **1292** karakter + `face/portrait/` **235** = **1527 model, 0 gagal
(9.3 GB)**, Spine **3.8.79** (kustom Yuna). Spine dirujuk langsung ke
`assets/chaoszero/`, game `chaoszero`.
