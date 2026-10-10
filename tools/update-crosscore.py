#!/usr/bin/env python3
"""Perbarui aset CrossCore (交错战线).

SUMBER UTAMA = mirror GitHub. CDN resmi `cdn.megagamelog.com` ada di balik
Volcengine (CN) dan mem-**blackhole** banyak host di luar CN (TCP connect
menggantung tanpa error, DNS menyebar ke 10 IP). Komunitas mencerminkan CDN
resmi ke GitHub, yang bisa diakses dari mana saja dan di-update berkala:

    kmou424/Crosscore_Anti_Hexie_Assets   (varian anti-sensor; prefabs_spine_*)
    R2iCecho/Crosscore_Assets_curr_1      (indeks ilist.txt)

Repo lain bisa ditambah lewat `CROSSCORE_GH` ("owner/repo", dipisah koma).

Alur:
    1. Daftar bundle `prefabs_spine_*` dari mirror GitHub (tree API).
    2. Unduh yang belum ada dari raw.githubusercontent.com.
    3. Ekstrak ke pohon aset viewer.
CDN resmi tetap dipakai lebih dulu bila `--manifest` diberikan atau bila CDN
kebetulan terjangkau.

Bundle = FakeHeader (sampah sebelum `UnityFS` asli; pangkas dgn rfind) + UnityFS.
Satu bundle = satu model:
    TextAsset <Name>          -> skeleton JSON
    TextAsset <Name>.atlas    -> atlas
    Texture2D <Name>          -> halaman tekstur

Pemakaian:
    /srv/venv-spine/bin/python tools/update-crosscore.py --check
    /srv/venv-spine/bin/python tools/update-crosscore.py --apply
    /srv/venv-spine/bin/python tools/update-crosscore.py --doctor
"""
import argparse
import io
import json
import os
import re
import subprocess
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor

# --------------------------------------------------------------------------- #
# sources
# --------------------------------------------------------------------------- #
CDN = "https://cdn.megagamelog.com/cross/release/android/curr_1"
MANIFEST_URL = f"{CDN}/ver.bytes"
CDN_HOSTS = [h for h in os.environ.get("CROSSCORE_CDN", CDN).split(",") if h]

GH_API = "https://api.github.com"
GH_RAW = "https://raw.githubusercontent.com"
# "owner/repo" atau "owner/repo@branch".
GH_REPOS = [r for r in os.environ.get(
    "CROSSCORE_GH",
    "kmou424/Crosscore_Anti_Hexie_Assets,R2iCecho/Crosscore_Assets_curr_1",
).split(",") if r]
# Direktori bundle di dalam repo (nama berkas = prefabs_spine_*).
GH_BUNDLE_DIR = os.environ.get("CROSSCORE_GH_DIR", "Custom")
GH_TOKEN = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")

# Proxy HTTP/HTTPS opsional (mis. VPN): CROSSCORE_PROXY=http://host:port
PROXY = os.environ.get("CROSSCORE_PROXY") or None
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
HEADERS = {"User-Agent": UA}

STATE_DIR = os.environ.get("CROSSCORE_STATE", "/srv/spine-assets/crosscore")
MANIFEST_DIR = os.path.join(STATE_DIR, "manifest")
DOWNLOAD_DIR = os.path.join(STATE_DIR, "downloads")
STATE_FILE = os.path.join(STATE_DIR, "state.json")
ASSET_DIR = os.environ.get("CROSSCORE_OUT", "/opt/spine-viewer/assets/crosscore")

PYTHON = os.environ.get("PY", "/srv/venv-spine/bin/python")
AB_RE = re.compile(rb"^prefabs_spine_[A-Za-z0-9_]+$")
SPINE_PREFIX = "prefabs_spine_"


def _log(msg):
    """Baris progres ke stderr: server menampilkannya sebagai log live."""
    sys.stderr.write("[%s] %s\n" % (time.strftime("%H:%M:%S"), msg))
    sys.stderr.flush()


# --------------------------------------------------------------------------- #
# HTTP helper (proxy-aware)
# --------------------------------------------------------------------------- #
def _opener():
    if PROXY:
        return urllib.request.build_opener(
            urllib.request.ProxyHandler({"http": PROXY, "https": PROXY}))
    return None


