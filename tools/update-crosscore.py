#!/usr/bin/env python3
"""Perbarui aset CrossCore (交错战线) dari CDN resmi.

Alur (tanpa APK, tanpa enkripsi simetris yang perlu di-brute-force):
    1. GET  https://cdn.megagamelog.com/cross/release/android/curr_1/ver.bytes
       -> manifest .NET BinaryFormatter: daftar AssetBundle (nama, size, md5)
    2. GET  <CDN>/Custom/<nama bundle>
    3. Simpan manifest terakhir; bandingkan untuk tahu bundle yang *baru* saja.
    4. Unduh yang baru, buka enkripsinya, ekstrak Spine-nya ke pohon aset viewer.

Bundle-nya "FakeHeader": ada sampah di depan header `UnityFS` yang asli.
`FakeHeader.py` komunitas memangkasnya dengan `content.rfind(b"UnityFS")`.
Sebagian bundle juga UnityCN (butuh key 32-hex) — sediakan lewat variabel
lingkungan `CROSSCORE_UNITYCN_KEY` kalau ternyata perlu; tanpa itu bundle CN
tetap gagal dan dilaporkan, bukan crash.

Ekstraksi TIDAK memerlukan dotnet/AssetStudio lagi: setelah header dipangkas,
UnityPy membaca bundle langsung (TextAsset skeleton JSON + atlas, Texture2D PNG).
Bila UnityPy tetap gagal dan `dotnet` + AssetStudioModCLI tersedia, dipakai
sebagai fallback.

Setiap bundle `prefabs_spine_*` berisi satu model utuh:
    <Name>.json    (skeleton; JSON — ekstensi .json agar viewer parse sbg teks)
    <Name>.atlas
    <Name>.png

Pemakaian:
    /srv/venv-spine/bin/python tools/update-crosscore.py --check
    /srv/venv-spine/bin/python tools/update-crosscore.py --apply
    # uji tanpa jaringan:
    /srv/venv-spine/bin/python tools/update-crosscore.py --check --manifest /path/ver.bytes
"""
import argparse
import io
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor

CDN = "https://cdn.megagamelog.com/cross/release/android/curr_1"
MANIFEST_URL = f"{CDN}/ver.bytes"
# CDN ini di balik Volcengine (CN); bila tidak terjangkau dari host ini,
# sediakan mirror lewat env CROSSCORE_CDN (dipisah koma).
CDN_HOSTS = [h for h in os.environ.get("CROSSCORE_CDN", CDN).split(",") if h]
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
HEADERS = {"User-Agent": UA}

STATE_DIR = os.environ.get("CROSSCORE_STATE", "/srv/spine-assets/crosscore")
MANIFEST_DIR = os.path.join(STATE_DIR, "manifest")
DOWNLOAD_DIR = os.path.join(STATE_DIR, "downloads")
STATE_FILE = os.path.join(STATE_DIR, "state.json")
ASSET_DIR = os.environ.get("CROSSCORE_OUT", "/opt/spine-viewer/assets/crosscore")

PYTHON = os.environ.get("PY", "/srv/venv-spine/bin/python")
ASSETSTUDIO = os.environ.get("ASSETSTUDIO",
                             "/opt/studio3/AssetStudioModCLI_net8_portable/AssetStudioModCLI.dll")
AB_RE = re.compile(rb"^prefabs_spine_[A-Za-z0-9_]+$")
SPINE_BUNDLE_RE = re.compile(r"^prefabs_spine_")


# --------------------------------------------------------------------------- #
# manifest
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
    """BinaryFormatter strings are 7-bit-length-prefixed; pair each AB name with
    the FileMD5/size that follow it. (A plain regex over the file over-matches:
    the byte after a name can itself be a letter.)"""
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


def http_get(url, timeout=60, retries=4):
    last = None
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except Exception as exc:  # noqa: BLE001
            last = exc
            time.sleep(1.5 * (i + 1))
    if last is None:
        raise RuntimeError(f"gagal mengunduh {url}")
    raise last


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


# --------------------------------------------------------------------------- #
# steps
# --------------------------------------------------------------------------- #
_FETCH_HELPER = (
    "import sys,urllib.request\n"
    "u=sys.argv[1];o=sys.argv[2]\n"
    "d=urllib.request.urlopen(u,timeout=12).read()\n"
    "open(o,'wb').write(d)\n"
)


