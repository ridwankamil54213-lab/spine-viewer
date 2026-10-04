#!/usr/bin/env python3
"""决战僵尸舞娘 (Decisive Battle Zombie Dancer) — Cocos Creator asset tool.

Game ini beda total dari 蜜桃乌托邦: BUKAN Unity, tapi **Cocos Creator 3.x JS**
(`libcocos2djs.so`, `assets/**/*.jsc`). Tidak ada AssetBundle / IDOLAB2 —
malah tidak ada enkripsi sama sekali di jalur hot-update ini (asetnya JSON/PNG
polos, cuma `_skeletonJson` yang perlu diurai dari struktur Cocos).

Chain (semua reverse-engineered dari IL tool + `startup-config.json` APK):

  1. APK berisi `assets/src/startup-config.json`  -> channel "18game"
       domainConfigUrls : kaipao-domains.bmmqga.com/domain-config.json
       resDomains       : res-kaipao.bmmqga.com  (+ cadangan xjhwlgy.com)
  2. GET  {mainDomain}/config/26/18game.json?h5t={ms}
       -> gameConfig.hotUpdateUrl = /18game/android/<ver>/
          gameConfig.resPath     = https://res-kaipao.bmmqga.com
  3. GET  {resPath}{hotUpdateUrl}project.manifest   (Cocos, 2720 aset)
  4. GET  {resPath}{hotUpdateUrl}assets/resources/config.<hash>.json
       -> paths/uuids/types: peta uuid -> path + tipe
  5. Untuk setiap `sp.SkeletonData`:
       a. unduh import/<xx>/<uuid>.<hash>.json  (Cocos array; _atlasText +
          _skeletonJson + textureNames ADA DI DALAMNYA — self-contained)
       b. unduh native/<xx>/<uuid>.<hash>.png   (halaman atlas, polos)
       c. tulis <out>/<model>/<nama>.skel|.json + .atlas + <page>.png

Catatan: `sp.SkeletonData` baru ada di hot-update (server), TIDAK ada di APK —
APK-nya cuma shell. Versi di APK (2.0.5.8) beda dari versi aset (2.0.4.9).

Usage:
    zhanjiang-download.py --apk game.apk --out bundles          # skeleton
    zhanjiang-download.py --apk game.apk --out bundles --textures
"""
import argparse
import io
import json
import os
import re
import sys
import time
import urllib.request
import zipfile
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
TIMEOUT = 180

