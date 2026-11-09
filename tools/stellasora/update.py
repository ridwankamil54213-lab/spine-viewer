#!/usr/bin/env python3
"""Pembaru Stella Sora (Yostar) — Spine 4.2 + Live2D Cubism 4.

Sumber PALING SEGAR yang bisa dipakai langsung (per 2026-11-09):

  model   https://pub-fc0f3c90b1b34cacb1ce80b771ca4b08.r2.dev/
          aset viewer komunitas morphthemoth/Stella-Sora-Live2d (Patch 2.0.1)
          - chars/<skin>/<variant>/*.model3.json -> Live2D (.moc3 + tekstur
            + motions/ + physics3), diratakan supaya cocok dengan scanner
            Live2D src/server.js (moc3 & tekstur di root folder, motions/
            dan expressions/ di subfolder).
          - events/<ref>/spine/*.skel/.atlas/.png -> Spine 4.2.43.
  data    raw.githubusercontent.com/morphthemoth/Stella-Sora-Live2d/master/
          data/{models,events,avg,characterid}.json (nama Inggris + varian).
  ilustrasi  avg/<id>/<pose>.png dari R2 yang sama (bukan halaman atlas).
  sinyal rilis  https://nova-static.stellasora.global/meta/win.html (CDN
          RESMI game, real-time) + commit AutumnVN/StellaSoraData (sync 5 mnt).
          Keduanya cuma jadi penanda kesegaran, bukan sumber model: repo
          komunitas bisa telat beberapa jam, tapi --check tetap tahu kalau
          game baru saja patch.

Pemakaian:
    /srv/venv-spine/bin/python tools/stellasora/update.py --check
    /srv/venv-spine/bin/python tools/stellasora/update.py --apply
    /srv/venv-spine/bin/python tools/stellasora/refresh.py   # --offline
"""
import argparse
import concurrent.futures as cf
import hashlib
import io
import json
import os
import re
import shutil
import sys
import time
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ASSETS = os.path.join(ROOT, "assets")
SPINE_OUT = os.environ.get("SS_SPINE_OUT", os.path.join(ASSETS, "stellasora"))
L2D_OUT = os.environ.get("SS_L2D_OUT", os.path.join(ASSETS, "stellasora-l2d"))
DATA = os.path.join(ROOT, "data")
THUMBS = os.environ.get("SS_THUMBS", os.path.join(ROOT, "public", "thumbs", "stellasora"))
CACHE = os.environ.get("SS_CACHE", "/srv/spine-assets/stellasora")
STATE_FILE = os.path.join(CACHE, "state.json")

R2 = "https://pub-fc0f3c90b1b34cacb1ce80b771ca4b08.r2.dev"
DATA_RAW = "https://raw.githubusercontent.com/morphthemoth/Stella-Sora-Live2d/master/data"
CDN_MANIFEST = "https://nova-static.stellasora.global/meta/win.html"
DATA_COMMIT_API = "https://api.github.com/repos/AutumnVN/StellaSoraData/commits?per_page=1"
UA = "spine-viewer-stellasora-updater/1.0"
WORKERS = 16
PAGE_RE = re.compile(r"\.(png|webp|jpe?g)$", re.I)
BAD = re.compile(r"[^A-Za-z0-9_.\-]+")
DATA_FILES = ("models.json", "events.json", "avg.json", "characterid.json")


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


def safe(s):
    return BAD.sub("_", s).strip("._") or "m"


def cache_path(rel):
    return os.path.join(CACHE, rel)


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


def fetch_data(offline=False):
    """4 data JSON komunitas + 2 sinyal kesegaran."""
    out = {}
    for name in DATA_FILES:
        p = cache_path("data-" + name)
        if offline:
            out[name] = open(p, "rb").read()
        else:
            raw = http_get(f"{DATA_RAW}/{name}", timeout=90)
            with open(p + ".part", "wb") as f:
                f.write(raw)
            os.replace(p + ".part", p)
            out[name] = raw
    signals = {}
    if offline:
        signals["cdnSha"] = load_state().get("cdnSha")
        signals["dataCommit"] = load_state().get("dataCommit")
    else:
        try:
            signals["cdnSha"] = hashlib.sha1(
                http_get(CDN_MANIFEST, tries=2, timeout=90)).hexdigest()[:12]
        except Exception as e:  # noqa: BLE001
            _log(f"  CDN manifest tak terbaca ({str(e)[:50]}), pakai cache")
            signals["cdnSha"] = load_state().get("cdnSha")
        try:
            c = json.loads(http_get(DATA_COMMIT_API, tries=2, timeout=60))[0]
            signals["dataCommit"] = c["sha"][:12]
        except Exception:  # noqa: BLE001
            signals["dataCommit"] = load_state().get("dataCommit")
    return out, signals


