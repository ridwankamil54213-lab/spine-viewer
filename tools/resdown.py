#!/usr/bin/env python3
"""resdown - CLI re-implementation of ResDownloader (SpineGods) for Linux.

Fetches Spine / Unity assets straight from public game CDNs, without the
Windows app (which is really just a per-game orchestrator: version -> manifest
-> generate URLs -> aria2c -> unpack -> decrypt).

This CLI keeps the same three-stage shape but stays data-driven, so adding a
game is a JSON entry, not a new class.

Subcommands
-----------
  catalog                     list the SpineGods games (bundled id -> name)
  list    <SOURCE>            parse a manifest/list and print matching assets
  fetch   <SOURCE>            download matching assets
  extract <BUNDLE...>|--dir   extract Spine (skel/atlas/png) from UnityFS bundles
  pipeline <SOURCE>           list -> fetch -> extract in one shot

SOURCE is either a URL or a local file. Manifest formats are auto-detected:
  * Unity/Cocos JSON manifest : {"assets": {"<name>": {"md5":..,"size":..}}}
  * CSV                       : "name,md5base64,size"   (e.g. otogi AdditionalAssets.csv)
  * JSON array of paths       : ["ui/a.png", ...]
  * newline-separated text    : one path per line

Examples
--------
  # what games exist?
  resdown catalog

  # which Spine assets does a game publish?
  resdown list https://web-assets.otogi-frontier.com/prodassets/GeneralWebGL/AssetBundlePatch/AdditionalAssets.csv \
      --base https://web-assets.otogi-frontier.com/prodassets/GeneralWebGL/Assets/ --filter '^chara/spine/'

  # download a handful
  resdown fetch <same> --filter '^chara/spine/' --out /tmp/otogi --limit 5

  # unpack what was downloaded
  resdown extract --dir /tmp/otogi/raw --out /tmp/otogi/spine
"""
from __future__ import annotations

import argparse
import base64
import concurrent.futures as cf
import hashlib
import json
import os
import re
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
UA_DEFAULT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36"


# --------------------------------------------------------------------------- #
# HTTP
# --------------------------------------------------------------------------- #
def make_opener(insecure: bool = False):
    ctx = ssl.create_default_context()
    if insecure:
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    return urllib.request.build_opener(urllib.request.HTTPSHandler(context=ctx))


