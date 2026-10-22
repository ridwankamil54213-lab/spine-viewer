# PokerFate / 扑克命运 — updater aset Spine

Game: [pokerfate.com](https://www.pokerfate.com/) · APK: `https://aws.poker-fate.com/dl/PokerFate_Android.apk`

Pipeline ini mengekstrak model Spine dari APK resmi. Semua tahap berjalan
lokal — tidak ada endpoint game yang dipanggil, tidak ada kredensial, dan
tidak ada berkas yang diunggah ke mana pun.

## Menjalankan

```bash
# APK sudah ada di /opt/games/pokerfate/PokerFate_Android.apk
python3 tools/pokerfate/update-pokerfate.py

# atau unduh ulang APK dulu
python3 tools/pokerfate/update-pokerfate.py --download

# simpan direktori kerja untuk diperiksa
python3 tools/pokerfate/update-pokerfate.py --keep-temp

# ekspor saja, jangan pasang ke assets/
python3 tools/pokerfate/update-pokerfate.py --skip-publish
```

Butuh: `UnityPy`, `lz4`, `Pillow` (sudah ada di `/srv/venv-spine`), dan `7z`.

Waktu jalan: ~25 menit (dekripsi 1,4 GB + ekspor 529 bundle).

## Empat jebakan yang sudah ditangani

### 1. Bundle dibungkus header `XENC`

Berkas di `assets/aa/Android/` tidak dimulai dengan `UnityFS`, jadi AssetStudio
dan UnityPy menolaknya. Formatnya `XENC (4B) + nonce (16B) + ciphertext`, dengan
keystream XOR yang **diderivasi ulang tiap 64 byte**:

```
n64   = LE64(nonce[0:8]) ^ LE64(nonce[8:16])
m     = mix(n64)                      # splitmix64 dua langkah
seed  = m ^ (m >> 31) ^ S
state = seed - blok * C               # pengurangan, bukan penjumlahan
xorshift(13, 7, 17); ambil state & 0xFF tiap byte
```

`S = 0xAF3E40196CB07413`, `C = 0x61C8864680B583EB`, diturunkan dari
`GameAssembly.dll` versi 2026-10.

**Konstanta terikat versi.** Kalau APK diperbarui, dekripsi akan menghasilkan
sampah. `decrypt.py` memverifikasi hasilnya (header `UnityFS` + field ukuran
masuk akal) dan berhenti dengan pesan jelas, bukan melanjutkan diam-diam.

### 2. `m_Script` merusak data biner

Ini bug yang paling lama tidak ketahuan. Di UnityPy, `TextAsset.m_Script`
dideklarasikan sebagai `str`, jadi isinya sudah didekode UTF-8 dengan
`errors="replace"` — **setiap byte >0x7F yang bukan UTF-8 valid berubah menjadi
`?` (0x3F)**.

Terukur pada `1001_1.skel`: byte >0x7F turun dari **30,3% menjadi 0,6%**. Model
tetap "terbuka" tapi runtime melempar `name cannot be null` atau
`boneData cannot be null`, karena panjang string yang dibaca salah.

Solusinya membaca ulang byte mentah dari serialisasi objek:

```
m_Name     : int32 len + bytes + align(4)
m_Script   : int32 len + bytes + align(4)   <-- yang dipakai
m_PathName : int32 len + bytes + align(4)
```

Untuk `.atlas` (teks) `m_Script` aman; untuk `.skel` (biner) tidak.

### 3. Atlas memakai kunci non-standar

PokerFate menulis `bounds`/`offsets`, Spine mengharapkan
`xy`/`size`/`orig`/`offset`/`index`. Tanpa konversi, model terbuka tapi tampak
"kurang bagian" karena Spine mengabaikan kunci yang tidak dikenal.

**Rotasi:** `bounds: x,y,w,h` adalah kotak yang benar-benar ditempati di halaman
(sudah memperhitungkan rotasi), jadi `size` yang ditulis harus **ditukar untuk
semua `rotate != 0`**. Ini ditentukan dengan mengukur, bukan menebak — pada
atlas `1015_1` (188 region, halaman 2048×2048):

| Perlakuan | Region keluar batas |
|---|---|
| tanpa tukar | 5 |
| tukar hanya 90/270 | 2 |
| tukar hanya 180 | 3 |
| **tukar semua `rotate != 0`** | **0** |

Kalau salah, gejalanya `Texture Error: frame does not fit inside the base
Texture dimension`.

### 4. Satu bundle bisa memuat beberapa model

Bundle `1001_3` memuat **empat** model berbeda: `1001_3_bishaji`, `1003_03`,
`1003_03_cat`, `1003_03_huaban`. Kalau semuanya ditulis ke satu direktori,
server memilih `.skel` pertama dan memasangkannya dengan atlas yang salah.

Exporter menulis **satu direktori per batang nama `.skel`**, dan atlas
dipasangkan berdasarkan batang nama yang sama.

## Hasil

| | |
|---|---|
| Bundle di APK | 529 |
| Bundle berisi Spine | 75 |
| Model diekspor | 178 |
| Ukuran di `assets/` | 427 MB |
| Runtime Spine | 4.1.24 |

454 bundle sisanya berisi tekstur, CG, dan audio — sudah diverifikasi dengan
memindai ulang semuanya, bukan diasumsikan.

## Berkas

| Berkas | Fungsi |
|---|---|
| `decrypt.py` | Buka bungkus XENC |
| `convert_atlas.py` | Atlas kustom → format Spine standar |
| `export_spine.py` | Bundle → `.skel`/`.atlas`/`.png` |
| `update-pokerfate.py` | Orkestrasi: unduh → ekstrak → dekripsi → ekspor → pasang |

## Lisensi dan etika

Skrip ini hanya memproses berkas yang kamu peroleh sendiri secara legal, untuk
belajar dan arsip pribadi. Jangan gunakan untuk komersial atau menyebarkan ulang
aset aslinya. Dukung versi resminya.