def spine_jobs(events):
    """[(folder, [(url_rel, dest_name), ...], display, char_id)]"""
    jobs = []
    cjk = re.compile(r"[\u4e00-\u9fff]")
    for ref, ev in sorted(events.items()):
        ev_name = ev.get("name") or f"Event {ref}"
        if cjk.search(ev_name):
            ev_name = f"Event {ref}"
        for sp in (ev.get("spines") or []):
            name = sp.get("name") or "spine"
            if cjk.search(name):
                name = "Spine"
            folder = safe(f"{ref}_{name}")
            files = []
            for key in ("skel", "atlas"):
                f = sp.get(key)
                if f:
                    files.append((f"events/{ref}/spine/{f}", f))
            for t in (sp.get("textures") or []):
                f = t.get("file")
                if f:
                    files.append((f"events/{ref}/spine/{f}", f))
            jobs.append({
                "game": "stellasora", "folder": folder, "files": files,
                "name": f"{ev_name} — {name}",
                "character": ev_name, "charId": None,
                "variant": name, "label": name,
            })
    return jobs


def l2d_refs(model3):
    """Daftar (url_rel, dest_rel) dari FileReferences sebuah .model3.json."""
    fr = model3.get("FileReferences") or {}
    out = []
    moc = fr.get("Moc")
    if moc:
        out.append((moc, os.path.basename(moc)))
    for t in (fr.get("Textures") or []):
        if t:
            out.append((t, os.path.basename(t)))
    for key in ("Physics", "DisplayInfo", "Pose"):
        f = fr.get(key)
        if f:
            out.append((f, os.path.basename(f)))
    for group in (fr.get("Motions") or {}).values():
        for m in group or []:
            f = m.get("File") if isinstance(m, dict) else None
            if f:
                out.append((f, "motions/" + os.path.basename(f)))
    for e in (fr.get("Expressions") or []):
        f = e.get("File") if isinstance(e, dict) else None
        if f:
            out.append((f, "expressions/" + os.path.basename(f)))
    return out


def l2d_jobs(models, charid_keys=()):
    """Satu job per varian. charId 3-digit dicocokkan dari characterid.json
    supaya family & thumbnail bisa dikelompokkan per karakter, bukan per skin."""
    keys = sorted(charid_keys, key=len, reverse=True)
    jobs = []
    for ch in models:
        cid = str(ch.get("id") or "")
        cname = ch.get("name") or cid
        char_key = next((k for k in keys if cid.startswith(k)), None)
        for v in (ch.get("variants") or []):
            p = v.get("path")
            # models.json juga memuat 36 varian ".skel" (sama dengan event
            # Spine di events.json) dan 5 "body.png" statis. Keduanya BUKAN
            # Live2D; jangan coba parse sebagai .model3.json.
            if not p or not p.endswith(".model3.json"):
                continue
            base = p.rsplit("/", 1)[0]
            folder = safe(v.get("name") or p.split("/")[-2])
            jobs.append({
                "game": "stellasora-l2d", "folder": folder,
                "base": base, "model3": p,
                "name": f"{cname} — {v.get('label') or 'Varian'}",
                "character": cname, "charId": char_key or cid,
                "variant": v.get("label") or "Varian", "label": v.get("label") or "Varian",
            })
    return jobs


def fetch_asset(url_rel):
    return http_get(R2 + "/" + urllib.parse.quote(url_rel, safe="/"),
                    tries=2, timeout=120)


def asset_cache_path(rel):
    return os.path.join(CACHE, "assets", rel.replace("/", "_"))


