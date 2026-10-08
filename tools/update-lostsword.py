#!/usr/bin/env python3
"""Lost Sword updater (official APK source — always current).

Source: the official XAPK on APKPure, package com.wemadeconnect.aos.lostdgl.

Pipeline:
    XAPK -> UnityStreamingAssetsPack.apk  (assets/aa/Android/*.bundle)
         -> UnityPy get_raw_data() -> TextAsset (.skel/.atlas) + Texture2D (.png)

WHY get_raw_data() INSTEAD OF obj.read():
    For these bundles UnityPy decodes TextAsset.m_Script into a `str`, which
    corrupts the binary .skel (bytes >= 0x80 do not round-trip through any text
    encoding). get_raw_data() returns the untouched bytes; we then parse Unity's
    TextAsset layout ourselves:

        int32  name_len
        char[] name            (padded to 4)
        int32  data_len
        byte[] data

    Texture2D still goes through obj.read().image (Pillow).

Layout written (what the viewer reads):
    assets/lostsword/<group>/<folder>/<stem>.{skel,atlas,png}
    group  = lobbyunit | unit | pet | atlas | lainnya  (from the bundle name)
    folder = the first skeleton stem in that bundle, so a bundle that ships a
             main model plus extra skeletons (fog layers, effects) keeps them
             together and the viewer shows them as one model with variants.

Usage:
    --check     probe the current XAPK version; on a version change list what
                the new bundles add. Cheap when up to date (1-byte request).
    --apply     download the XAPK if the version changed (cached otherwise) and
                extract only the skeleton stems that are not installed yet.
    --xapk PATH use an already-downloaded XAPK instead of fetching.
    --force     ignore the version stamp and scan every bundle again.
"""
import argparse
import collections
import io
import json
import os
import re
import shutil
import struct
import sys
import time
import urllib.parse
import urllib.request
import zipfile

import UnityPy

UnityPy.config.FALLBACK_UNITY_VERSION = os.environ.get("UNITY_FALLBACK", "2021.3.0f1")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "assets", "lostsword")
CACHE = os.path.join(ROOT, "cache", "lostsword")
XAPK_CACHE = os.path.join(CACHE, "lostsword.xapk")
STATE = os.path.join(ROOT, "data", "lostsword-state.json")

PKG = "com.wemadeconnect.aos.lostdgl"
XAPK_URL = os.environ.get(
    "LOSTSWORD_XAPK_URL",
    "https://d.apkpure.net/b/XAPK/%s?version=latest" % PKG,
)
SPLIT = "UnityStreamingAssetsPack.apk"
BUNDLE_DIR = "assets/aa/Android/"
UA = "Mozilla/5.0 (Linux; Android 13)"

TEXT_ASSET = "TextAsset"
TEXTURE2D = "Texture2D"


def _log(msg):
    sys.stderr.write("[%s] %s\n" % (time.strftime("%H:%M:%S"), msg))
    sys.stderr.flush()


def safe(name):
    return os.path.basename(str(name)).replace("\\", "/").split("/")[-1].strip()


def parse_text_asset(raw):
    """Unity TextAsset: int32 name_len, name (4-aligned), int32 size, data."""
    try:
        n = struct.unpack("<i", raw[0:4])[0]
        if not (0 < n < 512):
            return None, None
        name = raw[4 : 4 + n].decode("utf-8", "replace")
        pos = 4 + n
        pos += (4 - (pos % 4)) % 4  # pad to 4-byte boundary
        size = struct.unpack("<i", raw[pos : pos + 4])[0]
        if not (0 <= size <= len(raw) - pos - 4):
            return name, None
        return name, raw[pos + 4 : pos + 4 + size]
    except Exception:
        return None, None


def referenced_pages(atlas_blob):
    """Page filenames declared in the atlas text (first bare line of each page)."""
    out = set()
    text = atlas_blob.decode("utf-8", "replace")
    for line in text.splitlines():
        if not line.strip():
            continue
        if line.startswith(" "):
            continue
        if line.lower().endswith((".png", ".jpg", ".jpeg", ".webp")):
            out.add(line.strip().lower())
        else:
            break  # first non-image bare line = start of the region table
    return out


