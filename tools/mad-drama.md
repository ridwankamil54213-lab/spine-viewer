# Make Drama (MAD) — community rig library

Game key `mad-drama`, label **Make Drama**. Source is the community content
library behind [anyabot/MAD-Viewer](https://github.com/anyabot/MAD-Viewer) — the
same shape as the CZN integration (a model library, not a game CDN).

## Where the assets live
MAD-Viewer ships **no art**: its `public/data/cdn.json` maps each "unit" to a
bucket repo (`anyabot/MAD-assets-1` / `-2`), and `public/data/skin_list.json`
indexes the gallery. Each skin is a **folder of loose files** (not a tar):

```
skins/<unit>/files.json          -> {"files":["AF_CH0009.atlas","AF_CH0009.png",
                                     "AF_CH0009.skel","...","spine.json"]}
skins/<unit>/<Name>.skel         -> Spine BINARY skeleton (4.2.37)
skins/<unit>/<Name>.atlas        -> atlas; declares its page by ORIGINAL name
skins/<unit>/<Name>.png          -> 4096x4096 texture page (+ *_bg_*.png, postprocess_*)
skins/<unit>/spine.json          -> behaviour sidecar (animations, slots, touch …)
```

Served from raw.githubusercontent.com (jsDelivr throttles big repos). The
catalogue repo is vendored at `/opt/re-targets/mad-viewer`; the art is fetched
at extract time.

## Extraction — tools/extract-mad-viewer.py
For every `skin_list.json` entry it picks the unit (`<key>__onestore` preferred —
uncensored — else `__google`, else `<key>`), downloads the folder and rewrites it
to `assets/mad-drama/<unit>/`:

* skeleton + atlas renamed to `<unit>` (the scanner pairs skel/atlas by stem and
  names the model from the folder, so a `<Name>.skel` + `<Name>.atlas` pair
  already works — the rename just keeps ids stable);
* textures copied verbatim (the atlas references them by original name);
* `spine.json` is DROPPED — it is a sidecar, not a skeleton, and the scanner files
  every `.json` as a skeleton, so copying it would add a broken phantom model.

Result: **131 of 133** skins → 131 models. The 2 failures are the `dm_ma0001` /
`dm_ma0002` **drama** entries, whose `files.json` lists only PNGs and no skeleton
(texture-only), so they are skipped. Thumbnails come from the library's shared
`public/icons/skin/Thumbnail_<NAME>.webp` → `public/thumbs/mad-drama/` (74).

## Names + variants — applyMadNames()
`assets/mad-drama/_names.json` (unit → name/kind/store/character, built from
`characters.json`) labels each model and folds a character's rigs into one card:

* root = the **standing** rig, variants = **affection / desire / pleasure**, and
  both store builds labelled `(ONE)` / `(GP)`;
* e.g. Elisia: `Utama` · `Affection (ONE)` · `Desire (ONE)`.

93 cards from 131 models. Spine runtime 4.2 → the viewer's dedicated 4.2 stack
(pixi-spine's loader throws on 4.2, so `spineRuntime` is left null and the
client auto-detects). Render-verified: st_ch0009 root 2406 draw calls,
`Desire (ONE)` 8799, no console errors.

## Updater — tools/update-mad.py
Registered as `mad-drama` in `UPDATERS` / the client `UPDATABLE` map.
* `--check` — `git fetch` + `git show FETCH_HEAD:public/data/skin_list.json`, diff
  the skin-key set against `/opt/mad/state.json`.
* `--apply` — `git merge --ff-only FETCH_HEAD`, run the extractor for the new keys
  only, save state.

Same fetch rule as the CZN updater: no `--depth` (a shallow fetch grafts a root
that breaks `--ff-only`), merge `FETCH_HEAD`. First `--check` bootstraps the
baseline from the local catalogue.

    /srv/venv-spine/bin/python tools/extract-mad-viewer.py            # all skins
    /srv/venv-spine/bin/python tools/extract-mad-viewer.py --only af_ch0009
    /srv/venv-spine/bin/python tools/update-mad.py --check
    /srv/venv-spine/bin/python tools/update-mad.py --apply

## State
- `assets/mad-drama/` 131 models (Spine 4.2.37) → 93 cards
- `public/thumbs/mad-drama/` 74 thumbnails + `_manifest.json`
- viewer total after adding Make Drama: **38515 models**
