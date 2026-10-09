# 钢岚 / Mecharashi — `com.tentree.gp.mecharashi`

RPG taktis mecha (Ten Tree / 紫龙). **Unity 2020.3.49f1**. Semua model spine ada di
dalam APK (tidak perlu emulator / hot-update).

## Format

XAPK (APKPure) → `base_assets.apk` (1.86 GB) → `assets/ExportAssetBundle/*.b`
(**674 bundle**, ~1,6 GB). Nama bundle deskriptif: `pilot_pilotb00_abs.b`,
`mecha_wap_*`, `scenes_*`, `ui_*`, dll.

Header tiap `.b` **valid `UnityFS`** (versi `2020.3.49f1`) — tapi blok datanya
**terenkripsi UnityCN**. UnityPy sendiri bilang:

```
The BundleFile is encrypted, but no key was provided!
```

### Kunci

Kunci UnityCN ada di blog wdream / forum Live2DHub (hex string):

```
31433743463543423144313841304630      <=>  bytes 1C 7C F5 CB 1D 18 A0 F0
```

Pakai:

```python
import UnityPy
UnityPy.set_assetbundle_decrypt_key(bytes.fromhex("31433743463543423144313841304630"))
```

Catatan: `set_assetbundle_decrypt_key` butuh **16 byte** (bytes), bukan string hex
32-char — string hex akan ditolak ("Key length is wrong ... now is 32 bytes").

### Isi bundle

Tiap `pilot_*` memuat Spine lengkap: `.skel` (Spine **3.8.76**) + `.atlas` +
`Texture2D`. Setelah dekripsi, TextAsset sudah punya nama asli
(`Pilot_AdaDiazB.skel`, `Pilot_AdaDiazB.atlas`), jadi tinggal dicocokkan.

## Pakai

```bash
curl -L -o mecha.xapk "https://d.apkpure.net/b/XAPK/com.tentree.gp.mecharashi?version=latest"
unzip -q mecha.xapk -d mecha_ex
unzip -q mecha_ex/base_assets.apk "assets/ExportAssetBundle/*" -d mecha_b
/srv/venv-spine/bin/python tools/mecharashi/extract-mecharashi.py \
    --pack mecha_b/assets/ExportAssetBundle --out assets/mecharashi
```

Keluaran: **125 model** — `Pilot_<Nama>` (58, animasi Normal/Random/Touch1/Touch2)
+ varian `Pilot_<Nama>_CT` (cutin/ultimate) + `FridaGarcia_cutin`,
`Matilda_cutin`, dan `Pliot_Cassha` (typo bawaan game — blog menyebutnya juga).

## Jebakan

- **OOM**: bundle `pilot_*` punya tekstur 2048x1024 besar; decode ribuan
  `Texture2D` sekaligus menghabiskan RAM (proses ke-kill exit 137). Solusi:
  tulis setiap tekstur ke disk saat ditemukan (cache `_texcache/`) dan jangan
  tahan gambar di memori.
- 642 dari 674 bundle diproses (yang lain bukan bundle spine / gagal dekripsi).
- 125 model valid (skel+atlas+png lengkap).
