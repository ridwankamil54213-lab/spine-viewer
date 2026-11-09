# 欲洛降临 (EroEra) — `youdianse.com/game/detail/456`

Sumber: **Unity GameFramework hotupdate CDN** yang ditemukan dari `BuildInfo` di dalam APK (`eroera_20261013_V0.1.64.149_prod.apk`):
- `CheckVersionUrl`: `https://res-01.eepgames.com/buildCfg/0_1_64/Android/Version.txt` (fallback `res2.eepgames.com`, plus deteksi otomatis kenaikan versi dari `https://www.youdianse.com/game/detail/456`).
- `UpdatePrefixUri`: `https://res-01.eepgames.com/hotupdate/0_1_64/Android/`
- `GameFrameworkVersion.<hash8>.dat` (`VersionListHashCode & 0xffffffff`, gzip → `GFU\x02` binary version list: 245 resource bundle, 3.968 aset).

## Arsitektur & Ekstraksi (`tools/eroera/refresh.py`)

1. **Unduh selektif tanpa perlu mengunduh APK 641 MB**:
   Hanya mengunduh 75 bundle `Spine/*` (`Spine/Pet/Pets` + `Spine/Role/*`), `TbData/TbDatas` (`LoadType = 2` QuickDecrypt: 220 byte pertama di-XOR `struct.pack("<I", hash_code)`), dan `SpriteAtlas/Packs/Hero` ke `/srv/spine-assets/eroera/bundles/` (~258 MB total).
2. **174 model Spine (4.1.23 / 4.1.24)** di `assets/eroera/<slug>/`:
   - 30 karakter Hero (`hero_10001`..`hero_10030`) beserta varian:
     - `Utama` (`stand` / `00`)
     - `H Scene — Base (初级)` (`200XX/base`)
     - `H Scene — Adv (高级)` (`200XX/adv`)
     - `Interaction (调教)` (`400XX`)
     - `Activity — Show/Action/End/Click/FX` (`20001_b/*` untuk `10013` 沈小钰)
     - `Aim`, `Cover`, `Skill Cut`, `Skill Cut 2` (`r00X_h/*`, `z100XX_h/*`, `z100XX/*`)
   - 10 Pet (`pet_huoyanfeie`, `pet_haita`, `pet_leaves`, `pet_shuimu`, `pet_yanshitu`, `pet_huo`, `pet_weasel`, `pet_erkuohu`, `pet_niao`, `pet_long`).
   - 3 karakter tambahan (`role_c010`, `role_t001`, `role_t002` beserta `aim`/`cover`).
   - Menghapus BOM UTF-8 (`\ufeff`) dari `.atlas` (`c010_00.atlas`).
3. **Nama karakter Luban & 43 family (`assets/eroera/_names.json`)**:
   - Di-parse langsung dari binary `ByteBuf` Luban (`hero_tbheroshowgirl` & `pet_tbpetcharacter` di `TbData/TbDatas`).
   - Menghasilkan **43 kartu root** dan **131 varian** (`attachEroEraFamilies()` di `src/server.js`).
4. **Thumbnail kartu bertingkat (`public/thumbs/eroera/` + `_manifest.json`)**:
   - 64 berkas WebP yang diekstrak dari `Sprite` di `SpriteAtlas/Packs/Hero` (`card_1_1`..`card_30_3` 147×285 untuk Hero dan `p_kp41001`..`p_kp45002` 147×242 untuk Pet), menutup **165/174 model**.
   - Varian `Utama`/`Aim`/`Cover`/`Skill Cut` memakai `card_<N>_1.webp` (kostum tempur), `H Scene — Base` memakai `card_<N>_2.webp` (半裸), dan `H Scene — Adv` / `Interaction` memakai `card_<N>_3.webp` (全裸).

## Pembaruan & Verifikasi

```bash
# Sinkronkan bundle, model Spine, nama Luban, family, dan thumbnail
/srv/venv-spine/bin/python tools/eroera/refresh.py

# Kontrak updater untuk tombol "Periksa pembaruan" di UI
/srv/venv-spine/bin/python tools/eroera/update.py --check
/srv/venv-spine/bin/python tools/eroera/update.py --apply

# Verifikasi end-to-end (API + parser Spine 174/174 + Playwright UI)
node tools/check-eroera.cjs
```
