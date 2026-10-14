# Game icons (kartu game di viewer)

Ikon kartu game dibaca dari `public/thumbs/_game/<game-key>.png` lewat
`GET /api/game-icons` (server hanya melaporkan file yang benar-benar ada, jadi
UI tak pernah 404). Kalau tidak ada → viewer pakai badge huruf. Murni kosmetik.
Ditampilkan dengan `object-fit: cover`, jadi **sumber kotak lebih baik**.

Status 2026-10-14: **56 icon / 57 game** — hanya `demo` (folder uji) yang kosong.

## Cara mengisi

| Sumber | Tool | Catatan |
|---|---|---|
| APK lokal (paling andal) | `tools/extract-apk-icons.py` | baca `get_app_icon()`; fallback pindai `res/**` (launcher/icon/logo) |
| Play Store / QooApp / Nutaku / situs resmi | `tools/fetch-icons-web.py` | ambil `og:image`; Nutaku `thumbnail_s.jpg` = kotak 150×150 |
| Avatar Twitter resmi (situs ter-gate umur) | `tools/fetch-icons-web.py` (`ivntight`) | via `unavatar.io/twitter/<handle>` |
| Game turunan (‑cg/‑l2d/‑video) | salin icon induk | `DERIVED` di `tools/fetch-icons-web.py` |

```bash
/srv/venv-spine/bin/python tools/extract-apk-icons.py      # dari APK di disk
/srv/venv-spine/bin/python tools/fetch-icons-web.py        # dari web + salinan turunan
```

Game turunan yang memakai icon induk: `azurlane-l2d`←azurlane,
`lostsword-video`←lostsword, `dotabyss-l2d`←dotabyss, `girlwars-l2d`←girlwars,
`muvluv-cg`←muvluv, `shenlan-cg`←shenlan.

## Icon dari APK (10)
`blissful` (res/hW.png), `wuhua` (icon_oversea.webp), `dragontravelers`
(ic_launcher.png), `juezhan` (res/D2.png), `mitao-utopia` (res/oj.png),
`throne` (ic_launcher.png), `ysjh` (res/o-.png), `stellar` (res/Xy.png),
`shenlan` (res/oj.png), `xingjie` (res/D2.png).

## Icon dari web (22)
Play Store: `angelica`, `bluearchive`, `chaoszero`, `dotabyss`,
`goddessparadise`, `idleangels`, `isekaislowlife`, `mecharashi`, `orisries`,
`riichicity`, `talesofangels`. QooApp: `alcherystars`, `epic7`, `crosscore`,
`peachhan` (FREYA 夢姬), `girlwars`, `kink`. Situs resmi: `muvluv`, `tenkei`.
Nutaku: `everlusting`, `mengqi`, `starlust`. unavatar: `ivntight`.

## Game tanpa icon (1)
`demo` — folder percobaan (3 model), boleh dibiarkan.

## Jebakan
- `fetch-game-icons.py` **path `OUT`-nya dulu hardcoded `/srv/spine-viewer/...`**
  — direktori itu TIDAK ada (repo di `/opt/spine-viewer`), jadi tak pernah
  menulis ke tempat yang dibaca server. Sekarang repo-relative.
- Jangan tebak appid Steam: `3472100` = *SEXSTELLAR* (bukan IV-N-Tight) dan
  `2972820` = *Vice* (bukan Kink). Validasi lewat `api/appdetails` (cek `name`)
  sebelum memakai `header.jpg` — salah appid = icon game lain.
- Situs FANZA/DMM 18+ mengembalikan halaman age-gate (og:image kosong) → pakai
  avatar Twitter resmi lewat `unavatar.io`.
- QooApp: `ko`/`ja`/`en` semua jalan; `og:image` = ikon game asli.