def group_of(bundle_name):
    """Which asset group a bundle belongs to.

    The library only holds character-facing art (lobby paintings, battle
    units, pets). `prefabs_map_*` bundles carry scene backgrounds and layering
    props — hundreds of small skeletons that would bloat the library — so they
    are classified "map" and skipped by EXTRACT_GROUPS.
    """
    b = bundle_name.lower()
    if "_lobbyunit_" in b:
        return "lobbyunit"
    if "_pet_" in b:
        return "pet"
    if "_unit_" in b:
        return "unit"
    if "_atlas_" in b:
        return "atlas"
    return "map"


# Groups the updater extracts. "map" is deliberately excluded.
EXTRACT_GROUPS = {"lobbyunit", "unit", "pet", "atlas"}

# Bundle key: res_dir_[prefabs_]<group>_<name>_assets_all_<hash>.bundle
_BUNDLE_RE = re.compile(
    r"^res_dir_(?:prefabs_)?(?:lobbyunit_|pet_|unit_|atlas_)(?P<leaf>.+?)_assets_all_[0-9a-f]{8,}\.bundle$",
    re.I,
)


def folder_of(bundle_name):
    """Folder name for a bundle — its descriptive leaf.

    A model folder is named after its BUNDLE, not after the first skeleton:
    skeleton stems are NOT globally unique (many units ship a generic `ef` /
    `Back` / `Skill`), so naming folders after a stem would fuse unrelated
    models into one folder or make them collide. Bundle names are unique and
    human-readable (`prefabs_lobbyunit_cristina_bikini01` -> `cristina_bikini01`).
    """
    base = os.path.basename(bundle_name)
    leaf = _BUNDLE_RE.match(base)
    leaf = leaf.group("leaf") if leaf else base[: -len(".bundle")]
    leaf = re.sub(r"_+", "_", leaf).strip("_")
    # `prefabs_pet_pet_<name>` leaves a redundant "pet_" (the group token was
    # stripped once already); collapse it so the folder reads `moonrabbit_01`
    # instead of `pet_moonrabbit_01`.
    if leaf.lower().startswith("pet_"):
        leaf = leaf[4:]
    leaf = re.sub(r"[^0-9A-Za-z._-]", "-", leaf)
    return leaf or "model"


def pair_suffix(group, name):
    return "%s/%s" % (group, folder_of(name))


def folder_newer_than_bundle(split, name, group, folder):
    """True when the installed folder is at least as new as the bundle.

    Used by --changed to re-extract only bundles that were actually rebuilt in
    the new XAPK (bundle names carry a content hash, so a changed asset yields
    a new entry; an untouched asset keeps its old zip timestamp).
    """
    dest = os.path.join(OUT, group, folder)
    try:
        fmtime = os.path.getmtime(dest)
    except OSError:
        return False  # not installed yet -> must write
    try:
        info = split.getinfo(name)
        bt = time.mktime(tuple(info.date_time) + (0, 0, -1))
    except Exception:
        return False
    return fmtime >= bt


# --------------------------------------------------------------------------- #
# state
# --------------------------------------------------------------------------- #
def load_state():
    try:
        with open(STATE) as fh:
            return json.load(fh)
    except Exception:
        return {}


def save_state(**patch):
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    st = load_state()
    st.update(patch)
    tmp = STATE + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(st, fh)
    os.replace(tmp, STATE)


def installed_folders():
    """Keys of the model folders already on disk: "<group>/<bundle-leaf>".

    A folder is the unit of a model, so this is a folder-level set: one entry
    per installed bundle regardless of how many skeletons that folder holds
    (a character with fog/effect layers is still one bundle). This is exactly
    the bundle key, which is what makes --check idempotent and dedupes the
    redundant bundles the game ships (elizabeth vs elizabeth_special).
    """
    found = set()
    for dp, _, files in os.walk(OUT):
        rel = os.path.relpath(dp, OUT).replace(os.sep, "/")
        if rel == "." or rel.count("/") > 1:
            continue  # only <group>/<folder>
        if any(f.lower().endswith((".skel", ".json")) for f in files):
            found.add(rel.lower())
    return found


