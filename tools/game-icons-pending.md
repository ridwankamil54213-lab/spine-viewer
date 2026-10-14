# Game tanpa icon (belum punya `public/thumbs/_game/<key>.png`)

Icon kartu game diambil dari `public/thumbs/_game/<key>.png` (lihat
`tools/fetch-game-icons.py`). Kalau tidak ada, viewer jatuh ke badge huruf —
murni kosmetik, tapi daftar ini yang **masih perlu diisi**.

Status 2026-10-14: **19 punya icon / 38 belum** (dari 57 game yang punya model).
`azurlane-l2d` dan `lostsword-video` baru diisi dengan menyalin icon game
induknya — pola yang sama bisa dipakai untuk game turunan lain (`-cg`, `-l2d`).

## Yang sudah punya icon (19)
`alliancesages`, `alliancesages-cg`, `arkrecode`, `azurlane`, `azurlane-chibi`,
`azurlane-l2d`, `bd2`, `catshinobi`, `deposegirls`, `echocalypse`, `hazereverb`,
`lostsword`, `lostsword-video`, `nikke`, `pokerfate`, `projectqt`,
`shoujoukaisen`, `stellaraffinity`, `tenkafuma`.

## Yang BELUM punya icon (38)
| key | label | model | kandidat sumber icon |
|---|---|---|---|
| alcherystars | 白夜极光 (Alchemy Stars) | 328 | Play Store `com.tencent.baiyeint` / APK `res/` |
| angelica | Angelica Aster R (当归紫苑) | 328 | APK (Unity) → `get_app_icon()` |
| blissful | 极乐深渊 (Blissful Abyss) | 415 | APK |
| bluearchive | Bluearchive | 291 | Play Store `com.nexon.bluearchive` |
| chaoszero | Chaos Zero Nightmare | 1527 | Play Store |
| crosscore | CrossCore | 555 | CDN `cdn.megagamelog.com` (TCP-blok) / APK |
| demo | Demo | 3 | (folder uji — boleh diabaikan) |
| dotabyss | DotAbyss | 55 | `res/oj.png` (192×192, dari tools/fetch-game-icons.py catatan lama) |
| dotabyss-l2d | DotAbyss Live2D | 193 | menyusul `dotabyss` (icon sama) |
| dragontravelers | Dragon Travelers | 36 | APK |
| epic7 | Epic Seven | 1273 | Play Store `com.smilegate.epicseven` |
| everlusting | Everlusting Life | 234 | APK |
| girlwars | Girl Wars | 277 | CDN `girlwars-jp-cdncf.y2sgames.com` |
| girlwars-l2d | Girl Wars — Live2D | 84 | menyusul `girlwars` (icon sama) |
| goddessparadise | Goddessparadise | 336 | APK `com.asikagames.paradise.googleplay` |
| idleangels | Idleangels | 288 | Play Store |
| isekaislowlife | Isekaislowlife | 1539 | CDN `hvilla.ams3.cdn.digitaloceanspaces.com` |
| ivntight | イヴンタイト (IV-N-Tight) | 84 | APK |
| juezhan | 决战僵尸舞娘 | 67 | APK |
| kink | 异种啪乐町 (Kink) | 205 | Play Store `com.DrGame.Kink` |
| lostsword-video | Lost Sword — Video | 224 | ✅ sama dengan `lostsword` |
| mecharashi | 钢岚 (Mecharashi) | 125 | Play Store `com.tentree.gp.mecharashi` |
| mengqi | 梦琪领导 (President's Ambition) | 2220 | APK |
| mitao-utopia | Mitao Utopia | 252 | APK |
| muvluv | マブラヴ ガールズガーデンX | 1243 | situs resmi muvluv-girls-garden.com |
| muvluv-cg | マブラヴ ガールズガーデンX — CG | 1170 | menyusul `muvluv` (icon sama) |
| orisries | OrisRies | 301 | bundle APK (lihat `tools/extract-orisries-icons.py`) |
| peachhan | FREYA 夢姬 (Dream of Freya) | 281 | QooApp / APK LSJGAME |
| riichicity | Riichicity | 597 | APK |
| shenlan | 深蓝终末录 (Deep Blue) | 77 | APK |
| shenlan-cg | 深蓝终末录 (Deep Blue) — CG | 316 | menyusul `shenlan` (icon sama) |
| starlust | Star Lust | 178 | APK |
| stellar | Stellar Valkyries | 1302 | Play Store / youdianse 632 |
| talesofangels | Tales of Angels | 764 | Play Store |
| tenkei | 天啓パラドクスX (Tenkei Paradox X) | 682 | situs resmi |
| throne | Divine Throne | 369 | APK |
| wuhua | 物华弥新 (Neo Artifacts) | 36 | Play Store `com.cipaishe.wuhua.google` |
| xingjie | 性界大战 | 300 | APK |
| ysjh | 异世界后宫物语 | 1999 | APK |

## Cara mengisi
1. Tambahkan `("<key>", "<url>")` ke `GAMES` di `tools/fetch-game-icons.py`.
2. `/srv/venv-spine/bin/python tools/fetch-game-icons.py` → tulis `public/thumbs/_game/<key>.png` 128×128.
3. `/api/game-icons` otomatis mengenali file baru (cache di-bust oleh mtime).

> Game turunan (‑cg / ‑l2d / ‑video) bisa memakai icon yang sama dengan
> game induknya; cukup tambahkan entri dengan URL yang sama.
