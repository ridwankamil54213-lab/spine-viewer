#!/usr/bin/env python3
"""Ekstrak Spine dari Dragon Travelers (com.gametree.lhlr.gp).

Sumber (union — game memuat res_update dulu, fallback ke APK):
  - APK   : split_base_assets1.apk : assets/res/model/*.b
  - Device: /opt/dt/{model,effect,config,scene,act,timeline,hotfix,ui}/*.b

Bundel punya "fake header" bersarang: string "UnityFS" muncul 2-3 kali dan yang
ASLI adalah kemunculan TERAKHIR → pakai rfind(b"UnityFS"), bukan find().

Skeleton & atlas berupa TextAsset (kadang tanpa ekstensi → deteksi dari isi),
halaman tekstur berupa Texture2D. Digabung per nama dasar.

Pakai:
  python tools/extract-dragontravelers.py --apk /opt/dt/apk/split_base_assets1.apk \
      --dirs /opt/dt/model,/opt/dt/effect,... --out assets/dragontravelers
"""
import argparse, io, json, os, re, struct, subprocess, sys, zipfile, collections, shutil

import UnityPy

UnityPy.config.FALLBACK_UNITY_VERSION = os.environ.get("UNITY_FALLBACK", "2021.3.0f1")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_OUT = os.path.join(ROOT, "assets", "dragontravelers")
# Cache pulled off the rooted device's app data dir.
DT_CACHE = os.environ.get("DT_CACHE", "/opt/dt")
DT_DIRS = ["model", "effect", "config", "scene", "act", "timeline", "hotfix", "ui"]
DT_APK_SPLIT = "split_base_assets1.apk"
DT_PKG = os.environ.get("DT_PKG", "com.gametree.lhlr.gp")
DT_ADB = os.environ.get("DT_ADB", "adb -s 127.0.0.1:15555")
VER = re.compile(rb"^(\d+\.\d+)")
IMG = (b".png", b".jpg", b".webp", b".jpeg")


def log(m):
    sys.stderr.write("[%s] %s\n" % (__import__("time").strftime("%H:%M:%S"), m))
    sys.stderr.flush()


def pull(apk_out):
    """Refresh the sources from the device: res_update dirs + the asset split.

    The device copy in files/res_update is the hot-updated content the running
    game actually loads; the APK split (assets/res/model) is the fallback the
    game ships. Pulling both and taking the union is what makes this an updater.
    """
    os.makedirs(apk_out, exist_ok=True)
    base = "/sdcard/Android/data/%s/files/res_update" % DT_PKG
    for d in DT_DIRS:
        dst = os.path.join(DT_CACHE, d)
        os.makedirs(dst, exist_ok=True)
        r = subprocess.run(
            DT_ADB.split() + ["pull", "%s/%s" % (base, d), dst],
            capture_output=True, text=True,
        )
        n = len(os.listdir(dst))
        log("  pull %-9s -> %d berkas (%s)" % (d, n, "ok" if r.returncode == 0 else (r.stderr.strip()[-60:] or "gagal")))
    # APK splits live under an obfuscated /data/app path; resolve it via pm path.
    r = subprocess.run(DT_ADB.split() + ["shell", "pm", "path", DT_PKG],
                       capture_output=True, text=True)
    for line in r.stdout.splitlines():
        p = line.strip().replace("package:", "")
        if p.endswith(DT_APK_SPLIT):
            out = os.path.join(apk_out, DT_APK_SPLIT)
            subprocess.run(DT_ADB.split() + ["pull", p, out], capture_output=True, text=True)
            if os.path.exists(out):
                log("  pull %s -> %.0f MB" % (DT_APK_SPLIT, os.path.getsize(out) / 1024 ** 2))
            break


def load_clean(data):
    off = data.rfind(b"UnityFS")
    if off < 0:
        return None
    try:
        return UnityPy.load(io.BytesIO(data[off:]))
    except Exception:
        return None


def ta_blob(o):
    try:
        raw = o.get_raw_data()
        n = struct.unpack("<i", raw[0:4])[0]
        if not (0 < n < 512):
            return None, b""
        nm = raw[4 : 4 + n].decode("utf-8", "replace")
        p = 4 + n
        p += (4 - (p % 4)) % 4
        sz = struct.unpack("<i", raw[p : p + 4])[0]
        return nm, raw[p + 4 : p + 4 + sz]
    except Exception:
        return None, b""


def kind_of(nm, blob):
    low = (nm or "").lower()
    if low.endswith(".atlas"):
        return "atlas"
    if low.endswith(".skel"):
        return "skel"
    if low.endswith(".json") and blob.lstrip()[:11].startswith(b'{"skeleton'):
        return "skel"
    head = blob.lstrip()[:20]
    if head.startswith(b'{"skeleton'):
        return "skel"
    # Atlas: baris pertama berupa nama halaman .png/.jpg dan tidak ada 'filter:'
    first = blob.split(b"\n", 1)[0].strip().lower()
    if first.endswith(IMG) and b"format:" not in blob[:400].lower():
        return "atlas"
    # Skel biner: 8 byte hash lalu string versi "4.1"
    if len(blob) > 12 and VER.match(blob[8:16]):
        return "skel"
    return None


