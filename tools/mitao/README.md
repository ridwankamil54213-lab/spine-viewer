# Mitao Utopia (蜜桃乌托邦) updater

Perbarui model Spine game ini dari CDN, langsung ke pohon aset spine-viewer.
Dipanggil server lewat `GET /api/update/mitao-utopia` (tombol "Perbarui aset"
di header). **Sejak 2026-11 memakai pipeline iOS (v2)** karena kunci master
manifest Android v3 disembunyikan di Obfuz VM.

```bash
/srv/venv-spine/bin/python tools/update-mitao.py --check
/srv/venv-spine/bin/python tools/update-mitao.py --apply --manifest-only  # verifikasi aman
/srv/venv-spine/bin/python tools/update-mitao.py --apply                 # tambah model baru
/srv/venv-spine/bin/python tools/update-mitao.py --apply --replace       # ganti SELURUH aset dgn iOS
```

`--replace` mengekstrak ke staging dulu, menolak swap kalau hasilnya kurang dari
50 model valid (`.skel`/`.json` + `.atlas` + `.png`), lalu memindahkan pohon
aset lama ke `/srv/spine-assets/mitao/android-backup-<waktu>/` sebelum
menaruh hasil iOS. Backup itu di luar repo dan bisa dipulihkan kapan saja.
Tanpa `--replace`, folder model yang sudah ada **tidak ditimpa**.

## Kenapa iOS

