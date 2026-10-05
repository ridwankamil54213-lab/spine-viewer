#!/usr/bin/env python3
"""
Angelica Aster R (当归紫苑) — Spine extractor v2.

Fixes the v1 bug: a spine MODEL can be split across several bundles — page 1
lives in one bundle, page 2/3 in others (each bundle holds one Texture2D but the
atlas may list 2–3 pages). Publishing each bundle as its own folder left 53
models with a missing page ("Halaman atlas tidak tersedia").

v2 groups bundle contents by the SKELETON NAME (`<name>.skel`) and merges the
pages, writing one folder per model: <out>/<name>/{<name>.atlas,<name>.skel,
<page1>.png,<page2>.png,...}.

Flow (no auth, no decryption):
  catalog https://ast.angelicaaster.net/res/v1/WebGL/1/catalog_r_1.<v>.<h>.bin
  bundle  https://assets.cdnangelicaaster.net/res/v1/WebGL/1/<md5>.bundle

Usage:
  extract-angelica2.py [--keys bundle-keys.txt] [--workers 24] [--out DIR]
"""
import argparse, io, os, re, ssl, tempfile, threading, time, collections
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
import UnityPy

BASE = "https://assets.cdnangelicaaster.net/res/v1/WebGL/1/"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/136"
UnityPy.config.FALLBACK_UNITY_VERSION = os.environ.get("UVER", "2022.3.58f1")
_ctx = ssl.create_default_context(); _ctx.check_hostname = False; _ctx.verify_mode = ssl.CERT_NONE


def dl(name, timeout=90, retries=4):
    for i in range(retries):
        try:
            req = urllib.request.Request(BASE + name, headers={"user-agent": UA})
            op = urllib.request.build_opener(urllib.request.HTTPSHandler(context=_ctx))
            with op.open(req, timeout=timeout) as r:
                return r.read()
        except Exception:
            if i == retries - 1:
                return None
            time.sleep(1.0 * (i + 1))


def parse_bundle(data):
    """Return dict {model_name: {'atlas':..., 'skel':..., 'pages':[(pagename, PIL)]}} or None."""
    try:
        env = UnityPy.load(io.BytesIO(data))
    except Exception:
        return None
    # collect TextAssets + textures by their base name
    atlas_by = {}
    skel_by = {}
    tex_by = {}
    for o in env.objects:
        t = o.type.name
        try:
            d = o.read()
        except Exception:
            continue
        nm = getattr(d, "m_Name", "") or ""
        if t == "TextAsset":
            raw = d.m_Script
            raw = raw.encode("utf-8", "surrogateescape") if isinstance(raw, str) else bytes(raw)
            low = nm.lower()
            if low.endswith(".atlas"):
                atlas_by[nm[:-6]] = raw
            elif low.endswith(".skel"):
                skel_by[nm[:-5]] = raw
            elif low.endswith(".json"):
                skel_by[nm[:-5]] = raw
        elif t == "Texture2D":
            try:
                tex_by[nm] = d.image
            except Exception:
                pass
    out = {}
    for base, skel in skel_by.items():
        out[base] = {"skel": skel, "atlas": atlas_by.get(base), "pages": []}
    # assign textures: a page name like "<base>_2" belongs to model <base>
    for tname, img in tex_by.items():
        owner = tname
        while owner not in out and owner:
            # strip a trailing _<n> (page index)
            parts = owner.rsplit("_", 1)
            if len(parts) == 2 and parts[1].isdigit():
                owner = parts[0]
            else:
                break
        if owner in out:
            out[owner]["pages"].append((tname, img))
    return out or None


