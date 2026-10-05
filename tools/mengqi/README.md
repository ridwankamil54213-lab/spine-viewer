# 梦琪领导 / President's Ambition — Project Beauty R (cgg4game)

Spine extractor for **梦琪领导 / 总统的野望 / 首富2** (DMM side-title
"総裁の野望"), the "city builder + beauties" Ero-Lab title. Flow captured by
the community downloader scripts on live2dhub topic 4603 (posts #30, #37, #39).

## Why the naive approach fails

The game is a **Cocos Creator 2.x web build** (`richman2Release`) that is *not*
shipped as an APK bundle you can just unzip from a fixed URL. The resource list
is resolved at runtime:

1. The landing page redirect leaks the current resource version:

   | channel | probe |
   |---|---|
   | nutaku | `GET https://city2ntk.cgg4game.com/webfyen/nutakupc.php` |
   | dmm    | `GET https://city2dmm.cgg4game.com/webdmm/h5Index_dmmPC.php` |

   Both answer `302 Location: …richman2Release/<pf>.html?…&resVer=<HASH>&…`
   where `resVer` is the only thing needed.

2. `GET https://h.cgg4game.com/games/richman2Release/resource/default.res.<resVer>.json`
   → 949 KB nested tree:

   ```jsonc
   { "groups": …, "files": { "assets": …, "animation": {
       "Book": { "Book.atlas":"bb3388e8", "Book.json":"f4e664f4", "Book":"cace7f40" },
       "city": { "Dafuweng_jianzhu_UI": { "…atlas":"4f0d60b2", … } },
       … } } }
   ```

   A **spine model** is any dict that has both `<Name>.atlas` and `<Name>.json`
   string values; the bare `<Name>` entry is the texture-page hash.

3. Each file is fetched from the CDN (no auth, but a `Referer` helps):

   ```
   https://cdnen.cgg4game.com/games/richman2Release/resource/animation/<path>/<Name>_<atlasHash>.atlas
   https://cdnen.cgg4game.com/games/richman2Release/resource/animation/<path>/<Name>_<jsonHash>.json
   https://cdnen.cgg4game.com/games/richman2Release/resource/animation/<path>/<Name>_<texHash>.png
   ```

## Good news

- **No decryption.** The spine JSON is plain text (skeleton `3.7.94` on this
  build), the atlas is plain text, and the page is a plain PNG (P or RGBA).
- **~2220 models.** Buckets: `dmR` 871 (571 of them `dmR/city` — the H-scene
  character animations), `role` 270, `role_fishion` 268, `npc` 209, `city` 207,
  `secretary_fishion` 89, `secretary` 83, …

## Usage

```bash
/srv/venv-spine/bin/python extract-mengqi.py --fetch-config   # refresh default.res.json
/srv/venv-spine/bin/python extract-mengqi.py --list           # counts per bucket
/srv/venv-spine/bin/python extract-mengqi.py --extract \
    [--limit N] [--filter REGEX] --out /opt/spine-viewer/assets/mengqi
```

The extracted layout is `<out>/<path>/<Name>/{<Name>.json,.atlas,.png}` so the
viewer sidebar renders it as `dmR › role_fishion › <Name>`.

## Pitfalls

- The redirect must be read **without following it** (the CDN html 404s from a
  bare client); capture the `Location` header and pull `resVer` out of it.
- `referer: https://cdnen.cgg4game.com/` is required for the CDN files.
- A few models have **no bare `<Name>` texture entry** (texture shared/absent) —
  the extractor marks them `skip` on the PNG leg and still writes json+atlas.
