#!/usr/bin/env python3
"""Extract Lost Sword character videos (skill / summon cutscenes).

Lost Sword stores each character's skill & summon movies as a Unity **VideoClip**
inside `UnityDataAssetPack.apk`. The VideoClip object itself is only ~350 bytes
— it is metadata pointing at an external blob:

    m_ExternalResources.m_Source  -> "<hash>.resource"  (file in the same pack)
    m_ExternalResources.m_Offset  -> byte offset inside that .resource
    m_ExternalResources.m_Size    -> byte length
    m_OriginalPath                -> "Assets/Resources/Video/High/Skill/<Name>.mp4"

So the movie bytes live in `assets/bin/Data/<hash>.resource` at [offset, size).
We copy that slice out and name it from m_OriginalPath (extension included —
the pack holds both High .mp4 and Low .m4v variants of the same clip).

Usage:
    python tools/extract-lostsword-video.py            # uses cached XAPK
    python tools/extract-lostsword-video.py --xapk P   # explicit XAPK
    python tools/extract-lostsword-video.py --list     # inventory only
"""
import argparse
import collections
import io
import json
import os
import posixpath
import re
import sys
import zipfile

import UnityPy

UnityPy.config.FALLBACK_UNITY_VERSION = os.environ.get("UNITY_FALLBACK", "2021.3.0f1")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "assets", "lostsword-video")
CACHE = os.path.join(ROOT, "cache", "lostsword", "lostsword.xapk")
DATA_PACK = "UnityDataAssetPack.apk"
MANIFEST = os.path.join(ROOT, "data", "lostsword-videos.json")


def _log(msg):
    sys.stderr.write("[%s] %s\n" % (__import__("time").strftime("%H:%M:%S"), msg))
    sys.stderr.flush()


def scan(xapk):
    """Yield one dict per VideoClip, with its source slice + original path."""
    z = zipfile.ZipFile(xapk)
    pack = zipfile.ZipFile(z.open(DATA_PACK))
    infos = [
        i
        for i in pack.infolist()
        if i.file_size > 0 and not i.filename.startswith("META-INF")
    ]
    out = []
    for n, i in enumerate(infos, 1):
        try:
            env = UnityPy.load(io.BytesIO(pack.read(i.filename)))
        except Exception:
            continue
        for o in env.objects:
            if getattr(getattr(o, "type", None), "name", "") != "VideoClip":
                continue
            try:
                d = o.read()
            except Exception:
                continue
            er = getattr(d, "m_ExternalResources", None)
            src = getattr(er, "m_Source", None) if er else None
            if not src:
                continue
            out.append(
                {
                    "name": getattr(d, "m_Name", "?"),
                    "source": os.path.basename(str(src)),
                    "offset": int(getattr(er, "m_Offset", 0) or 0),
                    "size": int(getattr(er, "m_Size", 0) or 0),
                    "fps": getattr(d, "m_FrameRate", None),
                    "frames": getattr(d, "m_FrameCount", None),
                    "path": getattr(d, "m_OriginalPath", None)
                    or getattr(d, "m_SourceFile", None),
                }
            )
        if n % 4000 == 0:
            _log("  ...%d/%d (klip: %d)" % (n, len(infos), len(out)))
    return z, pack, out


def rel_out(path, name):
    """Destination subpath: keep the Video/<Quality>/<Category>/ tree."""
    p = (path or "").replace("\\", "/")
    m = re.search(r"Video/(.+)$", p, re.I)
    rel = m.group(1) if m else (name + ".mp4")
    rel = posixpath.normpath(rel).lstrip("/")
    rel = rel.replace("..", "_")
    if not os.path.splitext(rel)[1]:
        rel += ".mp4"
    return rel


def cmd_list(clips):
    by = collections.Counter()
    total = 0
    for c in clips:
        rel = rel_out(c["path"], c["name"])
        q = rel.split("/")[0] if "/" in rel else "?"
        by[q] += 1
        total += c["size"]
    print(
        json.dumps(
            {
                "ok": True,
                "clips": len(clips),
                "unique_names": len({c["name"] for c in clips}),
                "total_mb": round(total / 1024**2, 1),
                "by_quality": dict(by),
                "new": 0,
            },
            ensure_ascii=False,
        )
    )


def main():
    ap = argparse.ArgumentParser(description="Lost Sword video extractor")
    ap.add_argument("--xapk", default=CACHE)
    ap.add_argument("--list", action="store_true", help="inventaris saja")
    args = ap.parse_args()
    if not os.path.exists(args.xapk):
        print(json.dumps({"ok": False, "error": "XAPK tidak ada: %s" % args.xapk}))
        return 1

    _log("memindai VideoClip di %s…" % DATA_PACK)
    z, pack, clips = scan(args.xapk)
    _log("klip ditemukan: %d" % len(clips))
    if args.list:
        cmd_list(clips)
        return 0

    # Group by source .resource so each is read from the zip once.
    by_src = collections.defaultdict(list)
    for c in clips:
        by_src[c["source"]].append(c)

    added, failed, skipped = [], [], 0
    total = 0
    for n, (src, group) in enumerate(by_src.items(), 1):
        arc = DATA_PACK + "/assets/bin/Data/" + src
        # The zip may store the .resource under assets/bin/Data/.
        member = None
        for cand in ("assets/bin/Data/" + src, "assets/" + src, src):
            try:
                pack.getinfo(cand)
                member = cand
                break
            except KeyError:
                continue
        if not member:
            failed.append((src, "resource tak ada"))
            continue
        blob = pack.read(member)
        for c in group:
            rel = rel_out(c["path"], c["name"])
            dest = os.path.join(OUT, rel)
            if os.path.exists(dest) and os.path.getsize(dest) == c["size"]:
                skipped += 1
                continue
            data = blob[c["offset"] : c["offset"] + c["size"]]
            if len(data) != c["size"]:
                failed.append((rel, "ukuran %d != %d" % (len(data), c["size"])))
                continue
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            with open(dest, "wb") as fh:
                fh.write(data)
            added.append(rel)
            total += len(data)
        if n % 20 == 0:
            _log("  ...%d/%d .resource (ditulis: %d)" % (n, len(by_src), len(added)))

    os.makedirs(os.path.dirname(MANIFEST), exist_ok=True)
    with open(MANIFEST, "w") as fh:
        json.dump(
            {
                "clips": [
                    {
                        "name": c["name"],
                        "rel": rel_out(c["path"], c["name"]),
                        "fps": c["fps"],
                        "frames": c["frames"],
                        "bytes": c["size"],
                        "source": c["path"],
                    }
                    for c in sorted(clips, key=lambda x: rel_out(x["path"], x["name"]))
                ]
            },
            fh,
            indent=1,
        )

    _log("=== %d video ditulis (%.1f MB), %d dilewati, %d gagal ===" % (len(added), total / 1024**2, skipped, len(failed)))
    for f, why in failed[:8]:
        _log("   ! %s -> %s" % (f, why))
    print(
        json.dumps(
            {
                "ok": True,
                "clips": len(clips),
                "written": len(added),
                "skipped": skipped,
                "failed": len(failed),
                "mb": round(total / 1024**2, 1),
                "sample": added[:8],
                "new": 0,
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
