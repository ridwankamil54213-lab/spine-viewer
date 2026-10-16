# SpineGods game list (resdownloader ecosystem)

Harvested 2026-10-16 from the PUBLIC endpoint
`https://resdownloader.1919810.store/game.json` (no login required).

`resdownloader.exe` (by *phtcloud_dev*, v3.3 LTS, closed-source PyInstaller app) is a
resource downloader for **90 games** across **EroLab / Nutaku / OverPower / Fanza / DMM**.
It auto-unpacks Unity bundles, extracts Spine, and decrypts assets. Its backend
platform is **SpineGods** = the Discourse forum at `https://1919810.store` (login-gated).

Two public files exist on the CDN:
- `game.json` — the id→name map below.
- `ntkaefilelist.json` — one game's asset filename list (e.g. `AVG/…`, `Heros/…`
  with `HeroBG<id>_Lv<n>.unity3d`, `*_DE_AVG<n>.unity3d`, `*_Spine<n>.unity3d`).
  The actual `.unity3d` files live on another host and need the per-file manifest.

## ID → game name

| id | game | in viewer? |
|---|---|---|
| -1 | Spine转换器 (Spine converter) | — (bug: maps to demo/spineboy) |
| 1 | 天下布魔 | no |
| 5 | 贤者同盟 | **yes** (`alliancesages`) |
| 24 | 新世界狂欢 | no |
| 27 | 樱境物语 | no |
| 32 | 星陨计划 Ark Re:Code | **yes** (`arkrecode`) |
| 38 | 姬娘物语 | no |
| 40 | 星欲少女 | no |
| 52 | 梦娘 | no (peachhan family) |
| 54 | 传奇四叶草 | no |
| 55 | 双穹幻想Burst | no |
| 75 | 龙少女 | no (peachhan `m3productionasset`) |
| 103 | 欲望女神 | no |
| 113 | 万源圣魔录 (Orisries) | partial (`orisries`) |
| 115 | Megaha:Re 异世界实干记 | no |
| 116 | 恋欲忍娘 | no |
| 135 | 魔竞革命 | no |
| 144 | 伊芙消消乐 | no |
| 153 | 禁域战姬 | no |
| 176 | 末世觉醒：唯一的他 | no |
| 182 | 欲姬革命 | no |
| 186 | 绝能回响：觉醒 | no |
| 207 | 雀星 | no |
| 211 | 女神ALL-IN | no (login/token gated — known dead-end) |
| 243 | 黑色基因 | no (NIKKE-listed) |
| 252 | 偶像性域 | no |
| 275 / 277 | 星欲姬绊 | no |
| 280 | 欲望仙界 | no |
| 281 | 华京夜探 | no |
| 9938 | 首富 / Billionaire | no |
| 9939 | MistTrainGirlsX | no |
| 9940 | Azure Taboo | no |
| 9941 | 禁断の森生活R | no |
| 9942 | Muvluv Girls Garden | **yes** (`muvluv`) |
| 9943 | 蜜桃乌托邦 | **yes** (`mitao-utopia`) |
| 9944 | Horny Waifu: Kaiju Strike | no |
| 9945 | Isekai: Waifu Overlord | no |
| 9946 | Fighting Divas | no |
| 9947 | ハーレムオブトーキョー X | no |
| 9948 | 魔女契约 | no |
| 9949 | 宝石姫 Reincarnation | no |
| 9950 | 倍率高潮 | no |
| 9951 | ドットアビスX | partial (`dotabyss`) |
| 9952 | BrownDust2 | **yes** (`bd2`) |
| 9953 | 恋華煌姫 | no |
| 9954 | レゾナンスリリウムX | no |
| 9955 | 决战僵尸舞娘 | no |
| 9956 | Angel Lust | no |
| 9957 | Harem Fantasy | no |
| 9958 | 欲洛降临 | no |
| 9959 | 青楼大掌柜 | no |
| 9960 | 天空のファンタジーR | no |
| 9961 | OP萬界神姬 | no |
| 9962 | Passion Bay | no |
| 9963 | モンスター娘TD | no |
| 9964 | Mafia Queens | no |
| 9965 | Horny Waifu: Kaiju Strike | no |
| 9966 | 深宫淫梦传 | no |
| 9967 | Sagas of Exoworld | no |
| 9968 | Twinkle Star Knights X | no |
| 9969 | Goddess Contract | no |
| 9970 | Sail Girl | no |
| 9971 | dmm战国恋姬X | no |
| 9973 | Gray Maidens | no |
| 9974 | Thrones and Beauties | **yes** (`throne`) |
| 9975 | Shelter 69 | no |
| 9976 | Dolls Division | no |
| 9977 | Lust Goddess | no |
| 9978 | Beastie Creed | no |
| 9979 | OP絕能覺醒 | no |
| 9980 | Love X Debut | no |
| 9981 | King of Kinks | **yes** (`kink`) |
| 9982 | Aeons Echo | no |
| 9983 | Freya | **yes** (`peachhan`) |
| 9984 | Zafira | no (peachhan `m3productionasset`) |
| 9985 | Project QT | **yes** (`projectqt`) |
| 9986 | Heavy Metal Babes | no |
| 9987 | Sugar Conflict | no |
| 9988 | dmm学院物語X | no |
| 9989 | dmm童话边境 | no |
| 9990 | Eros Fantasy | no |
| 9991 | dmm幻能边境 | no |
| 9992 | Waifu Shop | no |
| 9993 | Ero Dorado | no |
| 9994 | 灵魂血统 | no |
| 9995 | 帝国公主 | no |
| 9996 | dmm总统的野望 | no |
| 9997 | Everlusting Life | **yes** (`everlusting`) |
| 9998 | 首富2 / 梦琪领导 | no |

## How this was obtained (for repeatability)
1. `resdownloader.exe` is a PyInstaller onefile; the real app is downloaded at runtime
   from `…/hotupdate/<program_version>.pyd` (a **Cython-compiled** module, `loader.pyx`).
2. Running it needs a **Chinese/UTF-8 Windows** locale, else `import loader` dies in
   `encodings\cp1252.py` (UnicodeEncodeError) before any GUI appears.
3. The app logs into SpineGods (`https://1919810.store`); `game.json` itself is public.
4. The Discourse forum is fully login-gated (`*.json` → `not_logged_in`).
