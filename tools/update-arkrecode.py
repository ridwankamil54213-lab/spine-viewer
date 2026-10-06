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
import shutil
import subprocess
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor

import urllib3

urllib3.disable_warnings()

API_URL = "https://game-arkre-nu.ecchi.xxx//Router/RouterHandler.ashx"
# The router hands back PatchDomain as a PLACEHOLDER ("http://PatchDomain/...")
# inside the catalog, so every bundle URL needs its host substituted.
#
# Two hosts serve the same tree, and they do NOT have the same coverage:
#   patch-arkre-nu...  (the router's own PathDomain) -> served 25/25 sampled
#                      bundles, including every CG skeleton
#   erdpu.gzxhcjz.com                               -> 23/25; it 403s on
#                      several skeleton bundles (a0001, a0022, ...)
# Earlier I concluded the router's host "never serves bundles" — that was
# wrong: it was fine, I had only tried it before learning that bundle names
# keep their slashed asset path. It is the better default, with the other
# host kept as a fallback for the handful it misses.
CDN_HOSTS = [
	"https://patch-arkre-nu.ecchi.xxx/GamePatch",
	"https://erdpu.gzxhcjz.com/GamePatch",
]
HEADERS = {
	"User-Agent": "UnityPlayer/2022.3.28f1 (UnityWebRequest/1.0, libcurl/8.5.0-DEV)",
	"X-Unity-Version": "2022.3.28f1",
	"Content-Type": "application/json",
}

STATE_DIR = "/srv/spine-assets/arkrecode"
CATALOG_DIR = os.path.join(STATE_DIR, "catalogs")
DOWNLOAD_DIR = os.path.join(STATE_DIR, "downloads")
STATE_FILE = os.path.join(STATE_DIR, "state.json")
# Where the viewer actually reads models: assets/arkrecode (di dalam repo).
# Default lama /srv/spine-assets/ark_out sudah usang — model ada di
# assets/arkrecode, sehingga check() salah melaporkan SEMUA bundle baru.
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASSET_DIR = os.environ.get("ARK_OUT", os.path.join(ROOT, "assets", "arkrecode"))
EXTRACTOR = "/srv/spine-viewer/tools/extract-unity-spine.py"
PYTHON = os.environ.get("PY", "/srv/venv-spine/bin/python")

# Only asset types the viewer can actually use.
WANT = re.compile(r"\.(skel|atlas|png|json)$", re.I)
SKIP = re.compile(r"(^|/)(catalog_|\.hash$|/Android/(settings|link))", re.I)

# Hanya pola model yang sudah ada di pohon aset viewer. Isi ark_out terdiri
# dari A####, CG_H####, H####, M#### dan B#### (313 H, 130 A, 71 M, 44 CG,
# 21 B). Tanpa filter ini updater mengunduh ribuan bundle UI/prefab/audio
# yang tidak pernah menjadi model — 20 bundle pertama saja semuanya UI.
# Hanya bundle CG: itulah yang menjadi model Spine utuh. Nama bundle
# menyisipkan path asetnya, jadi pola ini bisa dicocokkan langsung:
#   .../game/cg/a0001_<hash>.bundle        (skeleton)
#   .../game/cg/a0001/img_<hash>.bundle    (tekstur)
# Filter longgar berdasar id saja kemasukan banner (bn_logo_h002), prefab
# dan efek yang bukan model.
MODEL_BUNDLE = re.compile(
	r"/game/cg/[a-z]{1,2}\d{2,4}(?:_\d+)?(?:/img)?_[0-9a-f]{32}\.bundle$",
	re.I,
)


def bundle_urls(catalog_path: str) -> dict:
	"""Map nama berkas -> URL bundle yang bisa diunduh.

	m_InternalIds holds BOTH asset paths ("Assets/Game/CG/A0001/A0001.png")
	and bundle URLs written against a placeholder host:

	    http://PatchDomain/Android/<group>_assets_<name>_<hash>.bundle

	Only those URL entries are downloadable; the plain asset paths are not.
	The placeholder host is replaced with the real CDN that serves them, e.g.:

	  defaultduplicategroup_assets_assets/game/cg/a0001_1dc84...bundle
	  defaultduplicategroup_assets_assets/game/cg/a0001/img_7fd66...bundle
	"""
	with open(catalog_path, encoding="utf-8-sig") as f:
		data = json.load(f)
	out = {}
	for i in data.get("m_InternalIds", []):
		if not isinstance(i, str) or not i.startswith("http"):
			continue
		if not MODEL_BUNDLE.search(i):
			continue
		name = i.rsplit("/", 1)[-1]
		# http://PatchDomain/Android/x.bundle -> /Android/x.bundle (relpath)
		m = re.match(r"https?://PatchDomain(/.*)$", i)
		out[name] = m.group(1) if m else i
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


