# 白夜极光 / Alchemy Stars — `com.tencent.baiyeint`

SRPG bintang (Tencent). Unity **2019.4.40f1**.

## Format

XAPK → dua image **FAT32** (`main.obb` 2,0 GB + `patch.obb` 1,6 GB) di bawah
`Android/obb/com.tencent.baiyeint/`. OEM name boot sector = `fat32lib`: ini
bukan zip, melainkan disk image FAT32 biasa.

```bash
losetup /dev/loop6 main.obb
mount -t vfat -o ro /dev/loop6 /mnt/obb
```

Isinya `*.bundle` bernama deskriptif `<md5>@<nama>.bundle`. Yang ber-spine:
`*_spine_idle_prefab.bundle`, `*_spine_cg_idle_prefab.bundle` (211 di main,
158 di patch). Tiap bundle = Spine lengkap: TextAsset `.skel` + `.atlas` +
Texture2D (2048x2048). **Tidak ada enkripsi.**

## Pakai

```bash
# mount kedua obb, lalu:
/srv/venv-spine/bin/python tools/alcherystars/extract-alchemy.py /mnt/obb  /opt/games/alchemy_out
/srv/venv-spine/bin/python tools/alcherystars/extract-alchemy.py /mnt/obb2 /opt/games/alchemy_out2
# gabung (nama tak bentrok; patch menang kalau ada):
cp -rn alchemy_out/* alchemy_out2_merged ...   # atau copy manual
```

Hasil: **328 model** (main 185 + patch 143), Spine **3.8.94/3.8.99**, semua
ber-tekstur. Di viewer: `assets/alcherystars/<Nama>_spine_idle/`.

## Jebakan

- OBB bukan zip — `7z`/`unzip` gagal; harus FAT32 (loop mount atau pyfatfs).
- Tekstur 2048x2048 besar → stream ke disk (`_texcache/`), jangan tahan di RAM
  (kalau tidak, OOM exit 137 pada ~200 model).
- Live2D game ini (~1500 di blog wdream) TIDAK ada di OBB XAPK — game
  mengunduhnya saat runtime ke `move1`/`move2`. Hanya spine yang ikut di XAPK.