def http_get(url, timeout=60, retries=4, headers=None):
    hdrs = dict(HEADERS)
    if headers:
        hdrs.update(headers)
    opener = _opener()
    last = None
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers=hdrs)
            if opener is not None:
                with opener.open(req, timeout=timeout) as r:
                    return r.read()
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except Exception as exc:  # noqa: BLE001
            last = exc
            time.sleep(1.2 * (i + 1))
    if last is None:
        raise RuntimeError(f"gagal mengunduh {url}")
    raise last


def _gh_headers():
    return {"Authorization": f"Bearer {GH_TOKEN}"} if GH_TOKEN else {}


# --------------------------------------------------------------------------- #
# GitHub mirror
# --------------------------------------------------------------------------- #
def gh_default_branch(repo):
    try:
        d = json.loads(http_get(f"{GH_API}/repos/{repo}", timeout=20, headers=_gh_headers()))
        return d.get("default_branch", "main")
    except Exception:  # noqa: BLE001
        return "main"


def gh_tree_bundles(spec):
    """{nama bundle: info} untuk satu repo mirror.

    `spec` boleh "owner/repo" atau "owner/repo@branch".
    """
    repo, _, branch = spec.partition("@")
    if not branch:
        branch = gh_default_branch(repo)
    try:
        d = json.loads(http_get(
            f"{GH_API}/repos/{repo}/git/trees/{branch}?recursive=1",
            timeout=45, headers=_gh_headers()))
    except Exception:  # noqa: BLE001
        return {}
    out = {}
    for x in d.get("tree", []):
        if x.get("type") != "blob":
            continue
        base = x["path"].rsplit("/", 1)[-1]
        if base.startswith(SPINE_PREFIX) and x["path"].startswith(GH_BUNDLE_DIR + "/"):
            out[base] = {"repo": repo, "branch": branch, "path": x["path"]}
    return out


def gh_catalog():
    """Gabungkan daftar bundle dari semua mirror -> {nama: info}."""
    cat = {}
    for spec in GH_REPOS:
        got = gh_tree_bundles(spec)
        if got:
            cat.update(got)
    return cat


# --------------------------------------------------------------------------- #
# CDN manifest (sumber resmi — dicoba bila CDN terjangkau)
# --------------------------------------------------------------------------- #
def _read_7bit(data, i):
    val, shift = 0, 0
    for k in range(4):
        if i + k >= len(data):
            return None, None
        b = data[i + k]
        val |= (b & 0x7F) << shift
        shift += 7
        if not (b & 0x80):
            return val, i + k + 1
    return None, None


def parse_manifest(data: bytes):
    """BinaryFormatter strings = panjang 7-bit; pasangkan nama AB dgn MD5/ukuran."""
    names = []
    i = 0
    while i < len(data):
        ln, after = _read_7bit(data, i)
        if ln is None or after is None or not (8 <= ln <= 120) or after + ln > len(data):
            i += 1
            continue
        s = data[after:after + ln]
        if not re.match(rb"(prefabs|textures)_[A-Za-z0-9_]+$", s):
            i += 1
            continue
        tail = data[after + ln: after + ln + 90]
        m = re.search(rb"[0-9A-F]{32}", tail)
        if not m:
            i += 1
            continue
        p = after + ln + m.start() + 32
        size = int.from_bytes(data[p:p + 8], "little", signed=True) if p + 8 <= len(data) else 0
        names.append({"name": s.decode(), "md5": m.group().decode(), "size": size})
        i = after + ln
    return names


def spine_entries(data: bytes):
    return [e for e in parse_manifest(data) if AB_RE.match(e["name"].encode())]


_FETCH_HELPER = (
    "import sys,urllib.request\n"
    "u=sys.argv[1];o=sys.argv[2];p=(sys.argv[3] or None)\n"
    "op=urllib.request.build_opener(urllib.request.ProxyHandler({'http':p,'https':p})) if p else urllib.request\n"
    "d=op.urlopen(u,timeout=12).read()\n"
    "open(o,'wb').write(d)\n"
)


