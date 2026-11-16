# CrossCore (交错战线) — asset updater

> **Sumber aktif sekarang: https://crosscore.art/.**
> Yang dipanggil server adalah `tools/crosscore/update.py`, yang menjalankan
> `tools/crosscore/import-art.py` LALU `tools/crosscore/import-extras.py`
> (lihat README utama, section CrossCore).

## Pipeline aktif (crosscore.art)

| Skrip | Tugas | Hasil |
| --- | --- | --- |
| `import-art.py` | 134 karakter / 421 outfit / 486 scene | `assets/crosscore/<slug>/`, `assets/crosscore-cg/`, `_names.json`, thumbnail, `_manifest.json` |
| `import-extras.py` | efek + zona sentuh + suara | `assets/crosscore/<slug>_effF\|effB/`, `_extras.json`, `data/cc-interaction.json`, `public/audio/crosscore/clips/` |
| `update.py` | pembungkus `--check` / `--apply` untuk server | state + JSON hasil untuk `/api/update/crosscore` |
| `render-thumbs.cjs` + `normalize-thumbs.py` | screenshot 408 rig utama, crop ke subjek | `public/thumbs/crosscore-render/` (408 WebP + manifest 635 entri) |

Keduanya **idempoten** (berkas yang sudah ada dilewati) dan boleh dijalankan
mandiri:

```sh
python3 tools/crosscore/import-art.py --workers 8
python3 tools/crosscore/import-extras.py --workers 8   # ~1 mnt, 236 MB audio
python3 tools/crosscore/update.py --check
node tools/check-crosscore-extras.cjs
# thumbnail (butuh server hidup + Playwright + Pillow)
node tools/crosscore/render-thumbs.cjs --workers 3
node tools/check-crosscore-thumbs.cjs
```

`import-extras.py` wajib dijalankan **setelah** `import-art.py` karena memakai
`data/crosscore-art-catalog.json` dan atlas scene induk. Metadata efek/audio
ditulis ke `_extras.json` (terpisah dari `_names.json`) supaya apply berikutnya
tidak menimpanya.

Efek `front`/`back` memakai attachment yang sama dengan atlas induk: atlas
disalin dengan nama halaman ditulis ulang, dan PNG-nya di-**hardlink** supaya
227 rig efek tidak menggandakan ~1 GB tekstur di disk.

Zona sentuh (`official-zones.js` + `touch-zones.js`) ditulis ke
`data/cc-interaction.json` dengan `prefab` = slug model, sehingga mesin CCI
`src/viewer.js` langsung cocok. `audioId` berisi nama klip WebM, diputar
`cciApplyEvent()` saat area disentuh; `model.audio.tracks` menghidupkan tombol
audio bawaan `renderAudio()`.

> File di bawah `public/audio/`, `public/thumbs/crosscore-render/`, dan
> `assets/` hasil unduhan/render, di-ignore Git. Backupnya lewat auto-upload
> GDrive (`src/gdrive-upload.js`, root `public/audio/crosscore` dan
> `thumbs/crosscore-render`).

---
> Dokumen di bawah ini menjelaskan DUA pipeline LAMA: ArtHub / R2
> (`tools/update-crosscore-*.py`, `refresh-meta.py`) dan mirror komunitas
> berbasis AssetBundle `prefabs_spine_*` (`tools/update-crosscore.py`).
> Keduanya sudah diarsipkan dan tidak dipanggil server lagi.

Rangkuman pipeline lama (arsip):

CrossCore ships its Spine models as public AssetBundles on a resource CDN.
`tools/update-crosscore.py` keeps the viewer's `assets/crosscore/` tree in sync.

## Sources

**Primary: GitHub mirrors** (the official CDN blocks many non-CN hosts, so the
updater uses community mirrors that re-publish the official `curr_1` channel):

```
kmou424/Crosscore_Anti_Hexie_Assets    # anti-censor build; prefabs_spine_* bundles
R2iCecho/Crosscore_Assets_curr_1       # ilist.txt index (assets live on a branch)
```

Add more with `CROSSCORE_GH="owner/repo,owner/repo@branch"`.

