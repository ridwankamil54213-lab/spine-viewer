#!/usr/bin/env python3
"""Pembaru イヴンタイト (IV-N-Tight, DMM/FANZA, Dieselmine).

Build Unity WebGL-nya memakai **Unity Addressables** dengan konten remote di:

    https://eventight-sb.webaccel.saikyo.biz/dmm4sb/Unity6/Addressable_Test2/WebGL/
        catalog_0.0.1.json            (katalog, 3.2 MB)
        <hash>.bundle                 (1189 bundle; 226 di antaranya
                                       iv_characterdata_* = model Spine)

Model Spine (JSON 4.2.38/4.2.43) ada di dalam bundle sebagai TextAsset
`<nama>.json` + `<nama>.atlas`, dengan teksturnya Texture2D.

Alur:
    1. unduh catalog_0.0.1.json, parse dgn AddressablesTools
    2. untuk tiap aset ber-'spine', ambil DependencyKey -> bundle
    3. unduh bundle, buka dgn UnityPy, tulis TextAsset(.json/.atlas) + Texture2D(.png)
       ke assets/ivntight/<nama>/   (idempoten: bundle yg sudah diekstrak dilewati)

Pemakaian:
    /srv/venv-spine/bin/python tools/update-ivntight.py --check
    /srv/venv-spine/bin/python tools/update-ivntight.py --apply
"""
import argparse
import hashlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASSETS = os.path.join(ROOT, "assets")
OUT = os.environ.get("IVN_OUT", os.path.join(ASSETS, "ivntight"))
STATE_DIR = os.environ.get("IVN_STATE_DIR", "/srv/spine-assets/ivntight-update")
STATE_FILE = os.path.join(STATE_DIR, "state.json")
BUNDLE_DIR = os.path.join(STATE_DIR, "bundles")
NAMES = os.path.join(ROOT, "data", "ivntight-names.json")

CDN = os.environ.get(
    "IVN_CDN",
    "https://eventight-sb.webaccel.saikyo.biz/dmm4sb/Unity6/Addressable_Test2/WebGL",
).rstrip("/")
CATALOG = CDN + "/catalog_0.0.1.json"
UA = "spine-viewer-ivntight-updater/1.0"
PAGE_RE = re.compile(r"\.(png|jpg|jpeg|webp)$", re.I)


def _log(m):
    sys.stderr.write("[%s] %s\n" % (time.strftime("%H:%M:%S"), m))
    sys.stderr.flush()


def http_get(url, tries=4):
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=180) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code in (403, 429, 404):
                raise RuntimeError(f"HTTP {e.code} {url}") from e
            last = e
            time.sleep(1.5 * (i + 1))
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(1.5 * (i + 1))
    raise RuntimeError(f"GET gagal {url}: {last}")


def load_state():
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:  # noqa: BLE001
        return {}


def save_state(d):
    os.makedirs(STATE_DIR, exist_ok=True)
    tmp = STATE_FILE + ".part"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False)
    os.replace(tmp, STATE_FILE)


def load_catalog(saved):
    """(bytes katalog, versi). Di-cache supaya --check rutin tak unduh 3 MB."""
    if saved.get("catalogB64") and saved.get("catalogSha"):
        try:
            import base64
            raw = base64.b64decode(saved["catalogB64"])
            return raw, saved["catalogSha"]
        except Exception:  # noqa: BLE001
            pass
    raw = http_get(CATALOG)
    return raw, hashlib.sha1(raw).hexdigest()[:12]


def spine_bundles(cat):
    """{file.bundle: {'assets': [...], 'size': n}} untuk aset ber-spine."""
    res = cat.Resources
    out = {}
    for key, locs in res.items():
        if "spine" not in str(key).lower():
            continue
        for L in locs:
            iid = str(getattr(L, "InternalId", ""))
            if not (iid.endswith(".prefab") and "spine" in iid.lower()):
                continue
            dep = str(getattr(L, "DependencyKey", "") or "")
            if not dep:
                continue
            blocs = res.get(dep) or []
            for B in blocs:
                bi = str(getattr(B, "InternalId", ""))
                if not bi.endswith(".bundle"):
                    continue
                fname = bi.rsplit("/", 1)[-1]
                size = 0
                data = getattr(B, "data", None)
                if data is not None:
                    size = int(getattr(data, "bundle_size", 0) or 0)
                e = out.setdefault(fname, {"assets": [], "size": size})
                if iid not in e["assets"]:
                    e["assets"].append(iid)
    return out


