#!/usr/bin/env python3
"""Pembaru Zone Nova (禁域战姬, EROLABS) — Spine 4.1 dari CDN resmi.

Rantai sumbernya PUBLIK (tanpa login / tanpa file dari HP):

  1. Config  : zonenova.future-step.net:12000/ServerConfig/GetConfig
               ?appVersion=1.06&customAppIdentifier=EROLAB_ANDROID_RELEASE
               -> AssetBundlePath (CloudFront) + MasterDataDownloadPath.
               appVersion lain mengembalikan AssetBundlePath kosong.
  2. Katalog : <AssetBundlePath>Android/<MD5("Androidversion.json")>.ab
               = 9A188D7BF0BF119DE38B57A44DF3A917.ab. Berkasnya di-XOR
               rolling: plain[i] = cipher[i] ^ (i % 63). Hasilnya JSON
               {version, assetBundleMetadatas:{path:{hash,fileSizeInMB,...}}}.
  3. Bundle  : <AssetBundlePath>Android/<MD5("Android"+path)>.ab
               Prefix "UtS\\0 5.0." (fake header) + "UnityFS" di offset ~1-2 KB.
               Buang prefix, load dengan UnityPy (FALLBACK_UNITY_VERSION
               2022.3.62f2 karena versi Unity disembunyikan).
  4. Nama    : master-data.bytes (AES-256-CBC, KEY/IV di bawah) berisi
               MasterMemory/MessagePack + LZ4; tabel translation_ds memuat
               ["CHARACTER_NAME_<id>", zh, EN, ja, zh-TW].
  5. Ilustrasi: gacha-wiki-zone-nova/public/images/characters/*.jpg untuk
               thumbnail WebP (bukan halaman atlas).

Kredit algoritma: komunitas Live2DHub (topik 4502 / 4603) + repo
boring877/zone-nova-extractor untuk KDF/KEY/IV dan format MasterMemory.

Pemakaian:
    /srv/venv-spine/bin/python tools/zonenova/update.py --check
    /srv/venv-spine/bin/python tools/zonenova/update.py --apply
    /srv/venv-spine/bin/python tools/zonenova/refresh.py   # --offline
"""
import argparse
import concurrent.futures as cf
import difflib
import hashlib
import io
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import time
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUT = os.environ.get("ZN_OUT", os.path.join(ROOT, "assets", "zonenova"))
DATA = os.path.join(ROOT, "data")
THUMBS = os.environ.get("ZN_THUMBS", os.path.join(ROOT, "public", "thumbs", "zonenova"))
CACHE = os.environ.get("ZN_CACHE", "/srv/spine-assets/zonenova")
STATE_FILE = os.path.join(CACHE, "state.json")
NAMES_FILE = os.path.join(DATA, "zonenova-names.json")
FAMILY_FILE = os.path.join(DATA, "zonenova-family.json")
MANIFEST_FILE = os.path.join(THUMBS, "_manifest.json")

CONFIG_URL = ("https://zonenova.future-step.net:12000/ServerConfig/GetConfig"
              "?appVersion=1.06&customAppIdentifier=EROLAB_ANDROID_RELEASE")
MASTER_URL = "https://d23odp11837l0m.cloudfront.net/amgameasset/Prod/master-data.bytes"
WIKI_RAW = "https://raw.githubusercontent.com/boring877/gacha-wiki-zone-nova/main"
WIKI_TREE = ("https://api.github.com/repos/boring877/gacha-wiki-zone-nova"
             "/git/trees/main?recursive=1")
PLATFORM = "Android"
UNITY_VERSION = "2022.3.62f2"
XOR_MOD = 63
AES_KEY = "2c3a1bd0629a269cf539b35d01af6317d5b6302576331a1ad6e7af6414bfc719"
AES_IV = "f539b35d01af6317c19d9f69c7f4d1fc"
UA = "UnityPlayer/2022.3.62f2 (UnityWebRequest/1.0, libcurl/7.80.0-DEV)"
WORKERS = 12
PAGE_RE = re.compile(r"\.(png|webp|jpe?g)$", re.I)
SPINE_RE = re.compile(r"prefab/characterspine/(?P<kind>cg|portrait)/(?:(?P<cg>\d+)/)?(?P<id>\d+)$")

# Ejaan wiki yang beda dari translation EN.
NAME_ALIAS = {
    "naya": "naiya", "belphegor": "belphegar", "mammon": "greedmammon",
    "guinevere": "guinevere", "pennie": "penny",
}


