# Aeons Echo (女神觉醒 / EroLabs / NuTaku, id 9982) — findings

## Two paths lead away from the models

### 1. NuTaku APK — ships only broken Spine placeholders
```
gi.nutaku.com/apk-info/aeons-echo            -> {"version":264, ...}
nutaku.net/games/aeons-echo/app-update/?type=apk
  -> cdn1-dl.nutaku.net/product/android-app/aeons-echo/aeons-echo_264.apk  (778 MB)
```
The APK bundles everything in `assets/bin/Data/data.unity3d` (703 MB, 503k
objects): 191 Spine skeletons (`skeleton.skel` / `*.skel`) + 191 atlases + a full
Sprite atlas set. **But the bundled `.skel` files do not parse**: `frameCount must
be > 0: 0`, `name cannot be null`, `String in string table must not be null`
across the 3.7/3.8/4.0/4.1/4.2/4.3 runtimes, and the renderer draws 0 calls for
every model. They are first-launch placeholders; the real skeletons stream from
the CDN. (Skeleton names are generic, so folder<->atlas pairing is also ambiguous.)

### 2. CDN — the real models, but encrypted
The ResDownloader dump gives the (public, no-login) Aeons Echo control plane:
```
https://op.echoawakening.cc/version/version.lua?channel=erolab   # version/config
https://op.echoawakening.cc/version/allres-v1.lua                 # 2302-entry asset manifest
https://cdn.echoawakening.cc/mwyjZip/                             # asset root
```
`allres-v1.lua` maps 1155 spine entries, e.g.
```
["spine/E20977/action.skel"]={"res/v1/spine/E20977/action.skel.<md5>",105845,"spine/E20977","<md5>"}
```
Fetching works anonymously:
```
GET https://cdn.echoawakening.cc/mwyjZip/res/v1/spine/E20977/action.skel.<md5>  -> 200 (105845 B)
```
**However the downloaded payload is encrypted**: it starts with a fake header
(`9dw4r94m3#`) and the whole body is high-entropy — no Spine version string
anywhere, and no zlib/gzip. This is ResDownloader's `removefakehead` case; the app
also runs a per-game decrypt step (`*autounpack*` + `shuffle16/remove_waste_bytes`).
The cipher/keys are not in the recovered symbols, so the plaintext needs the
client's decryption routine (or a runtime capture of the decrypted buffer).

## Verdict
- APK route → nothing usable (placeholders).
- CDN route → 1155 real models reachable, but **encrypted**; needs the `mwyj`
  decrypt before they render. Recorded here so the work isn't repeated; picking a
  game whose CDN serves **plain** UnityFS (e.g. Azure Taboo, or the `otogi`
  bundles) is the faster win.
