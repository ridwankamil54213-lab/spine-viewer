# Brown Dust 2 (bd2) updater

> **Sumber aktif: https://github.com/Zormolo/Brown-Dust-2-Assets.**
> Yang dipanggil server sekarang adalah `tools/browndust/update.py`
> (lihat README utama, section Brown Dust 2) — wrapper yang menjalankan
> `tools/update-browndust.py` lalu `tools/browndust/refresh-thumbs.py`.
> Dokumen di bawah menjelaskan skrip unduh modelnya saja.

## Pipeline model (tools/update-browndust.py)

Pulls new Spine models from the community archive repo
**`github.com/Zormolo/Brown-Dust-2-Assets`** — the only source that maps an
opaque asset id (`char000203`) onto a character AND a costume.

## Source & transport

The repo is ~5 GB and stores binaries through **Git-LFS**, but
`raw.githubusercontent.com` returns the **real bytes**, not an LFS pointer, so
no `git-lfs` install is needed. Each file is verified against the git-blob SHA
from the GitHub Trees API (`sha1("blob <len>\0" + data)`), so truncated
downloads are rejected.

The single-call `git/trees/main?recursive=1` **500s** on a repo this size, so
the tree is fetched **per category** (`git/trees/main:assets/spine/<cat>`,
7 small calls).

## Layout produced

The repo stores `assets/spine/<category>/<Character>/<Costume>/<id>.skel`.
The updater writes straight into the viewer's layout (the same one
`tools/relayout-bd2.py` builds), so new models auto-form a "family" (main
model + variant dropdown):

```
character        -> assets/bd2-char/<Character>/<Costume>/<id>.skel
other variants   -> assets/bd2-char/<Character>/<Costume>/<Jenis>/<id>.skel
                    (Jenis = Skill-Cutscene, Interaction, Light-Novel-Talk, Tersensor)
no character     -> assets/bd2/<id>/<id>.skel
   (miscellaneous / special_animation)
```

## Usage

```sh
/srv/venv-spine/bin/python tools/update-browndust.py --check   # ~5 s, JSON
/srv/venv-spine/bin/python tools/update-browndust.py --apply    # download + install
```

`--check` reports `{total, installed, new, ids}`; `--apply` adds `extracted`,
`new_ids` (full viewer ids, because BD2 spans two roots `bd2/` + `bd2-char/`)
and `new_models`. Re-running `--check` after `--apply` returns `new: 0`.

Only directories whose skeleton is not yet installed are downloaded
(skeleton-level diff), so the updater is idempotent.

## Notes

- GitHub API rate-limits unauthenticated calls to 60/h; a `--check` uses ~9.
  Set `BD2_GH_TOKEN` to raise it.
- Progress goes to **stderr**; the JSON result goes to **stdout** (the
  `/api/update/:game` contract).
- State written to `/srv/spine-assets/bd2-update/state.json`.