def prefetch(rels, workers=WORKERS):
    """Unduh semua berkas R2 sekali jalan, paralel. Gagal (404) dilewati
    supaya ekstraksi tetap lanjut untuk model yang lengkap."""
    todo = sorted(set(rels))
    done = fail = skip = 0

    def one(rel):
        p = asset_cache_path(rel)
        if os.path.exists(p) and os.path.getsize(p) > 0:
            return "skip"
        try:
            raw = fetch_asset(rel)
        except Exception:  # noqa: BLE001
            return "fail"
        with open(p + ".part", "wb") as f:
            f.write(raw)
        os.replace(p + ".part", p)
        return "ok"

    with cf.ThreadPoolExecutor(max_workers=workers) as ex:
        for i, state in enumerate(ex.map(one, todo), 1):
            if state == "ok":
                done += 1
            elif state == "skip":
                skip += 1
            else:
                fail += 1
            if i % 500 == 0:
                _log(f"  prefetch {i}/{len(todo)} ok={done} skip={skip} gagal={fail}")
    _log(f"prefetch: {len(todo)} berkas, ok={done} skip={skip} gagal={fail}")
    return done, skip, fail


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--offline", action="store_true",
                    help="pakai data + aset yang sudah ada di cache (tanpa jaringan)")
    a = ap.parse_args()
    if not (a.check or a.apply):
        a.check = True

    os.makedirs(CACHE, exist_ok=True)
    saved = load_state()
    raws, signals = fetch_data(a.offline)
    models = json.loads(raws["models.json"])
    events = json.loads(raws["events.json"])
    avg = json.loads(raws["avg.json"])
    charid = json.loads(raws["characterid.json"])
    ver = hashlib.sha1(b"".join(raws[n] for n in DATA_FILES)).hexdigest()[:12]

    spine = spine_jobs(events)
    l2d = l2d_jobs(models, charid.keys())
    expected = len(spine) + len(l2d)
    installed = set(saved.get("installed") or [])
    result = {
        "ok": True, "version": ver,
        "previous": saved.get("version") or None,
        "changed": ver != saved.get("version"),
        "expected": expected, "have": len(installed),
        "new": max(0, expected - len(installed)),
        "spineModels": len(spine), "l2dModels": len(l2d),
        "cdnSha": signals.get("cdnSha"), "dataCommit": signals.get("dataCommit"),
        "source": "StellaSora L2D R2 + morphthemoth data + live Yostar CDN signal",
    }
    if a.check:
        saved["checkedAt"] = int(time.time())
        saved["cdnSha"] = signals.get("cdnSha")
        saved["dataCommit"] = signals.get("dataCommit")
        save_state(saved)
        print(json.dumps(result, ensure_ascii=False, indent=1))
        return 0

    _log(f"model: {len(spine)} Spine 4.2 + {len(l2d)} Live2D")
    os.makedirs(CACHE + "/assets", exist_ok=True)
    bucket = os.path.join(CACHE, "assets")

    def cached_asset(rel):
        p = asset_cache_path(rel)
        if os.path.exists(p) and os.path.getsize(p) > 0:
            return open(p, "rb").read()
        if a.offline:
            raise RuntimeError(f"offline: {rel} belum ada di cache")
        raw = fetch_asset(rel)
        with open(p + ".part", "wb") as f:
            f.write(raw)
        os.replace(p + ".part", p)
        return raw

    # --- prefetch paralel ---------------------------------------------------
    # Tanpa ini 293 model3 + ~3.500 berkasreferensi diunduh satu-satu dan
    # apply bisa makan belasan menit. Dua ronde: model3 dulu (biar tahu daftar
    # berkasnya), lalu semua referensi + aset Spine + potret AVG.
    if not a.offline:
        round1 = {rel for j in spine for rel, _ in j["files"]}
        round1.update(j["model3"] for j in l2d)
        for item in avg:
            body = (item.get("poses") or [{}])[0].get("body")
            if body and item.get("id"):
                round1.add("avg/" + item["id"] + "/" + body)
        prefetch(round1)
        round2 = set()
        for j in l2d:
            try:
                m3 = json.loads(cached_asset(j["model3"]))
            except Exception:  # noqa: BLE001
                continue
            for rel, _ in l2d_refs(m3):
                round2.add(j["base"] + "/" + rel)
        prefetch(round2)
        # Semua sudah di cache; sisa proses murni lokal & deterministik.
        a.offline = True

    names = {"stellasora": {}, "stellasora-l2d": {}}
    families = {"stellasora": {}, "stellasora-l2d": {}}
    new_ids = []
    model_chars = {}

    # ---- Spine: event/<ref>/spine/* ---------------------------------------
    for job in spine:
        dest = os.path.join(SPINE_OUT, job["folder"])
        if os.path.isdir(dest):
            shutil.rmtree(dest)
        os.makedirs(dest, exist_ok=True)
        got = 0
        atlas_name = None
        for rel, fname in job["files"]:
            try:
                raw = cached_asset(rel)
            except Exception as e:  # noqa: BLE001
                _log(f"  GAGAL {rel}: {str(e)[:60]}")
                continue
            if fname.lower().endswith(".atlas"):
                atlas_name = fname
                # Baris halaman atlas harus menunjuk nama berkas yang ada.
                ren = {f: os.path.basename(f) for _, f in job["files"]}
                txt = raw.decode("utf-8", "replace")
                nl = "\r\n" if "\r\n" in txt else "\n"
                lines = txt.splitlines()
                out = []
                for i, ln in enumerate(lines):
                    s = ln.strip()
                    if PAGE_RE.search(s) and not ln[:1].isspace():
                        nxt = next((lines[j].strip() for j in
                                    range(i + 1, min(len(lines), i + 4))
                                    if lines[j].strip()), "")
                        if re.match(r"^size:", nxt, re.I) and s in ren:
                            ln = ln.replace(s, os.path.basename(s))
                    out.append(ln)
                raw = (nl.join(out) + nl).encode("utf-8")
            with open(os.path.join(dest, os.path.basename(fname)), "wb") as f:
                f.write(raw)
            got += 1
        if got < 3 or not atlas_name:
            shutil.rmtree(dest, ignore_errors=True)
            continue
        mid = f"stellasora/{job['folder']}"
        new_ids.append(mid)
        names["stellasora"][job["folder"]] = {
            "name": job["name"], "character": job["character"],
            "variant": job["variant"], "source": "StellaSora event spine",
        }
        families["stellasora"].setdefault(job["character"], []).append(
            {"id": mid, "label": job["label"], "default": False,
             "name": job["character"]})
        model_chars[mid] = None

    # ---- Live2D: chars/<skin>/<variant>/ ----------------------------------
    for job in l2d:
        dest = os.path.join(L2D_OUT, job["folder"])
        if os.path.isdir(dest):
            shutil.rmtree(dest)
        os.makedirs(dest, exist_ok=True)
        try:
            m3 = json.loads(cached_asset(job["model3"]))
        except Exception as e:  # noqa: BLE001
            _log(f"  GAGAL model3 {job['model3']}: {str(e)[:60]}")
            shutil.rmtree(dest, ignore_errors=True)
            continue
        refs = l2d_refs(m3)
        okc = 0
        for rel, destrel in refs:
            full = job["base"] + "/" + rel
            try:
                raw = cached_asset(full)
            except Exception:  # noqa: BLE001
                continue
            target = os.path.join(dest, destrel)
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with open(target, "wb") as f:
                f.write(raw)
            okc += 1
        if not any(f.lower().endswith(".moc3") for f in os.listdir(dest)):
            shutil.rmtree(dest, ignore_errors=True)
            continue
        mid = f"stellasora-l2d/{job['folder']}"
        new_ids.append(mid)
        names["stellasora-l2d"][job["folder"]] = {
            "name": job["name"], "character": job["character"],
            "variant": job["variant"], "source": "StellaSora Live2D R2",
        }
        families["stellasora-l2d"].setdefault(job["charId"], []).append(
            {"id": mid, "label": job["label"],
             "default": job["label"].lower() in ("default", "utama"),
             "name": job["character"]})
        model_chars[mid] = job["charId"]

    # ---- nama + family -----------------------------------------------------
    os.makedirs(DATA, exist_ok=True)
    fam_count = {}
    for game in ("stellasora", "stellasora-l2d"):
        with open(os.path.join(DATA, game + "-names.json") + ".part", "w",
                  encoding="utf-8") as f:
            json.dump(names[game], f, ensure_ascii=False, indent=1, sort_keys=True)
        os.replace(os.path.join(DATA, game + "-names.json") + ".part",
                   os.path.join(DATA, game + "-names.json"))
        fl = []
        for key, mem in sorted(families[game].items()):
            if len(mem) < 2:
                continue
            mem.sort(key=lambda x: (not x["default"], x["id"]))
            fl.append({"root": mem[0]["id"], "name": mem[0]["name"],
                       "members": [{"id": x["id"], "label": x["label"]} for x in mem]})
        fam_count[game] = len(fl)
        with open(os.path.join(DATA, game + "-family.json") + ".part", "w",
                  encoding="utf-8") as f:
            json.dump({"families": fl}, f, ensure_ascii=False, indent=1, sort_keys=True)
        os.replace(os.path.join(DATA, game + "-family.json") + ".part",
                   os.path.join(DATA, game + "-family.json"))

    # ---- thumbnail ilustrasi dari potret AVG --------------------------------
    from PIL import Image  # noqa: PLC0415
    os.makedirs(THUMBS, exist_ok=True)
    portrait = {}
    for item in avg:
        sid = item.get("shortId") or ""
        m = re.search(r"_(\d+)$", sid)
        cid = m.group(1) if m else None
        body = (item.get("poses") or [{}])[0].get("body")
        if cid and body and cid not in portrait:
            portrait[cid] = ("avg/" + item["id"] + "/" + body, item.get("name"))

    def one(item):
        cid, (rel, _) = item
        out = os.path.join(THUMBS, cid + ".webp")
        if os.path.exists(out) and os.path.getsize(out) > 0:
            return True
        try:
            raw = cached_asset(rel)
            im = Image.open(io.BytesIO(raw)).convert("RGBA")
            im.thumbnail((320, 420), Image.Resampling.LANCZOS)
            tmp = out + ".part"
            im.save(tmp, "WEBP", quality=82, method=4)
            os.replace(tmp, out)
            return True
        except Exception as e:  # noqa: BLE001
            _log(f"  gagal thumb {cid}: {str(e)[:50]}")
            return False

    # Potret AVG sudah di-prefetch, jadi blok ini jalan walau mode offline.
    with cf.ThreadPoolExecutor(max_workers=WORKERS) as ex:
        list(ex.map(one, sorted(portrait.items())))
    manifest = {}
    for mid, cid in model_chars.items():
        if cid and cid in portrait and os.path.exists(
                os.path.join(THUMBS, cid + ".webp")):
            manifest[mid] = cid + ".webp"
    with open(os.path.join(THUMBS, "_manifest.json") + ".part", "w",
              encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=1, sort_keys=True)
    os.replace(os.path.join(THUMBS, "_manifest.json") + ".part",
               os.path.join(THUMBS, "_manifest.json"))

    saved.update({
        "version": ver, "appliedAt": int(time.time()),
        "installed": sorted((names["stellasora"].keys()) |
                            set(names["stellasora-l2d"].keys())),
        "spine": len(names["stellasora"]), "l2d": len(names["stellasora-l2d"]),
        "families": fam_count, "thumbs": len(set(manifest.values())),
        "cdnSha": signals.get("cdnSha"), "dataCommit": signals.get("dataCommit"),
        "characterNames": len(charid),
    })
    save_state(saved)
    result.update({
        "expected": len(new_ids), "have": len(new_ids), "new": 0,
        "added": len(new_ids), "new_ids": new_ids,
        "new_models": [x.split("/", 1)[1] for x in new_ids],
        "names": sum(len(v) for v in names.values()),
        "families": sum(fam_count.values()), "thumbs": len(set(manifest.values())),
        "thumbsManifest": len(manifest),
    })
    _log(f"=== selesai: {len(names['stellasora'])} Spine, "
         f"{len(names['stellasora-l2d'])} Live2D, "
         f"{sum(fam_count.values())} family, {len(set(manifest.values()))} thumbnail")
    print(json.dumps(result, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
