# How ResDownloader fetches game updates (reverse-engineered)

Recovered from a full process dump of `resdownloader.exe` (SpineGods, program 390).
The runtime app is a Cython module `loader.pyx` compiled to
`hotupdate/<program_version>.pyd` and downloaded into
`%LOCALAPPDATA%\resdownloader\390.pyd`, then `import loader`ed by the bootloader
(`downloader.exe`). All names below are Cython's real function/class names, which
survive inside the loaded module's string table (the module keeps its symbol table
in memory even though the on-disk `.pyd` is stripped).

There are **three independent update paths**.

## 1. Self-update (the launcher itself)
`checkself_for_update` → `is_newer_version` → `checkself_for_betaupdate`
→ `checkself_for_low` → `patchupdate` / `save_patchver` / `update_deltxt`.

```
GET https://resdownloader.1919810.store/erodownloader.json
    {latest_version, program_version, low_ver, loader_version, hash, serverurl, ...}
if is_newer_version(remote, local):
    GET https://resdownloader.1919810.store/hotupdate/<program_version>.pyd
    patchupdate()  -> write %LOCALAPPDATA%\resdownloader\<ver>.pyd
```
Constants involved: `VERSION_URL`, `MD5LIST_URL`, `PATCH_URL`, `MANIFEST_URL`,
`MANIFEST_NAME`, `MANIFEST_FILE_SIGN`, `BUILDIN_CATALOG_FILE_SIGN`,
`BUILDIN_CATALOG_VERSION`, `SUPPORTED_VERSIONS`, `GLOBAL_HASH_KEY`.

## 2. Game catalogue (which games exist / can be enabled)
`update_games`, `get_aelist`, `getnsailist`, `get_aelist`,
`getlackaefiles`, `getlackgaifiles`, plus `fetch_game_info` / `fetch_betagame_info`.

```
POST https://betasystem.1919810.store/api/{aelist,aentklist,gailist,wzzylist,checkcnloc,client/verify}
GET  https://resdownloader.1919810.store/game.json          # id -> name (90 games, public)
GET  {aedata,nsallin,wzzydata}.1919810.store/secret.php      # per-game asset filename list
```
`secret.php` is keyed on the logged-in `SpineGodsUsername`; it returns the asset
list **and** the signed URLs for the private buckets (see §4).

## 3. Per-game content update  (the interesting one)
Two flavours, chosen per game by the downloader class:

### 3a. Unity "version/manifest" games
`GameFrameworkVersionParser` (class in `yljldownloader`) parses a binary
`version` file: `xor_decrypt` → `read_7bit_encoded_int` → `read_encrypted_string`
→ `parse_assets` → `parse_resources_list` → `parse`. Entry point
`download_and_parse_manifest`. Then:
`parse_manifest` (or `load_manifest_from_bytes`) → walk the asset tree →
`generate_download_urls` → `export_aria2_txt` → `download_with_aria2c`.

### 3b. Addressables / catalog games
`getCatalogversion` / `getMAXversionformw` (after `xor`/`parse`/`encrypt`) →
`download_catalog` / `download_catalog_bytes` →
`CatalogDeserializer` / `parse_catalog_and_extract_bundles` →
`extract_catalog_url` / `extract_versioned_url` → same download tail.

### 3c. HTML/JSON listing games
`get_version_from_html`, `get_game_bin_url`, `get_game_url`,
`get_index_content`, `get_ablist`, `get_url_list`, `fetch_json`.

### Download tail (shared)
`calculate_md5`, `compare_files`, `process_diff_files`, `files_to_download`
(differential/delta updates) → write `aria2c` input txt → run
`aria2c -i <txt> -j 32 -s 16 -x 16` → `*autounpack*` / `unpackmain`
(`extract_all_zips`, `removefakehead`, `find_unityfs_offset`, `UNITYFS_MAGIC`,
`spinecover2`, `fixbone`).

## 4. Why the login can't be removed
The asset buckets are **private S3**; the app never holds a key. It sends the
`SpineGodsUsername` to `*.1919810.store/{ae.php,secret.php}` and the server returns
**time-limited signed URLs** for
`as1/as6.x.iczph.com|ppas.khvxz.com|as.mossorp.com/…/SecretDownloadAssets/…`.
Anonymous GET on the object returns `403 AccessDenied`. So the "login" is a
**server-side signing gate**, not a local branch — patching the client changes
nothing.

## 5. Function addresses (x64, ImageBase 0x180000000 as in the file header)
Found via the module's PyMethodDef tables in memory (name ptr → func ptr):

| function | VA |
|---|---|
| checkself_for_update | 0x180a0e220 |
| is_newer_version | 0x180a16ef0 |
| update_games | 0x180a9f140 |
| getversion | 0x18003dab0 |
| update_download_list | 0x180070cf0 |
| generate_download_urls | 0x1800763d0 |
| getCatalogversion | 0x1803b71b0 |
| fetch_secret_data | 0x1806bb310 |
| download_and_parse_manifest | 0x1804242c0 |
| patchupdate | 0x180aca660 |
| decrypt_version_json | 0x1804bb2c0 |
| parse_manifest | 0x1800d0e00 |
| get_version_info_from_manifest | 0x180281080 |
| main (module) | 0x180077b30 |

Ghidra's ImageBase for the rebuilt image is the ASLR base `0x7ff9ff870000`
(i.e. decompile at `0x7ff9ff870000 + (VA - 0x180000000)`).

## 6. Per-game downloader classes (222 total, one per game/variant)
Each class exposes the same shape, e.g. `mjgmdownloader{and,web}`,
`yljldownloader`, `Muvluvdownloader`, `Passion_Baydownload`, `HaremFantasydownloader`,
`Angel_Lustdownload`, `azuretaboodownload`, `blackgendownloadAndroid`,
`bd2{doanload,diffdoanload}`, `isekaidownloader`, `mitaodownloader`,
`crimson_youmataisen_xdownloader`, `sagasofexworld`, `SailGirldownload`,
`MafiaQueensdownloader`, `megaharedownloader{erolab,pc}`, `Billionairedownloadd`, …:
`load_manifest_from_bytes`, `parse_manifest`, `export_aria2_txt`, `get_game_url`,
`main`. Variants: `…diff…` = delta updater, `…and/web/pc/ios` = platform.
