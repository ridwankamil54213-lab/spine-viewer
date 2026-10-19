# Sailor Girl (DMM) — id 9970

Spine 4.0.64, **107 model**, tanpa login, tanpa enkripsi.

## Sumber

URL berasal dari string table `二游资源工具.exe` (tool .NET 4 MB, **bukan**
`resdownloader.exe` — dua tool berbeda, lihat catatan di bawah).

```
https://sailor-dev-dmm-sp.oss-ap-southeast-1.aliyuncs.com/sailorgirl_unity/android_ex/v7.0/
    PackageManifest_PackageEx_2026-06-11-890.bytes    (112 KB, YooAsset "OOY")
    {md5}.bundle                                      (satu bundle per model)
```

Bucket Aliyun OSS **terbuka**. Tidak ada signed URL, tidak ada XOR, tidak ada
fake header.

## Aturan penamaan bundle (penting)

Manifest YooAsset mencatat nama logis bundle
(`packageex_assets_resex_spine_role_r001_tryst.bundle`) **dan** md5-nya, tapi
file di CDN disimpan dengan nama **`{md5}.bundle`**. Memakai nama logis → 404.
Memakai `{md5}.bundle` → 200.

Pasangan (nama, md5) diambil dengan mencari md5 terdekat **sebelum** nama bundle
di blob manifest. Ini lebih tahan perubahan versi manifest daripada memaksakan
skema protobuf.

## Isi bundle

Setiap bundle berisi:

| Objek | Isi |
|---|---|
| `TextAsset` #1 | `<model>.json` — skeleton Spine JSON (1–5 MB) |
| `TextAsset` #2 | `<model>.atlas` — atlas teks, 1–3 halaman |
| `Texture2D` 1–3 | halaman atlas 2–4 K persegi |

Perhatikan: **nama folder model tidak selalu sama dengan nama file di dalam
bundle.** Contoh: folder `R002_TRYST` berisi `R001_Tryst.png`,
`R002_TRYST.json`, dan atlas yang menunjuk ke `R001_Tryst.png`. Ekstraktor harus
menamai PNG sesuai nama **di dalam bundle**, bukan sesuai nama folder, kalau
tidak atlas akan menunjuk ke halaman yang tidak ada.

## Pipeline

`/opt/sailorgirl/extract.py` — parse manifest → unduh `{md5}.bundle` → ekstrak
TextAsset + Texture2D ke `assets/sailorgirl/<MODEL>/`.

```bash
/srv/venv-spine/bin/python /opt/sailorgirl/extract.py            # semua
/srv/venv-spine/bin/python /opt/sailorgirl/extract.py --limit 3  # uji
```

Hasil terverifikasi: **107/107 model lengkap**, 0 gagal unduh, 488 MB.
Semua Spine 4.0.64, 73–324 tulang, animasi `idle`/`touch`/`rags`.

## Viewer

`src/server.js` `GAME_ROOTS`:

```js
{ match: "sailorgirl", key: "sailorgirl", label: "Sailor Girl (DMM)", spineRuntime: "4.0" }
```

`spineRuntime: "4.0"` wajib — kalau tidak, runtime default 4.1 dipakai dan
model 4.0.64 ditolak.

Terverifikasi render di browser: runtime 4.0, `Spine 4.0.64`, 223 tulang,
6 animasi, 0 error konsol.

## Dua tool yang sering tertukar

| | 二游资源工具 | resdownloader |
|---|---|---|
| Ukuran / teknologi | 4 MB, .NET (Costura) | 98 MB, PyInstaller + Cython `pyd` |
| Backend | 174 URL hardcoded, 102 host | SpineGods `1919810.store` |
| Sumber Sailor Girl | ✅ ya | tidak |
| King of Kinks | ❌ tidak ada | ✅ ya (`kokresdownloaderp`, id 9981) |

`二游资源工具.exe` adalah sumber daftar CDN di `game-cdn-list.md`. Probe 168
endpoint: **72 hidup** — lihat `eryou-endpoints.md`.