def atlas_pages(atlas_blob):
    out = []
    for line in atlas_blob.decode("utf-8", "replace").splitlines():
        if not line.strip():
            continue
        if line.startswith(" ") or ":" in line:
            if line.startswith(" ") or ":" in line:
                continue
        low = line.strip().lower()
        if low.endswith((".png", ".jpg", ".jpeg", ".webp")):
            out.append(low)
        else:
            break
    return out


def slug(s):
    s = re.sub(r"[^0-9A-Za-z._-]+", "-", str(s)).strip("-")
    return s or "model"


def iter_bundles(apk, dirs):
    if apk:
        z = zipfile.ZipFile(apk)
        for i in z.infolist():
            if i.filename.endswith((".b", ".bundle")):
                yield "apk:" + i.filename, z.read(i.filename)
    for d in dirs:
        if not d or not os.path.isdir(d):
            continue
        for f in sorted(os.listdir(d)):
            p = os.path.join(d, f)
            if os.path.isfile(p):
                yield "dir:" + p, open(p, "rb").read()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apk", default=os.path.join(DT_CACHE, "apk", DT_APK_SPLIT))
    ap.add_argument("--dirs", default=",".join(os.path.join(DT_CACHE, d) for d in DT_DIRS))
    ap.add_argument("--out", default=DEFAULT_OUT)
    ap.add_argument("--pull", action="store_true", help="tarik ulang sumber dari redroid dulu")
    ap.add_argument("--list", action="store_true")
    args = ap.parse_args()
    dirs = [d for d in args.dirs.split(",") if d]

    if args.pull:
        log("menarik sumber dari device…")
        pull(os.path.join(DT_CACHE, "apk"))

    # 1) kumpulkan semua TextAsset/Texture2D per bundle
    skel = {}   # base -> bytes (prefer device over apk: diproses belakangan menang)
    atlas = {}  # base -> bytes
    tex = {}    # lower -> (orig, image)
    order = []  # base urutan kemunculan
    n = 0
    for name, data in iter_bundles(args.apk, dirs):
        n += 1
        env = load_clean(data)
        if env is None:
            continue
        for o in env.objects:
            t = getattr(getattr(o, "type", None), "name", "")
            if t == "TextAsset":
                nm, blob = ta_blob(o)
                if not nm or not blob:
                    continue
                k = kind_of(nm, blob)
                if k == "skel":
                    base = nm.rsplit(".", 1)[0]
                    if base not in skel:
                        order.append(base)
                    skel[base] = blob
                elif k == "atlas":
                    atlas[nm.rsplit(".", 1)[0]] = blob
            elif t == "Texture2D":
                try:
                    d = o.read()
                    nm = d.m_Name
                    tex[nm.lower()] = (nm, d.image)
                except Exception:
                    pass
        if n % 300 == 0:
            log("  ...%d bundle (skel: %d, atlas: %d)" % (n, len(skel), len(atlas)))
    log("bundle dipindai: %d | skeleton: %d | atlas: %d | tekstur: %d" % (n, len(skel), len(atlas), len(tex)))

    models = []
    for base in order:
        if base not in atlas:
            continue
        models.append(base)
    log("model (skel+atlas): %d" % len(models))
    for m in sorted(models):
        log("   " + m)
    if args.list:
        print('{"ok": true, "models": %d}' % len(models))
        return 0

    os.makedirs(args.out, exist_ok=True)
    written = 0
    added = []
    for base in models:
        dest = os.path.join(args.out, slug(base))
        is_new = not os.path.isdir(dest)
        os.makedirs(dest, exist_ok=True)
        with open(os.path.join(dest, slug(base) + ".skel"), "wb") as fh:
            fh.write(skel[base])
        with open(os.path.join(dest, slug(base) + ".atlas"), "wb") as fh:
            fh.write(atlas[base])
        pages = atlas_pages(atlas[base])
        ntex = 0
        for pg in pages:
            key = pg.rsplit(".", 1)[0]
            if key in tex:
                onm, img = tex[key]
                fn = onm if onm.lower().endswith(".png") else onm + ".png"
                try:
                    img.save(os.path.join(dest, fn))
                    ntex += 1
                except Exception as e:
                    log("  ! tekstur %s: %s" % (fn, e))
        written += 1
        if is_new:
            added.append(slug(base))
        log("  + %s (%d tekstur)" % (slug(base), ntex))
    log("=== %d model ditulis ke %s ===" % (written, args.out))
    print('{"ok": true, "written": %d, "new": 0, "new_ids": %s, "out": "%s"}'
          % (written, json.dumps(["dragontravelers/" + a for a in added]), args.out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