def _log(m):
    sys.stderr.write("[%s] %s\n" % (time.strftime("%H:%M:%S"), m))
    sys.stderr.flush()


def http_get(url, tries=3, timeout=120):
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(1.2 * (i + 1))
    raise RuntimeError(f"GET gagal {url}: {last}")


def cached(name, raw, offline=False):
    p = os.path.join(CACHE, name)
    if offline:
        with open(p, "rb") as f:
            return f.read()
    tmp = p + ".part"
    with open(tmp, "wb") as f:
        f.write(raw)
    os.replace(tmp, p)
    return raw


def load_state():
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:  # noqa: BLE001
        return {}


def save_state(d):
    os.makedirs(CACHE, exist_ok=True)
    tmp = STATE_FILE + ".part"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=1, sort_keys=True)
    os.replace(tmp, STATE_FILE)


def ab_name(path):
    """Nama berkas AB = MD5(platform + path logis) uppercase."""
    return hashlib.md5((PLATFORM + path).encode("utf-8")).hexdigest().upper() + ".ab"


def ab_url(cfg, path):
    return cfg["AssetBundlePath"].rstrip("/") + "/" + PLATFORM + "/" + ab_name(path)


def xor_stream(raw):
    """Dekrip version.json / AB plaintext: plain[i] = cipher[i] ^ (i % 63)."""
    return bytes(c ^ (i % XOR_MOD) for i, c in enumerate(raw))


def get_config(offline=False):
    p = os.path.join(CACHE, "config.json")
    # JANGAN eval http_get() saat offline: argumen fungsi dievaluasi lebih
    # dulu, sehingga --offline tetap menyentuh jaringan walau cache ada.
    if offline:
        raw = open(p, "rb").read()
    else:
        raw = cached("config.json", http_get(CONFIG_URL, timeout=60), False)
    cfg = json.loads(raw)
    if not cfg.get("AssetBundlePath"):
        raise RuntimeError("AssetBundlePath kosong — config server sedang tidak merilis aset")
    return cfg, raw


def get_catalog(cfg, offline=False):
    if offline:
        return json.load(open(os.path.join(CACHE, "version.json"), encoding="utf-8")), \
            open(os.path.join(CACHE, "version.ab"), "rb").read()
    raw = http_get(ab_url(cfg, "version.json"), timeout=90)
    plain = xor_stream(raw)
    cat = json.loads(plain.decode("utf-8"))
    cached("version.ab", raw, False)
    cached("version.json", plain, False)
    return cat, raw


def aes_decrypt(raw):
    """AES-256-CBC + PKCS7. Pakai openssl agar tak bergantung pycryptodome."""
    p = subprocess.run(
        ["openssl", "enc", "-d", "-aes-256-cbc", "-K", AES_KEY,
         "-iv", AES_IV, "-nopad"],
        input=raw, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True,
    )
    plain = p.stdout
    pad = plain[-1]
    if not 1 <= pad <= 16 or plain[-pad:] != bytes([pad]) * pad:
        raise ValueError("PKCS7 padding tidak valid (key/IV berubah?)")
    return plain[:-pad]


def master_names(plain):
    """Ambil CHARACTER_NAME_* (kolom EN) dari tabel translation_ds."""
    import lz4.block  # noqa: PLC0415
    import msgpack  # noqa: PLC0415

    up = msgpack.Unpacker(raw=False, strict_map_key=False)
    up.feed(plain)
    header = next(up)
    base = up.tell()
    off, length = header["translation_ds"]
    region = plain[base + off:base + off + length]
    first = region[0]
    if first == 0xC7:
        elen, etype, pstart = region[1], region[2], 3
    elif first == 0xC8:
        elen, etype, pstart = struct.unpack_from(">H", region, 1)[0], region[3], 4
    else:
        elen, etype, pstart = struct.unpack_from(">I", region, 1)[0], region[5], 6
    payload = region[pstart:pstart + elen]
    if etype == 99:
        if payload[0] == 0xD2:
            size, comp = struct.unpack_from(">i", payload, 1)[0], payload[5:]
        else:
            size, comp = struct.unpack_from("<i", payload, 0)[0], payload[4:]
        rows = msgpack.unpackb(
            lz4.block.decompress(comp, uncompressed_size=size),
            raw=False, strict_map_key=False)
    else:
        rows = msgpack.unpackb(region, raw=False, strict_map_key=False)
    names = {}
    for r in rows:
        if (isinstance(r, list) and len(r) >= 4 and
                str(r[0]).startswith("CHARACTER_NAME_") and r[2]):
            names[str(r[0]).replace("CHARACTER_NAME_", "")] = str(r[2])
    return names


