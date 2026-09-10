# Live2DHub crawl — kategori 教学 (id=7, 21 topik) + /latest?page=16..20

Crawl: `https://live2dhub.com/c/7.json` (slug 教学 kosong, pakai id), `https://live2dhub.com/latest.json?page=16..20`,
isi topik via `https://live2dhub.com/raw/<id>` (87 topik di-raw).

## A. Game BARU (belum ada di assets/)

Sudah punya → di-skip: Azur Lane, BD2/棕色尘埃2, Epic7, NIKKE, 少女廻戦, CatShinobi, DeposeGirls,
DotaAbyss, DragonTravelers, Echocalypse, HazeReverb, LostSword, Orisries, PokerFate, ProjectQT,
StellarAffinity, TenkaFuma, AllianceSages, Arkrecode.

### Dari kategori 教学 (paling bernilai, semua ada tutorial lengkap)
| Game | Engine / Format | Catatan | Topik |
|---|---|---|---|
| 无期迷途 Path to Nowhere | Unity, Live2D moc3 | Cara baru SETELAH update 2026.5.14 (AS langsung tidak reliable lagi): pathID-based sort, `.fade`/`.fadeMotionList`, custom field `ControlIds`/`ControlTracks`, butuh Live2DCubismCore.dll | 6005 |
| 花亦山心之月 The Moonlit Oath | Unity + UnityCN + **custom Spine** | `.spineani` =动作 terpisah dari skel; script `MergeSkelAndAni.py` | 5701 |
| 三国志幻想大陆 | Cocos2D, **tanpa enkripsi** | hash-named files, mapping table 2–8MB, cari file terbesar (`FindLargeFiles.py`) | 5628 |
| 三国志アナザー / 幻想名将录 | Cocos2D Spine, ASTC-Beeplay, jsc xxtea | key dari `libcocos2djs.so`, `config.json` untuk restore nama file | 5608 |
| 新不良人 (+杯莫停) | cocos2djs | identik dgn 5608, FileUtils::getDataFromFile | 5904 |
| 黑色信标 BlackBeacon | UnityCN | key via `SetAssetBundleDecryptKey` → RC4 seed, ada layer `Game_Helper__Encrypt` | 5667 |
| 哥特少女勇闯恶魔城2 Sinisistar2 | Unity, **Rijndael/AES CBC+PKCS7** | tracing `RijndaelManagedTransform$$DecryptData` | 5678 |
| 银与绯 Silver and Blood | Unity PC, FakeHeader | set `resourceVersion = global`, Spine ada di `dragon2019/assets/Global_Res/HQ/UI` | 5292 |
| 奥奇传说 网页版 | Web, Spine tanpa enkripsi | `aoqi.100bt.com/h5/version.json`, brute-force ID, ~1193 spine | 5652 |
| 奥拉星 网页版 | Web, Spine tanpa enkripsi | `aola.100bt.com/h5/version.json`, pola sama | 5654 |
| 小小戰姬 / Mobile Goddess (来自黑洞的旅人) | **LayaAir** | `gwcrypto` mask dari URL → `getMaskCode`/`codec`; ada web build (F12 `console.log(gwcrypto)`) | 6190 |
| 第七史诗 SCSP v3 | — | v3 (3.8.99) parser `E7_Scsp2Json.py` (punya epic7, tapi ini versi baru) | 5799 |

### Dari /latest 16–20 (game + solusi yang sudah ketemu)
- **ミストトレインガールズ〜霧の世界の車窓から〜 X** (DMM/FANZA) — web = cocos2d, **Android/PC = Unity**; manifest `native-assets3.mist-train-girls.com/production-assets/Android/<ver>/catalog_ex_hd_*.json.br` (4846)
- **三国杀夺帅** (5236), **禁域战姬/绝区战姬** (4947), **晴空之下** (5126), **日替内室** (5144) → semua FakeHeader + hidden Unity version (2020.3.14f1)
- **蓝色星原** — UnityCN key `7a346c32336268352333356826333231`; asset `*.r` belum terpecahkan (5030)
- **樱境物语** — Nutaku/Erolab, `index.txt` protobuf/varint sejak v1.0.0 (5102)
- **Dolls Division / 浩劫前线** — signature `zbobv1`: XOR + ROR dengan key `78 21 7A 40 6F 23 62 24` (4988)
- **DMM クリムゾン妖魔大戦** — cocos, URL asset = UUID ter-base64 (decode 22-char base64 → uuid) (5147)
- **Lumina Prognosis** (FANZA) — config + uuid base64 decode (5071)
- **DeepOne** (FANZA) — API `getResource` OAuth, ada ownership check sejak akhir 2025 (5150)
- **我们的课后战争** — FANZA scenario txt, articles↔parameters (5077)
- **世界弹射物语** — `ScripterSugar/wdfp-extractor`, path wajib `dump/upload|medium_upload|small_upload` (4533)
- **催眠异世界** — **DragonBones bukan Spine** (dbbin), tidak bisa restore kurva (5043)
- **幻欲游乐园 / 幻欲游乐园2** — aelurum/AssetStudio cukup (4830)
- **MuvLuv Girls Garden X** — AddressablesTools + hidden version (4951)
- **绯染天空/绯红神约** — atlas pre-multiply → cukup ganti shader (5124)
- **绝能回响：觉醒** (5161) — cocos png: signature `9dw4r94m3`, key `n1n33n1n34`, output WebP
- **亮剑** (4960) — LZ4 stream double-buffer + ETC2
- **aftterimage** (5156) — UE4, AES key `0xD7ECDC83BDF513033C351B29BE8518A319AF70B2771846880A8BA27BBA5C701E`
- **百艳封神** — paket data sudah dishare (5081)
- **代号鸢** (5114) — teks ada di lua, cuma XOR; hook fungsi untuk dapat key

