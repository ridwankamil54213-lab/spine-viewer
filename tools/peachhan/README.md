# FREYA 夢姬 / Dream of Freya — CDN terbuka `asset.peachhan.com`

Game **FREYA 夢姬 / Dream of Freya** (developer **LSJGAME**, genre Bishōjo RPG
ADV). Alias yang dipakai tool: `梦娘 \ 幻姬 \ 梦姬 \ 少女总裁 \ Dream of Freya`.
Diambil dari CDN **`asset.peachhan.com`** — sumber CDN + alias game ditemukan dari
hasil bongkar `二游资源工具.exe` (lihat `tools/game-cdn-list.md`). **CDN-nya
TERBUKA** — tanpa login, tanpa signed URL.

## Manifest
```
https://asset.peachhan.com/mgameasset/m1productionasset/Android/version.json
  -> { "version": 861,
       "assetBundleMetadatas": { "<key>": {"hash":"...","fileSizeInMB":..,"dependencies":[]}, ... } }
```
Tiap `<key>` diunduh apa adanya (TANPA ekstensi): `…/Android/<key>` → UnityFS.
Bucket lain: `m3productionasset`, `amgameasset`, `m5gameasset` (game berbeda).

## Layout bundle (spine)
Satu bundle = satu folder model, isinya TextAsset + Texture2D:
```
herospine/<id>      -> <skel>.skel / .atlas / .png  (+ <id>_CG1, _CG2 = VARIAN CG)
spineasset/<name>   -> stand_boss.skel / .atlas / .png
battle/effectspine/<id>
```

## Pakai
```bash
/srv/venv-spine/bin/python tools/peachhan/extract-peachhan.py          # herospine+spineasset+effectspine
/srv/venv-spine/bin/python tools/peachhan/extract-peachhan.py herospine/78 herospine/8   # subset
```
Keluaran: **181 bundle → 281 model** di `assets/peachhan/` (860 MB; Spine 4.0.64).

## ⚠️ Jebakan WAJIB: TextAsset biner
`obj.read().m_Script` mengembalikan `str` dan **MERUSAK** `.skel` biner — byte
>= 0x80 berubah jadi `?` (`2b 19 3f 3f…` alih-alih `2b 19 96 8d…`) sehingga
viewer gagal parse. Selalu:
```python
nm, data = parse_text_asset(obj.get_raw_data())   # byte apa adanya
```
(layout TextAsset: int32 name_len / name align4 / int32 size / data).
Bug ini sempat muncul di sini: model terdaftar & punya animasi (parser server
menoleransi) tetapi GAGAL render di browser karena skeletonnya korup.

## Catatan
- 2 bundle pertama sempat `http 000` (transient) — jalankan ulang dengan prefix
  spesifik (`extract-peachhan.py herospine/78 herospine/8`) untuk melengkapinya.
- Nama game dikonfirmasi dari (a) blok alias UTF-16 di `二游资源工具.exe`
  (`梦娘\幻姬\梦姬\少女总裁\Dream of Freya`) yang letaknya TEPAT sebelum URL
  peachhan, dan (b) ikon `EventIcon_FreyaHub` di bundle. Nama resmi (QooApp):
  **FREYA 夢姬**, developer **LSJGAME**.
