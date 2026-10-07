#!/usr/bin/env python3
"""Pembaru Girl Wars JP (少女ウォーズ / com.y2sgames.girlwarsjp).

Game ini punya DUA jenis model, keduanya disediakan viewer komunitas
github.com/Hisyn/GW-L2D-Viewer (GitHub Pages, + repo untuk file Spine):

  SPINE  (Spine 4.0)   assets/spines/<id>/<spineName>.{skel,atlas,png}
                       assets/spines/<id>/cutscene/<cutsceneId>.{...}
  LIVE2D (Cubism 4)    assets/live2dcubism/<id>/<id>.moc3 (+ textures/, motions/)

Nama karakter + nama file tiap varian datang dari manifest repo
src/utils/character_list.ts (charName, costumeName, spine, cutscene).

Tata letak hasil (mengikuti yang dibaca viewer kita):
    assets/girlwars/<id>/<spineName>.skel|.atlas|.png      -> model utama
    assets/girlwars/<id>/ultimate/<cutsceneId>.*           -> VARIAN "Ultimate"
       (subfolder 'ultimate' otomatis jadi dropdown varian di viewer)
    assets/girlwars-l2d/<id>/<id>.moc3                     -> model Live2D
    assets/girlwars-l2d/<id>/texture_0N.png                -> dari textures/ (diratakan:
                                                              src/live2d.js mencocokkan
                                                              nama 'texture_0N' di akar)
    assets/girlwars-l2d/<id>/motions/*.motion3.json
    data/girlwars-names.json                               -> id -> {name, costume}

Pemakaian:
    /srv/venv-spine/bin/python tools/update-girlwars.py --check
    /srv/venv-spine/bin/python tools/update-girlwars.py --apply
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
DEST_SPINE = os.environ.get("GW_SPINE_OUT", os.path.join(ASSETS, "girlwars"))
DEST_L2D = os.environ.get("GW_L2D_OUT", os.path.join(ASSETS, "girlwars-l2d"))
STATE_DIR = os.environ.get("GW_STATE_DIR", "/srv/spine-assets/girlwars-update")
STATE_FILE = os.path.join(STATE_DIR, "state.json")
NAMES = os.path.join(ROOT, "data", "girlwars-names.json")

SITE = os.environ.get("GW_SITE", "https://hisyn.github.io/GW-L2D-Viewer").rstrip("/")
SPINE_BASE = SITE + "/assets/spines/"
L2D_BASE = SITE + "/assets/live2dcubism/"
MANIFEST = "https://raw.githubusercontent.com/Hisyn/GW-L2D-Viewer/main/src/utils/character_list.ts"
TREES = "https://api.github.com/repos/Hisyn/GW-L2D-Viewer/git/trees/main:src/assets/"
UA = "spine-viewer-girlwars-updater/1.0"
WORKERS = 10
SPINE_EXT = (".skel", ".atlas", ".png", ".jpg", ".jpeg", ".webp")


def _log(m):
	sys.stderr.write("[%s] %s\n" % (time.strftime("%H:%M:%S"), m))
	sys.stderr.flush()


def _token():
	for p in (os.path.expanduser("~/.config/github/token"), "/root/.config/github/token"):
		try:
			v = open(p, encoding="utf-8").read().strip()
			if v:
				return v
		except OSError:
			continue
	for k in ("GW_GH_TOKEN", "GH_TOKEN", "GITHUB_TOKEN"):
		if os.environ.get(k):
			return os.environ[k].strip()
	return None


GH_TOKEN = _token()


def http_get(url, tries=4):
	headers = {"User-Agent": UA}
	if GH_TOKEN and "api.github.com" in url:
		headers["Authorization"] = "Bearer " + GH_TOKEN
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


def parse_manifest():
	"""id -> {name, costume, spine, cutscene} dari character_list.ts."""
	ts = http_get(MANIFEST).decode("utf-8", "replace")
	out = {}
	for m in re.finditer(r'"(\d{3,6})":\s*\{([^}]*)\}', ts):
		o = dict(re.findall(r'"(\w+)":\s*"([^"]*)"', m.group(2)))
		if o.get("spine"):
			out[m.group(1)] = o
	return out


def fetch_trees(saved):
	"""{'spines': [path], 'live2dcubism': [path]} (di-cache di state)."""
	trees = saved.get("trees")
	if trees:
		return trees
	trees = {}
	for sub in ("spines", "live2dcubism"):
		t = json.loads(http_get(f"{TREES}{sub}?recursive=1"))
		if "tree" not in t:
			raise RuntimeError(f"trees {sub}: {t.get('message')}")
		trees[sub] = [x["path"] for x in t["tree"] if x.get("type") == "blob"]
		_log(f"  pohon {sub}: {len(trees[sub])} berkas")
	return trees


def installed():
	sp = set()
	if os.path.isdir(DEST_SPINE):
		for d in os.listdir(DEST_SPINE):
			if any(f.endswith(".skel") for f in os.listdir(os.path.join(DEST_SPINE, d))):
				sp.add(("spine", d))
	l2 = set()
	if os.path.isdir(DEST_L2D):
		for d in os.listdir(DEST_L2D):
			p = os.path.join(DEST_L2D, d)
			if os.path.isdir(p) and any(f.endswith(".moc3") for f in os.listdir(p)):
				l2.add(("l2d", d))
	return sp, l2


def plan(trees, manifest):
	"""Daftar unit kerja: dict(kind, id, files=[(url, rel_dest)])."""
	units = []
	# --- Spine -----------------------------------------------------------
	sp_by_id = {}
	for p in trees["spines"]:
		parts = p.split("/")
		if len(parts) < 2:
			continue
		cid = parts[0]
		if not p.lower().endswith(SPINE_EXT):
			continue
		if len(parts) == 2:
			sp_by_id.setdefault(cid, {"char": [], "ult": []})["char"].append(p)
		elif len(parts) == 3 and parts[1] == "cutscene":
			sp_by_id.setdefault(cid, {"char": [], "ult": []})["ult"].append(p)
	for cid, g in sorted(sp_by_id.items()):
		rec = manifest.get(cid) or {}
		files = []
		for p in g["char"]:
			files.append((SPINE_BASE + urllib.parse.quote(p), os.path.basename(p)))
		for p in g["ult"]:
			files.append((SPINE_BASE + urllib.parse.quote(p),
			              os.path.join("ultimate", os.path.basename(p))))
		units.append({"kind": "spine", "id": cid, "files": files,
		              "name": rec.get("charName") or cid,
		              "costume": rec.get("costumeName") or ""})

	# --- Live2D ----------------------------------------------------------
	l2_by_id = {}
	for p in trees["live2dcubism"]:
		parts = p.split("/")
		if len(parts) < 2:
			continue
		l2_by_id.setdefault(parts[0], []).append(p)
	for cid, paths in sorted(l2_by_id.items()):
		rec = manifest.get(cid) or {}
		files = []
		for p in paths:
			parts = p.split("/")
			base = os.path.basename(p)
			if len(parts) == 2:
				rel = base                       # moc3, model3.json, physics3.json
			elif parts[1] == "textures":
				rel = base                       # diratakan: viewer cari texture_0N di akar
			elif parts[1] in ("motions", "expressions"):
				rel = os.path.join(parts[1], base)
			else:
				rel = os.path.join(parts[1], base)
			files.append((L2D_BASE + urllib.parse.quote(p), rel))
		units.append({"kind": "l2d", "id": cid, "files": files,
		              "name": rec.get("charName") or cid,
		              "costume": rec.get("costumeName") or ""})
	return units


def fetch(job):
	url, rel = job
	try:
		return rel, http_get(url), None
	except Exception as e:  # noqa: BLE001
		return rel, None, str(e)[:70]


def main():
	ap = argparse.ArgumentParser()
	ap.add_argument("--check", action="store_true")
	ap.add_argument("--apply", action="store_true")
	ap.add_argument("--limit", type=int, default=0)
	a = ap.parse_args()
	if not (a.check or a.apply):
		a.check = True

	saved = load_state()
	_log("ambil manifest + pohon aset ...")
	manifest = parse_manifest()
	trees = fetch_trees(saved)
	units = plan(trees, manifest)
	ver = hashlib.sha1((json.dumps(trees, sort_keys=True)).encode()).hexdigest()[:12]

	sp_done, l2_done = installed()
	done_sp = {i for _, i in sp_done}
	done_l2 = {i for _, i in l2_done}
	todo = [u for u in units
	        if (u["kind"] == "spine" and u["id"] not in done_sp)
	        or (u["kind"] == "l2d" and u["id"] not in done_l2)]
	if a.limit:
		todo = todo[: a.limit]

	nsp = sum(1 for u in units if u["kind"] == "spine")
	nl2 = sum(1 for u in units if u["kind"] == "l2d")
	_log(f"model: spine={nsp} live2d={nl2} | terpasang: spine={len(done_sp)} l2d={len(done_l2)} | baru={len(todo)}")
	result = {
		"ok": True,
		"version": ver,
		"previous": saved.get("version") or None,
		"changed": ver != saved.get("version"),
		"total": len(units),
		"installed": len(done_sp) + len(done_l2),
		"new": len(todo),
		"spine": nsp,
		"live2d": nl2,
		"ids": [f"{u['kind']}/{u['id']}" for u in todo[:60]],
	}

	if a.check or not todo:
		saved.update({"version": ver, "checkedAt": int(time.time()), "trees": trees})
		save_state(saved)
		print(json.dumps(result, ensure_ascii=False, indent=1))
		return 0

	res_dict = {}
	for f in (NAMES,):
		try:
			res_dict = json.load(open(f, encoding="utf-8"))
		except Exception:  # noqa: BLE001
			res_dict = {}
	names = res_dict

	added = 0
	new_ids = []
	failed = []
	for i, u in enumerate(todo, 1):
		root = DEST_SPINE if u["kind"] == "spine" else DEST_L2D
		dest_root = os.path.join(root, u["id"])
		fetched = {}
		with cf.ThreadPoolExecutor(max_workers=WORKERS) as ex:
			for rel, data, err in ex.map(fetch, u["files"]):
				if data is None:
					failed.append(f"{u['kind']}/{u['id']}/{rel}: {err}")
				else:
					fetched[rel] = data
		need = ".skel" if u["kind"] == "spine" else ".moc3"
		if not any(r.endswith(need) for r in fetched):
			_log(f"  [{i}/{len(todo)}] {u['kind']}/{u['id']}: tanpa {need} (dilewati)")
			continue
		for rel, data in fetched.items():
			p = os.path.join(dest_root, rel)
			os.makedirs(os.path.dirname(p), exist_ok=True)
			tmp = p + ".part"
			with open(tmp, "wb") as fh:
				fh.write(data)
			os.replace(tmp, p)
		added += 1
		game = "girlwars" if u["kind"] == "spine" else "girlwars-l2d"
		new_ids.append(f"{game}/{u['id']}")
		nm = " ".join(x for x in (u["name"], u["costume"]) if x) or u["id"]
		names[u["id"]] = {"name": u["name"], "costume": u["costume"], "display": nm}
		_log(f"  [{i}/{len(todo)}] {u['kind']}/{u['id']}: {len(fetched)} berkas ({nm})")

	# tulis nama
	tmp = NAMES + ".part"
	with open(tmp, "w", encoding="utf-8") as f:
		json.dump(names, f, ensure_ascii=False, indent=1, sort_keys=True)
	os.replace(tmp, NAMES)

	saved.update({"version": ver, "appliedAt": int(time.time()), "trees": trees})
	save_state(saved)
	result.update({
		"added": added,
		"extracted": added,
		"failedFiles": len(failed),
		"new": 0,
		"new_ids": new_ids,
		"new_models": [x.split("/", 1)[1] for x in new_ids],
		"names": len(names),
	})
	_log(f"=== selesai: +{added} model, gagal={len(failed)}")
	for f in failed[:10]:
		_log("   GAGAL " + f)
	print(json.dumps(result, ensure_ascii=False, indent=1))
	return 0


if __name__ == "__main__":
	sys.exit(main())
