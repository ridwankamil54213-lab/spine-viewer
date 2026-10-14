# Daftar CDN / endpoint game (hasil bongkar `二游资源工具.exe`)

Tool Windows **`二游资源工具`** (C#/.NET, Costura/Fody) = downloader+extractor
**multi-game** (48 game). Selain alur unduh, di dalamnya tertanam **puluhan URL
CDN/API resmi** — berguna sebagai referensi saat menambah game baru.

Biner: `二游资源工具.exe` (4,2 MB) → `.NET assembly` (PE32 i386 Mono/.Net).
Decompile: `monodis --userstrings` / `monodis` (IL), atau jalankan di Windows.

## Kelas engine yang dipakai
| Kelas | Fungsi |
|---|---|
| `AssetsTools.NET.*` | baca/parse **Unity AssetBundle** |
| `AddressablesTools.*` | parse **Addressables catalog** |
| `二游资源工具.Plugins.YooAsset` | parse **YooAsset** catalog |
| `Texture.Astc.AstcDecoder` | **decode ASTC** → RGBA |
| `二游资源工具.XXTEA` | dekripsi XXTEA |
| `二游资源工具.解密相关` / `解压相关` | dekripsi & unzip |

## Game yang didukung tool (banyak sudah ada di viewer)
决战僵尸舞娘, 我推的浴姬, 放置天使, 碧海潮声, 绝对掌控, 绝顶特务X, 蜜桃乌托邦,
黑色基因, NIKKE, 万源圣魔录, 交错战线, 双穹幻想Burst, 女姬三国, 女神ALL_IN,
女神乐园, 少女三国, 少女回战, 少女战争, 放置少女, 星欲少女, 星陨计划, 梦娘龙少女,
棕色尘埃2, 樱井物语, 欲姬革命, 欲望女神, 欲洛降临, 永欲之生, 激射萌娘, 爱欲转生,
碧蓝航线, 神女觉醒, 禁域战姬, 红尘问仙, 群交避难所, 贤者同盟, 雀星, 魅欲别墅,
魔姬物语, 魔竞革命, MakeDrama…

## Metode unduh (nama method di IL)
`GetYouDianSeDownloadUrl`, `GetEroApkUrlAsync`, `GetEroGameUrlAsync`,
`GetDMMGameVerAndDownUrl`, `GetDMMGameVersion`, `GetH365ApkUrlAsync`,
`GetGameApkUrl`, `GetLatestSiteUrl`, `GetFinalUrlAsync`, `GetCountryByApiAsync`,
`DownloadList(ListUrl, BaseUrl, OnlyDownSpine)`.

## Endpoint server tool
```
http://47.76.55.11/api.php/local/local/cdn
  -> {cdn1:[cdn.nlphebei.com], cdn2:[cdn.yiyichongzhe.com], cdn3:[rpzk6rwihDDlGkb8Zc8L]}
```

## CDN / API per game (contoh penting)
- **Peachhan (女神ALL_IN?)**: `asset.peachhan.com/{amgame,m5game,mgame}asset/…/Android/*.ab`
- **OrisRies**: `assets.orisries.playhorny.com/config/cdn.json`, `soul.orixplay.com/OnigaoOutput/resources/<v>/Android/version.json`
- **BD2**: `bd2-cdn.akamaized.net/ServerData/Android/HD/<ver>/`, `mt.bd2.pmang.cloud`
- **CrossCore**: `cdn.megagamelog.com/cross/release/android/curr{,_1}/ver.bytes`
- **EroLabs/Blissful**: `cdn.taonplay.com/EroLabs/patch_config.json`, `cdn.taonplay.com/Nutaku/patch_config.json`
- **Everlusting**: `assetservice.adult-chess.com/ac/get_assets_with_als`
- **ChickGoddess**: `assetservice.chickgoddess.com/aw/get_assets_with_als`
- **Isekai SL**: `hvilla.ams3.cdn.digitaloceanspaces.com/isekai_android_bundle_1/…/Android.customManifest`
- **HornyVilla**: `hvilla.ams3.cdn.digitaloceanspaces.com/android_prod/hornyvilla/…/Android.customManifest`
- **Yokuhime**: `hvf-bundle.senpengna.com/Yokuhime/prod/1.1.7/Android/catalog_1.1.7.json`
- **NIKKE**: `global/jp/kr/sea/us-lobby.nikke-kr.com/v1/resourcehosts2`, `cloud.nikke-kr.com/route/`
- **GirlWars (JP)**: `girlwars-jp-cdncf.y2sgames.com/girlwars-jp/<ver>/Android/VersionFile.bytes`
- **Alchemy Stars??**: `lf16-c04.bytedgame.com/obj/lf-game-alisg/gdl_app_6689/HD/NewGirls_HD2Release/Android/assets/abfiles2235`
- **NewGirls**: `res2.eepgames.com/hotupdate/…`, `fx-plat-fzsn.c4games.com/common/script/clientVersion`
- **Mage Tale**: `data.lssvr.magetale.net/api/getupdateinfo.do`
- **Oathsakura / jsmn**: `data.<host>/api/getupdateinfo.do`
- **Angel mujoy**: `game.as.angel.mujoy.sg/version/outer/check_version`, `res3.angel.mujoy.sg/patch/<v>/android_extra/extra_files_info.txt`
- **DMM**: `api.store.games.dmm.com/freeapp/`, `p33-jp-prd-main.jedi-games.com:9090/p33/main/checkver`
- **Nikke-db 无关**: `demonicgirl.oss-cn-hongkong.aliyuncs.com/sailorgirl_unity/android/v7.0/`
- **Angelica Aster R**: `pro.everpp.net/api/game-assets/hash/latest/newbie-latest?platform=ANDROID`
- **灰色/其他**: `res.kaipaogames.com/18game/<v>/project.manifest`, `reload.prodjokerpacks.com/remote-assets/project.manifest`
- **YouDianSe**: `https://yodianse.com/app.js` (halaman memuat URL APK CloudFront bertanda-tangan)

## Catatan
- URL di atas adalah **nilai statis** di dalam tool; sebagian perlu token/versi
  runtime. Validasi dulu dengan `curl -sI` sebelum dipakai.
- Untuk game ber-**hot-update** (mis. IDOLSEX `chance.release.doremi.yds`): APK
  hanya berisi aset bawaan (`projectLocal.manifest`), aset Spine/HalfBody di
  unduh runtime dari CDN yang di-set lewat jawaban SDK (`media_url`).
