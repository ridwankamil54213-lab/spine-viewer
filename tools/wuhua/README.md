# 物华弥新 / Neo Artifacts — `com.cipaishe.wuhua.google`

Puzzle-artifact SRPG (Dragonest / 长游). Unity **2018.4.36f1**. Aset spine ada di
**Play Asset Delivery** `SmallPack1.apk` + `SmallPack2.apk` (bukan base APK).

## Format

Isi pack: `assets/bundles/<hash>.ab`. Tiap `.ab` adalah **UnityFS** yang
**blok datanya ter-XOR** — UnityPy sendiri hanya bilang "Decompression failed".
Metodenya dibocorkan di forum **live2dhub topik #5896** (`物华弥新解密逻辑求助`):

```
key = data[51]
XOR data[50:end] ^= key        # 50 tetap; `end` berubah antar versi game
```

`end` dicari per-berkas dengan UnityPy sebagai **oracle** (`tools/wuhua/extract-wuhua.py`
mencoba `end` 60..259 sampai bundle bisa dimuat). Untuk v1.5.0 semuanya `end=122`.

Setelah ditemukan, bundle memuat `TextAsset` ber-**nama asli**:
`KV.skel` / `KV.atlas`, `2.1kv.skel`, `huazhaojie.atlas`, dst — dan `Texture2D`
(biasa, BUKAN ASTC; Unity men-decode sendiri lewat `obj.read().image`).

## Isinya apa

- **36 Spine** (`.skel`+`.atlas`), semuanya **KV / splash art** (Spine **3.8.95**):
  `KV`, `KV002`, `KV2202`, `KVHH`, `KVSSSX`, `KVDQHY`, `KV_GJBZ`, `KVYZCA`,
  `1.9shang_kv`, `2.0shang_kv`, `2.1kv`, `2.2kv`, `kv_1.7niulong`,
  `banzhounianKV`, `huazhaojie`, `obkv`, `pipaPV`, `yinyoukv`, `logo`, + varian `_bg`.
- Bundle lain: 118 Shader, 1534 Lua script, 43 font, 1133/1534 TextAsset config,
  audio mixer. **Karakter/artefak tidak ada di pack** — game mengunduh model dari CDN
  (`resVersion r310`, `smallPack: true`) saat runtime. Menambahnya butuh login +
  pemetaan CDN.

## Pakai

```bash
# XAPK resmi (APKPure). SmallPack1 = 171 MB, SmallPack2 = 19 MB
curl -L -o wuhua.xapk "https://d.apkpure.net/b/XAPK/com.cipaishe.wuhua.google?version=latest"
unzip -q wuhua.xapk -d pack
unzip -q pack/SmallPack1.apk -d /tmp/wh1
unzip -q pack/SmallPack2.apk -d /tmp/wh2
/srv/venv-spine/bin/python tools/wuhua/extract-wuhua.py --pack /tmp/wh1 --out assets/wuhua
```

Keluaran: `assets/wuhua/<Nama>/{<Nama>.skel,<Nama>.atlas,*.png}`.

## Jebakan

- `decrypt()` dijalankan dengan **stderr dibungkam** (`mute_fd2()`): UnityPy
  mencetak "Error parsing file ..." untuk tiap kandidat `end` yang salah →
  ratusan ribu baris kalau tidak di-suppress.
- Semua `.ab` **harus** di-XOR dulu; jangan coba UnityFS langsung (gagal).
- Tekstur = PNG biasa, bukan ASTC (beda dgn Divine Throne / Neo Artifacts? cek
  lagi kalau game berubah). Jangan decode manual — pakai `obj.read().image`.
- 10 dari 36 model (varian `_bg`) tidak kebagian PNG: halaman atlas-nya tidak
  ada di pool tekstur bundle. Sisanya lengkap.