def safe(name, used=None):
    """Nama folder ASCII unik.

    PENTING: `\\w` di Python mencakup huruf CJK, jadi pola NAIF
    `[^\\w.-]` TIDAK membuang katakana/kanji — folder jadi berbahasa Jepang,
    lalu SERVER yang meng-slug id (CJK -> '-') dan beberapa model bertabrakan
    jadi id yang sama (mis. dua '1004_...'). Karena itu pakai rentang ASCII
    eksplisit, dan tambahkan hash pendek bila slug kehilangan karakter supaya
    tetap unik & stabil.
    """
    n = re.sub(r"[^A-Za-z0-9.\-]+", "_", name).strip("_.") or "m"
    if n != name.strip("_."):
        n = "%s_%s" % (n, hashlib.md5(name.encode("utf-8", "surrogateescape")).hexdigest()[:6])
    if used is not None:
        base, i = n, 2
        while n in used:
            n = "%s_%d" % (base, i)
            i += 1
        used.add(n)
    return n


def extract_bundle(path, dest_root):
    """Buka satu bundle Unity -> tulis model Spine.

    Return {folder_aman: nama_asli} supaya pemanggil bisa menyimpan nama
    tampilan (Jepang) karena folder-nya sengaja dibuat ASCII.
    """
    import UnityPy
    env = UnityPy.load(path)
    texts, texes = {}, {}
    for obj in env.objects:
        if obj.type.name == "TextAsset":
            try:
                d = obj.read()
            except Exception:
                continue
            nm = getattr(d, "m_Name", "") or ""
            data = getattr(d, "m_Script", None)
            if isinstance(data, str):
                data = data.encode("utf-8", "surrogateescape")
            texts[nm] = bytes(data or b"")
        elif obj.type.name == "Texture2D":
            try:
                d = obj.read()
                nm = getattr(d, "m_Name", "") or ""
            except Exception:
                continue
            texes[nm] = obj

    skeletons = {n: b for n, b in texts.items() if b.lstrip().startswith(b'{"skeleton"')}
    atlases = {}
    for n, b in texts.items():
        txt = b.decode("utf-8", "replace")
        pages = [ln.strip() for ln in txt.splitlines()
                 if ln.strip() and ln[0] not in " \t" and PAGE_RE.search(ln.strip())]
        if pages:
            atlases[n] = (txt, pages)

    out = {}
    for skname, skbytes in skeletons.items():
        base = re.sub(r"\.(json|skel)$", "", skname, flags=re.I)
        # atlas se-basis
        an = next((k for k in atlases if re.sub(r"\.atlas$", "", k, flags=re.I) == base), None)
        if not an:
            _log(f"    tanpa atlas: {skname}")
            continue
        atxt, pages = atlases[an]
        fol = safe(base)
        dest = os.path.join(dest_root, fol)
        os.makedirs(dest, exist_ok=True)
        open(os.path.join(dest, fol + ".json"), "wb").write(skbytes)
        open(os.path.join(dest, fol + ".atlas"), "w", encoding="utf-8").write(atxt)
        got = 0
        for pg in pages:
            stem = re.sub(r"\.(png|jpg|jpeg|webp)$", "", pg, flags=re.I)
            obj = texes.get(stem) or next((texes[k] for k in texes if k.startswith(stem)), None)
            if obj is None:
                continue
            # Simpan dengan NAMA HALAMAN DARI ATLAS (mis. "1004_ラルミン_
            # 戦闘時背面.png"), BUKAN nama aman: atlas merujuk nama itu, jadi
            # kalau beda, viewer tak menemukan tekstur dan model gagal dimuat.
            try:
                obj.read().image.save(os.path.join(dest, pg), "PNG")
                got += 1
            except Exception as e:  # noqa: BLE001
                _log(f"    gagal tekstur {pg}: {str(e)[:50]}")
        if got:
            out[fol] = base
            _log(f"    {fol} ({base}): {got}/{len(pages)} halaman")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()
    if not (a.check or a.apply):
        a.check = True

    import AddressablesTools as A
    saved = load_state()
    raw, ver = load_catalog(saved)
    cat = A.parse_json(raw.decode("utf-8", "replace"))
    bundles = spine_bundles(cat)
    done = set(saved.get("extracted") or [])
    todo = sorted(b for b in bundles if b not in done)
    if a.limit:
        todo = todo[: a.limit]
    total_mb = sum(bundles[b]["size"] for b in todo) / 1e6

    _log(f"katalog: {len(cat.Resources)} resource, versi {ver}")
    _log(f"bundle ber-Spine: {len(bundles)} | sudah: {len(done)} | baru: {len(todo)} (~{total_mb:.0f} MB)")
    for b in todo[:30]:
        _log(f"  BARU  {b}")

    result = {
        "ok": True,
        "version": ver,
        "previous": saved.get("catalogSha") or None,
        "changed": ver != saved.get("catalogSha"),
        "total": len(bundles),
        "installed": len(done),
        "new": len(todo),
        "ids": todo[:60],
    }

    if a.check or not todo:
        if a.check:
            import base64
            st = load_state()
            st.update({"catalogSha": ver, "checkedAt": int(time.time()),
                       "catalogB64": base64.b64encode(raw).decode()})
            save_state(st)
        print(json.dumps(result, ensure_ascii=False, indent=1))
        return 0

    os.makedirs(BUNDLE_DIR, exist_ok=True)
    os.makedirs(OUT, exist_ok=True)
    added = 0
    new_ids = []
    failed = []
    # folder aman -> nama tampilan (Jepang, asli dari TextAsset)
    names = saved.get("names") or {}
    for i, b in enumerate(todo, 1):
        path = os.path.join(BUNDLE_DIR, b)
        if not (os.path.exists(path) and os.path.getsize(path) > 0):
            try:
                data = http_get(f"{CDN}/{b}")
                tmp = path + ".part"
                open(tmp, "wb").write(data)
                os.replace(tmp, path)
            except Exception as e:  # noqa: BLE001
                failed.append(f"{b}: {str(e)[:80]}")
                _log(f"  [{i}/{len(todo)}] GAGAL unduh {b}: {str(e)[:60]}")
                continue
        try:
            models = extract_bundle(path, OUT)
            for fol, orig in models.items():
                names[fol] = orig
                new_ids.append(f"ivntight/{fol}")
            # Tandai bundle SELESAI walau 0 model: sebagian bundle ber-nama
            # 'spine' ternyata komponen IV/prefab khusus (bukan Spine-Unity),
            # jadi 0 model itu hasil yang benar dan tak boleh diunduh ulang.
            done.add(b)
            if models:
                added += 1
            _log(f"  [{i}/{len(todo)}] {b}: {len(models)} model")
        except Exception as e:  # noqa: BLE001
            failed.append(f"{b}: {str(e)[:80]}")
            _log(f"  [{i}/{len(todo)}] GAGAL ekstrak {b}: {str(e)[:60]}")

    # tulis kamus nama (dipakai server utk HUD); aman dijalankan berulang.
    try:
        with open(NAMES, encoding="utf-8") as f:
            disk_names = json.load(f)
    except Exception:  # noqa: BLE001
        disk_names = {}
    disk_names.update(names)
    tmp = NAMES + ".part"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(disk_names, f, ensure_ascii=False, indent=1, sort_keys=True)
    os.replace(tmp, NAMES)

    result.update({
        "added": added,
        "extracted": added,
        "failedFiles": len(failed),
        "new": 0,
        "new_ids": new_ids,
        "new_models": [x.split("/", 1)[1] for x in new_ids],
    })
    st = load_state()
    st.update({"catalogSha": ver, "appliedAt": int(time.time()),
               "extracted": sorted(done), "names": names})
    import base64
    st["catalogB64"] = base64.b64encode(raw).decode()
    save_state(st)

    _log(f"=== selesai: +{added} bundle, {len(new_ids)} model, gagal={len(failed)}")
    for f in failed[:10]:
        _log("   GAGAL " + f)
    print(json.dumps(result, ensure_ascii=False, indent=1))
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