Forum `live2dhub.com/t/topic/6410` (post #15) mengonfirmasi: **Android = v3,
iOS = v2, tidak saling kompatibel**. Empat container berhasil dipetakan
(semuanya lewat HTTP Range, tanpa unduh APK 198 MB):

| Container | Tempat | Skema | Status |
| --- | --- | --- | --- |
| `IDOLNAB3` | bundle Android 2.50.1 | XChaCha20-Poly1305, BLAKE2b keyed | **SOLVED** — `idol_rs_v3.py` |
| `IDOLRS1` + `IDOLAB2` + RSA-3072 | manifest Android 2.50.1 | AES-CBC/HMAC v2, kunci dirotasi | kunci master di Obfuz VM |
| `IDOLRS1` + `IDOLAB2` | manifest iOS 1.6.2 | AES-CBC/HMAC v2 | **SOLVED**, dipakai updater |
| `IDOLMD1` | `global-metadata.dat` (IL2CPP) | XChaCha20-Poly1305 | **SOLVED** — 17.736.188 byte |

Isi manifest Android dan iOS praktis identik: `plain_len` 1.188.128 vs
1.188.127 (selisih 1 byte = panjang string versi `2.50.1` vs `1.6.2`), 3226
bundle, 1038 bundle skeleton, nama model sama (`ass_30001` muncul di kedua).
Tapi **berkas bundlenya spesifik platform**: `FileHash` iOS ditolak endpoint
Android (`HTTP 400 RESOURCE_ACCESS_INVALID`), path CDN beda
(`/ReleaseGame18/iOS/1.6.2/` vs `/Android/2.50.1/`), kunci & skema beda.
Jadi pindah ke iOS berarti mengganti **seluruh** alur — bukan cuma kunci —
dan jangan mencampur bundle dua platform.

### Yang sudah dipecahkan (modul siap pakai)

* **iOS v2** — `tools/mitao/idol_v2.py`: `IDOLRS1` wrapper, `IDOLAB2`
  AES-256-CBC + HMAC-SHA256, KDF `IdolTime/AssetBundle/v2/…`, dan turunan kunci
  bundle `IdolTime/BundleEncryption/v2\n<SCOPE>\n<key_id>` dengan
  `SCOPE = Release_Game18_iOS/ios_cn_release`. Backend AES: `Crypto` →
  `cryptography` → fallback CLI `openssl` (venv service tidak punya dua
  library pertama). `--self-test` round-trip manifest + bundle, kunci scope,
  dan deteksi tamper; hijau di kedua interpreter.
* **Android v3** — `tools/mitao/idol_rs_v3.py`: Ghidra atas
  `lib/arm64-v8a/libidol_resource_guard.so` (71 KB). Header 0x60 `IDOLNAB3`,
  HChaCha20 + ChaCha20 counter 64-bit + Poly1305 per chunk 64 KiB,
  kunci = BLAKE2b keyed. `--self-test` cocok dengan OpenSSL. Disimpan untuk
  referensi/RE lanjutan, belum dipakai updater.
* **Metadata IL2CPP** — kunci `3d7900c1…` dari `decrypt_metadata.py`
  memverifikasi tag `IDOLMD1` dan membuka 17.736.188 byte
  `global-metadata.dat`. 468 kandidat kunci hex/base64 + 240 label KDF tetap
  gagal membuka HMAC manifest Android → kunci memang di VM, bukan literal.

## Alur updater iOS

1. `--check`: POST `/resource/url` (`resource_type: ios_cn_release`) →
   `release_id`, lalu ambil `PackageManifest_DefaultPackage.version` (teks
   kecil) → versi live. Bandingkan dengan `state.json`. Tidak mengunduh
   manifest penuh maupun APK.
2. `--apply --manifest-only`: ambil
   `PackageManifest_DefaultPackage_<versi>.bytes` lewat
   `/resource/access/batch`, dekrip via `idol_v2.decrypt_manifest()`, parse
   YooAsset, simpan ke `/srv/spine-assets/mitao/manifest.json`. **Aman untuk
   verifikasi**, tidak mengunduh bundle.
3. `--apply`: diff bundle skeleton (baru / hash berubah / hilang), resolve URL
   bertanda tangan per 20 berkas, unduh + dekrip via
   `idol_v2.decrypt_bundle(..., derive_bundle=True)`, simpan `UnityFS` ke
   `bundles/`, lalu `extract-spine.py` → `assets/mitao-utopia/<varian>_<id>/`
   **tanpa menimpa** yang sudah ada. State mencatat `platform: "ios"`,
   `release_id`, dan versi; `UPDATERS["mitao-utopia"].rescan: true` memaksa
   `/api/models` dipindai ulang setelah apply sukses.

`rawdata_spine_*` DAN `prefabs_spine_*` diambil (`SKELETON_MARKERS`):
sebagian `prefabs_spine_mesh_skill_*`, `_avg_*`, `_ui_cutin_*` berisi pasangan
`.skel` + `.atlas` asli. Prefab bukan skeleton tersaring saat ekstraksi.
Dokumen lama yang menyebut "hanya rawdata" sudah usang.

Struktur manifest Android (referensi RE, tidak dipakai updater):

```
0x00  "IDOLRS1\0" + 4 u32       wrapper 24 byte (payload_len = 1.189.472)
0x18  "IDOLAB2\0" + header v2   plain_len 1.188.128, salt/name_hash/tag 32 byte
...   chunk AES-CBC + HMAC      1.189.472 byte total
ekor  384 byte high-entropy     tanda tangan RSA-3072
```

## Nama karakter

Tabel lokalisasi di bundle (`Assets/Res/Configs/Gen/LocalizeConfig_{CN,TW,JP,EN}_Category.json`)
punya kunci `HEROINFO_Name_<id>` berisi 59 nama karakter/monster. Versi EN masih
placeholder (`text_en` berisi teks Tionghoa / kosong), jadi **tidak ada ejaan
Latin di bundle** — nama utama memakai ejaan Jepang asli (`text_jp`), fallback
TW lalu CN; ketiganya disimpan. `tools/mitao/refresh-names.py` menulis
`data/mitao-names.json` (143 model ter-cover dari 214), dibaca
`applyMitaoNames()` di `src/server.js`: `m.name` jadi
`綾乃 真理子 (front_10001)` supaya id tetap bisa dicari, dan `m.character`
membawa `name` / `nameCN` / `nameTW` / `source`. Semua varian satu id mewarisi
nama yang sama. Model tanpa entri (71, kebanyakan `ass_3000X`, `loading_*`,
`monster_20034+`) tetap memakai nama folder. `--apply` menyegarkan data ini
otomatis (non-fatal).

## Thumbnail & varian

**Thumbnail** diambil dari `DynamicSingleTextures/HeroSelectDisplay` hasil
`extract-all.py`: 35 sprite `HeroSelectDisplay_<id>.png` (bukan lembar
`__atlas.png`) dikonversi `tools/mitao/refresh-thumbs.py` jadi WebP 300px
(alpha dipertahankan) di `public/thumbs/mitao-utopia/`. Satu potret dipakai
bersama semua model dengan suffix id sama — `_manifest.json` memetakan 116
model ke 29 berkas. Model yang id-nya tidak ada di folder ini tetap memakai
badge huruf. Jalankan ulang dengan
`/srv/venv-spine/bin/python tools/mitao/refresh-thumbs.py` (idempoten,
`--force`); `--apply` updater memanggilnya otomatis sebagai langkah
kosmetik non-fatal.

**Varian** (`attachMitaoFamilies()` di `src/server.js`): `front_<id>` jadi
kartu root, `back/hfront/common/skill/hspecial_<id>` jadi baris di picker
Varian (label `Utama`, `Back`, `H Front`, `Common`, `Skill`, `H Special`). 78
model tersembunyi jadi varian. Seluruh 43 model `equip_*` dihapus permanen dari
`assets/mitao-utopia/` (manifest id tersimpan di `/tmp/mitao-equip-removed.json`;
bundle mentahnya tetap ada di `all-bundles/` kalau mau direstore). Hasil akhir:
**214 model / 136 kartu root / 78 varian**. `update-mitao.py --apply` membersihkan
`equip_*` lagi setelah ekstraksi supaya tidak muncul balik. Prefix lain
(`monster`, `loading`, …) sengaja tetap berdiri sendiri. Regresi:
`tools/check-mitao-variants.cjs` (26 assertion API + UI Playwright).

## Ekstraksi penuh + File Browser

Kalau mau memilih sendiri ikon/ilustrasi dari seluruh rilis, jalankan:

```bash
/srv/venv-spine/bin/python tools/mitao/extract-all.py
```

Tool ini mengunduh + mendekrip **semua 3226 bundle** (1,69 GiB) ke
`/srv/spine-assets/mitao/all-bundles/` (1038 bundle skeleton yang sudah ada
cukup di-hardlink), lalu mengekstrak tiap UnityFS via UnityPy ke
`/srv/spine-assets/mitao/extracted/` dengan path semirip `AssetPath` asli:
`Sprite` → `.png`, `Texture2D` → `...__atlas.png`, `TextAsset` → bytes. Objek
tanpa pasangan `AssetPath` masuk `extracted/_bundles/<bundle>/`. Tipe lain
(prefab, anim, controller, audio) tetap utuh di `all-bundles/` dan tercatat di
`extracted/_index.json`. Idempoten, `--download-only`, `--workers N`.

File Browser (v2.63.23) dipasang di port **8080** dengan root
`/srv/spine-assets/mitao`, unit systemd `filebrowser.service`, user `admin`,
sandi acak di `/root/.filebrowser-password` (mode 600). Login lewat
`http://<host>:8080/`. Endpoint tanpa token ditolak 401.
Catatan: service jalan sebagai root dengan scope seluruh direktori itu, jadi
siapa pun yang punya sandi bisa menulis/menghapus isinya — jangan buka port
8080 ke publik tanpa reverse proxy / allowlist IP.

## Berkas

| Berkas | Isi |
|---|---|
| `update-mitao.py` | CLI + alur check/apply pipeline iOS |
| `mitao/extract-all.py` | unduh + ekstrak seluruh bundle iOS |
| `mitao/refresh-thumbs.py` | WebP dari `HeroSelectDisplay` |
| `mitao/refresh-names.py` | `data/mitao-names.json` dari `HEROINFO_Name_*` |
| `mitao/idol_v2.py` | dekripsi `IDOLRS1`/`IDOLAB2` v2 (dipakai) |
| `mitao/idol_rs_v3.py` | dekripsi `IDOLNAB3` v3 Android (referensi) |
| `mitao/mitao_api.py` | helper lama Android (`/resource/url`, AES v2 2.48.3) |
| `mitao/mitao_manifest.py` | parser `PackageManifest` YooAsset |
| `mitao/extract-spine.py` | UnityPy → `.skel`/`.atlas`/`.png` |
| `tools/check-mitao.cjs` | 15 assertion, termasuk endpoint HTTP asli & `--manifest-only` |

State: `/srv/spine-assets/mitao/` (`manifest.json`, `bundles/`, `state.json`;
tidak ada lagi `game.apk`). Override dengan env `MITAO_STATE`.

Aset: **`ROOT/assets/mitao-utopia`** relatif repo (`ROOT` = parent `tools/`),
override `MITAO_OUT`. Jangan hardcode `/opt/spine-viewer/...` — service jalan
dengan `WorkingDirectory=/root/spine-viewer`, sehingga path itu membuat
`--check` melapor `have:0` dan `--apply` menulis ke pohon yang tidak dipindai.
Interpreter updater wajib `/srv/venv-spine/bin/python`.
