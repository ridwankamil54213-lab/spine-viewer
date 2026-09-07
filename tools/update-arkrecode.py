#!/usr/bin/env python3
"""Perbarui aset Ark Re:Code (星隕計劃) dari CDN resmi.

Game ini tidak dienkripsi: cukup tanya server versi berapa yang aktif,
unduh catalog Addressables-nya, bandingkan dengan catalog terakhir yang
kita simpan, lalu unduh hanya berkas barunya.

Alur (lihat juga tools/REFERENCES.md):
    1. PUT  /Router/RouterHandler.ashx  -> Info.PathDomain + Info.NewCatalogName
    2. GET  {PathDomain}/Android/{NewCatalogName}.json
    3. Bandingkan dengan catalog sebelumnya   -> daftar `added`
    4. Unduh yang baru, lalu ekstrak Spine-nya

Dipanggil oleh server lewat POST /api/update/arkrecode (tombol di UI).
Bisa juga dijalankan langsung:

    /srv/venv-spine/bin/python tools/update-arkrecode.py --check
    /srv/venv-spine/bin/python tools/update-arkrecode.py --apply
"""
import argparse
import json
import os
import re
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor

import urllib3

urllib3.disable_warnings()

API_URL = "https://game-arkre-nu.ecchi.xxx//Router/RouterHandler.ashx"
# The router hands back PatchDomain as a PLACEHOLDER ("http://PatchDomain/...")
# inside the catalog, and its own PathDomain host refuses bundles with 403.
# The host that actually serves them is this one, with the platform segment
# from the catalog left as-is ("Android", not "WebGL" — WebGL is a different,
# smaller bundle set).
CDN_BASE = "https://erdpu.gzxhcjz.com/GamePatch"
HEADERS = {
	"User-Agent": "UnityPlayer/2022.3.28f1 (UnityWebRequest/1.0, libcurl/8.5.0-DEV)",
	"X-Unity-Version": "2022.3.28f1",
	"Content-Type": "application/json",
}

STATE_DIR = "/srv/spine-assets/arkrecode"
CATALOG_DIR = os.path.join(STATE_DIR, "catalogs")
DOWNLOAD_DIR = os.path.join(STATE_DIR, "downloads")
STATE_FILE = os.path.join(STATE_DIR, "state.json")

# Only asset types the viewer can actually use.
WANT = re.compile(r"\.(skel|atlas|png|json)$", re.I)
SKIP = re.compile(r"(^|/)(catalog_|\.hash$|/Android/(settings|link))", re.I)


def bundle_urls(catalog_path: str) -> dict:
	"""Map nama berkas -> URL bundle yang bisa diunduh.

	m_InternalIds holds BOTH asset paths ("Assets/Game/CG/A0001/A0001.png")
	and bundle URLs written against a placeholder host:

	    http://PatchDomain/Android/<group>_assets_<name>_<hash>.bundle

	Only those URL entries are downloadable; the plain asset paths are not.
	The placeholder host is replaced with the real CDN that serves them.
	"""
	with open(catalog_path, encoding="utf-8-sig") as f:
		data = json.load(f)
	out = {}
	for i in data.get("m_InternalIds", []):
		if not isinstance(i, str) or not i.startswith("http"):
			continue
		name = i.rsplit("/", 1)[-1]
		if not name.endswith(".bundle"):
			continue
		# http://PatchDomain/Android/x.bundle -> <CDN_BASE>/Android/x.bundle
		m = re.match(r"https?://PatchDomain(/.*)$", i)
		out[name] = CDN_BASE + m.group(1) if m else i
	return out


def http_json_put(url: str, payload: dict, timeout: int = 25):
	req = urllib.request.Request(
		url, data=json.dumps(payload).encode(), headers=HEADERS, method="PUT"
	)
	with urllib.request.urlopen(req, timeout=timeout) as r:
		return json.loads(r.read().decode("utf-8", "replace"))


def http_get(url: str, timeout: int = 60) -> bytes:
	req = urllib.request.Request(url, headers=HEADERS)
	with urllib.request.urlopen(req, timeout=timeout) as r:
		return r.read()


def fetch_latest_catalog_meta() -> dict:
	"""Tanya server: versi catalog aktif + domain aset."""
	obj = http_json_put(API_URL, {"data": {}, "route": "GameServerDBSettingHandler.QueryBulletinInfoResult"})
	info = obj.get("Info", {})
	domain = info.get("PathDomain")
	name = info.get("NewCatalogName")
	if not domain or not name:
		raise RuntimeError(f"respons tidak lengkap: {list(info)}")
	return {
		"domain": domain,
		"catalog": name,
		"url": f"{domain}/Android/{name}.json",
		"versions": info.get("AvailableVersions", []),
	}


