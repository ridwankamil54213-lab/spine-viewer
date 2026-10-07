# 极乐深渊 (Blissful Abyss) — extraction notes

Cocos2d-lua game. Spine assets live under `assets/res/animation/**` in the APK,
encrypted with a **subtract cipher** (public key from the forum):

    plaintext[i] = cipher[i] - key[i % len(key)],  key = b"YUNMIAO2014RES"

## File mapping

| on disk        | meaning                                  | handling                        |
|----------------|------------------------------------------|---------------------------------|
| `<base>.jn`    | Spine skeleton **JSON** (Spine 2.1.27)   | decrypt -> `<base>.json`        |
| `<base>.atb`   | atlas text                               | decrypt -> `<base>.atlas`       |
| `<base>.pvr.ccz` | texture, `CCZ!` header + zlib -> PVR3   | decompress -> PNG -> `<base>.png` |
| `<base>.atlas` / `.png` / `.skel` | already plain       | copied as-is                    |

The `.pvr.ccz` is **not** encrypted: it starts with `CCZ!` + 12-byte header,
then zlib (offset 16) holding an uncompressed **PVR3 / RGBA8888** image.
`extract-blissful.py` decodes PVR3 to PNG by hand (no PVR library).

Most characters are **mesh / skinned-mesh** (region count 0), so they need the
viewer's mesh renderer, not just the region path. They are Spine **2.1.27** and
must be routed to the legacy 2.1 canvas viewer:
`{ match: "blissful", ..., spineRuntime: "2.1.27" }` in `GAME_ROOTS`
(src/server.js). See also the cache-signature note below.

## Build

```sh
/srv/venv-spine/bin/python tools/extract-blissful.py --apk /opt/blissful/BlissfulAbyss.apk
# -> assets/blissful/<base>/{<base>.json,<base>.atlas,<page>.png}   415 models
```

3 `.jn` are shared skeletons with no atlas of their own
(`spine1_2`, `spine4_2`, `spine5_2`) and are correctly skipped.

## Gotchas

- Atlas pages may carry a numeric suffix (`<base>0.png`, `<base>1.png`); the
  script rewrites the atlas page name from `.pvr.ccz` to `.png`.
- The viewer's `GAME_ROOTS` config feeds `scanModels()`, but the model cache
  signature was derived from assets/ mtimes only — editing a game entry did
  **not** invalidate the cache, so `spineRuntime` silently never took effect.
  Fixed by mixing a GAME_ROOTS fingerprint into the signature (see
  `SCAN_CONFIG` / `configHash` in src/server.js).
