# Girl Wars JP (少女ウォーズ / com.y2sgames.girlwarsjp)

The game has **two** model types, both served by the community viewer
**`github.com/Hisyn/GW-L2D-Viewer`** (GitHub Pages for Live2D; the raw repo
for Spine files):

| kind   | source path                                                       | count | version        |
|--------|-------------------------------------------------------------------|-------|----------------|
| Spine  | `assets/spines/<id>/<spineName>.{skel,atlas,png}`                 | 139   | Spine 4.0.56   |
| Spine  | `assets/spines/<id>/cutscene/<cutsceneId>.{...}` (Ultimate variant)| 138   | Spine 4.0.56   |
| Live2D | `assets/live2dcubism/<id>/<id>.moc3` + `textures/` + `motions/`   | 84    | Cubism 4       |

Character/costume names and the exact file names per variant come from the
repo manifest `src/utils/character_list.ts` (`charName`, `costumeName`,
`spine`, `cutscene`). The file trees come from the GitHub Trees API
(`git/trees/main:src/assets/spines?recursive=1`).

## Layout produced (flattened to what the viewer reads)

```
assets/girlwars/<id>/<spineName>.skel|.atlas|.png     -> main model
assets/girlwars/<id>/ultimate/<cutsceneId>.*          -> "Ultimate" variant
    (the nested `ultimate/` folder becomes a variant in the dropdown)
assets/girlwars-l2d/<id>/<id>.moc3                    -> Live2D model
assets/girlwars-l2d/<id>/texture_0N.png               -> leaked out of textures/
    (src/live2d.js matches `texture_0N` at the model root)
assets/girlwars-l2d/<id>/motions/*.motion3.json
assets/girlwars-l2d/<id>/model3.json
data/girlwars-names.json                              -> id -> {name, costume, display}
```

`data/girlwars-names.json` is applied by the server so models show e.g.
"Tsurihime SR" / "Nene SR" instead of the bare numeric id.

## Usage

```sh
/srv/venv-spine/bin/python tools/update-girlwars.py --check   # ~2 s, JSON
/srv/venv-spine/bin/python tools/update-girlwars.py --apply    # download + install
```

`--check` reports `{version, total, installed, new, spine, live2d}`;
`--apply` adds `added`/`extracted`/`new_ids`/`new_models`/`names`. Re-running
`--check` after `--apply` returns `new: 0` (idempotent — a unit is "done" when
its folder holds a `.skel` (Spine) or `.moc3` (Live2D)).

## Gotchas

- Spine files live in the **repo**, not on GitHub Pages (`/assets/spines/...`
  there is 404s); the Live2D files are on Pages. The updater uses the raw repo
  trees to enumerate both and the Pages URLs to download.
- Live2D textures must be **flattened** to the model root: the viewer's
  `src/live2d.js` synthesises the settings itself and looks for `texture_0N`
  filenames; a `textures/` subfolder would not match.
- The `ultimate` (skill cutscene) Spine is a **variant** of the same character,
  not a separate character, so it is nested under the character folder and the
  viewer groups it into the variant dropdown.
