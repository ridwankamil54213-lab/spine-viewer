# Girls Echo (com.girlsecho.gp) — findings

## Acquisition (worked)
APKPure serves both APK and XAPK without login:
```
HEAD/GET https://d.apkpure.com/b/XAPK/com.girlsecho.gp?version=latest
  -> 302 https://data.winudf.com/XAPK/...?filename=Girls+Echo_1.4_APKPure.xapk  (782 MB)
GET  https://d.apkpure.com/b/APK/com.girlsecho.gp?version=latest               (98 MB)
```
XAPK contents:
```
com.girlsecho.gp.apk            98 MB   (base; global-metadata.dat inside)
config.arm64_v8a.apk           132 MB   (lib/arm64-v8a/libil2cpp.so 86 MB)
install_time_asset_pack.apk    551 MB   <-- the asset pack
```
The asset pack holds `assets/assets/yoo/Default/*.bundle` — **707 Addressables
bundles, 528 MB total** (Unity 2022.3.62f2).

## Blocker: the bundles are UnityCN-encrypted
Every bundle starts with `43 78 7f 62 6f 50 45` — XOR **0x16** turns it into
`UnityFS\0` and the whole header then parses correctly:
```
UnityFS v8 · unity 5.x.x / 2022.3.62f2 · LZ4HC
blocksInfo compressed=77 uncompressed=101 · flags=0x243
flag bit 0x200 = encrypted  ->  UnityCN / ArchiveStorage
```
UnityPy confirms:
```
The BundleFile is encrypted, but no key was provided!
  key_sig = b'\x00\x00\x00\x15\x01\x00\x807\x00\x00\x80\xff\xff\xff\xffI'
  data_sig = b'f4:\xff>\xc1\xff5\x16\x16\x16\xc9\x16\x16\x16\x07'
```
This is the **UnityCN** scheme (`ArchiveStorageManager`):
`UNITY3D_SIGNATURE = b'#$unity3dchina!@'`, and the file key is recovered as
`AES-ECB(key).encrypt(key_sig) XOR data_sig == UNITY3D_SIGNATURE`.
`UnityPy.helpers.ArchiveStorageManager.brute_force_key(
  '/opt/re-targets/girlsecho/x/base/lib/arm64-v8a/libil2cpp.so', key_sig, data_sig)`
returned **None** — the 16-byte key is not a plain `\w{16}` run in libil2cpp (it is
built/obfuscated at runtime, or the sigs above are from a mis-staged buffer).

## To finish
Recover the UnityCN key from `libil2cpp.so` (86 MB) — e.g. with an il2cpp string
xref for the key setter, a runtime memory scan, or a purpose-built UnityCN key
extractor — then:
```python
UnityPy.set_assetbundle_decrypt_key(key)          # 16-byte UnityCN key
env = UnityPy.load(xor16(bundle))                 # header XOR 0x16 already needed
```
Spine skeletons would then be TextAsset `.skel`/`.atlas` inside those bundles.

**Status:** APK/XAPK + asset pack staged at `/opt/re-targets/girlsecho/`. Encrypted
like Aeons Echo / Otogi; needs the UnityCN key before anything is usable.
