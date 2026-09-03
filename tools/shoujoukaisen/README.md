# Shoujou Kaisen (少女廻戦)

Spine 3.8.97 — readable by pixi-spine directly, no conversion and no legacy
viewer needed (unlike Project QT).

## Source

XAPK from APKPure, 3.49 GB:

```
https://d.apkpure.com/b/XAPK/com.onemt.and.shoujokaisen?version=latest
```

Requires browser headers or it returns **403**:

```
User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) ... Chrome/120.0
Referer:    https://apkpure.com/shoujou-kaisen/com.onemt.and.shoujokaisen
```

Contents: `com.onemt.and.shoujokaisen.apk` (42 MB), `config.arm64_v8a.apk`
(45 MB), `unityAssets.apk` (**3.24 GB** — the models live here).
`unityAssets.apk` holds 19,705 entries: 18,872 `.asset`, 610 `.bnk`, 79 `.mp4`.

## Gotchas (both cost real debugging time)

1. **18 (or 23, or 25) junk bytes before the UnityFS header.** Every bundle
   starts with a stray `UnityFS\0\0\0\0\x08` + a Unity version string, THEN
   the real header. The version string varies in length, so the offset is NOT
   constant — find the **second** `UnityFS\0` and strip to it. Without this,
   UnityPy misparses and reports *"The BundleFile is encrypted, but no key was
   provided!"*, which is a red herring: the bundles are not encrypted.

   Also set `FALLBACK_UNITY_VERSION = "2022.3.62f2"`.

2. **Textures often live in a separate bundle.** `<name>_texture.asset`
   accompanies `<name>.asset`. Mining only the main bundle yields "no texture"
   for most models. Some models do embed their texture, so both must be tried.

3. **Some bundles hold TWO skeletons under the same name.** e.g.
   `ganning01` carries `Ganning01.skel` at 594 KB *and* at 410 B, plus two
   atlases (177 B and 8879 B) — same names, so pairing by stem is
   meaningless. Pick the **largest skel with the largest atlas**; that is the
   real set (verified: ganning01 258 bones, simayi01 370, tongyuan01 442).
   Matching by stem picks the truncated atlas and every region lookup fails
   with `Region not found in atlas`.

   This cost 17 models on the first full run and another 3 on the retry.

## Extraction

```sh
/root/venv-ls/bin/python tools/shoujoukaisen/extract.py \
    /root/sk-dl/unityAssets.apk /root/sk-models
```

1343 model bundles under `assets/assets/model/`. Each yields one folder:

```
<stem>/<stem>.skel     Spine 3.8.97
<stem>/<Name>.atlas    original name; page refs point at the png(s)
<stem>/<Name>.png      one or more pages (multi-page atlases are common)
```

Note the atlas keeps its **original** capitalised name while the skel is named
after the folder stem — the atlas's internal page reference is what matters,
and it matches the png we write.

## Results

**1330 models extracted, all Spine 3.8.97, 0 failures**, 587 with multi-page
atlases, 0 missing atlas pages. Test: `test-shoujoukaisen.js`.

13 of the 1343 bundles hold no Spine model at all and are correctly skipped:
most are **Live2D Cubism** rigs (`CubismMouthParameter`, `ArtMesh`, thousands
of MeshRenderers — a different format this viewer can't read), plus one
background that is only a Material/Shader.

## Icon

Taken from the APK rather than the web —
`res/drawable-xxhdpi-v11/licon.png` inside `com.onemt.and.shoujokaisen.apk`
(192×192 → 128×128). Not listed in `tools/fetch-game-icons.py` on purpose.
