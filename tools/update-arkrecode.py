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
EXTRACTOR = os.path.join(ROOT, "tools", "extract-unity-spine.py")
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

# Hanya bundle yang benar-benar memuat Spine. Di Ark Re:Code Spine ada di
# game/hero/ (mis. "b001_<hash>.bundle" -> B001.skel + B001_1.atlas, dan
# "b001/img_<hash>.bundle" -> halaman teksturnya). Sebagian atlas/skeleton
# tersebar di bundle "…duplicategroup_…cg_h004_a.atlas_<hash>.bundle", jadi
# pola kedua menangkapnya. game/cg/ justru ilustrasi Live2D (Texture2D+Sprite),
# BUKAN Spine — mengunduhnya hanya membuang waktu.
MODEL_BUNDLE = re.compile(
	r"/game/hero/\S*_[0-9a-f]{32}\.bundle$"
	r"|(?:cg_)?[a-z]{1,2}\d{2,4}(?:_[a-z])?\.(?:atlas|skel)_[0-9a-f]{32}\.bundle$",
	re.I,
)
_HERO_SKEL = re.compile(r"/game/hero/([a-z]{1,2}\d{2,4}(?:_\d+)?)_[0-9a-f]{32}\.bundle$", re.I)
_HERO_IMG = re.compile(r"/game/hero/([a-z]{1,2}\d{2,4})/img_[0-9a-f]{32}\.bundle$", re.I)
_DUP = re.compile(r"(?:cg_)?([a-z]{1,2}\d{2,4})(?:_[a-z])?\.(?:atlas|skel)_[0-9a-f]{32}\.bundle$", re.I)


def model_id_for(i: str):
	"""Id model (uppercase, mis. 'B001'/'H004') dari sebuah URL bundle."""
	for rx in (_HERO_SKEL, _HERO_IMG, _DUP):
		m = rx.search(i)
		if m:
			return m.group(1).upper()
	return None


def stem_installed(stem: str, have: set) -> bool:
	"""True bila model untuk `stem` sudah ada.

	Satu bundle hero bisa memuat beberapa skeleton dengan nama berbeda dari
	stem-nya (H004 -> CG_H004_a/CG_H004_b; B001 -> B001/B001_1), jadi 'sudah
	ada' mencakup: folder stem itu sendiri, turunannya (<stem>_<n>), atau
	folder ber-prefix CG_<stem>_."""
	s = stem.upper()
	if s in have or any(h.startswith(s + "_") for h in have):
		return True
	return any(h.startswith("CG_" + s + "_") for h in have)



def installed_models() -> set:
	if not os.path.isdir(ASSET_DIR):
		return set()
	return {n.upper() for n in os.listdir(ASSET_DIR) if os.path.isdir(os.path.join(ASSET_DIR, n))}


def processed_models() -> set:
	"""Id yang SUDAH diproses (punya Spine ATAU terbukti bukan Spine).

	Banyak bundle CG Ark Re:Code ternyata ilustrasi Live2D (Texture2D+Sprite),
	bukan Spine, jadi tidak pernah menghasilkan folder. Tanpa catatan ini
	mereka akan diunduh+dieksktrak ulang setiap kali — lambat dan sia-sia.
	"""
	return {str(x).upper() for x in load_state().get("processed", [])}


def model_bundles(urls: dict):
	"""Kelompokkan bundle menjadi model.

	Kembalikan (models, files) dengan:
	  models : {ID: [nama_berkas, …]}   — ID = folder model (mis. 'A0038')
	  files  : nama_berkas -> relpath    — hanya berkas milik model tsb.
	"""
	files = {}
	models = {}
	for name, rel in urls.items():
		mid = model_id_for(rel) or model_id_for(name)
		if not mid:
			continue
		files[name] = rel
		models.setdefault(mid, []).append(name)
	return models, files



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
	"""Ambil catalog terbaru dan hitung model yang belum ada di disk.

	Yang dihitung adalah MODEL (bundle skeleton), bukan berkas: sebuah model
	punya 1 skeleton + 0..n tekstur, jadi melaporkan jumlah berkas membuat
	angka melambung dan terasa seperti "harus unduh semuanya".
	"""
	os.makedirs(CATALOG_DIR, exist_ok=True)
	meta = fetch_latest_catalog_meta()
	state = load_state()

	# Sudah punya catalog ini? Pakai ulang, jangan unduh 25 MB lagi.
	local = os.path.join(CATALOG_DIR, meta["catalog"] + ".json")
	if not os.path.exists(local):
		_log(f"mengunduh catalog {meta['catalog']}…")
		raw = http_get(meta["url"])
		with open(local, "wb") as f:
			f.write(raw)
	urls = bundle_urls(local)  # nama berkas -> relpath
	models, model_files = model_bundles(urls)
	have = installed_models() | processed_models()
	missing = sorted(m for m in models if not stem_installed(m, have))
	_log(f"catalog {meta['catalog']}: {len(models)} model, {len(have)} ada, {len(missing)} baru")
	return {
		"ok": True,
		"catalog": meta["catalog"],
		"previous": state.get("catalog"),
		"changed": bool(missing) or state.get("catalog") != meta["catalog"],
		"versions": meta.get("versions", []),
		"total": len(models),
		"installed": len(have),
		"new": len(missing),
		"samples": missing[:10],
		"new_models": missing[:10],
		"domain": meta["domain"],
	}


