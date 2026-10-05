# CrossCore (交错战线) — asset updater

CrossCore ships its Spine models as public AssetBundles on a resource CDN;
there is no APK unpacking step. `tools/update-crosscore.py` keeps the viewer's
`assets/crosscore/` tree in sync with that CDN.

## Source

```
https://cdn.megagamelog.com/cross/release/android/curr_1/ver.bytes
  -> .NET BinaryFormatter manifest: every AssetBundle (name, size, md5)
https://cdn.megagamelog.com/cross/release/android/curr_1/Custom/<AB name>
  -> the AssetBundle itself
```

Each `prefabs_spine_*` bundle is **self-contained**: skeleton (a TextAsset whose
payload is JSON), the atlas text, and the page texture all live in the one
bundle, so one bundle == one model and no cross-bundle texture matching is
needed.

## Bundles are FakeHeader-encoded

The bundles carry junk before the real `UnityFS` magic (the community
`FakeHeader.py` trims it with `content.rfind(b"UnityFS")`). Once trimmed,
**UnityPy reads them directly** — no dotnet / AssetStudioModCLI needed:

```python
data = raw[raw.rfind(b"UnityFS"):]        # trim_fake_header
env  = UnityPy.load(io.BytesIO(data))     # then TextAsset + Texture2D
```

Some titles also use UnityCN (needs a 32-hex key via
`UnityPy.set_assetbundle_decrypt_key`); pass it as `CROSSCORE_UNITYCN_KEY` if a
future CrossCore build turns out to need it. Without it, CN bundles simply
report an error instead of crashing.

## Usage

```sh
# apa yang baru? (cepat, ≤30s; ramah walau CDN tak terjangkau)
/srv/venv-spine/bin/python tools/update-crosscore.py --check
# unduh + ekstrak yang baru ke assets/crosscore/
/srv/venv-spine/bin/python tools/update-crosscore.py --apply
# uji tanpa jaringan, pakai ver.bytes lokal
/srv/venv-spine/bin/python tools/update-crosscore.py --check  --manifest /path/ver.bytes
/srv/venv-spine/bin/python tools/update-crosscore.py --apply  --manifest /path/ver.bytes
```

Env: `CROSSCORE_CDN` (mirror, dipisah koma), `CROSSCORE_FETCH_TIMEOUT` (detik,
default 30), `CROSSCORE_STATE` (default `/srv/spine-assets/crosscore`),
`CROSSCORE_OUT` (default `assets/crosscore`), `CROSSCORE_UNITYCN_KEY`.

## Output layout

```
assets/crosscore/<Name>/<Name>.json   (or .skel — JSON vs binary skeleton)
assets/crosscore/<Name>/<Name>.atlas
assets/crosscore/<Name>/<page>.png
```

## From the web UI

Open the CrossCore game in the viewer — a check button appears in the header
(auto-check on enter). A red dot means there is something new; clicking asks to
confirm, then downloads in the background and marks new models with a NEW badge.

## Notes / gotchas

- `assets/crosscore` may be a **symlink** into a big disk (`/srv/spine-assets`).
  The scanner and this updater both follow it; write the models, not a fresh dir.
- The CDN sits behind Volcengine (CN) and **blackholes** some hosts (TCP connect
  hangs with no error, DNS fans out to many IPs, so `urllib`/SIGALRM alone are
  not enough). Manifest fetch therefore runs in a subprocess with a hard kill;
  `--check` always returns within `CROSSCORE_FETCH_TIMEOUT` instead of hanging.
- `check()` diffs against the files **actually on disk**, not only the saved
  state, so a first run on an already-complete install reports "up to date".
- Never re-download a bundle whose size matches what is already in `downloads/`.

## History

The original extraction (`tools/extract-crosscore.py`) used AssetStudioModCLI
(batches of ~30 to avoid the ~6.5 GB RSS OOM from ASTC textures). The updater
reimplements the pipeline natively on Linux via UnityPy so the viewer can refresh
itself without the .NET toolchain.
