# イヴンタイト (IV-N-Tight) — DMM/FANZA web game, Dieselmine

Unity **WebGL** build. Its addressable content is remote, and the Spine models
(JSON 4.2.38/4.2.43) live inside the remote bundles.

## How it was found (login → CDN)

The game runs inside an OpenSocial gadget iframe → `iv-n-tight.saikyo.biz`. The
actual Unity player is served from
`iv-n-tight.saikyo.biz/app_data/` (needs the DMM session cookies), which
streams the loader from a CDN. The loader config gives:

```
buildUrl = https://iv-n-tight.webaccel.saikyo.biz/dmm4data/Unity6/BuildData/Build
  dmm4_build.loader.js / .data.unityweb / .wasm.unityweb / .framework.js.unityweb
```

`dmm4_build.data.unityweb` is **brotli** wrapping a `UnityWebData1.0.0`
container (magic 16 B + `headerLength` u32, then records), which holds
`data.unity3d` (UnityFS), `resources.resource`, `sharedassets*.resource`,
`global-metadata.dat`. That bundle has a handful of Spine models
(`prin`, `watermelon`, the NPC 立ち絵, …).

## The addressables CDN (main Spine source)

`data.unity3d` embeds the remote addressables paths:

```
https://eventight-sb.webaccel.saikyo.biz/dmm4sb/Unity6/Addressable_Test2/WebGL/
    catalog_0.0.1.json   (+ .hash)     <- 3.2 MB catalog
    <hash>.bundle                      <- 1189 bundles
```

(mirrors: S3 `eventight-sb.s3.ap-northeast-1.amazonaws.com/dmm4sb/...`).
The catalog maps `CharacterBackSpine_<id>` / `CharacterBattleSpine_<id>`
keys → a `CharacterBattleSpine_<id>.prefab` whose DependencyKey points at an
`iv_characterdata_<id>__<hash>.bundle`. Those bundles hold the Spine data as
**TextAsset** (`<name>.json` skeleton + `<name>.atlas`) with the texture as a
`Texture2D`.

## Usage

```sh
# extract the 6 models that ship inside the build (data.unity3d):
/srv/venv-spine/bin/python tools/extract-ivntight.py --bundle /opt/ivntight/extract/data.unity3d

# updater: downloads ALL bundles (Test2+Test3) and finds Spine by CONTENT
/srv/venv-spine/bin/python tools/update-ivntight.py --check   # ~0.4 s, JSON
/srv/venv-spine/bin/python tools/update-ivntight.py --apply    # download + scan + extract
```

`--apply` downloads **every** bundle (~3.8 GB across Test2+Test3), then scans
each UnityFS bundle for a Spine JSON TextAsset. Filtering by catalog name is
NOT enough: the catalog stores no bundle sizes, and some Spine bundles have
random-hash names with no "spine" anywhere (e.g. the `chiika`/`Clarity`/
`Ep_boss*` models). Found: 136 unique Spine bundles → 84 models (the other
Test3 bundles are duplicate copies of the same character data). The bundles are
cached under `/srv/spine-assets/ivntight-update/bundles-all/` so re-runs are
instant (scan-only, ~3 min).

`--check` reports `{version, previous, changed, total, installed, new}`
(catalog sha1 = version). `--apply` downloads each Spine bundle to
`/srv/spine-assets/ivntight-update/bundles/` (kept, so re-runs are instant),
extracts to `assets/ivntight/<safe-name>/`, and writes
`data/ivntight-names.json` (safe-name → original Japanese name, which the
server uses for the HUD). Re-running `--check` after `--apply` returns `new: 0`.

## Gotchas

- **`\w` includes CJK.** A naive `[^\w.-]` "safe" name keeps katakana/kanji, so
  the folder is non-ASCII; the viewer then slugs the model id (CJK → `-`) and
  several models collide into the same id. Use an explicit ASCII range and add
  a short md5 when characters were lost — stable and collision-free. The real
  name is kept in `data/ivntight-names.json`.
- **Write the atlas PNG under the name the atlas references** (the original
  Japanese page name), not the sanitized one — the viewer resolves page names
  from the atlas and otherwise fails to load the model.
- `iv_enemybattlespine_group_*` bundles are custom IV/effect prefabs (no
  Spine TextAsset) → 0 models; mark such bundles done anyway so they are not
  re-downloaded.
- The build is mostly 3D: only ~67 of these models are Spine. No Live2D (moc3).
