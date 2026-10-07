#!/usr/bin/env python3
"""Pembaru イヴンタイト (IV-N-Tight, DMM/FANZA, Dieselmine).

Strategi: **unduh SEMUA bundle lalu cari yang ber-Spine dari ISINYA**, bukan
menebak dari nama. Katalognya TIDAK menyimpan ukuran, dan sebagian bundle
ber-Spine (mis. bundle ber-hash acak) tak punya kata "spine" di katalog —
cara "filter nama" melewatkannya.

Sumber (Unity Addressables remote):
    https://eventight-sb.webaccel.saikyo.biz/dmm4sb/Unity6/Addressable_Test2/WebGL/
    https://eventight-sb.webaccel.saikyo.biz/dmm4sb/Unity6/Addressable_Test3/WebGL/
        catalog_0.0.1.json  +  <file>.bundle
(mirror S3: eventight-sb.s3.ap-northeast-1.amazonaws.com/dmm4sb/...)

Model Spine (JSON 4.2.38/4.2.43) ada di dalam bundle sebagai TextAsset
(`<nama>.json` + `<nama>.atlas`) dengan teksturnya Texture2D.

Alur --apply:
    1. unduh katalog Test2+Test3 -> daftar semua bundle
    2. unduh SEMUA bundle ke cache (resumable)
    3. scan cache: bundle UnityFS yang TextAsset-nya berisi JSON Spine
    4. ekstrak -> assets/ivntight/<nama-aman>/{.json,.atlas,.png}
       + data/ivntight-names.json (nama Jepang asli)
    Bundle yang sudah dipindai ditandai selesai -> --check jadi `new: 0`.

Pemakaian:
    /srv/venv-spine/bin/python tools/update-ivntight.py --check
    /srv/venv-spine/bin/python tools/update-ivntight.py --apply
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
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASSETS = os.path.join(ROOT, "assets")
OUT = os.environ.get("IVN_OUT", os.path.join(ASSETS, "ivntight"))
STATE_DIR = os.environ.get("IVN_STATE_DIR", "/srv/spine-assets/ivntight-update")
STATE_FILE = os.path.join(STATE_DIR, "state.json")
CACHE = os.path.join(STATE_DIR, "bundles-all")
NAMES = os.path.join(ROOT, "data", "ivntight-names.json")

CDNS = {
    "Test2": os.environ.get(
        "IVN_CDN2",
        "https://eventight-sb.webaccel.saikyo.biz/dmm4sb/Unity6/Addressable_Test2/WebGL",
    ).rstrip("/"),
    "Test3": os.environ.get(
        "IVN_CDN3",
        "https://eventight-sb.webaccel.saikyo.biz/dmm4sb/Unity6/Addressable_Test3/WebGL",
    ).rstrip("/"),
}
UA = "spine-viewer-ivntight-updater/1.0"
PAGE_RE = re.compile(r"\.(png|jpg|jpeg|webp)$", re.I)
WORKERS = 12


def _log(m):
	sys.stderr.write("[%s] %s\n" % (time.strftime("%H:%M:%S"), m))
	sys.stderr.flush()


def http_get(url, tries=4):
	last = None
	for i in range(tries):
		try:
			req = urllib.request.Request(url, headers={"User-Agent": UA})
			with urllib.request.urlopen(req, timeout=180) as r:
				return r.read()
		except urllib.error.HTTPError as e:
			if e.code in (403, 429, 404):
				raise RuntimeError(f"HTTP {e.code} {url}") from e
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


def all_bundles(saved):
	"""(jobs, sigs). jobs = [[tag, filename], ...] dari katalog Test2+Test3."""
	import base64

	import AddressablesTools as A
	jobs = []
	sigs = {}
	catalogs = saved.get("catalogs") or {}
	for tag, base in CDNS.items():
		c = catalogs.get(tag) or {}
		raw = None
		if c.get("b64"):
			try:
				raw = base64.b64decode(c["b64"])
			except Exception:  # noqa: BLE001
				raw = None
		if raw is None:
			raw = http_get(base + "/catalog_0.0.1.json")
		sha = hashlib.sha1(raw).hexdigest()[:12]
		sigs[tag] = sha
		catalogs[tag] = {"sha": sha, "b64": base64.b64encode(raw).decode()}
		cat = A.parse_json(raw.decode("utf-8", "replace"))
		names = set()
		for k, v in cat.Resources.items():
			ks = str(k)
			if ks.endswith(".bundle"):
				names.add(ks)
			for L in v:
				iid = str(getattr(L, "InternalId", ""))
				if iid.endswith(".bundle"):
					names.add(iid.rsplit("/", 1)[-1])
		for f in sorted(names):
			jobs.append([tag, f])
		_log(f"  katalog {tag}: {len(names)} bundle (sha {sha})")
	saved["catalogs"] = catalogs
	return jobs, sigs


def download_all(jobs):
	"""(ok, fail, bytes, fails). Unduh semua bundle ke CACHE/<tag>/<file>."""
	os.makedirs(CACHE, exist_ok=True)

	def one(job):
		tag, fname = job
		dest = os.path.join(CACHE, tag, fname)
		if os.path.exists(dest) and os.path.getsize(dest) > 0:
			return ("skip", os.path.getsize(dest), None)
		os.makedirs(os.path.dirname(dest), exist_ok=True)
		try:
			data = http_get(f"{CDNS[tag]}/{fname}")
		except Exception as e:  # noqa: BLE001
			return ("fail", 0, f"{fname}: {str(e)[:60]}")
		tmp = dest + ".part"
		with open(tmp, "wb") as fh:
			fh.write(data)
		os.replace(tmp, dest)
		return ("ok", len(data), None)

	ok = fail = skip = 0
	nbytes = 0
	fails = []
	with cf.ThreadPoolExecutor(max_workers=WORKERS) as ex:
		for i, (state, n, err) in enumerate(ex.map(one, jobs), 1):
			if state == "ok":
				ok += 1
				nbytes += n
			elif state == "skip":
				skip += 1
				nbytes += n
			else:
				fail += 1
				fails.append(err)
			if i % 250 == 0:
				_log(f"  unduh {i}/{len(jobs)} ok={ok} skip={skip} fail={fail} {nbytes/1e6:.0f}MB")
	return ok, fail, nbytes, fails


def scan_spine(candidates):
	"""Scan bundle kandidat; kembalikan {filename: tag} yang ber-Spine.

	Hanya bundle UnityFS yang bisa dibuka; yang lain dilewati (memang bukan).
	"""
	import UnityPy
	found = {}
	for i, (tag, fname) in enumerate(candidates, 1):
		p = os.path.join(CACHE, tag, fname)
		if not os.path.exists(p):
			continue
		try:
			with open(p, "rb") as fh:
				if fh.read(8) != b"UnityFS\0":
					continue
			env = UnityPy.load(p)
			for obj in env.objects:
				if obj.type.name != "TextAsset":
					continue
				d = obj.read()
				b = getattr(d, "m_Script", b"") or b""
				if isinstance(b, str):
					b = b.encode("utf-8", "surrogateescape")
				if b.lstrip().startswith(b'{"skeleton"'):
					found[fname] = tag
					break
		except Exception:  # noqa: BLE001
			continue
		if i % 250 == 0:
			_log(f"  scan {i}/{len(candidates)} (ber-Spine: {len(found)})")
	return found


def safe(name, used=None):
	"""Nama folder ASCII unik.

	PENTING: `\\w` di Python mencakup huruf CJK, jadi pola NAIF
	`[^\\w.-]` TIDAK membuang katakana/kanji — folder jadi berbahasa Jepang,
	lalu SERVER yang meng-slug id (CJK -> '-') dan beberapa model bertabrakan
	jadi id yang sama. Pakai rentang ASCII eksplisit + hash pendek.
	"""
	n = re.sub(r"[^A-Za-z0-9.\-]+", "_", name).strip("_.") or "m"
	if n != name.strip("_."):
		n = "%s_%s" % (n, hashlib.md5(name.encode("utf-8", "surrogateescape")).hexdigest()[:6])
	if used is not None:
		base, i = n, 2
		while n in used:
			n = "%s_%d" % (base, i)
			i += 1
		used.add(n)
	return n


def extract_bundle(path, dest_root):
	"""Buka satu bundle Unity -> tulis model Spine.

	Return {folder_aman: nama_asli} supaya pemanggil bisa menyimpan nama
	tampilan (Jepang) karena folder-nya sengaja dibuat ASCII.
	"""
	import UnityPy
	env = UnityPy.load(path)
	texts, texes = {}, {}
	for obj in env.objects:
		if obj.type.name == "TextAsset":
			try:
				d = obj.read()
			except Exception:  # noqa: BLE001
				continue
			nm = getattr(d, "m_Name", "") or ""
			data = getattr(d, "m_Script", None)
			if isinstance(data, str):
				data = data.encode("utf-8", "surrogateescape")
			texts[nm] = bytes(data or b"")
		elif obj.type.name == "Texture2D":
			try:
				d = obj.read()
				nm = getattr(d, "m_Name", "") or ""
			except Exception:  # noqa: BLE001
				continue
			texes[nm] = obj

	skeletons = {n: b for n, b in texts.items() if b.lstrip().startswith(b'{"skeleton"')}
	atlases = {}
	for n, b in texts.items():
		txt = b.decode("utf-8", "replace")
		pages = [ln.strip() for ln in txt.splitlines()
		         if ln.strip() and ln[0] not in " \t" and PAGE_RE.search(ln.strip())]
		if pages:
			atlases[n] = (txt, pages)

	out = {}
	for skname, skbytes in skeletons.items():
		base = re.sub(r"\.(json|skel)$", "", skname, flags=re.I)
		an = next((k for k in atlases if re.sub(r"\.atlas$", "", k, flags=re.I) == base), None)
		if not an:
			_log(f"    tanpa atlas: {skname}")
			continue
		atxt, pages = atlases[an]
		fol = safe(base)
		dest = os.path.join(dest_root, fol)
		os.makedirs(dest, exist_ok=True)
		with open(os.path.join(dest, fol + ".json"), "wb") as fh:
			fh.write(skbytes)
		with open(os.path.join(dest, fol + ".atlas"), "w", encoding="utf-8") as fh:
			fh.write(atxt)
		got = 0
		for pg in pages:
			stem = re.sub(r"\.(png|jpg|jpeg|webp)$", "", pg, flags=re.I)
			obj = texes.get(stem) or next((texes[k] for k in texes if k.startswith(stem)), None)
			if obj is None:
				continue
			# Simpan dgn NAMA HALAMAN DARI ATLAS (Jepang), bukan nama aman:
			# atlas merujuk nama itu; kalau beda, viewer tak menemukan tekstur.
			try:
				obj.read().image.save(os.path.join(dest, pg), "PNG")
				got += 1
			except Exception as e:  # noqa: BLE001
				_log(f"    gagal tekstur {pg}: {str(e)[:50]}")
		if got:
			out[fol] = base
			_log(f"    {fol} ({base}): {got}/{len(pages)} halaman")
	return out


def write_names(names):
	try:
		with open(NAMES, encoding="utf-8") as f:
			disk = json.load(f)
	except Exception:  # noqa: BLE001
		disk = {}
	disk.update(names)
	tmp = NAMES + ".part"
	with open(tmp, "w", encoding="utf-8") as f:
		json.dump(disk, f, ensure_ascii=False, indent=1, sort_keys=True)
	os.replace(tmp, NAMES)
	return len(disk)


def main():
	ap = argparse.ArgumentParser()
	ap.add_argument("--check", action="store_true")
	ap.add_argument("--apply", action="store_true")
	ap.add_argument("--limit", type=int, default=0)
	a = ap.parse_args()
	if not (a.check or a.apply):
		a.check = True

	saved = load_state()
	jobs, sigs = all_bundles(saved)
	ver = hashlib.sha1(json.dumps(sigs, sort_keys=True).encode()).hexdigest()[:12]
	done = set(saved.get("scanned") or [])
	pending = [j for j in jobs if j[1] not in done]

	_log(f"total bundle: {len(jobs)} | sudah dipindai: {len(done)} | baru: {len(pending)}")
	result = {
		"ok": True,
		"version": ver,
		"previous": saved.get("version") or None,
		"changed": ver != saved.get("version"),
		"total": len(jobs),
		"installed": len(done),
		"new": len(pending),
		"ids": [f for _, f in pending[:60]],
	}

	if a.check:
		saved["version"] = ver
		saved["checkedAt"] = int(time.time())
		save_state(saved)
		print(json.dumps(result, ensure_ascii=False, indent=1))
		return 0

	# ---- apply: unduh semua, scan isi, ekstrak yang ber-Spine -------------
	_log("unduh semua bundle (cache) ...")
	ok, fail, nbytes, fails = download_all(jobs)
	_log(f"unduh: ok={ok} gagal={fail} {nbytes/1e6:.0f}MB")
	for f in fails[:10]:
		_log("   GAGAL " + f)

	cand = [j for j in jobs if j[1] not in done]
	if a.limit:
		cand = cand[: a.limit]
	_log(f"scan {len(cand)} bundle kandidat ...")
	found = scan_spine(cand)
	_log(f"ber-Spine: {len(found)}")

	os.makedirs(OUT, exist_ok=True)
	names = saved.get("names") or {}
	new_ids = []
	extracted = 0
	for i, (fname, tag) in enumerate(sorted(found.items()), 1):
		p = os.path.join(CACHE, tag, fname)
		try:
			models = extract_bundle(p, OUT)
		except Exception as e:  # noqa: BLE001
			_log(f"  GAGAL ekstrak {fname}: {str(e)[:60]}")
			continue
		for fol, orig in models.items():
			names[fol] = orig
			new_ids.append(f"ivntight/{fol}")
		if models:
			extracted += 1
		if i % 25 == 0:
			_log(f"  ekstrak {i}/{len(found)}")

	# tandai SEMUA kandidat selesai (sudah dipindai) agar tak diulang
	done.update(j[1] for j in cand)

	nf = write_names(names)
	st = load_state()
	st.update({"version": ver, "appliedAt": int(time.time()),
	           "scanned": sorted(done), "names": names})
	save_state(st)

	result.update({
		"added": extracted,
		"extracted": extracted,
		"spineBundles": len(found),
		"failedFiles": fail,
		"new": 0,
		"new_ids": new_ids,
		"new_models": [x.split("/", 1)[1] for x in new_ids],
		"names": nf,
	})
	_log(f"=== selesai: {len(found)} bundle Spine, {extracted} diekstrak, "
	     f"{len(new_ids)} model, gagal={fail}")
	print(json.dumps(result, ensure_ascii=False, indent=1))
	return 0


if __name__ == "__main__":
	sys.exit(main())
