#!/usr/bin/env python3
"""Download the BD2 JP voice lines and character icons from
github.com/myssal / Jelosus2/BD2-L2D-Viewer.

Only JP audio is fetched (KR is deliberately skipped) — 603 files, ~19 MB,
plus 199 icons (~2 MB).

Writes:
  /srv/spine-assets/bd2-media/audio/<costumeId>/<n>.webm
  /srv/spine-assets/bd2-media/icons/<costumeId>.png
  /srv/spine-assets/bd2-media/audio-manifest.json

Never pipe the download straight into an interpreter: write the file, then
parse it. Resumable — existing files of the right size are skipped.
"""
import concurrent.futures as cf
import json
import os
import re
import sys
import urllib.request

REPO = "Jelosus2/BD2-L2D-Viewer"
BRANCH = "main"
RAW = f"https://raw.githubusercontent.com/{REPO}/{BRANCH}/"
DEST = "/srv/spine-assets/bd2-media"
AUDIO_DIR = os.path.join(DEST, "audio")
ICON_DIR = os.path.join(DEST, "icons")
WORKERS = 16

ok = skipped = failed = 0
failures = []


def fetch(rel, out):
    """Download one repo path to `out`. Returns (ok, bytes, error)."""
    global ok, skipped, failed
    url = RAW + rel
    if os.path.exists(out) and os.path.getsize(out) > 0:
        return ("skip", os.path.getsize(out), None)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "spine-viewer/1.0"})
        with urllib.request.urlopen(req, timeout=90) as r:
            data = r.read()
        tmp = out + ".part"
        with open(tmp, "wb") as f:
            f.write(data)
        os.replace(tmp, out)
        return ("ok", len(data), None)
    except Exception as e:
        return ("fail", 0, str(e)[:120])


def run(jobs, label):
    global ok, skipped, failed
    done = 0
    with cf.ThreadPoolExecutor(max_workers=WORKERS) as ex:
        futs = {ex.submit(fetch, rel, out): (rel, out) for rel, out in jobs}
        for fut in cf.as_completed(futs):
            rel, out = futs[fut]
            try:
                state, n, err = fut.result()
            except Exception as e:  # noqa: BLE001
                state, n, err = "fail", 0, str(e)[:120]
            if state == "ok":
                ok += 1
            elif state == "skip":
                skipped += 1
            else:
                failed += 1
                failures.append(f"{rel}: {err}")
            done += 1
            if done % 100 == 0:
                print(f"  {label}: {done}/{len(jobs)}", flush=True)


def main():
    lst = json.load(open("/tmp/bd2-dl-list.json"))

    # --- audio: JP only -------------------------------------------------
    audio_jobs = []
    manifest = {}
    pat = re.compile(r"src/assets/audios/([^/]+)/JP/(.+)\.webm$")
    for rel in lst["jp"]:
        m = pat.search(rel)
        if not m:
            continue
        cid, base = m.group(1), m.group(2)
        # Char000101_BattleReady_1 -> keep order via the trailing index
        idx = base.rsplit("_", 1)[-1]
        out = os.path.join(AUDIO_DIR, cid, f"{idx}.webm")
        audio_jobs.append((rel, out))
        manifest.setdefault(cid, []).append({"file": f"{idx}.webm", "label": base})

    print(f"audio JP: {len(audio_jobs)} file, {len(manifest)} kostum")
    run(audio_jobs, "audio")

    # --- icons ----------------------------------------------------------
    icon_jobs = []
    icons = {}
    ipat = re.compile(r"src/assets/char_icons/icon_(.+)\.png$")
    for rel in lst["icons"]:
        m = ipat.search(rel)
        if not m:
            continue
        key = m.group(1)  # e.g. char000101
        out = os.path.join(ICON_DIR, f"{key}.png")
        icon_jobs.append((rel, out))
        icons[key] = f"{key}.png"

    print(f"icon: {len(icon_jobs)} file")
    run(icon_jobs, "icon")

    # --- manifest -------------------------------------------------------
    os.makedirs(DEST, exist_ok=True)
    with open(os.path.join(DEST, "audio-manifest.json"), "w", encoding="utf-8") as f:
        json.dump({k: sorted(v, key=lambda x: x["file"]) for k, v in sorted(manifest.items())},
                  f, ensure_ascii=False, indent=1)
    with open(os.path.join(DEST, "icon-manifest.json"), "w", encoding="utf-8") as f:
        json.dump(icons, f, ensure_ascii=False, indent=1, sort_keys=True)

    print(f"\nok={ok} skip={skipped} gagal={failed}")
    for f_ in failures[:15]:
        print("   ", f_)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