**Official CDN** (tried first when reachable; also used with `--manifest`):

```
https://cdn.megagamelog.com/cross/release/android/curr_1/ver.bytes
  -> .NET BinaryFormatter manifest: every AssetBundle (name, size, md5)
https://cdn.megagamelog.com/cross/release/android/curr_1/Custom/<AB name>
  -> the AssetBundle itself
```

Each `prefabs_spine_*` bundle is **self-contained**: skeleton (a TextAsset whose
payload is JSON, named just `<Name>` — no extension), the atlas text, and the
page texture all live in the one bundle, so one bundle == one model.

## Bundles are FakeHeader-encoded

The bundles carry junk before the real `UnityFS` magic (the community
`FakeHeader.py` trims it with `content.rfind(b"UnityFS")`). Once trimmed,
**UnityPy reads them directly** — no dotnet / AssetStudioModCLI needed:

```python
data = raw[raw.rfind(b"UnityFS"):]        # trim_fake_header
env  = UnityPy.load(io.BytesIO(data))     # then TextAsset + Texture2D
```

Some titles also use UnityCN (needs a 32-hex key via
`UnityPy.set_assetbundle_decrypt_key`); pass it as `CROSSCORE_UNITYCN_KEY` if a
future CrossCore build turns out to need it. Without it, CN bundles simply
report an error instead of crashing.

## Usage

```sh
# apa yang baru? (cepat, ≤30s; ramah walau CDN tak terjangkau)
/srv/venv-spine/bin/python tools/update-crosscore.py --check
# unduh + ekstrak yang baru ke assets/crosscore/
/srv/venv-spine/bin/python tools/update-crosscore.py --apply
# uji tanpa jaringan, pakai ver.bytes lokal
/srv/venv-spine/bin/python tools/update-crosscore.py --check  --manifest /path/ver.bytes
/srv/venv-spine/bin/python tools/update-crosscore.py --apply  --manifest /path/ver.bytes
```

Env: `CROSSCORE_CDN` (mirror, dipisah koma), `CROSSCORE_FETCH_TIMEOUT` (detik,
default 30), `CROSSCORE_STATE` (default `/srv/spine-assets/crosscore`),
`CROSSCORE_OUT` (default `assets/crosscore`), `CROSSCORE_UNITYCN_KEY`.

## Output layout

```
assets/crosscore/<Name>/<Name>.json   (or .skel — JSON vs binary skeleton)
assets/crosscore/<Name>/<Name>.atlas
assets/crosscore/<Name>/<page>.png
```

## From the web UI

Open the CrossCore game in the viewer — a check button appears in the header
(auto-check on enter). A red dot means there is something new; clicking asks to
confirm, then downloads in the background and marks new models with a NEW badge.

## Notes / gotchas

- `assets/crosscore` may be a **symlink** into a big disk (`/srv/spine-assets`).
  The scanner and this updater both follow it; write the models, not a fresh dir.
- The official CDN sits behind Volcengine (CN) and **blackholes** many non-CN
  hosts (TCP connect hangs with no error, DNS fans out to many IPs) — verified
  from an AWS Tokyo box: every CDN IP times out, while `baidu`/`github` are
  fine. That is why the **GitHub mirror is the default source**, and why the
  manifest fetch runs in a subprocess with a hard kill (`--check` still returns
  within `CROSSCORE_FETCH_TIMEOUT` when only the CDN is reachable-ish).
- `--doctor` reports both paths: how many `prefabs_spine_*` the mirror has, and
  whether any CDN IP accepts TCP:443. Run it first when something looks blocked.
- `check()` diffs against the files **actually on disk**, not only the saved
  state, so a first run on an already-complete install reports "up to date".
- `CROSSCORE_PROXY=http://host:port` routes both manifest and downloads through
  a proxy, if one is available.

## History

The original extraction (`tools/extract-crosscore.py`) used AssetStudioModCLI
(batches of ~30 to avoid the ~6.5 GB RSS OOM from ASTC textures). The updater
reimplements the pipeline natively on Linux via UnityPy so the viewer can refresh
itself without the .NET toolchain.
