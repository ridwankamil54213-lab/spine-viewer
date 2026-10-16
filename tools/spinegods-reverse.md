# ResDownloader / SpineGods — reverse-engineering notes

Target: `resdownloader.exe` (https://resdownloader.1919810.store/) — closed-source
PyInstaller app by *phtcloud_dev* (v3.7 / program 390) that downloads & unpacks
Spine/Live2D/CG assets for ~90 adult games (EroLab / Nutaku / OverPower / Fanza / DMM).

## TL;DR on "remove the login"
The login is **NOT a local check** — it cannot be bypassed by patching the exe.
The real logic lives in a Cython-compiled `hotupdate/390.pyd` (x86-64, stripped,
runtime-unpacked) and the actual asset buckets are **private S3** returned as
**server-signed URLs**. The app submits your `SpineGodsUsername` to
`*.1919810.store` (`ae.php` / `secret.php`), which replies with the asset list and
signed URLs. Patch the client and the server still answers 403 — there is nothing
local to flip.

What IS reachable **without login** (and is far more useful):
1. `resdownloader.1919810.store/game.json` — id→name map of all 90 games.
2. `{aedata,nsallin,wzzydata}.1919810.store/secret.php` — per-game asset manifests
   (aedata 1144 entries, nsallin 404, wzzydata 135; mostly `Spine/*.unity3d`).
3. A ~40-entry map of the CDNs the app talks to (carved from the process dump).

## How we got here (repeatable)
The binary refuses to load under `import loader` unless the Windows console is
UTF-8 (else `encodings/cp1252.py` throws before the GUI). Instead of fighting the
packer statically we:
1. RDP'd into a Windows box (port 7777, `/sec:rdp`), drove it with `xdotool`
   against an Xvfb display.
2. Reached the desktop through the app's modal login dialog by opening a new
   shell via the **Win+R Run box** (a system hotkey that works above the modal).
3. `\\tsclient\share` (RDP drive redirect) gave full **shell exec + file I/O**
   on the Windows guest — no client-side tooling needed.
4. `certutil -urlcache -f https://live.sysinternals.com/procdump64.exe` then
   `procdump64 -ma <pid>` → 436 MB full dump of the running process.
5. Parsed the minidump with a hand-rolled reader (Memory64ListStream) to carve
   the runtime-unpacked `390.pyd` (14 MB) and grep **all** memory for URLs,
   headers, and function names. The unpacked module still had Python's
   `__doc__`/source strings, which is where the endpoint list came from.

## Endpoint / CDN map (from the dump)
Control plane (`1919810.store` family):
- `1919810.store` — SpineGods **Discourse forum** (login-gated; `*.json`→not_logged_in).
- `getuser.1919810.store/{checkid,checkuser}.php` — account lookup.
- `betasystem.1919S1810.store/api/{aelist,aentklist,gailist,wzzylist,checkcnloc,client/verify}` — POST-only.
- `aedata|nsallin|wzzydata.1919810.store/{ae.php,secret.php,ignore_list.json}` — manifests.
- `ipcheck.1919810.store/cnipcheck.php`.

Private asset buckets (need signed URLs — 403 anonymous):
`as1/as6.x.iczph.com`, `ppas.khvxz.com`, `as.mossorp.com`
`/AssetsByPlatform/CommonOrAndroid/SecretDownloadAssets/{SpinesZip,ImagesZip,videosZip,editVideoZip}/`
(`SpinesZip` = zipped Spine bundles, `Spines/<cat>/<id>_*.unity3d` = loose).

Public / testable spines (from the same dump):
`assets4.mist-train-girls.com/.../Spines/Stills/`, `sakura-pro-r18-oss.game101.cn/stg/cache/role_spine/`,
`as6.x.iczph.com`, `asset.crimsonyouma.com/adult/pc/A/`, `assets.orisries.playhorny.com/bundle/Android/art/`,
`cdn.gamezdjsmr.net/images/download_res/Android/proj.manifest` (5846 assets, `sk_*.atlas`),
`cdn.passionbay.game` (open S3 list; `spineshare_assets_all_*.bundle`),
`hvilla.ams3.cdn.digitaloceanspaces.com/isekai_android_bundle_1/...` (open),
`dl.masterofives.com/BundlesDatabase/Android/`, `cdn.megahare.com/prod/res/*`,
`game-arkre-labs.ecchi.xxx/WebGL/StreamingAssets/aa/catalog.json` (25 MB),
`waifushop.tendertroupe.com/StreamingAssets/aa/settings.json`, …

## Files
- `tools/spinegods-games.md` / `spinegods-game.json` — the 90-game catalogue.
- `tools/spinegods-data/*_secret.php` — per-game asset manifests harvested here.
- `tools/spinegods-data/gamezdjsmr-assets.json` — parsed Unity manifest (5846 entries).
