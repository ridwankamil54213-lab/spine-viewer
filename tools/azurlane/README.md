# Azur Lane (azurlane) updater — ship skins (spine paintings)

Pulls new character skins from the community repo
**`github.com/ww-rm/azurlane_spinepainting`** (碧蓝航线 dynamic painting
archive). Covers the `azurlane` game root — the ship skins. The
`azurlane-chibi` root (SD chibi models) is a **different asset set** and is not
handled here.

## Source

- `docs/index.json` maps `ship -> skins -> {skelName, atlasName, pages[]}`
  (plus Chinese `chName`s) — everything needed to fetch and place a model.
- Files live at `docs/<Ship>/<Skin>/<name>` and are fetched through
  `raw.githubusercontent.com`, which is **not** subject to the GitHub **API**
  rate limit (only 2 requests per check: 1 for the index; the rest are raw
  downloads). No token needed.

## Layout produced

```
assets/azurlane/<Skin>/<Skin>.skel
assets/azurlane/<Skin>/<Skin>.atlas
assets/azurlane/<Skin>/<page>.png     (every page the atlas lists)
```

Exactly what the viewer reads (one folder = one model). `data/azurlane-names.json`
gains an entry (`shipName`/`skinName`/`displayName`) for each new skin from the
repo's Chinese names, so new models show a real name with no editing.

## Usage

```sh
/srv/venv-spine/bin/python tools/update-azurlane.py --check   # ~0.3 s, JSON
/srv/venv-spine/bin/python tools/update-azurlane.py --apply    # download + install
```

`--check` returns `{version, previous, changed, total, installed, new, ids}`
(`version` = sha1 of the index, so an unchanged index means `changed: false`).
`--apply` adds `added`/`extracted`/`new_ids`/`new_models`/`namesAdded`.
Re-running `--check` after `--apply` returns `new: 0`.

Diff is at skeleton level (a skin is "new" only if none of its skeleton stems is
installed), so it is idempotent. HTML error pages that a raw fetch may return
are rejected before they are written as a `.skel`.

## Notes

- Progress goes to **stderr**, the JSON result to **stdout**
  (`/api/update/:game` contract). State: `/srv/spine-assets/azurlane-update/state.json`.
- Because BD2-style "family" grouping is not used here, new ids are exactly
  `azurlane/<Skin>`; the updater reports them in `new_ids`.