# --------------------------------------------------------------------------- #
# source: version probe + download
# --------------------------------------------------------------------------- #
def probe_version(url=XAPK_URL):
    """Cheaply learn the current version from the redirect's filename.

    A one-byte range request still returns the Location header, so this costs
    a few hundred ms instead of the ~2.6 GB download.
    """
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Range": "bytes=0-0"})
    with urllib.request.urlopen(req, timeout=60) as r:
        loc = r.headers.get("Location") or r.geturl()
        size = r.headers.get("Content-Length")
    name = urllib.parse.unquote(loc)
    m = re.search(r"_(\d+(?:\.\d+)+)_", name)
    ver = m.group(1) if m else None
    m2 = re.search(r"full_size=(\d+)", loc)
    return ver, int(m2.group(1)) if m2 else (int(size) if size and size.isdigit() else None)


def download_xapk(url, dest):
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    part = dest + ".part"
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=120) as r, open(part, "wb") as fh:
        total = int(r.headers.get("Content-Length") or 0)
        done = 0
        step = 200 * 1024 * 1024
        mark = 0
        while True:
            chunk = r.read(1024 * 1024)
            if not chunk:
                break
            fh.write(chunk)
            done += len(chunk)
            if done - mark >= step:
                mark = done
                pct = "%.0f%%" % (100 * done / total) if total else ""
                _log("  unduh %.2f GB %s" % (done / 1024**3, pct))
    os.replace(part, dest)
    _log("  XAPK: %.2f GB -> %s" % (os.path.getsize(dest) / 1024**3, dest))


def ensure_xapk(explicit=None, version=None, want_size=None):
    if explicit:
        return explicit, "given"
    if os.path.exists(XAPK_CACHE):
        if want_size and os.path.getsize(XAPK_CACHE) == want_size:
            return XAPK_CACHE, "cached"
        if not want_size:
            return XAPK_CACHE, "cached"
    _log("mengunduh XAPK (versi %s)..." % (version or "?"))
    download_xapk(XAPK_URL, XAPK_CACHE)
    return XAPK_CACHE, "downloaded"


def open_split(xapk):
    z = zipfile.ZipFile(xapk)
    return z, zipfile.ZipFile(z.open(SPLIT))


def list_bundles(split):
    return sorted(
        i.filename
        for i in split.infolist()
        if i.filename.startswith(BUNDLE_DIR) and i.filename.endswith(".bundle")
    )


# --------------------------------------------------------------------------- #
# bundle -> models
# --------------------------------------------------------------------------- #
def is_json_skeleton(blob):
    """True when a TextAsset holds a Spine JSON skeleton.

    Some models ship the skeleton as a Spine JSON with NO extension at all
    (TextAsset named "iris", "mordred", "Mercedes", …), so extension matching
    misses them entirely. Their content always opens with `{"skeleton"`.
    """
    return blob[:16].lstrip()[:11].startswith(b'{"skeleton')


def parse_bundle(data):
    """Return ({stem: {'skel'|'json':bytes,'atlas':bytes}}, {tex_stem: image}).

    A skeleton is recognised EITHER by a `.skel`/`.json` extension OR by its
    content, because Lost Sword ships some skeletons as extension-less JSON
    TextAssets. `.atlas` is always extension-matched (its first line is a page
    filename, so content sniffing is unreliable there).
    """
    env = UnityPy.load(io.BytesIO(data))
    texts, pages = {}, {}
    for obj in env.objects:
        kind = getattr(getattr(obj, "type", None), "name", "")
        if kind == TEXT_ASSET:
            nm, blob = parse_text_asset(obj.get_raw_data())
            if not (nm and blob):
                continue
            low = nm.lower()
            if low.endswith(".atlas"):
                texts.setdefault(nm.rsplit(".", 1)[0], {})["atlas"] = blob
            elif low.endswith(".skel"):
                texts.setdefault(nm.rsplit(".", 1)[0], {})["skel"] = blob
            elif low.endswith(".json") or is_json_skeleton(blob):
                texts.setdefault(nm.rsplit(".", 1)[0], {})["json"] = blob
        elif kind == TEXTURE2D:
            try:
                d = obj.read()
            except Exception:
                continue
            nm = getattr(d, "m_Name", None) or ""
            if nm:
                try:
                    pages[nm.rsplit(".", 1)[0].lower()] = (nm, d.image)
                except Exception:
                    pass
    return texts, pages