def load_state() -> dict:
	if os.path.exists(STATE_FILE):
		try:
			return json.load(open(STATE_FILE))
		except Exception:
			pass
	return {}


def save_state(state: dict) -> None:
	os.makedirs(STATE_DIR, exist_ok=True)
	with open(STATE_FILE, "w") as f:
		json.dump(state, f, indent=1)


def catalog_names(path: str) -> set:
	with open(path, encoding="utf-8-sig") as f:
		data = json.load(f)
	return {i.rsplit("/", 1)[-1] for i in data.get("m_InternalIds", []) if isinstance(i, str)}


def check() -> dict:
	"""Ambil catalog terbaru dan bandingkan dengan yang terakhir disimpan."""
	os.makedirs(CATALOG_DIR, exist_ok=True)
	meta = fetch_latest_catalog_meta()
	state = load_state()

	# Sudah punya catalog ini? Pakai ulang, jangan unduh 25 MB lagi.
	local = os.path.join(CATALOG_DIR, meta["catalog"] + ".json")
	if not os.path.exists(local):
		raw = http_get(meta["url"])
		with open(local, "wb") as f:
			f.write(raw)
	new_names = catalog_names(local)

	prev = state.get("catalog")
	added = sorted(new_names)
	removed = 0
	if prev and prev != meta["catalog"]:
		prev_path = os.path.join(CATALOG_DIR, prev + ".json")
		if os.path.exists(prev_path):
			old_names = catalog_names(prev_path)
			added = sorted(new_names - old_names)
			removed = len(old_names - new_names)

	wanted = [n for n in added if WANT.search(n) and not SKIP.search(n)]
	return {
		"catalog": meta["catalog"],
		"previous": prev,
		"changed": prev != meta["catalog"],
		"versions": meta.get("versions", []),
		"total": len(new_names),
		"added": len(added),
		"removed": removed,
		"wanted": len(wanted),
		"samples": wanted[:10],
		"domain": meta["domain"],
	}


def apply_update(limit: int = 0, workers: int = 8) -> dict:
	"""Unduh berkas baru yang belum ada di disk.

	Not every catalog bundle is served: skeleton bundles under
	`assets/game/cg/<id>_<hash>.bundle` return 403 while their `img_`
	siblings under `.../<id>/img_<hash>.bundle` are fine, and a random
	sample of 12 catalog bundles came back 11x200/1x403. So failures are
	counted and reported per file rather than aborting the run.
	"""
	info = check()
	os.makedirs(DOWNLOAD_DIR, exist_ok=True)

	# Bangun ulang daftar URL bundle dari catalog.
	catalog_path = os.path.join(CATALOG_DIR, info["catalog"] + ".json")
	urls = bundle_urls(catalog_path)

	# Berkas yang sudah ada tidak diunduh ulang.
	todo = [n for n in urls if not os.path.exists(os.path.join(DOWNLOAD_DIR, n))]
	if limit:
		todo = todo[:limit]

	done = failed = 0
	errors = []

	def get(name):
		try:
			raw = http_get(urls[name])
			with open(os.path.join(DOWNLOAD_DIR, name), "wb") as f:
				f.write(raw)
			return None
		except Exception as exc:
			return f"{name}: {exc}"

	with ThreadPoolExecutor(max_workers=workers) as ex:
		for err in ex.map(get, todo):
			if err:
				failed += 1
				if len(errors) < 5:
					errors.append(err)
			else:
				done += 1

	state = load_state()
	state["catalog"] = info["catalog"]
	state["last_update"] = time.strftime("%Y-%m-%d %H:%M:%S")
	save_state(state)

	return {
		"catalog": info["catalog"],
		"downloaded": done,
		"failed": failed,
		"errors": errors,
		"dir": DOWNLOAD_DIR,
	}


def main() -> int:
	ap = argparse.ArgumentParser()
	ap.add_argument("--check", action="store_true", help="hanya cek versi & hitung yang baru")
	ap.add_argument("--apply", action="store_true", help="unduh berkas baru")
	ap.add_argument("--limit", type=int, default=0)
	args = ap.parse_args()

	if args.apply:
		print(json.dumps(apply_update(limit=args.limit), indent=1, ensure_ascii=False))
	elif args.check:
		print(json.dumps(check(), indent=1, ensure_ascii=False))
	else:
		ap.print_help()
		return 2
	return 0


if __name__ == "__main__":
	sys.exit(main())
