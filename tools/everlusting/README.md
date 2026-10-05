# Everlusting Life (adult-chess.com / Nutaku) — Spine extraction

Community downloader target from live2dhub topic 4603 (posts #40, #124).
Result: **~2495 Spine models** (Spine 4.2.40 JSON), no decryption.

## Flow

```
POST https://assetservice.adult-chess.com/ac/get_assets_with_als
     headers: x-country: JP ; content-type: application/json
     body:    {"state": "ac-release-v3.0.0", "static_type": "webgl_bundles"}
  -> {"result": {"assets": { "<category>": [ {uid,name,url,size,hash,
                                              backup_url,cloudfront_url}, ... ] } }}
```

Categories: `main` (2366), `ttr_second_fight` (50), `ttr_third_fight` (32),
`ttr_before_third` (16), `ttr_before_name` (16), `ttr_harem` (15).

Each entry URL is a **plain UnityFS AssetBundle** (Unity 2022.3.20f1) with
exactly one Spine model:

| object | content |
|---|---|
| `TextAsset "<Name>.atlas"` | Spine atlas (plain text) |
| `TextAsset "<Name>"` | Spine skeleton (plain JSON, Spine 4.2.40) |
| `Texture2D "<Name>"` | page PNG (2048×2048) |

A handful of entries (e.g. `*_preview`) are **Texture2D-only** — plain preview
stills, not spine — and are reported as `skip-not-spine`.

## Usage

```bash
/srv/venv-spine/bin/python extract-everlusting.py --version 3.0.0 --list
/srv/venv-spine/bin/python extract-everlusting.py --extract \
    [--filter REGEX] [--limit N] [--workers 8] --out /opt/spine-viewer/assets/everlusting
```

Output: `<out>/<category>/<name>/{<name>.json,.atlas,.png}`.

## Notes

- `--version` must be a release the service still serves (`3.0.0` worked; the
  community post used `2.0.0`). Wrong versions return an empty `assets` map.
- Every entry carries both a primary `url`/`cloudfront_url` and a `backup_url`;
  the extractor falls back to the backup on a failed download.
- Spine here is 4.2.x, so it renders through the official 4.2 renderer
  (`spine-pixi-v7-42`), not pixi-spine's 3.7/3.8/4.0/4.1 stack.
