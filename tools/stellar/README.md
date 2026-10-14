# Stellar Valkyries (jjw / yds) — Cocos2d-x Lua

Game adult (YouDianSe, id 632). Engine **Cocos2d-x Lua** (`libcocos2dlua.so`).

## Sumber

APK dari halaman YouDianSe detail 632 (CloudFront signed URL). Semua aset
spine **plain di dalam APK** (tanpa bundling):

```
assets/res/spine/<id>/<name>.{skel,atlas,png}          # model tunggal
assets/res/spine/<id>/<scene>/{skeleton.skel,atlas,png} # karakter dgn beberapa CG
```

- `.skel`  = Spine **BINARY 4.1.24**, TIDAK terenkripsi (dipakai apa adanya).
- `.atlas` = teks biasa, TIDAK terenkripsi.
- `.png`   = **TERENKRIPSI**.

## Enkripsi PNG: header "abcgame" + XXTEA

Tiap PNG berawalan 7 byte `abcgame` lalu data XXTEA (di-set lewat
`LuaStack::setXXTEAKeyAndSign` di libcocos2dlua.so / dipanggil dari Lua).

**Skema dekripsi** (diverifikasi: hasilnya berawalan `\x89PNG`):

```python
key  = b"wX34UsTVXt4RezWe"
data = xxtea.decrypt(raw[7:] + pad, key, padding=False)  # pad ke kelipatan 4
```

Kuncinya **sama** untuk game yang memakai header `abcgame` (mis. 天姬契约,
op-18, dll) — ditemukan dari forum **live2dhub** (topics 4772/5359: "xxtea
签名:abcgame 密钥:wX34UsTVXt4RezWe"). Kunci TIDAK ada di `.so`/`.dex`
(brute-force 150k string gagal) karena diset dari sisi Lua/Java saat runtime.

Tanpa dekripsi: browser menolak PNG ->
`InvalidStateError: The source image could not be decoded`,
viewer bilang "Halaman atlas 'skeleton.png' tidak ditemukan".

## Pakai

```bash
# 1. unduh APK dari YouDianSe detail 632 (URL CloudFront bertanda-tangan)
# 2. ekstrak + dekripsi PNG
/srv/venv-spine/bin/python tools/stellar/extract-stellar.py
```

Keluaran: **1242 model** di `assets/stellar/` (`.skel` + `.atlas` + PNG
terdekripsi). Di viewer: root `stellar`, label "Stellar Valkyries".

## Varian

Sebagian karakter mengirim beberapa CG sebagai **subfolder**
(`stellar/<id>/cg1_spine1 … cg1_spine4`). Folder container BUKAN model, jadi
aturan family khusus di `attachFamilies()` (`svGroups`) mengelompokkannya:
1 family per container, scene pertama = "Utama".

## Catatan

- 8 karakter punya varian (3–6 CG); 1234 sisanya model tunggal.
- Jebakan: menaruh skrip bernama `inspect.py` di direktori kerja membuatnya
  membayangi modul stdlib `inspect` -> `PIL`/`dataclasses` gagal impor.