## B. Tutorial TEKNIS yang berguna (reusable, bukan game-spesifik)

1. **UnityCN key hunting** — `SetAssetBundleDecryptKey` → xref `GameAOT_AOT$$Awake` → `Game_GenerateData$$Generate`; raw string adalah RC4 seed, masih ada layer transform (5667).
2. **Identifikasi AES/Rijndael dari il2cpp** — cari `DecryptData` / `FinalDecrypt`, tentukan mode (CBC/ECB) & padding (PKCS7 vs ANSI X923) dari branch nilai 2/4 (5678).
3. **Cocos2d-js** — key xxtea ada di `libcocos2djs.so` (`AppDelegate::applicationDidFinishLaunching`: `setEncryptKey` + `jsb_set_xxtea_key`); `config.json` = restore nama file (5608/5904/5190).
4. **FakeHeader + versi Unity disembunyikan** — `PackageInstaller/Script/FakeHeader.py`, tool `https://resdownload.7sec.fun/resdownloader/`, AssetStudio Raz/AXiX (`Specify Game → FakeHeader`). Versi bisa dibaca dari asset file langsung; untuk TextAsset/Texture2D beda versi jauh tidak masalah (3156/4947/4992).
5. **Addressables terenkripsi** — XOR 4-byte key dari hash nama file (`AddressableEncryptHelp__Decrypt`), dan varian LZ4 stream double-buffer + ETC2 (4622/4960).
6. **Merge Spine multi-file / skin**:
   - gabung skel terpisah: `spine_combine_3.6.53_and_3.8.99.exe -s <folder>` (4880)
   - skin terpisah: duplikat skel/atlas/png + rename `_s1`, ganti isi atlas (5084)
   - **wajib**: nama file json/skel == atlas, kalau tidak viewer menolak (5154)
   - skala atlas: spine 4.x punya baris `scale:0.61` di atlas → harus diset saat import, kalau tidak melengkung (5189)
   - unpack atlas: `Rin-Wood/SpineAtlas` v1.0.8 (4919)
   - merge alpha png: script `merge_alpha_*.py` (5186)
7. **Extract moc3 tanpa folder Managed** — tetap bisa: AnimationClip/Animator→motion3.json, MonoBehaviour→moc3+physics3, Texture2D→texture; cocokkan PathID (4863).动作 bisa berupa `.fade.json` (4870).
8. **Web game Spine** — versi kecil `version.json` + brute-force rentang ID, pakai UN*X timestamp → versi untuk ambil manifest penuh (5652/5654).
9. **DMM/FANZA asset URL** — 22-char base64 ↔ UUID (script decode/encode uuid, 5071/5147).
10. **TextAsset terenkripsi Unity** — zlib + **MasterMemory + MessagePack** (`[MemoryTable("translation_info")]`) (5204).
11. **YooAsset** (Unity 3D baru, mis. 转职魔王X) — struktur manifest mirip struct C (5148).
12. **Protobuf/varint manual** untuk manifest Nutaku/Erolab (5102).
13. **TEA 32-bit** (火影/超杀默示录) — 32 round, delta `0x9E3779B9`, big-endian; jangan pakai so 32-bit (5225).
14. **Live2DViewerEX**: beda file wpk/lpk/spk/json; `change_cos` vs `replace_tex` vs parameter set untuk换装 (3903/1239/3900); ArtmeshOpacity untuk sembunyikan mesh error (194).
15. **Viewer alternatif**: `VirtualWaifu` (wpk/lpk/dragonbones) (5049), `ww-rm/SpineViewer` 0.12.15 (konversi skel→json 3.8.99), `chibi-gif` (konversi 3.3–3.6 → 3.8).

## C. Repo/script yang sering dipakai (kumpulan)
- `violet-wdream/.Scripts` — DecryptBundles.py, UnityCN.py, MergeSkelAndAni.py, E7_Scsp2Json.py, FindLargeFiles.py
- `violet-wdream/GamesArchive` — manifest game (AoQiChuanShuo, dll)
- `RazTools/Studio`, `aelurum/AssetStudio`, `AXiX-official/Studio`, `SiMaLaoShi/AssetStudio_Tuanjie`
- `PackageInstaller/Script` (FakeHeader.py), `PackageInstaller/DataTable`
- `Razmoth/UnityCNLive2DExtractor`, `ScripterSugar/wdfp-extractor`, `Rin-Wood/SpineAtlas`, `ww-rm/SpineViewer`