def fetch_manifest(store=True):
    """Unduh ver.bytes via subprocess + hard-kill (CDN suka 'blackhole')."""
    os.makedirs(MANIFEST_DIR, exist_ok=True)
    local = os.path.join(MANIFEST_DIR, "ver.bytes")
    deadline = int(os.environ.get("CROSSCORE_FETCH_TIMEOUT", "30"))
    tmp = local + ".part"
    if os.path.exists(tmp):
        os.remove(tmp)
    _log(f"mengambil manifest CDN {MANIFEST_URL}")
    try:
        proc = subprocess.run(
            [PYTHON, "-c", _FETCH_HELPER, MANIFEST_URL, tmp, PROXY or ""],
            capture_output=True, text=True, timeout=deadline,
        )
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"timeout {deadline}s (CDN tidak terjangkau)")
    if proc.returncode != 0 or not os.path.exists(tmp):
        raise RuntimeError((proc.stderr or proc.stdout or "unduhan gagal").strip()[:200])
    raw = open(tmp, "rb").read()
    os.replace(tmp, local)
    return raw


# --------------------------------------------------------------------------- #
# state
# --------------------------------------------------------------------------- #
def load_state():
    if os.path.exists(STATE_FILE):
        try:
            return json.load(open(STATE_FILE))
        except Exception:
            pass
    return {}


def save_state(state):
    os.makedirs(STATE_DIR, exist_ok=True)
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=1)


def _installed_names():
    if not os.path.isdir(ASSET_DIR):
        return set()
    out = set()
    for n in os.listdir(ASSET_DIR):
        d = os.path.join(ASSET_DIR, n)
        if not os.path.isdir(d):
            continue
        # Terhitung "sudah ada" bila punya skeleton, ATAU sudah ditandai .skip
        # (bundle yang ternyata bukan spine, mis. VFX/particle) supaya tidak
        # terus dilaporkan "missing" setiap kali check.
        if (os.path.exists(os.path.join(d, n + ".json"))
                or os.path.exists(os.path.join(d, n + ".skel"))
                or os.path.exists(os.path.join(d, n + ".skip"))):
            out.add(n)
    return out


def _targets(manifest_path=None):
    """Kembalikan (sumber, [{'name','model','gh'}]). CDN dulu, lalu GitHub."""
    if manifest_path:
        raw = open(manifest_path, "rb").read()
        return "local-manifest", [
            {"name": e["name"], "model": e["name"][len(SPINE_PREFIX):]}
            for e in spine_entries(raw)]
    try:
        raw = fetch_manifest()
        entries = spine_entries(raw)
        if entries:
            return "cdn", [{"name": e["name"], "model": e["name"][len(SPINE_PREFIX):]}
                           for e in entries]
    except Exception as exc:  # noqa: BLE001
        _log(f"CDN tak terjangkau ({exc}); pakai mirror GitHub")
    cat = gh_catalog()
    return "github", [
        {"name": n, "model": n[len(SPINE_PREFIX):], "gh": cat[n]}
        for n in sorted(cat) if n.startswith(SPINE_PREFIX)]


def check(manifest_path=None):
    try:
        source, targets = _targets(manifest_path)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"tak bisa mengambil daftar: {exc}",
                "reachable": False, "bundles": 0, "added": 0, "missing": 0, "new_models": []}
    if not targets:
        return {"ok": False, "error": "tak ada model dari CDN maupun GitHub",
                "reachable": False, "bundles": 0, "added": 0, "missing": 0, "new_models": []}
    installed = _installed_names()
    cur = {t["model"] for t in targets}
    state = load_state()
    prev = set(state.get("models", []))
    added = sorted(cur - prev) if prev else []
    missing = sorted(cur - installed)
    return {
        "ok": True,
        "source": source,
        "bundles": len(cur),
        "installed": len(cur & installed),
        "added": len(added),
        "missing": len(missing),
        "removed": len(prev - cur),
        "changed": bool(missing or added),
        "new_models": (missing or added)[:30],
    }


# --------------------------------------------------------------------------- #
# decryption + extraction
# --------------------------------------------------------------------------- #
def trim_fake_header(data: bytes) -> bytes:
    """FakeHeader = sampah sebelum `UnityFS` asli (kemunculan TERAKHIR)."""
    pos = data.rfind(b"UnityFS")
    return data[pos:] if pos > 0 else data


_PAGE_RE = re.compile(r"\.(png|jpe?g|webp)$", re.I)


