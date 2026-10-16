# Chaos Zero Nightmare — Rigs (community library)

Source: https://github.com/BenNoSleep/czn-animation-viewer (MIT/CC fan project,
static site, Spine 3.8 WebGL). It ships pre-decoded CZN rigs so we don't have to
wrestle the game's Yuna `.scsp`/`.sct` container ourselves.

## Repo layout
```
index.json    { rigs:[{slug,id,kind,subtype,name,thumb}] (1143),
                cutins:[{slug,id,kind,subtype,name,thumb}] (951) }
rigs/<slug>/skeleton.json   Spine 3.8.79 skeleton, GZIP-compressed JSON
rigs/<slug>/skeleton.atlas  text atlas; page line is "<slug>.webp"
rigs/<slug>/<slug>.webp     texture page
cutins/*.webp               cut-in still frames (raster, not Spine) + thumbs/
thumbs/*.png                portraits
```
Total repo ~2 GB (rigs 750 MB, cutins 353 MB).

## Integration
The viewer keys a model by its file stem, so the repo's `skeleton.json` +
`skeleton.atlas` (both stem `skeleton`) would collapse. `tools/czn-rigs.py`
rewrites each rig to the folder slug and gunzips the skeleton:
```
rigs/<slug>/{skeleton.json,skeleton.atlas,<slug>.webp}
   ->  assets/czn-rigs/<slug>/{<slug>.json,<slug>.atlas,<slug>.webp}
```
It also writes `assets/czn-rigs/_names.json` (slug -> {name, kind, subtype}) from
the repo catalog (e.g. `1056_01` -> "Rei", `30075_01` -> "Sereniel").

```bash
git clone --depth 1 --filter=blob:none --no-checkout \
  https://github.com/BenNoSleep/czn-animation-viewer.git czn-repo
cd czn-repo && git sparse-checkout init --cone && git sparse-checkout set rigs cutins index.json && git checkout
/srv/venv-spine/bin/python tools/czn-rigs.py czn-repo/rigs assets/czn-rigs czn-repo/index.json
```
`GAME_ROOTS`: `{match:"czn-rigs", key:"czn-rigs", label:"Chaos Zero Nightmare — Rigs",
spineRuntime:"3.8", pmaDefault:false}`.

## Result
1143 rigs in the viewer (total 38960 models), render-verified Spine 3.8.79:
`1056_01` calls=255 verts=987309, `30075_01` calls=235 verts=728265,
`30084_01` calls=253 verts=1020192.

## Not (yet) integrated
- (all three initial gaps are now done — see below)

## Cut-ins gallery ("a")
`cutins/` (951 WebP stills: `<id>_fhd`, `<id>_ux`, `ci_collapse_<id>_NN`) is not
Spine, so it rides the viewer's existing **image-gallery** path: the folder is
named `czn-cutins-cg` (the `-cg` suffix is the trigger) and declared in
`GAME_ROOTS` as `{match:"czn-cutins-cg", key:"czn-cutins-cg",
label:"Chaos Zero Nightmare — Cut-ins"}`. Rendered as stills (pan/zoom/export)
via `format:"image"`; `imageFile` = `/assets/czn-cutins-cg/<slug>.webp`.

## Thumbnails ("thumbs")
`tools/czn-thumbs.py` copies the library's thumbnail PNGs into
`public/thumbs/<game>/` and writes the per-game `_manifest.json` (model id ->
file), which is how the server already discovers thumbnails:
```
public/thumbs/czn-rigs/      174 png  + _manifest.json  (399 rig ids)
public/thumbs/czn-cutins-cg/ 951 png  + _manifest.json  (951 cutin ids)
```
(The rig thumbs are shared across a character's many rigs, so 174 files cover
399 entries.)

## Character names ("b")
Both games' models are relabelled from `assets/<game>/_names.json` by
`applyCznNames()` in `scanModels()`: the card name becomes e.g. `Rei — skin`
rather than `portrait 1003 front`, and a `character:{name,source,skin}` link is
attached. Names come straight from the library's `index.json`
(`1056_01`->Rei, `30075_01`->Sereniel, `1003_fhd`->Nia, …).

## Final state
- `czn-rigs` 1143 models (Spine 3.8.79, render-verified) + `czn-cutins-cg` 951
  images → **2094 cards**; viewer total **39911 models**.
- Thumb API serves 174 rig + 951 cutin thumbnails (all HTTP 200).
