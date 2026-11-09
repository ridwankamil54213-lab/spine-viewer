# Craving Quest / Lusty Odyssey — pak komunitas Live2DHub

Sumber: <https://live2dhub.com/t/topic/4791> — "【绅士冒险】spine文件分享" oleh
`yaoyi` (2025-06). Dua tautan Baidu (提取码 `star`): CG karakter dan HCG. Yang
diimpor ke sini **HCG**-nya (`动态HCG.rar`, 244 MB).

Password arsip (kedua lapis, tertulis di topik): `bilibili@耀依永恒`
— bukan `star`, itu kode ekstrak Baidu.

## Isi pak

81 folder karakter → 79 model. Tiap folder = satu CG H beranimasi:
`.skel`/`.prefab` + `.atlas` + `.png`, plus `desktop.ini` dan konfigurasi
**Live2DViewerEX** (`{A,B,C,D}-*.json`, `type: 9`, `change_cos` per kostum).
Konfigurasi ViewerEX **tidak** diimpor — viewer ini memakai nama animasi dari
skeleton (`01`–`04`).

- 35 folder: skeleton `.skel` biner (Spine 3.8.55, dua model 3.8.99).
- 44 folder: skeleton **Spine JSON** yang disimpan ber-ekstensi `.prefab`.
  Isinya JSON asli (`{"skeleton":{"spine":"3.8.55"},...}`), bukan prefab Unity —
  jadi cukup di-rename jadi `.json`.
- Atlas tanpa baris `pma:`; texel transparannya hitam bersih (bukan sisa warna
  putih seperti 蜜桃乌托邦), jadi PMA dibiarkan Auto.

## Langkah impor

```bash
aria2c "https://d.pcs.baidu.com/file/..." --out "动态HCG.rar" \
    --header "User-Agent:pan.baidu.com"
python3 tools/lustyodyssey/prepare-pack.py \
    --src 动态HCG.rar \
    --assets assets \
    --names data/lustyodyssey-names.json
```

Lalu tambah `GAME_ROOTS` (`src/server.js`) + ikon di
`public/thumbs/_game/lustyodyssey.png`, dan restart service.

## Jebakan yang sudah ketemu

1. **Password zip harus byte GBK.** Arsipnya dibuat di Windows dengan password
   Tionghoa, jadi `7z` membandingkan byte GBK — `-p'bilibili@耀依永恒'` dari shell
   UTF-8 dijawab "Wrong password" walau RAR luarnya terbuka. Kirim byte-nya
   langsung (`"…".encode("gbk")`), bukan `str`.
2. **Nama folder wajib ASCII.** Klien membangun URL aset dari `model.id`, dan id
   itu path relatif yang sudah disanitasi (`[^\w.\-/]` → `-`). Folder full
   Tionghoa runtuh jadi `-A-D` untuk puluhan model: id duplikat, atlas 404.
   Nama aslinya dipulihkan lewat `data/lustyodyssey-names.json` +
   `applyLustyNames()` di `src/server.js`.
3. **Nama skeleton harus sama dengan atlas.** Pak ini menyimpan beberapa berkas
   sebagai `e008_03.atlas #44` / `Skeleton.atlas #13087` (sisa alat ekstrak
   penulis), yang membuat pasangan skeleton↔atlas tidak ketemu — suffix itu
   dibuang.
4. **Atlas halaman kedua.** Satu folder ("安[幻流霜回雪]…") punya dua atlas
   dengan nama dasar sama; yang diimpor hanya halaman pertama yang disebut
   skeleton, sisanya ikut tersalin tapi belum pernah dipakai.
