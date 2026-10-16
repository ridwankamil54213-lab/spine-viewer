# ResDownloader 390.pyd — function inventory

Source: `loader-symbols.json` (2 491 Cython `loader.*` symbols recovered from the
live process dump) + `methods.json` (1 358 PyMethodDef name→address entries).

Totals: **775 module-level symbols**, of which **94 are named functions**; **222
classes**; the rest are lambdas/genexprs and nested `<func>.<genexpr>` entries.

## A. Module-level named functions (94)
### Update / launcher
`checkself_for_update` `checkself_for_betaupdate` `checkself_for_low` `updatechecker`
`update_games` `patchupdate` `betacheck` `betachecksln` `betacheckV2`
`canuseaedatabase` `autogetbetakey` `buyaefiles` `buycoffee` `cleartxt` `save_LANSET`
### Config / env
`load_config` `save_config` `get_location` `get_machine_code` `get_game_root_url`
`resource_pathexe` `checkcn` `has_chrome_in_current_dir` `getchromev` `reinstallchrome`
`has_7z_in_current_dir` `openpyddir` `delete_files_in_folder` `clear_notebook_tabs`
### Account / userdata
`aelogin` `nsallinlogin` `userloginself` `checkbanuser` `checkbanuserbak`
`senduserdata` `parse_tokenjson`
### Game catalogue
`fetch_game_info` `fetch_betagame_info` `getlackaefiles` `getlackgaifiles`
`custom_resource_download` `diffcustom_resource_download` `custom_resource_decoder`
### Download helpers
`download_with_aria2c` `download_and_resize_image` `download_image_if_not_exists`
`load_and_resize_image_pillow` `resizeicon_image` `getntkapkurl` `ntkapkdownload`
### Protobuf (game "yj" protocol)
`encode_varint` `encode_length_delimited` `build_protobuf` `send_requestyj`
`send_requestblackgen` `decode_varint` `decode_protobuf` `parse_responseyj` `extract_fieldyj`
### Per-game entry points (thin wrappers)
`arkresdownloader` `dggzdownloader` `hcwxdownloader` `isekaidownloader` `jdzkdownloader`
`kokresdownloaderp` `lovedx` `megaharedownloader` `mjgmdownloader` `mjgm2downloader`
`mndownloadernu` `lsndownload` `lsndownloadnu` `lsndiff` `lsndiffnu` `mndiffnu`
`nsallinlogin` `pjyntk` `blltdownload` `blltdownloadfanza` `xueyuanwuyudownload`
`ywnsdownloader` `yzplddownloader` `jsdsyls` `yfxxl` `yfyx`
### Unpack entry points
`autounpackfile` `lsnunpack` `lsnunpacknu` `nmunpacknu` `meunpack` `yjautounpack`
`mjgmautounpack` `mjgm2autounpack` `xyjhautounpack` `pjyntkautounpack` `kokautounpackp`
`run_spinecover2` `spinecover2`
### UI / misc
`main` `mainweb` `dcweb` `openpapage` `openbbspage` `openlive2dpage`
`create_game_tabs` `create_settings_tab` `debuglogout`

## B. Classes by role (222)

### AUTH / LOGIN (8)
`loginspinegoods` (Discourse: `login`, `load_cookies`, `cookies_valid`,
`save_cookies_incremental`, `update_discourse_username`, `check_api`, `load_full_json`)
`logiaeero` `logiaeop` `logiwzzyop` `nsallinloginero` `nsallinloginop18`
`nsallinlogindmm` `nsallinloginntk`
→ these share: `on_open/on_message/on_close/on_error` (websocket),
`send_login` `send_msg` `send_event` `send_heartbeat` `decode_node_socket`
`decodesevermsg` `extract_hash_from_response` `save_secret_hash` `fetch_secret_data`
`get_account_info` `getsockurl`; browser-login ones add `getosapi`
(`start_browser`, `start_proxy`, `Interceptor.response`) and `geterolabtoken`,
`logincaptcha`, `fuckcaptcha`, `is_browser_closed`.

### DOWNLOAD (82)
One class per game/variant. Canonical shape (Unity "version/manifest" games):
`load_manifest_from_bytes` → `parse_manifest` → `export_aria2_txt` → `get_game_url` → `main`.
Addressables games: `getCatalogversion`/`getMAXversionformw` + `create_patcher`.
Key ones: `mndownloader` (`get_version_json`, `generate_download_urls`, `get_bundle_path`,
`save_to_file`, `main`), `yljldownloader` (`GameFrameworkVersionParser`),
`megaharedownloaderpc` (`getCatalogversion.encrypt/.parse/.xor`, `getMAXversionformw`,
`get_unity_hash128`, `removefakehead`, `calculate_final_sha256`),
`Muvluvdownloader` (`download_catalog_bytes`, `parse_catalog_and_extract_bundles`,
`get_dynamic_paths`, `extract_dynamic_path`, `deep_find_assets_urls`),
`Passion_Baydownload`, `wzzydownloader`, `nsaidownloader`, `SailGirldownload`,
`MafiaQueensdownloader`, `HaremFantasydownloader`, `Angel_Lustdownload`,
`azuretaboodownload`, `blackgendownloadAndroid`, `mitaodownloader`,
`crimson_youmataisen_xdownloader`, `isekaidownloader`, `fightingdivas`,
`sagasofexworld`, `xssndownloaderowndatabase`, `Billionairedownloadd`, `downloadMGX`, ….