def fetch_manifest(store=True):
    """Unduh ver.bytes; simpan di manifest/ untuk diff berikutnya.

    Host ini (Volcengine/CN) sering 'blackhole': connect() menggantung tanpa
    error dan DNS memetakan banyak IP, sehingga SIGALRM/urllib-timeout TIDAK
    cukup (Python otomatis mengulang syscall yang ter-interupsi). Karena itu
    unduhan dijalankan di subprocess dan dibunuh paksa lewat timeout, supaya
    `--check` SELALU balik cepat.
    """
    os.makedirs(MANIFEST_DIR, exist_ok=True)
    local = os.path.join(MANIFEST_DIR, "ver.bytes")
    deadline = int(os.environ.get("CROSSCORE_FETCH_TIMEOUT", "30"))
    tmp = local + ".part"
    if os.path.exists(tmp):
        os.remove(tmp)
    _log(f"mengambil manifest {MANIFEST_URL}")
    try:
        proc = subprocess.run(
            [PYTHON, "-c", _FETCH_HELPER, MANIFEST_URL, tmp],
            capture_output=True, text=True, timeout=deadline,
        )
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"timeout {deadline}s (host tidak terjangkau)")
    if proc.returncode != 0 or not os.path.exists(tmp):
        raise RuntimeError((proc.stderr or proc.stdout or "unduhan gagal").strip()[:200])
    raw = open(tmp, "rb").read()
    os.replace(tmp, local)
    return raw


def spine_entries(data: bytes):
    return [e for e in parse_manifest(data) if AB_RE.match(e["name"].encode())]


def _log(msg):
    """Baris progres ke stderr: server menampilkan ini sebagai log live."""
    sys.stderr.write("[%s] %s\n" % (time.strftime("%H:%M:%S"), msg))
    sys.stderr.flush()


def check(manifest_path=None):
    state = load_state()
    try:
        raw = open(manifest_path, "rb").read() if manifest_path else fetch_manifest()
        entries = spine_entries(raw)
        _log(f"manifest: {len(entries)} bundle spine")
        cur = {e["name"] for e in entries}
        prev = set(state.get("bundles", []))
        added = sorted(cur - prev)
        # Diff against what is ACTUALLY on disk, not just the saved state: a
        # first ever run has no state, yet all models may already be present.
        def installed(n):
            d = os.path.join(ASSET_DIR, n)
            return os.path.exists(os.path.join(d, n + ".json")) or os.path.exists(os.path.join(d, n + ".skel"))
        missing = [e["name"] for e in entries
                   if not installed(e["name"][len("prefabs_spine_"):])]
        result = {
            "ok": True,
            "bundles": len(entries),
            "added": len(added),
            "missing": len(missing),
            "removed": len(prev - cur),
            "changed": bool(added or missing),
            "new_models": [m[len("prefabs_spine_"):] for m in (added or missing)[:20]],
            "source": "local-manifest" if manifest_path else "cdn",
        }
    except Exception as exc:  # noqa: BLE001
        cur = state.get("bundles", [])
        result = {
            "ok": False,
            "error": f"tidak bisa mengambil manifest: {exc}",
            "reachable": False,
            "bundles": len(cur),
            "added": 0,
            "new_models": [],
        }
    return result


# --------------------------------------------------------------------------- #
# decryption + extraction
# --------------------------------------------------------------------------- #
def trim_fake_header(data: bytes) -> bytes:
    """FakeHeader = junk before the real `UnityFS` magic (last occurrence)."""
    pos = data.rfind(b"UnityFS")
    if pos > 0:
        return data[pos:]
    return data


_PAGE_RE = re.compile(r"\.(png|jpe?g|webp)$", re.I)


def extract_with_unitypy(raw: bytes, dest: str, name: str, cn_key=None):
    """Return (status, note). Writes <dest>/<name>.<json|skel> + <name>.atlas + pages.

    Handles both skeleton encodings seen across games:
      * spine JSON  shipped as a TextAsset named `*.prefab` (CrossCore) or `*.json`
      * spine BINARY shipped as a TextAsset named `*.skel`
    Page textures are named after the atlas's own page entry, so a model whose
    texture object name differs from the atlas reference still resolves.
    """
    import UnityPy  # imported lazily so --check needs no heavy deps

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
    # Save each page under the name the atlas references (page lines are the
    # non-indented lines that look like image files).
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


