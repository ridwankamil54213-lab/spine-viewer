#!/usr/bin/env python3
"""Pembaru Azur Lane (azurlane) — skin kapal (spine painting).

Sumber  : github.com/ww-rm/azurlane_spinepainting (repo komunitas 碧蓝航线
          dynamic painting). Self-contained: docs/index.json memetakan
          ship -> skin -> {skelName, atlasName, pages[]}, dan berkasnya ada di
          docs/<Ship>/<Skin>/.
          Unduhan lewat raw.githubusercontent.com (tak butuh GitHub API dan
          tak kena rate limit API; cukup 2 request: 1 index + N berkas).
Layout  : assets/azurlane/<Skin>/<Skin>.skel (+ .atlas + halaman .png)
          — persis yang sudah dibaca viewer (folder = satu model / skin).
Nama    : menambah entri ke data/azurlane-names.json dari nama TIONGHOA repo
          (chName), hanya untuk skin baru yang belum punya nama.

`--check` = 1 permintaan (index) + diff; `--apply` = unduh + pasang.
Progres -> stderr; hasil JSON -> stdout (kontrak /api/update/:game).
"""
import argparse
import concurrent.futures as cf
import hashlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASSETS = os.path.join(ROOT, "assets")
DEST = os.path.join(ASSETS, "azurlane")
NAMES = os.path.join(ROOT, "data", "azurlane-names.json")
STATE_DIR = os.environ.get("AZL_STATE_DIR", "/srv/spine-assets/azurlane-update")
STATE_FILE = os.path.join(STATE_DIR, "state.json")

REPO = "ww-rm/azurlane_spinepainting"
BRANCH = os.environ.get("AZL_BRANCH", "main")
RAW = f"https://raw.githubusercontent.com/{REPO}/{BRANCH}/"
INDEX_URL = RAW + "docs/index.json"
# Sumber nama INGGRIS (resmi). Di balik Cloudflare — coba langsung dulu, lalu
# lewat r.jina.ai yang bisa menembusnya. Hanya untuk NAMA; berkas tetap dari
# repo ww-rm (nagami tak menghosting skeleton-nya).
NAGAMI_URLS = (
    "https://data.nagami.moe/spine/index.json",
    "https://r.jina.ai/https://data.nagami.moe/spine/index.json",
)
UA = "spine-viewer-azurlane-updater/1.0"
WORKERS = 8


def _log(msg):
    sys.stderr.write("[%s] %s\n" % (time.strftime("%H:%M:%S"), msg))
    sys.stderr.flush()


def http_get(url, tries=4):
    headers = {"User-Agent": UA}
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=120) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code in (403, 429):
                raise RuntimeError(f"HTTP {e.code} {url}") from e
            if e.code == 404:
                raise RuntimeError(f"HTTP 404 {url}") from e
            last = e
            time.sleep(1.5 * (i + 1))
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(1.5 * (i + 1))
    raise RuntimeError(f"GET gagal {url}: {last}")


def fetch_english_names():
    """{asset: {id, shipName, skinName, displayName, type}} dari nagami.

    Opsional: kalau gagal (Cloudflare), kembalikan {} dan updater tetap jalan
    memakai nama Tionghoa dari repo. Daftar nama yang dipakai:
      - jika skin sudah punya nama Inggris (bukan CJK) -> DIPERTAHANKAN;
      - jika masih CJK -> ditimpa nama Inggris;
      - skin baru -> langsung nama Inggris.
    """
    for url in NAGAMI_URLS:
        try:
            raw = http_get(url, tries=2)
            if url.endswith(".json") and url.startswith(NAGAMI_URLS[0]):
                data = json.loads(raw)
            else:
                txt = raw.decode("utf-8", "replace")
                m = re.search(r"Markdown Content:\s*", txt)
                body = txt[m.end():] if m else txt
                data = json.loads(body[body.find("{"):body.rfind("}") + 1])
            out = {}
            for s in data.get("skins", []):
                asset = s.get("asset")
                ship = (s.get("shipName") or "").strip()
                if not asset or not ship:
                    continue
                skin = (s.get("skinName") or "").strip()
                out[asset] = {
                    "id": s.get("id"),
                    "shipName": ship,
                    "skinName": skin or None,
                    "displayName": f"{ship} — {skin}" if skin and skin != ship else ship,
                    "type": s.get("type"),
                }
            _log(f"nama Inggris dari nagami: {len(out)} entri")
            return out
        except Exception as e:  # noqa: BLE001
            _log(f"nagami gagal ({str(e)[:60]}) — pakai nama Tionghoa saja")
    return {}


def is_cjk(s):
    return bool(re.search(r"[\u3400-\u9fff]", s or ""))


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
        json.dump(d, f)
    os.replace(tmp, STATE_FILE)


def entries_from_index(idx):
    """[(skin, ship, shipCh, skinCh, [spec,...])] dari docs/index.json."""
    out = []
    for ship, sh in idx.items():
        ship_ch = (sh.get("chName") or "").strip()
        for skin, sk in (sh.get("skins") or {}).items():
            specs = sk.get("spines") or []
            if not specs:
                continue
            out.append((skin, ship, ship_ch, (sk.get("chName") or "").strip(), specs))
    return out


def installed_stems():
    got = set()
    if not os.path.isdir(DEST):
        return got
    for dp, _, fs in os.walk(DEST):
        for f in fs:
            if f.endswith(".skel"):
                got.add(f[:-5])
    return got