### DIFF / UPDATE (18)
`mndiff` `msjxdiffdownloader` `qtdownloaderdiff` `sqdiff` `xztmdiff` `yjdiffwin`
`yjdiffand` `lsndiffpc` `lsndiffand` `lsndiffnupc` `lsndiffnuand` `mndiffnupc`
`mndiffnuand` `mjgmdiffand` `mjgmdiffweb` `eddownloaddiff` `bd2diffdoanload`
`blackgendiffand`
→ differential updater: `calculate_md5` `compare_files` `process_diff_files`
`files_to_download` `convert_mib_to_bytes` `is_size_match` `check_local_files`.

### UNPACK (72)
`mjgmautounpack{and,web}` `lsnunpack{and,pc}` `nmunpack` `xyjhautounpack{a,pc}`
`yjautounpack{win,and}` `erodautounpack` `passionbayautounpack` `Muvluvunpack`
`bd2unpack` `isekaiautounpack` `mitaounpack` `azuretaboounpack` `cqsycunpack`
`thbjunpack` `bcunpacker` `wzzyautounpack` `xankautounpack` `Burstautounpack`, …
→ shared: `unpackmain`, `removefakehead`, `find_unityfs_offset`,
`extract_all_zips`, `unzip_file`, `unzip_skip_existing`, `unzippy`,
`decrypt_unity_asset`, `decrypt_files_in_folder`, `remove_waste_bytes`,
`shuffle16`, `sha1_hashed`, `getpasswd{,.encrypt_string,.pad,.unpad}`,
`unpack_textures_and_text`, `decode_uuid`, `has_sp_skeleton_data`, `getspresjson`,
`spinecover2`, `fixbone`.

### OTHER (42)
thumbs/icons: `download_and_resize_image`; page launchers; `zjsbb`;
`get_ntktoken`; `shelter69`; `luminaprognosisdoenload`; `oenshinshix`; etc.

## C. Shared method vocabulary (count = #classes using it)
| n | method | purpose |
|---|---|---|
| 55 | `process_file` | per-file worker |
| 47 | `sanitize_filename` | filename cleanup |
| 44 | `container_matches` | bundle/container type detect |
| 40 | `main` | entry point |
| 25 | `unpackmain` | unpack driver |
| 17 | `decrypt_unity_asset` `remove_waste_bytes` `sha1_hashed` `shuffle16` `decrypt_files_in_folder` | asset decryption (16-byte shuffle + waste-byte strip) |
| 16 | `extract_all_zips` | zip expansion |
| 15 | `unzippy` | zip |
| 14 | `decode_uuid` | uuid→path |
| 13 | `save_to_file` `resdownloader` `has_sp_skeleton_data` `adjust_extension` | url list, spine sniff |
| 12 | `get_version_info_from_manifest` `unzip_file` `unzip_skip_existing` | version/manifest |
| 11 | `parse_manifest` `getspresjson` | Unity manifest |
| 10 | `get_version_json` | version JSON |
| 9  | `export_aria2_txt` `create_patcher` | aria2c input / patch |
| 8  | `getmainurl` `load_manifest_from_bytes` | manifest |
| 7  | `generate_download_urls` `download_with_aria2` `is_size_match` `check_local_files` `convert_mib_to_bytes` `save_secret_hash` `extract_hash_from_response` | url gen / delta |

## D. Unified per-game pipeline
```
[auth if needed: loginspinegoods | logiae* | nsallinlogin*]
 -> getversion / get_version_json / get_version_info_from_manifest / getCatalogversion
 -> parse_manifest / load_manifest_from_bytes / parse_catalog_and_extract_bundles
 -> generate_download_urls (+getmainurl/get_game_url)  [diff classes: compare_files]
 -> export_aria2_txt / save_to_file
 -> download_with_aria2c (aria2c -i txt -j 32 -s 16 -x 16)
 -> *autounpack* : removefakehead -> find_unityfs_offset -> extract_all_zips
                 -> decrypt_unity_asset (shuffle16/remove_waste_bytes)
                 -> spinecover2/fixbone -> has_sp_skeleton_data -> Spine out
```