def spine_entries(cat):
    """[(path_logis, meta, kind, cg_no, char_id)] untuk semua bundle Spine."""
    out = []
    for path, meta in sorted(cat["assetBundleMetadatas"].items()):
        m = SPINE_RE.search(path)
        if not m:
            continue
        kind, cg, cid = m.group("kind"), m.group("cg"), m.group("id")
        folder = (f"cg{cg}_{cid}" if kind == "cg" else f"portrait_{cid}")
        out.append((path, meta, kind, cg, cid, folder))
    return out


def extract_ab(raw, dest, folder):
    """Buang fake-header UtS, load UnityPy, tulis .skel/.atlas/.png.

    Return nama skeleton (tanpa ekstensi) atau None kalau bukan bundle Spine.
    """
    import warnings  # noqa: PLC0415
    import UnityPy  # noqa: PLC0415

    warnings.filterwarnings("ignore", category=UserWarning)
    UnityPy.config.FALLBACK_UNITY_VERSION = UNITY_VERSION
    i = raw.find(b"UnityFS", 0, 16384)
    if i < 0:
        return None
    env = UnityPy.load(io.BytesIO(raw[i:]))
    texts, texes = {}, {}
    for obj in env.objects:
        try:
            d = obj.read()
        except Exception:  # noqa: BLE001
            continue
        n = getattr(d, "m_Name", "") or ""
        if obj.type.name == "TextAsset":
            s = getattr(d, "m_Script", b"")
            if isinstance(s, str):
                s = s.encode("utf-8", "surrogateescape")
            texts[n] = bytes(s or b"")
        elif obj.type.name == "Texture2D":
            try:
                texes[n] = d.image.convert("RGBA")
            except Exception:  # noqa: BLE001
                pass
    skels = [n for n in texts if n.lower().endswith(".skel")]
    atlases = [n for n in texts if n.lower().endswith(".atlas")]
    if not skels or not atlases:
        return None
    os.makedirs(dest, exist_ok=True)
    stem = None
    for n in skels + atlases:
        stem = re.sub(r"\.(skel|atlas)$", "", n, flags=re.I)
        with open(os.path.join(dest, n), "wb") as f:
            f.write(texts[n])
    # Halaman atlas -> Texture2D dengan nama sama; simpan persis sesuai atlas.
    atlas_txt = texts[atlases[0]].decode("utf-8", "replace")
    lines = atlas_txt.splitlines(True)
    for idx, ln in enumerate(lines):
        s = ln.strip()
        if not PAGE_RE.search(s) or ln[:1].isspace():
            continue
        nxt = next((lines[j].strip() for j in
                    range(idx + 1, min(len(lines), idx + 4)) if lines[j].strip()), "")
        if not re.match(r"^size:", nxt, re.I):
            continue
        key = re.sub(r"\.(png|webp|jpe?g)$", "", s, flags=re.I)
        img = texes.get(key) or texes.get(s) or next(
            (v for k, v in texes.items() if k.startswith(key)), None)
        if img is None:
            continue
        with open(os.path.join(dest, s), "wb") as f:
            import PIL.Image  # noqa: PLC0415
            buf = io.BytesIO()
            img.save(buf, "PNG")
            f.write(buf.getvalue())
        # Nama halaman mungkin masih mengandung karakter aneh -> samakan.
    return stem


def wiki_images(offline=False):
    p = os.path.join(CACHE, "wiki-images.json")
    if offline:
        # Offline tulen: kalau daftar belum pernah diunduh, jangan sentuh
        # jaringan. Thumbnail yang sudah ada di THUMBS tetap dipakai lewat
        # filter eksistensi berkas pada manifest.
        if os.path.exists(p):
            return json.load(open(p, encoding="utf-8"))
        return []
    tree = json.loads(http_get(WIKI_TREE, timeout=90))["tree"]
    paths = [x["path"] for x in tree
             if x.get("type") == "blob" and
             x["path"].startswith("public/images/characters/") and
             "card" not in x["path"].lower() and
             PAGE_RE.search(x["path"])]
    with open(p + ".part", "w", encoding="utf-8") as f:
        json.dump(paths, f)
    os.replace(p + ".part", p)
    return paths