def _log(msg: str) -> None:
	"""Baris progres ke stderr: server menampilkannya sebagai log live."""
	sys.stderr.write("[%s] %s\n" % (time.strftime("%H:%M:%S"), msg))
	sys.stderr.flush()


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

	Each bundle is tried against every host in CDN_HOSTS in order, because
	neither host has complete coverage on its own. Residual failures are
	counted per file rather than aborting the run.
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
	_log(f"mengunduh {len(todo)} berkas (workers={workers})")

	done = failed = 0
	errors = []

	def get(name):
		rel = urls[name]
		# Coba tiap host bergiliran: coverage-nya tidak sama persis.
		last = ""
		for host in CDN_HOSTS:
			try:
				raw = http_get(host + rel)
				with open(os.path.join(DOWNLOAD_DIR, name), "wb") as f:
					f.write(raw)
				return None
			except Exception as exc:
				last = f"{name}: {exc}"
		return last

	with ThreadPoolExecutor(max_workers=workers) as ex:
		for err in ex.map(get, todo):
			if err:
				failed += 1
				_log(f"GAGAL {err}")
				if len(errors) < 5:
					errors.append(err)
			else:
				done += 1
				if done % 50 == 0:
					_log(f"unduh {done}/{len(todo)}")

	state = load_state()
	state["catalog"] = info["catalog"]
	state["last_update"] = time.strftime("%Y-%m-%d %H:%M:%S")
	save_state(state)

	# Tahap 3: ekstrak Spine dari bundle yang baru diunduh langsung ke
	# pohon aset viewer. Tanpa ini berkas hanya menumpuk di downloads/
	# dan tidak pernah muncul di antarmuka.
	extracted = 0
	extract_error = None
	extract_log = ""
	seen_new = []
	extract_dup = 0
	# Ekstrak selama ADA berkas di folder unduhan, bukan hanya ketika ada
	# yang baru terunduh — kalau disyaratkan `done > 0`, menjalankan ulang
	# setelah unduhan selesai melewati ekstraksi sepenuhnya.
	downloads = []
	if os.path.isdir(DOWNLOAD_DIR):
		downloads = [f for f in os.listdir(DOWNLOAD_DIR) if f.endswith(".bundle")]
	if downloads:
		tmp_out = os.path.join(STATE_DIR, "extract_tmp")
		os.makedirs(tmp_out, exist_ok=True)
		env = dict(os.environ, BUNDLE_DIR=DOWNLOAD_DIR, OUT=tmp_out)
		proc = None
		try:
			proc = subprocess.run(
				[PYTHON, EXTRACTOR],
				env=env, cwd="/srv/spine-viewer",
				capture_output=True, text=True, timeout=7200, check=False,
			)
			extract_log = (proc.stdout or "")[-600:] + (proc.stderr or "")[-600:]
			_log(f"ekstraksi selesai (rc={proc.returncode})")
		except Exception as exc:
			extract_error = str(exc)
			extract_log = ""
		# Pindahkan model baru ke pohon aset tanpa menimpa yang sudah ada.
		os.makedirs(ASSET_DIR, exist_ok=True)
		already = set(os.listdir(ASSET_DIR))
		seen_new = []
		for name in os.listdir(tmp_out):
			src = os.path.join(tmp_out, name)
			dst = os.path.join(ASSET_DIR, name)
			if not os.path.isdir(src):
				continue
			if os.path.exists(dst):
				continue  # model sudah ada, biarkan
			shutil.move(src, dst)
			extracted += 1
			if len(seen_new) < 10:
				seen_new.append(name)
		# Berapa hasil ekstrak yang ternyata sudah ada — berguna untuk
		# membedakan "tidak ada model baru" dari "ekstrak gagal".
		extract_total = sum(
			1 for n in os.listdir(tmp_out) if os.path.isdir(os.path.join(tmp_out, n))
		)
		extract_dup = extract_total - extracted
		shutil.rmtree(tmp_out, ignore_errors=True)
		_log(f"ekstrak: {extracted} model baru, {extract_dup} sudah ada")

	return {
		"catalog": info["catalog"],
		"downloaded": done,
		"failed": failed,
		"extracted": extracted,
		"new_models": seen_new,
		"already_had": extract_dup,
		"asset_dir": ASSET_DIR,
		"extract_error": extract_error,
		"extract_log": extract_log,
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