B64 = {c: i for i, c in enumerate(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/")}


def log(*a):
    print(*a, flush=True)


def decode_uuid(u: str) -> str:
    """Cocos compressed uuid (22 char) -> full 36-char uuid.

    first 2 chars kept, then each pair expands to 3 hex chars:
      n+1 = 2 bits, n+1 = 4 bits, n+1 = 4 bits
    """
    if not u or len(u) != 22:
        return u
    out = u[0] + u[1]
    for i in range(2, 22, 2):
        l = B64[u[i]]
        r = B64[u[i + 1]]
        out += "%x%x%x" % (l >> 2, ((l & 3) << 2) | (r >> 4), r & 0xF)
    return "%s-%s-%s-%s-%s" % (out[0:8], out[8:12], out[12:16], out[16:20], out[20:32])


def http_get(url: str, timeout: int = TIMEOUT) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = r.read()
    # Beberapa CDN balikin 200 dengan body XML error.
    if data[:5] == b"<?xml":
        raise RuntimeError(f"CDN error body: {data[:120]!r}")
    return data


def http_json(url: str, timeout: int = TIMEOUT):
    return json.loads(http_get(url, timeout).decode("utf-8", "replace"))


# --- 1..3: temukan versi hot-update + manifest -------------------------------
def read_startup_config(apk: str, channel: str = "18game") -> dict:
    with zipfile.ZipFile(apk) as z:
        name = next(n for n in z.namelist() if n.endswith("startup-config.json"))
        cfg = json.loads(z.read(name).decode("utf-8-sig"))
    ch = (cfg.get("channels") or {}).get(channel)
    if not ch:
        raise RuntimeError(f"channel {channel!r} tidak ada di startup-config.json")
    return cfg, ch


def resolve_hot_update(apk: str, channel: str = "18game") -> dict:
    cfg, ch = read_startup_config(apk, channel)
    code = ch["backstageCode"]
    ms = int(time.time() * 1000)

    # domain-config (opsional, buat kesegaran resDomains)
    for dc in ch.get("domainConfigUrls") or []:
        try:
            d = http_json(dc)
            if d.get("resDomains"):
                ch["resDomains"] = d["resDomains"]
            break
        except Exception:
            continue

    last = None
    for md in ch["mainDomains"]:
        url = f"{md.rstrip('/')}/config/{code}/{channel}.json?h5t={ms}"
        try:
            cfgj = http_json(url)
        except Exception as e:
            last = f"{url}: {e}"
            continue
        gc = cfgj.get("gameConfig") or {}
        if not gc.get("hotUpdateUrl"):
            last = f"{url}: tidak ada hotUpdateUrl"
            continue
        return {
            "index": cfg.get("index"),
            "channel": channel,
            "backstageCode": code,
            "version": gc.get("version"),
            "resPath": (gc.get("resPath") or "").rstrip("/"),
            "hotUpdateUrl": gc["hotUpdateUrl"],
            "resDomains": ch["resDomains"],
            "configUrl": url,
        }
    raise RuntimeError(f"tidak bisa ambil config game ({last})")


def load_manifest(base: str) -> dict:
    return http_json(base.rstrip("/") + "/project.manifest")


def load_resource_config(base: str, manifest: dict) -> dict:
    """config.<hash>.json untuk paket 'resources'."""
    cands = [k for k in manifest["assets"]
             if k.startswith("assets/resources/config.") and k.endswith(".json")]
    if not cands:
        raise RuntimeError("config.json resources tidak ada di manifest")
    return http_json(base.rstrip("/") + "/" + cands[0])


# --- 4..5: petakan uuid -> file, ambil spine --------------------------------
def file_for(uuid_full: str, manifest: dict, kind: str) -> str:
    """kind: 'import' atau 'native'. Cocokkan tanpa tanda hubung."""
    want = uuid_full.replace("-", "")
    for k in manifest["assets"]:
        kk = k.replace("-", "")
        if want in kk and f"/{kind}/" in k:
            return k
    return ""


def spine_entries(rcfg: dict) -> list:
    """Semua sp.SkeletonData: [{name, path, uuid, skel_key, tex_uuids, atlas}]."""
    paths, uuids, types = rcfg["paths"], rcfg["uuids"], rcfg["types"]
    skel_type = types.index("sp.SkeletonData") if "sp.SkeletonData" in types else -1
    out = []
    for k, v in paths.items():
        if v[1] != skel_type:
            continue
        idx = int(k)
        out.append({"name": v[0], "path": v[0], "uuid": uuids[idx],
                    "index": idx})
    return out


def parse_cocos_asset(raw: bytes):
    """Ambil objek Cocos dari array deserialisasi.

    Struktur: [ver, sharedUuids, sharedStrings, classDefs, ...,
               [objId, *fields]] dan classDefs menyebut urutan field.
    objek pertama ada di list terakhir yang elemennya sendiri list.
    """
    d = json.loads(raw.decode("utf-8", "replace"))
    # classDefs
    cls = d[3][0]
    fields = cls[1]
    # cari list objek: list of lists dgn >1 elemen, ambil yg terakhir
    rows = [e for e in d if isinstance(e, list) and e and isinstance(e[0], list) and len(e[0]) > 1]
    obj = None
    for r in reversed(d):
        if isinstance(r, list) and r and isinstance(r[0], list) and len(r[0]) > 1:
            obj = r[0]
            break
    if obj is None:
        return None, None, None
    vals = obj[1:]
    rec = {}
    for nm, val in zip(fields[:len(vals)], vals):
        rec[nm] = val
    return rec, fields, d


def sanitize(s: str) -> str:
    s = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", str(s)).strip("._ ")
    return s or "model"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apk", required=True, help="APK (untuk startup-config.json)")
    ap.add_argument("--out", required=True)
    ap.add_argument("--channel", default="18game")
    ap.add_argument("--textures", action="store_true", help="unduh juga halaman PNG")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--only", default=None, help="filter substring path")
    args = ap.parse_args()

    info = resolve_hot_update(args.apk, args.channel)
    log(f"channel    : {info['channel']} (backstage {info['backstageCode']})")
    log(f"versi aset : {info['version']}")
    log(f"resPath    : {info['resPath']}")
    log(f"hotUpdate  : {info['hotUpdateUrl']}")
    base = info["resPath"] + info["hotUpdateUrl"]
    log(f"base       : {base}\n")

    manifest = load_manifest(base)
    log(f"manifest   : {len(manifest['assets'])} aset")
    rcfg = load_resource_config(base, manifest)
    log(f"config     : {len(rcfg['paths'])} path\n")

    entries = spine_entries(rcfg)
    if args.only:
        entries = [e for e in entries if args.only in e["path"]]
    if args.limit:
        entries = entries[:args.limit]
    log(f"spine      : {len(entries)} skeleton untuk diunduh\n")

    os.makedirs(args.out, exist_ok=True)
    ok = fail = 0
    fails = []
    for i, e in enumerate(entries, 1):
        full = decode_uuid(e["uuid"])
        skel_key = file_for(full, manifest, "import")
        if not skel_key:
            fail += 1; fails.append(f"{e['path']}: skeleton {full} tak ada di manifest"); continue
        try:
            raw = http_get(base.rstrip("/") + "/" + skel_key)
            rec, fields, arr = parse_cocos_asset(raw)
        except Exception as ex:
            fail += 1; fails.append(f"{e['path']}: {ex}"); continue
        if not rec or "_skeletonJson" not in rec:
            fail += 1; fails.append(f"{e['path']}: bukan sp.SkeletonData"); continue

        name = sanitize(rec.get("_name") or os.path.basename(e["path"]))
        mdir = os.path.join(args.out, sanitize(e["path"]))
        os.makedirs(mdir, exist_ok=True)

        # atlas + skeleton JSON
        atlas = rec.get("_atlasText") or ""
        open(os.path.join(mdir, f"{name}.atlas"), "w", encoding="utf-8").write(atlas)
        sj = rec["_skeletonJson"]
        if isinstance(sj, str):
            open(os.path.join(mdir, f"{name}.json"), "w", encoding="utf-8").write(sj)
            ext = ".json"
        else:
            open(os.path.join(mdir, f"{name}.json"), "w", encoding="utf-8").write(
                json.dumps(sj, ensure_ascii=False))
            ext = ".json"

        # halaman atlas
        pages = [l.strip() for l in atlas.splitlines()
                 if l.strip().lower().endswith((".png", ".jpg")) and " " not in l.strip()]
        tex_uuids = rec.get("textureNames") or []
        done = 0
        if args.textures:
            for pg in pages:
                # textureNames sejajar dengan halaman; uuid dari d[1] dependency
                dep = arr[1] if len(arr) > 1 and isinstance(arr[1], list) else []
                for cu in dep:
                    tfull = decode_uuid(cu)
                    tkey = file_for(tfull, manifest, "native")
                    if tkey and tkey.lower().endswith((".png", ".jpg", ".webp")):
                        try:
                            blob = http_get(base.rstrip("/") + "/" + tkey)
                            open(os.path.join(mdir, pg), "wb").write(blob)
                            done += 1
                        except Exception:
                            pass
                        break
        ok += 1
        if i % 5 == 0 or i == len(entries):
            log(f"[{i}/{len(entries)}] ok={ok} fail={fail} tex={done}  ({e['path']})")

    log(f"\nSELESAI ok={ok} fail={fail} -> {args.out}")
    if fails:
        log(f"\ngagal ({len(fails)}):")
        for f in fails[:12]:
            log("  ", f)


if __name__ == "__main__":
    main()