def norm(s):
    return re.sub(r"[^a-z0-9]", "", s.lower())


def resolve_thumb(char_name, images):
    by = {}
    for p in images:
        by.setdefault(norm(os.path.basename(p).rsplit(".", 1)[0]), p)
    n = NAME_ALIAS.get(norm(char_name), norm(char_name))
    hit = by.get(n) or next((v for k, v in by.items()
                             if k.startswith(n) or n.startswith(k)), None)
    if not hit:
        close = difflib.get_close_matches(n, list(by), n=1, cutoff=0.72)
        hit = by[close[0]] if close else None
    return hit


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--offline", action="store_true",
                    help="pakai config/katalog/master/AB yang sudah ada di cache")
    a = ap.parse_args()
    if not (a.check or a.apply):
        a.check = True

    os.makedirs(CACHE, exist_ok=True)
    saved = load_state()
    cfg, cfg_raw = get_config(a.offline)
    cat, cat_raw = get_catalog(cfg, a.offline)
    ver = hashlib.sha1(cfg_raw + cat_raw).hexdigest()[:12]
    entries = spine_entries(cat)
    installed = set(saved.get("installed") or [])
    result = {
        "ok": True,
        "version": ver,
        "previous": saved.get("version") or None,
        "changed": ver != saved.get("version"),
        "catalogVersion": cat.get("version"),
        "catalogBundles": len(cat["assetBundleMetadatas"]),
        "expected": len(entries),
        "have": len(installed),
        "new": max(0, len(entries) - len(installed)),
        "source": "zonenova.future-step.net + CloudFront amgameasset",
    }
    if a.check:
        saved["checkedAt"] = int(time.time())
        save_state(saved)
        print(json.dumps(result, ensure_ascii=False, indent=1))
        return 0

    _log(f"katalog v{cat.get('version')}: {len(cat['assetBundleMetadatas'])} bundle, "
         f"{len(entries)} Spine")

    # --- master data (nama karakter Inggris) --------------------------------
    md_path = os.path.join(CACHE, "master-data.bytes")
    if a.offline:
        md_raw = open(md_path, "rb").read()
    else:
        md_raw = cached("master-data.bytes",
                        http_get(cfg.get("MasterDataDownloadPath") or MASTER_URL,
                                 timeout=180), False)
    names_en = master_names(aes_decrypt(md_raw))
    _log(f"nama karakter EN: {len(names_en)}")

    # --- unduh + ekstrak semua bundle Spine ---------------------------------
    jobs = []
    for path, meta, kind, cg, cid, folder in entries:
        jobs.append((path, folder, kind, cg, cid))
    dl_dir = os.path.join(CACHE, "bundles")
    os.makedirs(dl_dir, exist_ok=True)

    def fetch(job):
        path, folder, kind, cg, cid = job
        p = os.path.join(dl_dir, ab_name(path))
        if os.path.exists(p) and os.path.getsize(p) > 0:
            return (folder, p, None)
        try:
            if a.offline:
                raise RuntimeError("offline: berkas AB belum ada di cache")
            raw = http_get(ab_url(cfg, path), timeout=180)
            tmp = p + ".part"
            with open(tmp, "wb") as f:
                f.write(raw)
            os.replace(tmp, p)
            return (folder, p, None)
        except Exception as e:  # noqa: BLE001
            return (folder, None, f"{path}: {str(e)[:70]}")

    okc = 0
    fails = []
    with cf.ThreadPoolExecutor(max_workers=WORKERS) as ex:
        for i, (folder, p, err) in enumerate(ex.map(fetch, jobs), 1):
            if err:
                fails.append(err)
                continue
            okc += 1
            if i % 50 == 0:
                _log(f"  unduh {i}/{len(jobs)} ok={okc} gagal={len(fails)}")
    _log(f"unduh selesai: {okc}/{len(jobs)}, gagal={len(fails)}")

    import warnings  # noqa: PLC0415
    import UnityPy  # noqa: PLC0415
    warnings.filterwarnings("ignore", category=UserWarning)
    UnityPy.config.FALLBACK_UNITY_VERSION = UNITY_VERSION

    names, families, new_ids, model_meta = {}, {}, [], {}
    for path, folder, kind, cg, cid in jobs:
        p = os.path.join(dl_dir, ab_name(path))
        if not os.path.exists(p):
            continue
        dest = os.path.join(OUT, folder)
        if os.path.isdir(dest):
            shutil.rmtree(dest)
        try:
            stem = extract_ab(open(p, "rb").read(), dest, folder)
        except Exception as e:  # noqa: BLE001
            _log(f"  GAGAL ekstrak {folder}: {str(e)[:70]}")
            continue
        if not stem:
            shutil.rmtree(dest, ignore_errors=True)
            continue
        char = names_en.get(cid) or f"Character {cid}"
        label = (f"{char} — CG {cg}" if kind == "cg" else f"{char} — Portrait")
        names[folder] = {
            "name": label, "character": char, "id": cid,
            "kind": "CG" if kind == "cg" else "Portrait",
            "variant": f"CG {cg}" if kind == "cg" else "Portrait",
            "source": "Zone Nova master-data translation_ds",
        }
        mid = f"zonenova/{folder}"
        new_ids.append(mid)
        model_meta[folder] = (char, cid)
        families.setdefault(cid, []).append({
            "id": mid, "label": f"CG {cg}" if kind == "cg" else "Portrait",
            "default": kind == "portrait", "name": char,
        })

    # --- nama + family ------------------------------------------------------
    os.makedirs(DATA, exist_ok=True)
    fam_list = []
    for cid, mem in sorted(families.items()):
        if len(mem) < 2:
            continue
        mem.sort(key=lambda x: (not x["default"], x["id"]))
        fam_list.append({"root": mem[0]["id"], "name": mem[0]["name"],
                         "members": [{"id": x["id"], "label": x["label"]} for x in mem]})
    for p, payload in ((NAMES_FILE, names), (FAMILY_FILE, {"families": fam_list})):
        with open(p + ".part", "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=1, sort_keys=True)
        os.replace(p + ".part", p)

    # --- thumbnail ilustrasi dari GachaWiki ---------------------------------
    os.makedirs(THUMBS, exist_ok=True)
    from PIL import Image  # noqa: PLC0415
    images = wiki_images(a.offline)
    char_thumb, manifest = {}, {}
    for folder, (char, cid) in model_meta.items():
        art = char_thumb.get(cid)
        if art is None:
            art = resolve_thumb(char, images)
            char_thumb[cid] = art
        if art:
            manifest[f"zonenova/{folder}"] = f"{cid}.webp"

    def one(item):
        cid, art = item
        out = os.path.join(THUMBS, f"{cid}.webp")
        if os.path.exists(out) and os.path.getsize(out) > 0:
            return True
        try:
            raw = http_get(WIKI_RAW + "/" + urllib.parse.quote(art, safe="/"),
                           timeout=90)
            im = Image.open(io.BytesIO(raw)).convert("RGBA")
            im.thumbnail((320, 420), Image.Resampling.LANCZOS)
            tmp = out + ".part"
            im.save(tmp, "WEBP", quality=82, method=4)
            os.replace(tmp, out)
            return True
        except Exception as e:  # noqa: BLE001
            _log(f"  gagal thumbnail {cid}: {str(e)[:60]}")
            return False

    todo = [(cid, art) for cid, art in char_thumb.items() if art]
    if not a.offline:
        with cf.ThreadPoolExecutor(max_workers=WORKERS) as ex:
            list(ex.map(one, todo))
    manifest = {k: v for k, v in manifest.items()
                if os.path.exists(os.path.join(THUMBS, v))}
    os.makedirs(THUMBS, exist_ok=True)
    with open(MANIFEST_FILE + ".part", "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=1, sort_keys=True)
    os.replace(MANIFEST_FILE + ".part", MANIFEST_FILE)
    used = set(manifest.values())
    for f in os.listdir(THUMBS):
        if f.endswith(".webp") and f not in used:
            os.remove(os.path.join(THUMBS, f))

    saved.update({
        "version": ver, "catalogVersion": cat.get("version"),
        "appliedAt": int(time.time()), "installed": sorted(names),
        "models": len(new_ids), "names": len(names_en),
        "families": len(fam_list), "thumbs": len(used),
    })
    save_state(saved)
    result.update({
        "expected": len(names), "have": len(names), "new": 0,
        "added": len(new_ids), "new_ids": new_ids,
        "new_models": [x.split("/", 1)[1] for x in new_ids],
        "names": len(names), "families": len(fam_list),
        "thumbJobs": len(todo), "thumbs": len(used),
        "failedFiles": len(fails),
    })
    _log(f"=== selesai: {len(names)} model, {len(fam_list)} family, "
         f"{len(used)} thumbnail, gagal unduh={len(fails)}")
    print(json.dumps(result, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
