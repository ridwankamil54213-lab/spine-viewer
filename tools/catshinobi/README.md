# Cat Shinobi (ねこ親方 / com.cookapps.catshinobi) — asset updater

Cat Shinobi is a Unity **Addressables** game. Nothing lives on a separate CDN:
every Spine skeleton ships inside the 528 MB APK split
`split_UnityDataAssetPack.apk`, in one big bundle
`assets/aa/Android/defaultlocalgroup_assets_all_*.bundle` (492 MB) plus a small
`boot_assets_*.bundle`. So the "update" is: pull the split from the device
(redroid), scan the bundles, extract only the skeletons that are not in
`assets/catshinobi/` yet.

## Usage

```sh
# what's new?  (cheap on repeat: skips the 528 MB pull when the device split
# size matches the cached copy)
/srv/venv-spine/bin/python tools/update-catshinobi.py --check
# pull + extract only the new skeletons into assets/catshinobi/
/srv/venv-spine/bin/python tools/update-catshinobi.py --apply

# offline / already-pulled:
... --check --apk /opt/catshinobi/split_UnityDataAssetPack.apk
... --apply --bundles /opt/catshinobi/aa/assets/aa/Android
```

Env: `CS_OUT` (default `assets/catshinobi`), `CS_WORK` (default
`/srv/spine-assets/catshinobi-update`), `ADB`, `ADB_SERIAL` (default
`127.0.0.1:15555`).

## Output layout

```
assets/catshinobi/<Name>/<Name>.skel
assets/catshinobi/<Name>/<Name>.atlas
assets/catshinobi/<Name>/<page>.png
```

## Gotchas (learned the hard way)

- **TextAsset must be read raw.** `obj.read().m_Script` decodes to `str` and
  corrupts binary `.skel`; parse Unity's TextAsset layout manually from
  `get_raw_data()` (int32 name_len / padded name / int32 size / bytes).
- **Never `obj.read()` a Texture2D while scanning.** Decoding all 2584 textures
  costs minutes; read `m_Width`/`m_Height` via `read_typetree()` to rank
  duplicates, then decode ONLY the pages an atlas references.
- **Duplicate texture names**: keep the LARGEST (width×height); picking the
  first saves a small page whose coordinates don't match the atlas.
- A skeleton stem may be split on underscores (`02_Hino` + `Reona_Ingame`)
  while the atlas name is one token — that's a bundle quirk, not a bug.
- The Addressables catalog is local (`catalog.bin` in the split, `m_IsLocal…`
  false but no remote profile); there is no remote group to fetch.