def models_of(texts, pages):
    """Pair each skeleton (binary or JSON) with its atlas + declared textures."""
    out = []
    for stem, blobs in texts.items():
        data = blobs.get("skel") or blobs.get("json")
        if not (data and blobs.get("atlas")):
            continue
        is_json = blobs.get("json") is not None
        refs = referenced_pages(blobs["atlas"])
        ref_stems = {r.rsplit(".", 1)[0] for r in refs}
        texs = []
        for lstem, (orig, img) in pages.items():
            if refs and lstem not in ref_stems:
                continue
            fname = orig if orig.lower().endswith(".png") else orig + ".png"
            texs.append((fname, img))
        out.append(
            {
                "stem": stem,
                "data": data,
                "ext": ".json" if is_json else ".skel",
                "atlas": blobs["atlas"],
                "texs": texs,
            }
        )
    return out


def model_rel_id(group, folder, stem):
    """Relative model id as the server builds it: <group>/<folder>[#<stem>].

    The server ids a multi-skeleton folder as `<group>/<folder>#<stem>` and a
    single-skeleton folder as just `<group>/<folder>` (folder == stem). Compare
    case-insensitively because the folder is lower-cased from the bundle name
    while the stem keeps its original casing.
    """
    same = stem.lower() == folder.lower()
    return "%s/%s" % (group, folder) if same else "%s/%s#%s" % (group, folder, stem)


def write_models(models, group, folder):
    dest = os.path.join(OUT, group, folder)
    # When overwriting (a changed bundle), clear first so renamed/removed
    # siblings don't linger — the folder must mirror the bundle exactly.
    if os.path.isdir(dest):
        shutil.rmtree(dest, ignore_errors=True)
    os.makedirs(dest, exist_ok=True)
    written = 0
    for m in models:
        with open(os.path.join(dest, m["stem"] + m["ext"]), "wb") as fh:
            fh.write(m["data"])
        with open(os.path.join(dest, m["stem"] + ".atlas"), "wb") as fh:
            fh.write(m["atlas"])
        for fname, img in m["texs"]:
            try:
                img.save(os.path.join(dest, fname))
            except Exception as e:  # noqa: BLE001
                _log("  ! tekstur %s gagal: %s" % (fname, e))
        written += 1
    return written, dest


# --------------------------------------------------------------------------- #
# check / apply
# --------------------------------------------------------------------------- #
def do_check(args):
    st = load_state()
    try:
        version, size = probe_version()
    except Exception as e:  # blackhole network
        _log("probe versi gagal: %s" % e)
        version, size = None, None
    installed = len(installed_folders())
    _log("versi sekarang: %s (terpasang: %s)" % (version, st.get("version") or "-"))

    if version and st.get("version") == version and not args.force:
        result = {
            "ok": True,
            "version": version,
            "installed_version": st.get("version"),
            "installed": installed,
            "new": 0,
            "note": "sudah versi terbaru",
        }
        _log("sudah versi terbaru, tidak ada yang baru")
        return result

    # A version change (or --force) needs the split to know what is new.
    try:
        xapk, how = ensure_xapk(args.xapk, version, size)
    except Exception as e:
        _log("unduh gagal: %s" % e)
        return {
            "ok": False,
            "version": version,
            "installed_version": st.get("version"),
            "installed": installed,
            "new": None,
            "error": "unduh gagal: %s" % e,
        }
    z, split = open_split(xapk)
    bundles = list_bundles(split)
    _log("bundle di XAPK: %d (%s)" % (len(bundles), how))

    known = set(st.get("bundles") or [])
    fresh = bundles if args.force or not known else [b for b in bundles if b not in known]
    have = installed_folders()
    new_total = 0
    new_ids = []
    for i, name in enumerate(fresh, 1):
        group = group_of(name)
        if group not in EXTRACT_GROUPS:
            continue  # scene maps: not part of the model library
        folder = folder_of(name)
        key = ("%s/%s" % (group, folder)).lower()
        if key in have:
            continue
        try:
            texts, pages = parse_bundle(split.read(name))
        except Exception as e:  # noqa: BLE001
            _log("  ! %s: %s" % (os.path.basename(name)[:50], e))
            continue
        for m in models_of(texts, pages):
            new_total += 1
            new_ids.append(model_rel_id(group, folder, m["stem"]))
        if i % 60 == 0:
            _log("  ...%d/%d (baru: %d)" % (i, len(fresh), new_total))
    z.close()
    _log("model baru: %d" % new_total)
    return {
        "ok": True,
        "version": version,
        "installed_version": st.get("version"),
        "installed": installed,
        "new": new_total,
        "new_bundles": len(fresh),
        "new_ids": new_ids,
        "note": "versi baru" if st.get("version") != version else "pindai ulang",
    }