def extract_with_assetstudio(bundle_dir: str, out_dir: str):
    """Fallback: aelurum AssetStudioModCLI (butuh dotnet)."""
    dotnet = shutil.which("dotnet")
    if not dotnet or not os.path.exists(ASSETSTUDIO):
        return None
    os.makedirs(out_dir, exist_ok=True)
    r = subprocess.run([dotnet, ASSETSTUDIO, bundle_dir, "-o", out_dir, "--log-level", "error"],
                       capture_output=True, text=True)
    return r.returncode == 0


def apply_update(limit=0, workers=8, manifest_path=None):
    info = check(manifest_path=manifest_path)
    if not info.get("ok") and not manifest_path:
        # CDN tidak terjangkau — kembalikan apa adanya, jangan crash.
        return {"ok": False, "error": info.get("error"), "downloaded": 0, "extracted": 0}

    raw = open(manifest_path, "rb").read() if manifest_path else open(
        os.path.join(MANIFEST_DIR, "ver.bytes"), "rb").read()
    entries = spine_entries(raw)
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)

    # Hanya unduh bundle Spine yang belum ada / ukurannya beda.
    def need(e):
        p = os.path.join(DOWNLOAD_DIR, e["name"])
        return not (os.path.exists(p) and os.path.getsize(p) == e["size"])

    todo = [e for e in entries if need(e)]
    if limit:
        todo = todo[:limit]

    downloaded = failed = 0
    errors = []
    total = len(todo)
    _log(f"mengunduh {total} bundle baru (workers={workers})")

    def get(e):
        nonlocal downloaded, failed
        last = ""
        for host in CDN_HOSTS:
            try:
                body = http_get(f"{host}/Custom/{e['name']}")
                with open(os.path.join(DOWNLOAD_DIR, e["name"]), "wb") as f:
                    f.write(body)
                downloaded += 1
                if downloaded % 10 == 0 or downloaded == total:
                    _log(f"unduh {downloaded}/{total}")
                return
            except Exception as exc:  # noqa: BLE001
                last = f"{e['name']}: {exc}"
        failed += 1
        if len(errors) < 5:
            errors.append(last)
        _log(f"GAGAL {last}")

    if todo:
        with ThreadPoolExecutor(max_workers=workers) as ex:
            list(ex.map(get, todo))

    # Ekstraksi ke pohon aset viewer.
    cn_key = os.environ.get("CROSSCORE_UNITYCN_KEY")
    extracted = already = 0
    new_models = []
    for e in entries:
        name = e["name"][len("prefabs_spine_"):]
        dest = os.path.join(ASSET_DIR, name)
        if os.path.exists(os.path.join(dest, name + ".json")):
            already += 1
            continue
        p = os.path.join(DOWNLOAD_DIR, e["name"])
        if not os.path.exists(p):
            continue
        try:
            status, note = extract_with_unitypy(open(p, "rb").read(), dest, name, cn_key)
        except Exception as exc:  # noqa: BLE001
            status, note = "error", str(exc)[:80]
        if status == "ok":
            extracted += 1
            if len(new_models) < 20:
                new_models.append(name)
            _log(f"ekstrak OK {name} ({note})")
        elif status in ("load-fail", "error"):
            # fallback ke AssetStudio bila mungkin (sekali saja untuk batch ini)
            if extract_with_assetstudio(DOWNLOAD_DIR, os.path.join(STATE_DIR, "as_out")):
                pass
            errors.append(f"{name}: {status} {note}")
            _log(f"ekstrak GAGAL {name}: {status} {note}")

    state = load_state()
    state["bundles"] = sorted(e["name"] for e in entries)
    state["last_update"] = time.strftime("%Y-%m-%d %H:%M:%S")
    save_state(state)
    _log(f"selesai: {extracted} model diekstrak, {already} sudah ada, {failed} gagal")

    return {
        "ok": True,
        "bundles": len(entries),
        "downloaded": downloaded,
        "failed": failed,
        "extracted": extracted,
        "already_had": already,
        "new_models": new_models,
        "asset_dir": ASSET_DIR,
        "errors": errors,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--manifest", default=None, help="ver.bytes lokal (uji tanpa jaringan)")
    a = ap.parse_args()

    if a.apply:
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