def http_get(url, ua=UA_DEFAULT, timeout=60, retries=4, opener=None):
    """GET with exponential backoff. Returns (bytes, content_type)."""
    last = None
    for i in range(max(1, retries)):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": ua, "Accept": "*/*"})
            with (opener or make_opener()).open(req, timeout=timeout) as r:
                return r.read(), r.headers.get("Content-Type", "")
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(min(2 ** i, 8))
    if last is None:
        last = RuntimeError(f"GET failed: {url}")
    raise last


def http_to_file(url, dest, **kw):
    data, _ = http_get(url, **kw)
    os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)
    with open(dest, "wb") as f:
        f.write(data)
    return len(data)


def is_url(s: str) -> bool:
    return s.startswith(("http://", "https://"))


def load_source(src, **kw):
    """Return (text, base_url_hint). base_url_hint = dirname of a remote source."""
    if is_url(src):
        data, ctype = http_get(src, **kw)
        base = src.rsplit("/", 1)[0] + "/"
        try:
            return data.decode("utf-8-sig"), base
        except UnicodeDecodeError:
            return data.decode("latin-1"), base
    with open(src, "r", encoding="utf-8-sig", errors="replace") as f:
        return f.read(), os.path.dirname(os.path.abspath(src)) + "/"


# --------------------------------------------------------------------------- #
# Manifest parsing -> list of {"name", "size", "md5", "url"}
# --------------------------------------------------------------------------- #
def _b64_md5_to_hex(s: str):
    try:
        raw = base64.b64decode(s)
        if len(raw) == 16:
            return raw.hex()
    except Exception:  # noqa: BLE001
        pass
    if re.fullmatch(r"[0-9a-fA-F]{32}", s):
        return s.lower()
    return None


def parse_manifest(text: str, base: str):
    """Auto-detect manifest format. Returns (assets, detected_base)."""
    stripped = text.lstrip()

    # --- JSON ---
    if stripped[:1] in "[{":
        try:
            doc = json.loads(text)
        except json.JSONDecodeError:
            doc = None
        if doc is not None:
            if isinstance(doc, dict) and isinstance(doc.get("assets"), dict):
                # Unity / Cocos: {"assets": {name: {md5,size,..}}}
                base2 = doc.get("packageUrl") or base
                out = []
                for name, meta in doc["assets"].items():
                    if isinstance(meta, dict):
                        out.append({"name": name, "size": meta.get("size"),
                                    "md5": (meta.get("md5") or meta.get("hash")),
                                    "url": urllib.parse.urljoin(base2, name)})
                    else:
                        out.append({"name": name, "size": None, "md5": None,
                                    "url": urllib.parse.urljoin(base2, name)})
                return out, base2
            if isinstance(doc, list):
                return ([{"name": str(x), "size": None, "md5": None,
                          "url": urllib.parse.urljoin(base, str(x))} for x in doc], base)

    # --- CSV: name,md5base64,size ---
    lines = text.splitlines()
    if lines and "," in lines[0] and re.search(r"name", lines[0], re.I) and "size" in lines[0].lower():
        out = []
        for ln in lines[1:]:
            parts = ln.rstrip("\r").split(",")
            if len(parts) < 2 or not parts[0]:
                continue
            name = parts[0]
            md5 = _b64_md5_to_hex(parts[1]) if len(parts) > 1 else None
            size = None
            if len(parts) > 2 and parts[2].strip().isdigit():
                size = int(parts[2])
            out.append({"name": name, "size": size, "md5": md5,
                        "url": urllib.parse.urljoin(base, name)})
        if out:
            return out, base

    # --- plain text / newline list ---
    out = []
    for ln in lines:
        ln = ln.strip()
        if not ln or ln.startswith("#"):
            continue
        out.append({"name": ln, "size": None, "md5": None,
                    "url": urllib.parse.urljoin(base, ln)})
    return out, base


def compile_filter(pattern):
    if not pattern:
        return None
    rx = re.compile(pattern, re.I)
    return lambda name: bool(rx.search(name))


# --------------------------------------------------------------------------- #
# catalog
# --------------------------------------------------------------------------- #
def cmd_catalog(args):
    path = os.path.join(HERE, "spinegods-game.json")
    with open(path, encoding="utf-8") as f:
        games = json.load(f)
    rows = sorted(games.items(), key=lambda kv: (len(kv[0]), kv[0]))
    if args.json:
        print(json.dumps({k: v for k, v in rows}, ensure_ascii=False, indent=1))
        return
    print(f"{'id':>6}  game")
    for gid, name in rows:
        print(f"{gid:>6}  {name}")
    print(f"\n{len(games)} games (source: resdownloader.1919810.store/game.json)")


# --------------------------------------------------------------------------- #
# list / fetch / pipeline
# --------------------------------------------------------------------------- #
def _resolve_assets(src, args):
    text, hint = load_source(src, ua=args.ua, timeout=args.timeout,
                             retries=args.retries, opener=make_opener(args.insecure))
    assets, base = parse_manifest(text, hint)
    if args.base:
        base = args.base
        for a in assets:
            a["url"] = urllib.parse.urljoin(base, a["name"])
    flt = compile_filter(args.filter)
    if flt:
        assets = [a for a in assets if flt(a["name"])]
    if args.host_map:
        mapping = [kv.split("=", 1) for kv in args.host_map]
        for a in assets:
            for o, n in mapping:
                a["url"] = a["url"].replace(o, n)
    if args.limit:
        assets = assets[: args.limit]
    return assets, base


def cmd_list(args):
    assets, base = _resolve_assets(args.source, args)
    if args.json:
        print(json.dumps(assets, ensure_ascii=False, indent=1))
        return
    print(f"# base: {base}")
    print(f"# {len(assets)} assets (after filter)")
    total = 0
    for a in assets:
        sz = a.get("size")
        if isinstance(sz, int):
            total += sz
            print(f"{sz:>12,}  {a['name']}")
        else:
            print(f"{'':>12}  {a['name']}")
    if total:
        print(f"\n# total size: {total:,} bytes ({total/1048576:.1f} MiB)")


def _fetch_one(args, a):
    dest = os.path.join(args.out, "raw", a["name"])
    if os.path.exists(dest) and not args.force:
        return a["name"], os.path.getsize(dest), "cached"
    data, _ = http_get(a["url"], ua=args.ua, timeout=args.timeout,
                       retries=args.retries, opener=make_opener(args.insecure))
    if args.md5 and a.get("md5"):
        got = hashlib.md5(data).hexdigest()
        if got != a["md5"]:
            return a["name"], len(data), f"MD5 MISMATCH (want {a['md5']}, got {got})"
    os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)
    with open(dest, "wb") as f:
        f.write(data)
    return a["name"], len(data), "ok"


def cmd_fetch(args):
    assets, base = _resolve_assets(args.source, args)
    if args.dry_run:
        for a in assets:
            print(a["url"])
        return
    print(f"# {len(assets)} assets -> {args.out}/raw  ({args.jobs} jobs)")
    ok = bad = 0
    with cf.ThreadPoolExecutor(max_workers=args.jobs) as ex:
        futs = {ex.submit(_fetch_one, args, a): a for a in assets}
        for fut in cf.as_completed(futs):
            name, n, status = fut.result()
            mark = "✔" if status in ("ok", "cached") else "✘"
            print(f"  {mark} {n:>10,}  {name}   [{status}]")
            ok += status in ("ok", "cached")
            bad += status not in ("ok", "cached")
    print(f"\n# done: {ok} ok, {bad} failed")
    if args.extract and ok:
        cmd_extract(argparse.Namespace(dir=os.path.join(args.out, "raw"),
                                       out=os.path.join(args.out, "spine"),
                                       bundles=[], unity_version=args.unity_version))


# --------------------------------------------------------------------------- #
# extract (delegates to the battle-tested tools/extract-unity-spine.py)
# --------------------------------------------------------------------------- #
def cmd_extract(args):
    bundles = list(args.bundles or [])
    if args.dir:
        for root, _dirs, files in os.walk(args.dir):
            for fn in files:
                bundles.append(os.path.join(root, fn))
    # keep only UnityFS files
    unis = []
    for b in bundles:
        try:
            with open(b, "rb") as f:
                if f.read(8).startswith(b"UnityFS"):
                    unis.append(b)
        except OSError:
            continue
    if not unis:
        print("! no UnityFS bundles found to extract")
        return

    # stage bundles into a flat temp dir; the extractor matches *.bundle and
    # reads a flat listing, so give every staged file a .bundle suffix.
    staging = os.path.join(args.out, "_bundles")
    os.makedirs(staging, exist_ok=True)
    staged = []
    for i, b in enumerate(unis):
        base = re.sub(r"[^A-Za-z0-9._-]+", "_", os.path.basename(b)) or f"asset{i}"
        if not base.endswith(".bundle"):
            base += ".bundle"
        dest = os.path.join(staging, base)
        with open(b, "rb") as s, open(dest, "wb") as d:
            d.write(s.read())
        staged.append(base)

    script = os.path.join(HERE, "extract-unity-spine.py")
    env = dict(os.environ)
    env["BUNDLE_DIR"] = staging
    env["OUT"] = args.out
    env["ONLY_BUNDLES"] = ",".join(staged)
    if args.unity_version:
        env["UNITY_VERSION"] = args.unity_version
    print(f"# extracting {len(unis)} bundle(s) with {os.path.relpath(script, HERE)} -> {args.out}")
    rc = subprocess.call([sys.executable, script], env=env)
    if rc != 0:
        print(f"! extractor exited {rc}", file=sys.stderr)
        sys.exit(rc)


def cmd_pipeline(args):
    _resolve = lambda: _resolve_assets(args.source, args)  # noqa: E731
    assets, _ = _resolve()
    if not assets:
        print("! no assets matched")
        return
    if args.dry_run:
        for a in assets:
            print(a["url"])
        return
    print(f"# pipeline: {len(assets)} assets")
    ok = 0
    with cf.ThreadPoolExecutor(max_workers=args.jobs) as ex:
        futs = [ex.submit(_fetch_one, args, a) for a in assets]
        for fut in cf.as_completed(futs):
            name, n, status = fut.result()
            print(f"  {'✔' if status in ('ok', 'cached') else '✘'} {n:>10,}  {name}  [{status}]")
            ok += status in ("ok", "cached")
    raw = os.path.join(args.out, "raw")
    print(f"# fetched {ok}/{len(assets)} -> {raw}")
    cmd_extract(argparse.Namespace(dir=raw, out=os.path.join(args.out, "spine"),
                                   bundles=[], unity_version=args.unity_version))


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def add_common(p):
    p.add_argument("--ua", default=UA_DEFAULT)
    p.add_argument("--timeout", type=int, default=60)
    p.add_argument("--retries", type=int, default=4)
    p.add_argument("--insecure", action="store_true", help="skip TLS verification")
    p.add_argument("--filter", help="regex applied to asset names")
    p.add_argument("--base", help="override asset base URL")
    p.add_argument("--host-map", action="append", metavar="OLD=NEW",
                   help="rewrite a host/path prefix in asset URLs (repeatable)")
    p.add_argument("--limit", type=int, help="cap number of assets")
    p.add_argument("--json", action="store_true")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="resdown", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("catalog", help="list SpineGods games")
    c.add_argument("--json", action="store_true")
    c.set_defaults(func=cmd_catalog)

    for name, fn in (("list", cmd_list), ("fetch", cmd_fetch)):
        p = sub.add_parser(name, help=f"{name} assets from a manifest")
        p.add_argument("source", help="manifest URL or local file")
        add_common(p)
        if name == "fetch":
            p.add_argument("--out", required=True)
            p.add_argument("--jobs", type=int, default=8)
            p.add_argument("--force", action="store_true")
            p.add_argument("--md5", action="store_true", help="verify MD5 from manifest")
            p.add_argument("--dry-run", action="store_true")
            p.add_argument("--extract", action="store_true", help="run extractor afterwards")
            p.add_argument("--unity-version", default=None)
        p.set_defaults(func=fn)

    e = sub.add_parser("extract", help="extract Spine from UnityFS bundles")
    e.add_argument("bundles", nargs="*")
    e.add_argument("--dir", help="directory of bundles")
    e.add_argument("--out", required=True)
    e.add_argument("--unity-version", default=None)
    e.set_defaults(func=cmd_extract)

    pl = sub.add_parser("pipeline", help="list -> fetch -> extract")
    pl.add_argument("source")
    add_common(pl)
    pl.add_argument("--out", required=True)
    pl.add_argument("--jobs", type=int, default=8)
    pl.add_argument("--force", action="store_true")
    pl.add_argument("--md5", action="store_true")
    pl.add_argument("--dry-run", action="store_true")
    pl.add_argument("--unity-version", default=None)
    pl.set_defaults(func=cmd_pipeline)

    args = ap.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