def plan(entries, installed):
    """Skin yang skeleton-nya belum terpasang."""
    new = []
    for skin, ship, ship_ch, skin_ch, specs in entries:
        stems = {os.path.splitext(s.get("skelName", ""))[0] for s in specs}
        if stems & installed:
            continue
        new.append({"skin": skin, "ship": ship, "shipCh": ship_ch,
                    "skinCh": skin_ch, "specs": specs})
    return sorted(new, key=lambda x: x["skin"])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()
    if not (a.check or a.apply):
        a.check = True

    saved = load_state()
    raw_index = http_get(INDEX_URL)
    version = hashlib.sha1(raw_index).hexdigest()[:12]
    idx = json.loads(raw_index)
    entries = entries_from_index(idx)
    installed = installed_stems()
    new = plan(entries, installed)
    if a.limit:
        new = new[: a.limit]
    changed = version != saved.get("version")

    _log(f"index: {len(entries)} skin di {len(idx)} kapal, versi {version}")
    _log(f"skeleton terpasang: {len(installed)}")
    _log(f"skin baru: {len(new)}")
    for m in new[:40]:
        _log(f"  BARU  {m['skin']:24s} ({m['ship']})")

    result = {
        "ok": True,
        "version": version,
        "previous": saved.get("version") or None,
        "changed": changed,
        "total": len(entries),
        "installed": len(installed),
        "new": len(new),
        "ids": [m["skin"] for m in new],
    }

    if a.check or not new:
        st = load_state()
        st.update({"version": version, "checkedAt": int(time.time())})
        save_state(st)
        print(json.dumps(result, ensure_ascii=False, indent=1))
        return 0

    # ---- unduh berkas tiap skin baru -----------------------------------
    jobs = []  # (url, dest)
    for m in new:
        folder = os.path.join(DEST, m["skin"])
        for sp in m["specs"]:
            names = [sp.get("skelName"), sp.get("atlasName")] + list(sp.get("pages") or [])
            for fn in names:
                if not fn:
                    continue
                url = RAW + "docs/" + urllib.parse.quote(f"{m['ship']}/{m['skin']}/{fn}")
                jobs.append((url, os.path.join(folder, fn)))

    _log(f"mengunduh {len(jobs)} berkas untuk {len(new)} skin ...")
    results = [None] * len(jobs)
    failed = []

    def fetch(i):
        url, dest = jobs[i]
        try:
            data = http_get(url)
        except Exception as e:  # noqa: BLE001
            return i, None, str(e)[:120]
        if not data:
            return i, None, "kosong"
        return i, data, None

    done = 0
    with cf.ThreadPoolExecutor(max_workers=WORKERS) as ex:
        for i, data, err in ex.map(fetch, range(len(jobs))):
            results[i] = data
            if data is None:
                failed.append(f"{jobs[i][0]}: {err}")
            done += 1
            if done % 25 == 0:
                _log(f"  unduh {done}/{len(jobs)} (gagal={len(failed)})")
    _log(f"unduhan selesai: ok={sum(1 for x in results if x)} gagal={len(failed)}")
    for f in failed[:10]:
        _log("   GAGAL " + f)

    if a.apply:
        english = fetch_english_names()
    else:
        english = {}

    added = 0
    new_names = {}
    try:
        names = json.load(open(NAMES, encoding="utf-8"))
    except Exception:  # noqa: BLE001
        names = {}
    for m in new:
        folder = os.path.join(DEST, m["skin"])
        skels = 0
        for i, (url, dest) in enumerate(jobs):
            if os.path.dirname(dest) != folder:
                continue
            data = results[i]
            if data is None:
                continue
            fn = os.path.basename(dest)
            if fn.endswith(".skel"):
                # tolak halaman error HTML yang menyamar jadi berkas
                if data[:1] in (b"<",) or b"<html" in data[:200].lower():
                    continue
                skels += 1
            os.makedirs(folder, exist_ok=True)
            tmp = dest + ".part"
            with open(tmp, "wb") as f:
                f.write(data)
            os.replace(tmp, dest)
        if not skels:
            continue
        added += 1
        # Nama: pakai nama INGGRIS (nagami) bila ada; nama CJK yang sudah
        # tersimpan juga ditimpa. Fallback: nama Tionghoa dari repo.
        rec = dict(english.get(m["skin"]) or {})
        if not rec:
            rec = {
                "id": None,
                "shipName": m["shipCh"] or m["ship"],
                "skinName": m["skinCh"] or None,
                "displayName": (" — ".join(x for x in (m["shipCh"], m["skinCh"]) if x)
                                or m["skin"]),
                "type": "spine",
            }
        rec["source"] = "nagami-moe" if english.get(m["skin"]) else "ww-rm/azurlane_spinepainting"
        cur = names.get(m["skin"])
        if m["skin"] not in names or is_cjk((cur or {}).get("displayName")):
            new_names[m["skin"]] = rec
    if new_names:
        names.update(new_names)
        tmp = NAMES + ".part"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(names, f, ensure_ascii=False, indent=1, sort_keys=True)
        os.replace(tmp, NAMES)
        _log(f"nama ditambahkan/diperbaiki: {len(new_names)}")

    result.update({
        "added": added,
        "extracted": added,
        "failedFiles": len(failed),
        "new": 0,
        "new_ids": [f"azurlane/{m['skin']}" for m in new
                    if os.path.isdir(os.path.join(DEST, m["skin"]))],
        "new_models": [m["skin"] for m in new],
        "namesAdded": len(new_names),
    })
    st = load_state()
    st.update({"version": version, "appliedAt": int(time.time()), "added": added,
               "new_ids": result["new_ids"], "new_models": result["new_models"]})
    save_state(st)

    _log(f"=== selesai: +{added} skin, berkas gagal={len(failed)}")
    print(json.dumps(result, ensure_ascii=False, indent=1))
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
