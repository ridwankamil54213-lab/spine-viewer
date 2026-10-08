# Dragon Travelers / 龙魂旅人 — extractor

Paket: **`com.gametree.lhlr.gp`** (GameTree). Versi device: 1.17.0.

## Sumber: device (root tidak diperlukan untuk data dir)

Game memuat aset dari dua tempat; kita ambil **union** keduanya:

1. **`/sdcard/Android/data/com.gametree.lhlr.gp/files/res_update/<dir>/*.b`**
   — konten hot-update yang benar-benar dipakai game berjalan.
   Direktori: `model effect config scene act timeline hotfix ui raw`.
2. **APK split `split_base_assets1.apk`** (352 MB, `assets/res/**/*.b`, 2319
   bundle) — aset bawaan sebagai fallback.
   Path APK ter-obfuscate; resolve dengan `adb shell pm path <pkg>`.

`res_tmp/bundlemap_*.txt` (3,6 MB) **terenkripsi** (header `zip_v2`) — tidak dipakai.
`raw/` = audio/video CriWare (`.awb` AFS2, `.acb` `@UTF`, `.usm`), bukan spine.

## Gotcha: fake header bersarang

Bundel punya header palsu: string `UnityFS` muncul 2–3 kali dan yang **asli
adalah kemunculan TERAKHIR** → pakai `raw.rfind(b"UnityFS")`. Memotong sampai
kemunculan kedua menyisakan header palsu dan UnityPy gagal dengan pesan
menyesatkan *"Position cannot be negative"* (kelihatan seperti enkripsi, bukan).
Tidak ada UnityCN.

## Skeleton: deteksi dari ISI, bukan ekstensi

Skeleton/atlas adalah TextAsset yang **kadang tanpa ekstensi**. Deteksi:
- skel biner → 8 byte hash lalu string versi (`4.1`);
- skel JSON → diawali `{"skeleton`;
- atlas → baris pertama nama halaman `.png`/`.jpg` tanpa `format:`.

Beberapa nama berawalan **`l2d_`** (mis. `l2d_puluomixiusi`) itu **Spine**,
bukan Live2D. Game ini **tidak punya Live2D sama sekali** (0 `.moc3`, 0 library
Cubism, 0 script MonoBehaviour cubism/live2d) — hanya Spine + aset 3D + VFX/UI.

## Pakai

```
python tools/extract-dragontravelers.py --pull     # tarik sumber dari redroid lalu ekstrak
python tools/extract-dragontravelers.py            # ekstrak dari cache /opt/dt
python tools/extract-dragontravelers.py --list     # inventaris saja
```

Env: `DT_PKG`, `DT_ADB` (default `adb -s 127.0.0.1:15555`), `DT_CACHE` (`/opt/dt`).

## Hasil

**26 model Spine** (union APK + res_update), Spine **4.1.23/4.1.24**:

`lihui_*` (shirenmonv, yingjiajianji, huangjiaanwei, lindilingzhu, suoer,
yaojing, qigefei, kaowenguan, plmxs), `haogandu_*` (hela, yingjiajianji_hexie,
zhousi), `shilaimu_*` (gj, battleoverwin), `icon_hero_*` (6), `*_pf01`
(kaowenguan, luoji, moshushi, pinuocao), `DailyAsst_03_ui`, `DailyAsstluoji`,
`acactposter_guofu`, `AvFlyBird_Role(_UAV)`, `loading`, `loading1`,
`spine_ui_*` (jjzl, property_bulunxierde, pveresource_bg_wave).

Beberapa model punya **skin** sensor/tidak (mis. `lihui_yingjiajianji`:
`default / feihexie / hexie`).

## Viewer

Terdaftar di `GAME_ROOTS` sebagai `dragontravelers` (spineRuntime `4.1`,
`pmaDefault: false`). Tombol update muncul lewat `UPDATERS.dragontravelers`
dengan `noCheck: true` + `applyArgs: ["--pull"]` — menekan tombol menarik ulang
aset dari redroid lalu ekstraksi, lalu badge NEW dipasang dari `new_ids`.
