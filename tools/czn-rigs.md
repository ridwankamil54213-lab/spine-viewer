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
- `cutins/` is 951 WebP stills (raster), not Spine — the viewer draws Spine only,
  so these would need the existing `<game>-cg` image-gallery path to show up.
- `_names.json` is written but the scan still labels models by slug; wiring the
  names into the model title would need a server-side mapping hook.
