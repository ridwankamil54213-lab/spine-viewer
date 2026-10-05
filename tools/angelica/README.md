# Angelica Aster R (当归紫苑) — Spine extraction

DMM/FANZA Unity Addressables game. Spine ships as plain UnityFS bundles —
**no decryption**, but the catalog hides which bundle is which, so bundles must
be found **by content**.

## Locating the bundles

```
https://ast.angelicaaster.net/res/v1/WebGL/1/
    catalog_r_1.<ver>.<hash>.bin          # ~17 MB binary Addressables catalog
```

Download URL for a bundle (from the catalog's keys):

```
https://assets.cdnangelicaaster.net/res/v1/WebGL/1/<md5>.bundle
```

The catalog lists **43184** bundle keys, all plain `<md5>.bundle`. The
asset-group names ARE obfuscated (`ydz`, `rqk`, `ruigce`, …), and the readable
`Assets/Download/...` keys point only at runtime textures with no `chara`/`spine`
in the path — so the catalog cannot tell you which bundle holds a skeleton.

### Consequence: content scan

Spine bundles must be recognised after download:

| a SPINE bundle contains | other bundles contain |
|---|---|
| `TextAsset "<name>.atlas"` (plain atlas) | `AudioClip vo_*` (voice) |
| `TextAsset "<name>.skel"` (**plain Spine BINARY 4.0.64**) | `AnimationClip` |
| `Texture2D "<name>"` | `Sprite` / bare `Texture2D` |
| `MonoBehaviour "<name>_SkeletonData"` / `_Atlas` | `AnimatorController` |

Empirical rate: **~1.1%** of bundles are spine (11/1000 random sample) →
~450–500 models over the whole set; full download ≈ **4.6 GB** at ~110 KB/bundle.

## Gotchas

- **Unity version string is stripped** from every bundle header, so UnityPy
  fails with *"No valid Unity version found"*. Fix:
  `UnityPy.config.FALLBACK_UNITY_VERSION = "2022.3.58f1"` (the version the
  community article reports). Auto-detection still falls back per-file, but the
  assets parse correctly once the fallback is set.
- A **size filter is useless** (spine min 52 KB, non-spine p99 ≈ 532 KB, so
  filtering by size keeps 325/989 non-spine for ~3% precision) — scan content.
- The API CDN is fast enough to just stream all bundles and discard non-spine
  ones without keeping them on disk.

## Usage

```bash
# generate the key list from the catalog
python - <<'PY'
import addressablestools
cat = addressablestools.parse(open("catalog_webgl.bin","rb").read())
open("bundle-keys.txt","w").write("\n".join(k for k in cat.resources if str(k).endswith(".bundle")))
PY

/srv/venv-spine/bin/python extract-angelica.py --sample 300      # measure spine ratio
/srv/venv-spine/bin/python extract-angelica.py --extract --workers 24 \
      --out /opt/spine-viewer/assets/angelica
```

Output: `<out>/<md5>/{<md5>.atlas,<md5>.skel,<md5>.png}`.

## Tools used

- `addressablestools` (pip) — reads the binary Addressables catalog
  (`catalog.resources`, `.keys`, `.internal_ids`).
- `UnityPy` 1.25.4 with `FALLBACK_UNITY_VERSION` set.
- `violet-wdream/.Scripts` `Utils/AddressablesToolsPy/catalog_bin_reader.py`
  is the community reference for the same catalog format.
