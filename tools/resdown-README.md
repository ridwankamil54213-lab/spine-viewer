# resdown — ResDownloader-style CLI for Linux

`tools/resdown.py` re-implements what the Windows **ResDownloader / SpineGods**
app does with 222 per-game Cython classes, but as one data-driven tool:

```
manifest / list  ->  fetch (parallel, md5-checked)  ->  extract Spine (skel/atlas/png)
```

It targets **public game CDNs** directly (no login, no Windows, no aria2c).

## Subcommands

| cmd | what |
|---|---|
| `catalog` | list the 90 SpineGods games (bundled `spinegods-game.json`) |
| `list <SOURCE>` | parse a manifest/list and print matching assets + sizes |
| `fetch <SOURCE> --out DIR` | download matching assets to `DIR/raw/` (parallel, `--md5`) |
| `extract [BUNDLES…] --dir D --out O` | extract Spine from UnityFS bundles to `O/` |
| `pipeline <SOURCE> --out DIR` | `list → fetch → extract` in one shot |

`SOURCE` = a remote URL or a local file. Formats are auto-detected:

* **Unity/Cocos JSON manifest** — `{"assets": {"<name>": {"md5":…, "size":…}}}`
  (uses `packageUrl` as the base if present)
* **CSV** — `name,md5base64,size` (e.g. otogi `AdditionalAssets.csv`)
* **JSON array** of paths
* **plain newline list**

Common options: `--base URL`, `--filter REGEX`, `--limit N`, `--host-map OLD=NEW`,
`--jobs N`, `--md5`, `--dry-run`, `--unity-version`.

## Examples

```bash
P=/srv/venv-spine/bin/python

# what games are there?
$P tools/resdown.py catalog

# what Spine assets does Otogi Frontier publish?
$P tools/resdown.py list \
  https://web-assets.otogi-frontier.com/prodassets/GeneralWebGL/AssetBundlePatch/AdditionalAssets.csv \
  --base  https://web-assets.otogi-frontier.com/prodassets/GeneralWebGL/Assets/ \
  --filter '^chara/spine/'

# fetch + extract 3 of them
$P tools/resdown.py pipeline \
  https://web-assets.otogi-frontier.com/prodassets/GeneralWebGL/AssetBundlePatch/AdditionalAssets.csv \
  --base  https://web-assets.otogi-frontier.com/prodassets/GeneralWebGL/Assets/ \
  --filter '^chara/spine/(10011|10012|10013)$' \
  --out /tmp/otogi

# just download (verify md5), extract later
$P tools/resdown.py fetch <SOURCE> --out /tmp/g --md5 --filter 'spine'
$P tools/resdown.py extract --dir /tmp/g/raw --out /tmp/g/spine
```

## Known public (no-login) sources

| game | manifest | asset base |
|---|---|---|
| Otogi Frontier | `…/otogi-frontier.com/prodassets/GeneralWebGL/AssetBundlePatch/AdditionalAssets.csv` | `…/GeneralWebGL/Assets/` |
| (gamezdjsmr) | `https://cdn.gamezdjsmr.net/images/download_res/Android/proj.manifest` | same dir |
| Ark Re:Code | `https://game-arkre-labs.ecchi.xxx/WebGL/StreamingAssets/aa/catalog.json` | same |
| Isekai | `https://hvilla.ams3.cdn.digitaloceanspaces.com/isekai_android_bundle_1/Isekai_bundle/prod/isekai36/Android.customManifest` | same dir |
| Waifu Shop | `https://waifushop.tendertroupe.com/StreamingAssets/aa/settings.json` | same |
| Muvluv | `https://assets.muvluv-girls-garden.com/production-public/` | same |

See `spinegods-reverse.md` for the full ~40-host map carved from the app dump.

## Notes / limits

* `extract` delegates to `tools/extract-unity-spine.py` (battle-tested: picks the
  largest of duplicate textures, `get_raw_data()` to keep binary `.skel` intact,
  trims fake headers via `rfind("UnityFS")`). It stages bundles as `*.bundle`
  and passes `ONLY_BUNDLES`.
* Some CDNs rate-limit (they'll 403/404 intermittently); `fetch` retries with
  exponential backoff.
* Raw Spine files (`Spines/<cat>/<id>.unity3d` on `*.iczph.com` etc.) need
  **server-signed URLs** → not reachable anonymously (that is the part the app's
  login gate protects). This CLI works with the sources that ARE public.
* Pure Spine `.skel/.atlas` (non-UnityFS) sources are out of scope for `extract`
  (it's Unity-bundle oriented); use `fetch` + the `.skel`/`.atlas` directly.
