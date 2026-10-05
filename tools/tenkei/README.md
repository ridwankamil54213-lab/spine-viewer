# 天啓パラドクスX / Tenkei Paradox X — Spine extraction

DMM/FANZA Unity Addressables game (KMS / EXNOA). Spines ship as plain UnityFS
bundles — **no decryption**. 341 full + 341 "light" LOD → ~682 models.

## Locating the bundles

Asset URLs are built from three catalogs on an Azure blob host:

```
https://cdne-paripari-prod.tenkei-paradox.com/production/
    production<N>-864dc0b0-6f1a-4aaa-bb36-703600ea7966/Assets/<Platform>/
    ├── base_catalog.json
    ├── assets_catalog.json     <- the spine/background/still bundles live here
    └── vfx_catalog.json
```

- `<Platform>` = `Android` or `WebGL` (same assets).
- `<N>` **changes with every game update**. At time of writing the live trees
  were `production7/8/9`; `probe_production()` just tries 1..12 and keeps the
  highest that answers. A stale N returns HTTP 404 `BlobNotFound`.
- The uuid `864dc0b0-…-703600ea7966` has been stable.

Catalog entries look like:

```
PariPariPublicRemote/spines_assets_spines/<id>_<hash>.bundle
PariPariPublicRemote/spineslight_assets_spineslight/<id>_<hash>.bundle
PariPariPublicRemote/backgrounds_assets_backgrounds/<…>.bundle
PariPariPublicRemote/stills_assets_stills/<…>.bundle
PariPariPublicRemote/characterillustrationx_assets_characterillustrationx/<…>.bundle
```

Download URL = `<base>/production/production<N>-<uuid>/Assets/<Platform>/`
+ the entry **with the leading `PariPariPublicRemote/` stripped**.

## Bundle contents (one Spine model each)

| object | content |
|---|---|
| `TextAsset "<id>.atlas"` | Spine atlas (plain text) |
| `TextAsset "<id>.skel"` | Spine **binary** 3.8.9x (plain) |
| `Texture2D "<id>"` | page PNG (2048×2048) |

## Usage

```bash
/srv/venv-spine/bin/python extract-tenkei.py --probe          # find live production<N>
/srv/venv-spine/bin/python extract-tenkei.py --list           # counts per category
/srv/venv-spine/bin/python extract-tenkei.py --extract --cat spines_assets_spines \
      [--limit N] [--filter RX] [--workers 8] --out /opt/spine-viewer/assets/tenkei
# repeat with --cat spineslight_assets_spineslight
```

Output: `<out>/<category>/<id>/{<id>.atlas,<id>.skel,<id>.png}`.

## Notes

- `assets_catalog.json` is ~5.5 MB; `vfx_catalog.json` ~11 MB (effects). The
  spine sets are only in `assets_catalog.json` here, but `vfx_catalog.json`
  may hold more — pass `--catalog vfx_catalog.json --cat <dir>` to mine it.
- Spine is 3.8.x **binary**, so it renders through the pixi-spine 3.8 runtime
  (not the 4.2 renderer).
- Two bundles per character id: `spines` (full detail) and `spineslight`
  (heavier compression / lower LOD). Both are kept.