def do_apply(args):
    st = load_state()
    try:
        version, size = probe_version()
    except Exception as e:  # noqa: BLE001
        _log("probe versi gagal (%s), lanjut pakai cache" % e)
        version, size = None, None

    xapk, how = ensure_xapk(args.xapk, version, size)
    _log("XAPK: %s (%s)" % (xapk, how))
    z, split = open_split(xapk)
    bundles = list_bundles(split)
    _log("bundle: %d" % len(bundles))

    known = set(st.get("bundles") or [])
    if args.force or args.changed or not known:
        fresh = bundles
    else:
        fresh = [b for b in bundles if b not in known]
    mode = "force" if args.force else "changed" if args.changed else "new"
    _log("bundle untuk dipindai: %d (%s)" % (len(fresh), mode))

    have = installed_folders()
    added, failed, skipped = [], [], 0
    map_skipped = 0
    for i, name in enumerate(fresh, 1):
        group = group_of(name)
        if group not in EXTRACT_GROUPS:
            map_skipped += 1
            continue  # scene maps: not part of the model library
        if args.only and group != args.only:
            continue
        folder = folder_of(name)
        key = pair_suffix(group, name).lower()
        if key in have and not args.force:
            # Up-to-date unless --changed and the bundle is newer than the
            # folder we already wrote from it.
            if not args.changed or folder_newer_than_bundle(split, name, group, folder):
                continue
        try:
            texts, pages = parse_bundle(split.read(name))
        except Exception as e:  # noqa: BLE001
            failed.append((name, str(e)))
            continue
        models = models_of(texts, pages)
        if not models:
            skipped += 1
            continue
        n, dest = write_models(models, group, folder)
        have.add(key)
        for m in models:
            added.append(model_rel_id(group, folder, m["stem"]))
        _log("  + %d model -> %s" % (n, os.path.relpath(dest, ROOT)))
        if i % 40 == 0:
            _log("  ...%d/%d (baru: %d)" % (i, len(fresh), len(added)))

    z.close()
    save_state(
        version=version,
        full_size=size,
        bundles=bundles,
        installed=len(installed_folders()),
        applied_at=time.strftime("%Y-%m-%d %H:%M:%S"),
    )
    _log("=== hasil: %d model ditulis, %d gagal, %d bukan-spine, %d bundle peta dilewati ===" % (len(added), len(failed), skipped, map_skipped))
    return {
        "ok": True,
        "version": version,
        "previous_version": st.get("version"),
        "added": len(added),
        "new": 0,
        "new_ids": added,
        "failed": len(failed),
        "skipped_maps": map_skipped,
        "installed": len(installed_folders()),
    }


def main():
    ap = argparse.ArgumentParser(description="Lost Sword updater")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--check", action="store_true", help="probe versi + hitung model baru")
    g.add_argument("--apply", action="store_true", help="unduh + ekstrak model baru")
    ap.add_argument("--xapk", help="pakai berkas XAPK yang sudah ada")
    ap.add_argument("--force", action="store_true", help="abaikan cap versi, pindai semua bundle")
    ap.add_argument(
        "--changed",
        action="store_true",
        help="pindai semua bundle tapi hanya tulis ulang yang berkasnya lebih baru dari folder",
    )
    ap.add_argument("--only", choices=sorted(EXTRACT_GROUPS), help="batasi ke satu grup")
    args = ap.parse_args()

    if args.xapk and not os.path.exists(args.xapk):
        ap.error("XAPK tidak ada: %s" % args.xapk)

    result = do_check(args) if args.check else do_apply(args)
    # stdout stays a single JSON blob (the server stops logging here).
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
