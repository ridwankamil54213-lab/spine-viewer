# Azure Taboo (EroLabs / pinkcore / NuTaku) — how it was obtained

## 1. Discovered the CDN host (from the ResDownloader dump)
The `390.pyd` string table listed, for Azure Taboo:
```
https://cdn-aussetzen-bb.pinkcore.net/      # "aussetzen" = German for "taboo"
https://cdn-aussetzen-im.pinkcore.net
https://cdn-aussetzen-ls.pinkcore.net       # ls = Star Lust (already extracted)
https://cdn-aussetzen-tkfm.pinkcore.net     # tkfm = Tenka Fuma (already extracted)
```
Every `cdn-aussetzen-*` path is a catch-all returning
`{"cdn_domain": "https://<prefix>-download.pinkcore.net"}`, so Azure Taboo's
bucket is `bb-download.pinkcore.net`. That bucket is private S3 (403 on list;
needs an exact key + signed URL at runtime) → the same server-side gate as the
other ResDownloader sources.

## 2. Instead of the asset CDN, grab the APK (public)
NuTaku publishes a per-title APK download endpoint:
```
https://gi.nutaku.com/apk-info/<slug>                        -> {"version":N,"url":"…"}
https://www.nutaku.net/games/<slug>/app-update/?type=apk     -> 302 cdn1-dl.nutaku.net/…/<slug>_N.apk
```
For Azure Taboo: `azure-taboo_30.apk` (247 MB). This works for any NuTaku
title — a generic way to obtain the full client (and its bundled/offline assets).

## 3. What the APK contains
`assets/art/<...>.unity3d` (425 bundles) and 15 hero Spine bundles under
```
assets/prefab/hero/herospines/hero_<id>/hero_<id>1.unity3d
assets/hotfix/spine.unity3d
assets/art/materials/spine/renderquadsweepmaterial.unity3d
```
Each hero bundle is a plain UnityFS (magic at offset 0, no fake header) holding
a full Spine set: `TextAsset <name>.skel` (binary, `4.3.39-beta`),
`TextAsset <name>.atlas` (`pma:true`), 2–3 `Texture2D` pages, plus
`SpineAtlasAsset` / `SkeletonDataAsset` MonoBehaviours.

## 4. Extraction
```bash
/srv/venv-spine/bin/python tools/resdown.py extract \
    --dir <APK>/assets/prefab/hero/herospines --out /tmp/at-spine
# -> 15 models; plus 3 chouka_* from the UI, 18 total
```
The viewer renders them with the **4.3** runtime (`spine-pixi-v7` ^4.3.13):
`GAME_ROOTS` entry `{match:"azuretaboo", key:"azuretaboo", label:"Azure Taboo",
spineRuntime:"4.3", pmaDefault:true}`.

## 5. Beyond the APK (the rest of the catalogue)
The APK only ships a starter set; the live game streams everything else from
`bb-download.pinkcore.net`. That host is private S3, so the full set needs the
in-game session/signature — out of reach anonymously (same limit as the Spine
`SpinesZip` buckets). The APK route at least yields a working, playable subset
(18 models) and is a generic method for every NuTaku title.