def extract_with_unitypy(raw: bytes, dest: str, name: str, cn_key=None):
    """Tulis <dest>/<name>.<json|skel> + <name>.atlas + halaman PNG. (status, note)."""
    import UnityPy  # lazy

    data = trim_fake_header(raw)
    if cn_key:
        try:
            UnityPy.set_assetbundle_decrypt_key(bytes.fromhex(cn_key))
        except Exception:
            pass
    try:
        env = UnityPy.load(io.BytesIO(data))
    except Exception as exc:  # noqa: BLE001
        return "load-fail", str(exc)[:80]
    skel = None
    skel_ext = None
    atlas = None
    pages = []
    for o in env.objects:
        t = o.type.name
        try:
            d = o.read()
        except Exception:
            continue
        nm = getattr(d, "m_Name", "") or ""
        if t == "TextAsset":
            payload = d.m_Script
            payload = payload.encode("utf-8", "surrogateescape") if isinstance(payload, str) else bytes(payload)
            head = payload[:512]
            low = nm.lower()
            if low.endswith(".atlas") or (b"size:" in head[:64] and b"format:" in head[:256]):
                atlas = atlas or payload.decode("utf-8", "replace")
            elif payload[:1] == b"{" and b'"skeleton"' in head:
                if skel is None:
                    skel, skel_ext = payload, ".json"
            elif low.endswith((".skel", ".prefab")) and skel is None:
                skel, skel_ext = (payload, ".json") if payload[:1] == b"{" else (payload, ".skel")
            elif skel is None and low.startswith(name.lower()):
                # CrossCore: skeleton TextAsset dinamai <Name> tanpa ekstensi.
                skel, skel_ext = (payload, ".json") if payload[:1] == b"{" else (payload, ".skel")
        elif t == "Texture2D":
            try:
                pages.append((nm, d.image))
            except Exception:
                pass
    if skel is None or atlas is None:
        return "not-spine", f"skel={skel is not None} atlas={atlas is not None}"
    os.makedirs(dest, exist_ok=True)
    with open(os.path.join(dest, name + (skel_ext or ".json")), "wb") as f:
        f.write(skel)
    with open(os.path.join(dest, name + ".atlas"), "w", encoding="utf-8") as f:
        f.write(atlas)
    # Simpan tiap halaman memakai nama yang dirujuk atlas.
    refs = [ln.strip() for ln in atlas.splitlines()
            if ln.strip() and not ln[0].isspace() and _PAGE_RE.search(ln.strip())]
    used = set()
    for ref in refs:
        stem = ref.rsplit(".", 1)[0]
        for i, (pnm, img) in enumerate(pages):
            if i in used:
                continue
            if pnm == ref or pnm.rsplit(".", 1)[0] == stem:
                used.add(i)
                img.save(os.path.join(dest, ref), "PNG")
                break
    for i, (pnm, img) in enumerate(pages):
        if i in used:
            continue
        fn = pnm if pnm.lower().endswith(".png") else (pnm + ".png" if pnm else f"{name}_{i}.png")
        img.save(os.path.join(dest, fn), "PNG")
    note = f"pages={len(used)}"
    if len(refs) > len(used):
        note += f" missing={len(refs) - len(used)}"
    return "ok", note


