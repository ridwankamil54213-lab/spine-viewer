# Project QT (Nutaku's Project QT)

**Status: working** — 1333 models after culling UI/banner bundles.

## The problem this game posed

Project QT ships **Spine 2.1.27** skeletons. pixi-spine 4.0.6 ships runtimes
for 3.7 / 3.8 / 4.0 / 4.1 only — none can read a 2.x binary (all four were
tried and all four failed).

## What was tried, and what the evidence showed

| Attempt | Result |
| --- | --- |
| Convert 2.1.27 → 3.8 JSON (`extract_convert.py`) | Technically **perfect**: triangles, UVs and weighted vertices all byte-identical to the source. Still **renders scrambled**. |
| Fix unsigned draw-order amounts in `spBinaryReader` | Real bug, real fix (76 → 84 models converted). Did **not** fix scrambling. |
| Setup pose only (no animation) | Still scrambled → deform timelines are not the cause. |
| Bake bone weights into static vertices | **Worse** — model fell apart completely. |
| Add `worldVerticesLength` to weighted meshes | No effect — the field was already present. |
| Re-test the 3.8 conversion through pixi-spine (2026-09-01) | **Still scrambled.** Numbers looked healthy (no exploded vertices, spans within bounds) but the picture was garbled. |

### Warning: numeric checks do not catch this

The 3.8 conversion passes every objective metric and still draws wrong:

- `worldVerticesLength` matches the vertex count
- 0 exploded vertices, 0 non-finite coordinates
- max vertex span equals the model height exactly

**Only looking at it reveals the scrambling.** Do not migrate this game back
to pixi-spine on numeric evidence alone — see the note in `src/server.js`.

## Root cause

The **data was never the problem**. Runtime 3.8's weighted-mesh path
desynchronises on the **5–11 bones per vertex** these models use: when the
runtime re-walks the weights, **8,306 of 8,403 vertices** come out >50% wrong
(e.g. a weight sum of 58.0 instead of 1.0), throwing vertices thousands of
units away.

Decisive proof: loading the **original, unconverted** `.skel` in a native
2.1.27 viewer draws every model correctly.

## The fix

Keep the original files and route this game to a runtime that reads them:

1. **`prepare_native.py`** — extracts the original `.skel` / `.atlas` /
   textures from the UnityFS bundles (no conversion).
2. **`vendor/spine2127/`** — the [Kurumifans/spine](https://github.com/Kurumifans/spine)
   viewer, a GWT build of the Spine 2.1.27 runtime. Spine Runtimes License;
   users need their own Spine license to use it. Served at `/legacy-spine/`.
3. **Server** — `detectFromBinary` now accepts major 2 (was 3–4 only), and
   `pickRuntime` returns `"legacy-2.1.27"` for it. Models get
   `spineRuntime` + `needsLegacyViewer`.
4. **Client** — `loadModel()` diverts those models to `loadLegacyModel()`,
   which swaps the stage for an iframe on `/legacy-spine/index.html?url=…`.
   `teardownLegacyViewer()` cleans up when switching back to a normal model.

## Finding the models (the filename was a trap)

The first pass only fetched bundles whose **name** contained "spine" and got
**86** models. That was badly wrong — most character bundles are called things
like `Pet1018.unity3d` or `Event_7.unity3d`.

Opening all **1930** `.unity3d` bundles instead found **1859** with a real
skeleton + atlas. `scan_bundles.py` does this by reading asset names out of
each UnityFS rather than trusting the filename.

Two gotchas along the way:

- 68 bundles had **spaces in their URL**, which `urllib` refuses outright.
  `download_all.py` now quotes the path (`safe="/:%"`).
- Bundles store the atlas under a generic name (`Skeleton.atlas`) while the
  viewer looks for `<model>.atlas`. `extract_all.py` renames it to match the
  skeleton, otherwise every model 404s on load.

## Culling

1859 includes a lot of non-character assets — buttons, banners, event UI.
Removed on request (moved to `/root/qt-removed/`, not deleted):

| Filter | Removed |
| --- | --- |
| `skill` / `attack` | 168 |
| `BirthdayEventButton`, `BirthdayEventGift`, `CarnivalButton`, `FestivalShop`, `Gashapon`, `GirlsWatchButton`, `ModelEventButton`, `StepDownGachaButton`, `VotingEventButton`, `Tarot` | 359 |

**1333 models remain.**

## Known trade-offs

The legacy viewer is a separate GWT app with its own controls, so the host
UI's timeline / skin / export controls are **disabled** for these models
rather than faked. Playback, zoom and transform live in the embedded viewer.

## Layout

```
/root/projectqt-raw/      86 downloaded .unity3d bundles (~2 GB)
/root/projectqt-native/   extracted originals (symlinked as assets/projectqt)
```

## Reproducing

```sh
# 1. Download ALL .unity3d bundles, not just the ones named "*spine*".
python3 tools/projectqt/download_all.py /tmp/qt-assets.json /root/projectqt-all

# 2. Open each bundle and report which hold a real skeleton + atlas.
/root/venv-ls/bin/python tools/projectqt/scan_bundles.py \
    /root/projectqt-all /root/qt-scan-all.txt

# 3. Extract them, renaming the atlas to match the skeleton.
/root/venv-ls/bin/python tools/projectqt/extract_all.py \
    /root/projectqt-all /root/projectqt-native2
```

`qt-assets.json` comes from
`https://us.nkrpg.com/api/system/assets` (header `X-QOOKIA-DEVICE-TYPE: web`);
bundles are served from the `download_path` CDN with the same header.

## Tests

- `test-spine-version.js` — version detection + dispatch across **every**
  game (74 skeletons, 0 failures). Catches regressions in the 2.x bounds.
- `test-projectqt-legacy.js` — the iframe swap, the legacy badge, and that
  switching back to a normal model restores the pixi-spine controls.