def atlas_pages(atlas_text):
    out = []
    lines = atlas_text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    for i, ln in enumerate(lines):
        if re.match(r'^[^\s].*\.(png|jpg|jpeg)$', ln.strip()) and ln == ln.lstrip():
            for j in range(i + 1, min(i + 4, len(lines))):
                if lines[j].strip().startswith("size:"):
                    out.append(ln.strip())
                    break
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--keys", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "bundle-keys.txt"))
    ap.add_argument("--workers", type=int, default=24)
    ap.add_argument("--out", default="/opt/spine-viewer/assets/angelica")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--start", type=int, default=0)
    a = ap.parse_args()

    keys = [l.strip() for l in open(a.keys) if l.strip().endswith(".bundle")]
    if a.start or a.limit:
        keys = keys[a.start:(a.start + a.limit) if a.limit else None]
    print(f"  bundles: {len(keys)} (start={a.start})", flush=True)

    # model_name -> metadata {skel, atlas, page_src:{pagename: tempfile}}
    tmpdir = tempfile.mkdtemp(prefix="_pages-", dir=os.path.dirname(os.path.abspath(a.out.rstrip("/"))))
    print(f"  spill dir: {tmpdir}", flush=True)
    acc = {}
    lock = threading.Lock()
    st = collections.Counter()

    def work(name):
        data = dl(name)
        if not data:
            with lock:
                st["dlfail"] += 1
            return
        parsed = parse_bundle(data)
        if not parsed:
            with lock:
                st["nonspine"] += 1
            return
        with lock:
            st["spine_bundles"] += 1
            for base, d in parsed.items():
                slot = acc.setdefault(base, {"skel": None, "atlas": None, "pages": {}})
                if d["skel"] and not slot["skel"]:
                    slot["skel"] = d["skel"]
                if d["atlas"] and not slot["atlas"]:
                    slot["atlas"] = d["atlas"]
                # spill decoded pages to temp files NOW so we never hold many
                # full-size PIL images in RAM at once (that OOM'd the run).
                for pn, img in d["pages"]:
                    if pn in slot["pages"]:
                        continue
                    # save with an explicit PNG format: PIL cannot infer a
                    # format from an extension-less temp path and would raise.
                    fp = os.path.join(tmpdir, f"{base}__{re.sub(r'[^A-Za-z0-9_.-]','_',pn)}.png")
                    try:
                        img.save(fp, "PNG")
                        img.close()
                    except Exception:
                        continue
                    slot["pages"][pn] = fp

    t0 = time.time()
    with ThreadPoolExecutor(max_workers=a.workers) as ex:
        futs = {ex.submit(work, k): k for k in keys}
        for i, f in enumerate(as_completed(futs), 1):
            if i % 1000 == 0:
                print(f"  [{i}/{len(keys)}] models={len(acc)} spine_bundles={st['spine_bundles']} ({time.time()-t0:.0f}s)", flush=True)

    # write
    import shutil
    written = missing_pages = 0
    for base, d in acc.items():
        if not (d["skel"] and d["atlas"]):
            continue
        dest = os.path.join(a.out, base)
        os.makedirs(dest, exist_ok=True)
        want = atlas_pages(d["atlas"].decode("utf-8", "replace"))

        def find_page(pn):
            # The atlas page name usually carries ".png"; the Texture2D object
            # name does NOT. Try both spellings.
            for key in (pn, re.sub(r'\.(png|jpg|jpeg)$', '', pn, flags=re.I)):
                if key in d["pages"]:
                    return d["pages"][key]
            return None

        for pn in want:
            src = find_page(pn)
            if src:
                shutil.copyfile(src, os.path.join(dest, pn))
        if any(find_page(pn) is None for pn in want):
            missing_pages += 1
        ext = ".json" if d["skel"][:1] == b"{" else ".skel"
        open(os.path.join(dest, base + ext), "wb").write(d["skel"])
        open(os.path.join(dest, base + ".atlas"), "wb").write(d["atlas"])
        written += 1
    shutil.rmtree(tmpdir, ignore_errors=True)
    print(f"  DONE models={written} missing-pages={missing_pages} (bundles spine={st['spine_bundles']} nonspine={st['nonspine']} dlfail={st['dlfail']}) in {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