def extract_bundle_set(download_dir: str, members: list) -> list:
	"""Ekstrak SKEL+ATLAS+PNG dari sekumpulan bundle di download_dir.

	Mengembalikan daftar {name, skel, atlas, ok} untuk tiap model yang
	ditemukan. Decode tekstur hanya untuk halaman yang dirujuk atlas, jadi
	sebuah model kecil selesai dalam hitungan detik.
	"""
	bundles = [f for f in members if os.path.exists(os.path.join(download_dir, f))]
	if not bundles:
		return []
	os.makedirs(ASSET_DIR, exist_ok=True)
	env = dict(
		os.environ,
		BUNDLE_DIR=download_dir,
		ONLY_BUNDLES=",".join(bundles),
		TO=ASSET_DIR,
		OUT_JSON="1",
	)
	proc = subprocess.run(
		[PYTHON, EXTRACTOR], env=env, cwd=ROOT,
		capture_output=True, text=True, timeout=1800, check=False,
	)
	if proc.returncode != 0:
		raise RuntimeError((proc.stderr or proc.stdout or "extractor gagal")[-300:])
	return json.loads(proc.stdout)


def apply_update(limit: int = 0, workers: int = 8) -> dict:
	"""Unduh & ekstrak HANYA model yang belum ada di buku aset viewer.

	Tiap model = 1 skeleton + 0..n tekstur; dikelompokkan lewat model_id_for().
	Untuk setiap model: unduh berkasnya, lalu ekstrak per-model (bukan sekaligus)
	supaya progres terlihat dan tiap langkah pendek.
	"""
	info = check()
	os.makedirs(DOWNLOAD_DIR, exist_ok=True)
	urls = bundle_urls(os.path.join(CATALOG_DIR, info["catalog"] + ".json"))
	models, files = model_bundles(urls)
	have = installed_models() | processed_models()

	todo = sorted(m for m in models if not stem_installed(m, have))
	if limit:
		todo = todo[:limit]
	_log(f"mengunduh {len(todo)} model baru (workers={workers})")

	done = failed = 0
	errors = []

	def get(mid):
		last = ""
		for name in models.get(mid, []):
			rel = files[name]
			dest = os.path.join(DOWNLOAD_DIR, name)
			if os.path.exists(dest) and os.path.getsize(dest) > 0:
				continue
			ok = False
			for host in CDN_HOSTS:
				try:
					raw = http_get(host + rel)
					with open(dest, "wb") as f:
						f.write(raw)
					ok = True
					break
				except Exception as exc:
					last = f"{name}: {exc}"
			if not ok:
				return last
		return None

	with ThreadPoolExecutor(max_workers=workers) as ex:
		for err in ex.map(get, todo):
			if err:
				failed += 1
				_log(f"GAGAL {err}")
				if len(errors) < 5:
					errors.append(err)
			else:
				done += 1
				if done % 25 == 0:
					_log(f"unduh {done}/{len(todo)} model")

	state = load_state()
	state["catalog"] = info["catalog"]
	state["last_update"] = time.strftime("%Y-%m-%d %H:%M:%S")
	# Semua model dalam `todo` sudah dicoba: yang menghasilkan Spine punya
	# folder, sisanya terbukti bukan Spine. Catat supaya tidak diulang.
	state["processed"] = sorted(set(state.get("processed", [])) | {m for m in todo})
	save_state(state)

	# Ekstrak per model supaya progres terlihat dan tiap langkah pendek.
	os.makedirs(ASSET_DIR, exist_ok=True)
	extracted = 0
	seen_new = []
	extract_errors = []
	for i, mid in enumerate(todo, 1):
		members = [f for f in models.get(mid, []) if os.path.exists(os.path.join(DOWNLOAD_DIR, f))]
		if not members:
			extract_errors.append(f"{mid}: berkas tidak terunduh")
			_log(f"ekstrak {i}/{len(todo)} {mid}: GAGAL (berkas tidak ada)")
			continue
		try:
			results = extract_bundle_set(DOWNLOAD_DIR, members)
		except Exception as exc:
			extract_errors.append(f"{mid}: {exc}")
			_log(f"ekstrak {i}/{len(todo)} {mid}: GAGAL {str(exc)[:70]}")
			continue
		doc = next((r for r in results if r.get("ok")), results[0] if results else None)
		_log(f"ekstrak {i}/{len(todo)} {mid} → {doc.get('name') if doc else '?'} "
		     f"({'skel+atlas' if (doc and doc.get('atlas')) else 'tanpa atlas'})")
		if doc and doc.get("ok"):
			extracted += 1
			if len(seen_new) < 50:
				seen_new.append(doc.get("name") or mid)

	return {
		"catalog": info["catalog"],
		"total": info["total"],
		"installed": info["installed"],
		"new": info["new"],
		"downloaded": done,
		"failed": failed,
		"extracted": extracted,
		"new_models": seen_new,
		"already_had": len(have),
		"asset_dir": ASSET_DIR,
		"extract_errors": extract_errors[:10],
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
