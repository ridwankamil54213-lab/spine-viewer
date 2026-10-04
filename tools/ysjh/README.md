# 异世界后宫物语 (Isekai Harem Monogatari) — Cocos Creator 2.4

Paket: `com.luckystargame.jdxy.ysjh…` (18game build, mirror Divine Throne).
Engine: **Cocos Creator 2.4** (`libcocos2djs.so`). Aset di dalam APK:
`assets/assets/<bundle>/{config.json, import/, native/, index.jsc}` dengan bundle
`resources` (62.8k file), `app`, `main`, `internal`, `sp`, `scripts`.

## Enkripsi

Seluruh berkas di `assets/` dibungkus:

```
prefix = b"GenSanaSneG"     (11 byte, di awal tiap file terenkripsi)
key    = b"mygame!fuck@you~"
```

- **.json / .atlas / .jsc** -> **XOR** berulang dgn key.
- **.png / .jpg** -> **XXTEA** (Cocos xxtea, ukuran kelipatan 4) dgn key sama.
- **.bin** (skeleton) -> **tidak** dienkripsi; itu Spine **biner 3.8.99**.
- **.mp3** -> tidak dienkripsi.

Prefix & key ditemukan langsung di string `lib/arm64-v8a/libcocos2djs.so`
(`strings … | grep -i mygame`). Kalau lain kali tidak ketemu: XOR byte setelah
prefix dgn known-plaintext (`{"paths":{` untuk JSON) untuk memunculkan key.

## Struktur spine

`config.json` (XOR) memberi `paths`/`uuids`/`types` seperti biasa, tetapi:

- `sp.SkeletonData` (2000 entri) -> `import/<xx>/<...>.json` (XOR) + `native/<xx>/<uuid36>.bin` (plain).
- Texture2D ada di `paths` tapi **native-nya tidak memakai uuid tsb**; nama file
  PNG native memakai namespace uuid lain yang **tidak berkorelasi** dengan config.

Jadi tekstur dicocokkan lewat **DIMENSI halaman**: atlas menulis `size: W,H`
untuk tiap halaman, dan `texindex.py` meng-index semua native `.png`
terdekode berdasarkan `WxH`. Satu tekstur boleh dipakai banyak model (jangan
"pakai sekali").

Record `sp.SkeletonData` di import json (format Cocos serialized, array):

```
[ ... , [1, ["<uuid22>"], 0,
  [["sp.SkeletonData", ["_name","_native","_atlasText","textureNames","textures"], -1, 3]],
  [[0,0,1,2,3,4,5]],
  [[0, "<Nama>", ".bin", "<atlasText LENGKAP>", ["<Nama>.png"], [<textures>]]] , ...]
```

`_atlasText` memuat header + semua region atlas; jangan cari file `.atlas` terpisah.

## Alur

```bash
# 1. ekstrak APK
unzip -o ysjh.apk "assets/*" -d x
# 2. index dimensi tekstur
/srv/venv-spine/bin/python tools/ysjh/texindex.py x/assets/assets/resources /tmp/tex.json 8
# 3. ekstrak (skel + atlas + png)
/srv/venv-spine/bin/python tools/ysjh/extract-ysjh.py \
    --assets x/assets/assets --out /opt/spine-viewer/assets/ysjh \
    --packs resources --texindex /tmp/tex.json
```

## Jebakan

- Nama file `native/*.png` memakai format uuid aneh `8-5-5-5-9` dan tidak ada di
  `uuids` config mana pun. Jangan berasumsi cocok; pakai indeks dimensi.
- `textures` di record sering cuma `[0]` (index ke table lain), jadi tidak bisa
  dipakai sebagai uuid; lagi-lagi dimensi atlas adalah kuncinya.
- `import/` dan `native/` punya tabel uuid terpisah; skeleton `.bin` memakai uuid
  dari config (`paths`+`uuids`), sedangkan PNG tidak.
- File `import/<uuid>.json` **bukan** milik aset ber-uuid itu (nama file acak);
  bangun peta `nama -> record` dengan memindai semua import json sekali.

## Hasil

**1999 skeleton, 0 gagal (1 anomali `uieffect_10000` tanpa record), ~1.2 GB**,
Spine **3.8.99**. Kategori: `seffect` 935, `uieffect` 502, `sanim` 166,
`sbody` 150, `sstay` 149, `sbuff` 89, `shgame` 9.
