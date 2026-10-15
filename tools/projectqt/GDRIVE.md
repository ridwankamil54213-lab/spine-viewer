# Project QT — model dari Google Drive

Folder `assets/projectqt/` diisi **utuh dari Google Drive**
(folder id `1HmKSMyHrXmkIvQqwevDmtjVM8n3FR0Kz`), menggantikan 1323 model lama
yang seluruhnya `.skel` biner 2.1.27 (harus konversi dulu, dan hasilnya tak bisa
dirender runtime 3.8/4.x).

## Cara mengambil

```bash
rclone copy "saf:" assets/projectqt.new \
  --drive-root-folder-id 1HmKSMyHrXmkIvQqwevDmtjVM8n3FR0Kz \
  --transfers 16 --checkers 16 --drive-chunk-size 32M
rm -rf assets/projectqt && mv assets/projectqt.new assets/projectqt
rm -f data/models-cache.json          # paksa cold scan
systemctl restart spine-viewer.service
curl -s "http://127.0.0.1:3000/api/models?refresh=1" > /dev/null
```

JANGAN unduh ke `/tmp` — di host ini `/tmp` adalah **tmpfs 7.7 GB** dan isinya
4,67 GB. Unduh langsung ke `assets/`.

## Isi Drive

| | |
|---|---|
| folder | 1863 (lama: 1316) |
| berkas | 5627 (`.json` 1833, `.png` 1863, `.atlas` 1863) |
| ukuran | 4,67 GiB |
| tiap folder | `<nama>.json` + `<nama>.atlas` + `<nama>.png` |

## Hasil di viewer

- **1863 model** (lama 1323), total viewer 38.018.
- **1795 model Spine 3.8.99** — dimuat langsung pixi-spine (tanpa iframe legacy).
  Diuji render acak **12/12 OK, 0 error**.
- **68 folder masih 2.1.27**, terbagi:
  - **38 punya sibling `.json`** → viewer memakai `.json` itu di jalur kanvas 2.1
    (`loadLegacyModel` memilih sibling bila `skeletonFile` = `.skel`), render OK.
  - **29 hanya `.skel` biner** (Drive tidak menyertakan JSON-nya) → tampil pesan
    "Jalankan tools/convert-spine2.py" (memandu, bukan crash). Konversi butuh
    converter eksternal SpineConverter2.1.27 (lihat `tools/convert-spine2.py`;
    parser bawaan hanya ~8% berhasil pada Project QT).

## Catatan jebakan

- **`.gitignore`: `assets/*`** — 4,7 GB ini TIDAK ikut git. Backup ke Drive
  (folder yang sama) adalah salinannya.
- Folder Drive menyertakan `.json` 2.1 untuk 38 model **beserta** `.skel`. Pairer
  server (`pairSkeletonAtlas`) sengaja memilih `.skel` (benar untuk BD2, yang
  JSON-nya tanpa animasi), karena itu perbaikan sibling-.json dilakukan di
  `loadLegacyModel` (viewer), bukan di pairer — supaya BD2 tidak ikut berubah.
- Dua `rclone copy` pertama gagal/terhenti karena `/tmp` tmpfs; yang benar
  menulis ke `assets/projectqt.new`.
