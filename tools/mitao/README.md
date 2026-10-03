# Mitao Utopia (蜜桃乌托邦) updater

Perbarui model Spine game ini dari CDN resminya, langsung ke pohon aset
spine-viewer. Dipanggil server lewat `GET /api/update/mitao-utopia`
(tombol "Perbarui aset" di header, muncul saat membuka game ini).

```bash
/srv/venv-spine/bin/python tools/update-mitao.py --check   # murah, ~0.3 s
/srv/venv-spine/bin/python tools/update-mitao.py --apply
/srv/venv-spine/bin/python tools/update-mitao.py --apply --apk /path/game.apk
```

## Kenapa begini

Manifest bundle (daftar berkas + versi paket) **hanya ada di dalam APK**, jadi
tidak bisa "cek versi" tanpa mengunduhnya (~197 MB). Karena itu:

* `--check` **tidak menyentuh jaringan** selain `/resource/url` (kecil). Ia
  membaca manifest yang terakhir disimpan dan melaporkan versi live dari
  `release_id`. Tombol di UI jadi selalu murah.
* `--apply` mengunduh APK **sekali**, menyimpan manifest + bundle di
  `/srv/spine-assets/mitao/`, lalu di jalankan berikutnya cukup membaca
  manifest itu (APK tidak diunduh ulang kecuali dengan `--apk`).

## Alur `--apply`

1. Ambil `/resource/url` → `release_id`, `upgrade_url`.
2. Pakai APK lokal / yang tersimpan / unduh baru → baca
   `PackageManifest_DefaultPackage_*.bytes`.
3. Bandingkan manifold skeleton (`rawdata_spine_*`) dengan yang tersimpan:
   mana yang **baru**, **berubah** (hash beda), **hilang**.
4. Unduh yang perlu saja (yang sudah ada dan berheader `UnityFS` dilewati),
   lalu dekripsi container `IDOLAB2` persis seperti downloader aslinya.
5. Ekstrak `.skel`/`.atlas`/`.png` (butuh `--apply` yang benar-benar mengunduh
   sesuatu; ekstraksi penuh ada di `tools/mitao/extract-spine.py`).
6. Pasang ke `assets/mitao-utopia/<varian>_<id>/` **tanpa menimpa** yang ada.

Hanya `rawdata_spine_*` yang diambil. `prefabs_spine_mesh_*` (mesh 3D) dan
`prefabs_spine_ui_*` (prefab UI) tidak pernah menjadi model — lihat
`references/mitao-extraction.md` di skill `spine-viewer-pma`.

## Berkas

| Berkas | Isi |
|---|---|
| `update-mitao.py` | CLI + alur check/apply |
| `mitao/mitao_api.py` | `/resource/url`, `/resource/access/batch`, dekripsi `IDOLAB2` |
| `mitao/mitao_manifest.py` | parser `PackageManifest` (YooAsset, biner) |
| `mitao/extract-spine.py` | UnityPy → `.skel`/`.atlas`/`.png` (kunci folder = `<varian>_<id>`) |

State: `/srv/spine-assets/mitao/` (`game.apk`, `manifest.json`, `bundles/`,
`state.json`). Override dengan env `MITAO_STATE`, `MITAO_OUT`.