# --------------------------------------------------------------------------- #
# apply
# --------------------------------------------------------------------------- #
def apply_update(limit=0, workers=8, manifest_path=None):
    try:
        source, targets = _targets(manifest_path)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"tak bisa mengambil daftar: {exc}",
                "downloaded": 0, "extracted": 0}
    if not targets:
        return {"ok": False, "error": "tak ada model dari CDN maupun GitHub",
                "downloaded": 0, "extracted": 0}

    installed = _installed_names()
    todo = [t for t in targets if t["model"] not in installed]
    if limit:
        todo = todo[:limit]
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)
    _log(f"sumber={source}: {len(targets)} model, {len(todo)} baru (workers={workers})")

    downloaded = failed = 0
    errors = []
    total = len(todo)

    def get(t):
        nonlocal downloaded, failed
        local = os.path.join(DOWNLOAD_DIR, t["name"])
        errs = []
        if t.get("gh"):  # mirror GitHub dulu
            info = t["gh"]
            try:
                body = http_get(f"{GH_RAW}/{info['repo']}/{info['branch']}/{info['path']}",
                                timeout=180, headers=_gh_headers())
                with open(local, "wb") as f:
                    f.write(body)
                downloaded += 1
                if downloaded % 10 == 0 or downloaded == total:
                    _log(f"unduh {downloaded}/{total}")
                return
            except Exception as exc:  # noqa: BLE001
                errs.append(f"gh={exc}")
        for host in CDN_HOSTS:  # lalu CDN resmi
            try:
                body = http_get(f"{host}/Custom/{t['name']}")
                with open(local, "wb") as f:
                    f.write(body)
                downloaded += 1
                return
            except Exception as exc:  # noqa: BLE001
                errs.append(f"cdn={exc}")
        failed += 1
        if len(errors) < 5:
            errors.append(f"{t['name']}: {'; '.join(errs)[:140]}")
        _log(f"GAGAL unduh {t['name']}")

    if todo:
        with ThreadPoolExecutor(max_workers=workers) as ex:
            list(ex.map(get, todo))

    cn_key = os.environ.get("CROSSCORE_UNITYCN_KEY")
    extracted = already = 0
    new_models = []
    for t in targets:
        model = t["model"]
        dest = os.path.join(ASSET_DIR, model)
        if model in installed:
            already += 1
            continue
        p = os.path.join(DOWNLOAD_DIR, t["name"])
        if not os.path.exists(p):
            continue
        try:
            status, note = extract_with_unitypy(open(p, "rb").read(), dest, model, cn_key)
        except Exception as exc:  # noqa: BLE001
            status, note = "error", str(exc)[:80]
        if status == "ok":
            extracted += 1
            if len(new_models) < 30:
                new_models.append(model)
            _log(f"ekstrak OK {model} ({note})")
        elif status == "not-spine":
            # Bundle yang ternyata bukan spine (VFX/particle) — tandai supaya
            # tidak dilaporkan "missing" terus tiap check.
            os.makedirs(dest, exist_ok=True)
            with open(os.path.join(dest, model + ".skip"), "w") as f:
                f.write(f"bukan spine: {note}\n")
            _log(f"lewati {model} (bukan spine: {note})")
        elif status in ("load-fail", "error"):
            errors.append(f"{model}: {status} {note}")
            _log(f"ekstrak GAGAL {model}: {status} {note}")

    state = load_state()
    state["models"] = sorted(t["model"] for t in targets)
    state["source"] = source
    state["last_update"] = time.strftime("%Y-%m-%d %H:%M:%S")
    save_state(state)
    _log(f"selesai: {extracted} baru, {already} sudah ada, {failed} gagal unduh")

    return {
        "ok": True,
        "source": source,
        "bundles": len(targets),
        "downloaded": downloaded,
        "failed": failed,
        "extracted": extracted,
        "already_had": already,
        "new_models": new_models,
        "asset_dir": ASSET_DIR,
        "errors": errors,
    }


# --------------------------------------------------------------------------- #
# doctor
# --------------------------------------------------------------------------- #
def doctor():
    import socket
    out = {"ok": False, "steps": []}
    try:
        cat = gh_catalog()
        out["github_bundles"] = len(cat)
        out["steps"].append(f"mirror GitHub: {len(cat)} bundle prefabs_spine_*")
        out["ok"] = len(cat) > 0
    except Exception as exc:  # noqa: BLE001
        out["steps"].append(f"GitHub gagal: {exc}")
    host = MANIFEST_URL.split("/")[2]
    try:
        ips = sorted({str(i[4][0]) for i in socket.getaddrinfo(host, 443, proto=socket.IPPROTO_TCP)})
        out["steps"].append(f"DNS CDN {host} -> {', '.join(ips[:6])}")
        ok = []
        for ip in ips[:6]:
            try:
                with socket.create_connection((ip, 443), timeout=5):
                    ok.append(ip)
            except Exception:  # noqa: BLE001
                pass
        out["cdn_reachable_ips"] = ok
        out["steps"].append(f"CDN TCP OK: {ok or 'TIDAK ADA (diblok dari host ini)'}")
    except Exception as exc:  # noqa: BLE001
        out["steps"].append(f"DNS CDN gagal: {exc}")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--doctor", action="store_true",
                    help="diagnosa keterjangkauan (mirror GitHub + CDN resmi)")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--manifest", default=None, help="ver.bytes lokal (uji tanpa jaringan)")
    a = ap.parse_args()

    if a.doctor:
        print(json.dumps(doctor(), indent=1, ensure_ascii=False))
    elif a.apply:
        print(json.dumps(apply_update(limit=a.limit, workers=a.workers, manifest_path=a.manifest),
                         indent=1, ensure_ascii=False))
    elif a.check:
        print(json.dumps(check(manifest_path=a.manifest), indent=1, ensure_ascii=False))
    else:
        ap.print_help()
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
