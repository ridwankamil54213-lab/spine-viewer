# 异种啪乐町 (Kink / com.DrGame.Kink) — extraction notes

No CDN dance needed: a community dump already contains the **AssetStudio
extraction**, so we just reorganise it.

## Source

Community RAR (live2dhub topic 5375), password `1234`:
`com.DrGame.Kink_20251121.rar` (~5.4 GB) — Google Drive id
`1ufujR5gd4vRXwtHKt5KRMvK04HCE0iTs` (MEGA + Baidu mirrors exist).

Download + unpack:

```sh
/srv/venv-spine/bin/gdown 1ufujR5gd4vRXwtHKt5KRMvK04HCE0iTs -O com.DrGame.Kink.rar
# only what we need (630 files, ~300 MB, not 5.4 GB):
7z l -p1234 com.DrGame.Kink.rar | awk 'NF>=6{print $6}' \
  | grep -E '/Spine/' | grep -iE '\.(skel|atlas|png)$' > list.txt
7z x -p1234 -oout -i@list.txt com.DrGame.Kink.rar
```

## Layout

The dump has Spine under `…/Assets/Project/Addressable/**/Spine/**`, one
triplet per model — `<stem>.skel` + `<stem>.atlas` + `<stem>.png` side by side
(all 205 skeletons paired, 0 missing):

- `Arts/CHA/<CHAxxx>/Spine/Tachie/<stem>.skel` — character tachie
- `Arts/CHA/<CHAxxx>/Spine/HCG/<stem>.skel` — HCG illustrations
- `Spine/Enemy/`, `Arts/MainPage/Spine/`, `Arts/Date/Spine/`, `Spine/Tutorial/`

Atlas declares `pma:true`, `scale:0.75`, and a single `size:4096,4096` page.

## Build

```sh
KINK_SRC=/opt/kink/out /srv/venv-spine/bin/python tools/extract-kink.py
# -> assets/kink/<stem>/{<stem>.skel,<stem>.atlas,<page>.png}   205 models
```

## Gotchas

- File names can carry a doubled suffix (`BaseBear.skel.skel`); strip only ONE
  `.skel` or the sibling `<stem>.atlas` lookup fails.
- Spine versions are mixed inside one game (4.2.20 / 4.2.36 / 4.2.40); the
  viewer's 4.2 runtime handles all of them.
