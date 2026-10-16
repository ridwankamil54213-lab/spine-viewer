# Otogi Frontier (web-assets.otogi-frontier.com) — extraction status

## Source (public, no login)
The game's Addressables patch manifest is open:
```
https://web-assets.otogi-frontier.com/prodassets/GeneralWebGL/AssetBundlePatch/AdditionalAssets.csv
   name,md5base64,size            (76k rows)
https://web-assets.otogi-frontier.com/prodassets/GeneralWebGL/Assets/<name>
```
It lists **10 076** Spine bundles under `chara/spine/<id>`, plus `chara/homestand`,
`chara/bustshot`, `effect/*`, … Each `chara/spine/<id>` bundle is a plain
`UnityFS` (magic at offset 0, no fake header, no encryption), holding
`TextAsset <name>.skel` (binary, **Spine 3.6.52**) + `.atlas` (pma:true) +
Texture2D pages.

## Extraction
```bash
/srv/venv-spine/bin/python tools/resdown.py pipeline \
  "https://web-assets.otogi-frontier.com/prodassets/GeneralWebGL/AssetBundlePatch/AdditionalAssets.csv" \
  --base "https://web-assets.otogi-frontier.com/prodassets/GeneralWebGL/Assets/" \
  --filter '^chara/spine/' --limit 400 --out DIR --jobs 6 --unity-version 2022.3.32f1
```
→ 400/400 fetched, **312 models** written (skel+atlas+png), 0.22 GB.

## Blocker
Copying all 312 models into `assets/otogi/` makes the viewer **crash on the
model-cache build**: `FATAL ERROR: invalid table size — JavaScript heap out of
memory` (v8 `KeyedStoreIC_Slow`/`AddDataElement`), ~1.5 GB peak, reproducibly.
Removing the otogi tree restores the viewer (37 817 models). Not a plain heap
limit: raising `--max-old-space-size` to 4 GB does not help, and no single file
looks anomalous (largest `.skel` 803 KB, `.atlas` 4 KB, no giant `size:` line, no
odd folder names). Suspect a model whose parsed structure explodes a JS object;
needs bisecting the 312 folders to find it.

**Status:** otogi is held outside `assets/` for now. To fix: bisect the 312
folders (move half in, restart, watch `models-cache.json`), or make the server's
model scanner defensive (bail on models exceeding N attachment/region counts).
