#!/usr/bin/env python3
"""Pembaru イヴンタイト (IV-N-Tight, DMM/FANZA, Dieselmine).

Strategi: **unduh SEMUA bundle lalu cari yang ber-Spine dari ISINYA**, bukan
menebak dari nama. Katalognya TIDAK menyimpan ukuran, dan sebagian bundle
ber-Spine (mis. bundle ber-hash acak) tak punya kata "spine" di katalog —
cara "filter nama" melewatkannya.

Sumber (Unity Addressables remote):
    https://eventight-sb.webaccel.saikyo.biz/dmm4sb/Unity6/Addressable_Test2/WebGL/
    https://eventight-sb.webaccel.saikyo.biz/dmm4sb/Unity6/Addressable_Test3/WebGL/
        catalog_0.0.1.hash  +  catalog_0.0.1.json  +  <file>.bundle
(mirror S3: eventight-sb.s3.ap-northeast-1.amazonaws.com/dmm4sb/...)

`.hash` (32 hex, 2 GET kecil) adalah sidik jari rilis katalog. --check SELALU
membacanya dari CDN: kalau berubah, katalog .json diunduh ulang walau sudah
ada cache di state.json. Tanpa ini updater buta terhadap rilis game baru.

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
    /srv/venv-spine/bin/python tools/update-ivntight.py --apply --rescan

`--rescan` mengabaikan daftar `scanned` dan memindai ULANG semua bundle dari
cache (tanpa unduh ulang) untuk verifikasi bahwa tidak ada model yang kelewat.
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
CATALOG_JSON = "catalog_0.0.1.json"
CATALOG_HASH = "catalog_0.0.1.hash"
HASH_RE = re.compile(r"^[0-9a-f]{32}$")
UA = "spine-viewer-ivntight-updater/1.0"
PAGE_RE = re.compile(r"\.(png|jpg|jpeg|webp)$", re.I)
WORKERS = 12

# AddressablesTools.parse_json masih dipakai (API `.Resources` beda dengan
# penerus `addressablestools`), jadi sembunyikan warning depresiasi agar log
# updater tetap bersih.
import warnings  # noqa: E402

warnings.filterwarnings(
	"ignore", message="AddressablesTools.parse_json is deprecated",
	category=DeprecationWarning,
)


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


def remote_catalog_hashes(saved):
	"""Sidik jari katalog LIVE dari CDN (2 GET x 32 byte).

	Unity Addressables menaruh hash build di `catalog_0.0.1.hash`; isinya BUKAN
	md5 dari file .json, tapi berubah setiap katalog dirilis ulang. Tanpa ini
	`--check` cuma membaca katalog yang tersimpan di state.json dan akan
	selamanya melaporkan "up to date" walau game sudah update.

	Kalau CDN sedang down, fallback ke hash terakhir yang tersimpan supaya
	versi tidak loncat-loncat (false positive `changed: true`).
	"""
	out = {}
	for tag, base in CDNS.items():
		try:
			h = http_get(f"{base}/{CATALOG_HASH}", tries=2).decode(
				"ascii", "replace").strip().lower()
			if HASH_RE.fullmatch(h):
				out[tag] = h
			else:
				_log(f"  {tag}: hash katalog tak dikenal, pakai cache")
		except Exception as e:  # noqa: BLE001
			_log(f"  {tag}: hash katalog gagal ({str(e)[:60]}), pakai cache")
	for tag, c in (saved.get("catalogs") or {}).items():
		if tag not in out and c.get("remoteHash"):
			out[tag] = c["remoteHash"]
	return out


def all_bundles(saved, remote_hashes=None):
	"""(jobs, sigs) dari katalog Test2+Test3; cache dipakai hanya bila hash
	cocok dengan hash LIVE, kalau tidak katalog diunduh ulang dari CDN."""
	import base64

	import AddressablesTools as A

	jobs = []
	sigs = {}
	catalogs = saved.get("catalogs") or {}
	hashes = remote_hashes or {}
	for tag, base in CDNS.items():
		c = catalogs.get(tag) or {}
		rh = hashes.get(tag) or c.get("remoteHash") or ""
		live = bool(hashes.get(tag))
		# Cache boleh dipakai kalau: ada isinya DAN (hash live tak terbaca ATAU
		# hash live sama dengan hash yang menempel pada cache tersebut).
		cache_ok = bool(c.get("b64")) and (not live or c.get("remoteHash") == rh)
		raw = None
		if cache_ok:
			try:
				raw = base64.b64decode(c["b64"])
			except Exception:  # noqa: BLE001
				raw = None
		if raw is None:
			_log(f"  {tag}: unduh {CATALOG_JSON} (hash {rh[:12] or 'n/a'})")
			raw = http_get(f"{base}/{CATALOG_JSON}")
		sha = hashlib.sha1(raw).hexdigest()[:12]
		sigs[tag] = sha
		catalogs[tag] = {
			"sha": sha,
			"remoteHash": rh,
			"b64": base64.b64encode(raw).decode(),
		}
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
		_log(f"  katalog {tag}: {len(names)} bundle (sha {sha}, hash {rh[:12] or 'n/a'})")
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


# Sama persis dengan aturan id di src/server.js:
#   rel.replace(/[^\w.\-/]+/g, "-")   (\w = ASCII [A-Za-z0-9_])
LEGACY_BAD = re.compile(r"[^A-Za-z0-9_.\-/]+")


def normalize_folders():
	"""Perbaiki folder warisan yang namanya masih non-ASCII.

	Server men-slug nama folder jadi id model, tapi viewer menyusun URL aset
	dari id itu. Jadi folder `000000_NPC_コハク_立ち絵_export` menghasilkan id
	`000000_NPC_-_-_export` dan SEMUA berkasnya 404. Konvensi repo: folder
	ASCII + nama Jepang asli disimpan di data/ivntight-names.json.

	Dijalankan di --apply supaya hasil tools/extract-ivntight.py (yang menulis
	nama asli) otomatis tertata ulang. Mengembalikan {slug: nama_asli}.
	"""
	if not os.path.isdir(OUT):
		return {}
	fixed = {}
	for old in sorted(os.listdir(OUT)):
		src = os.path.join(OUT, old)
		if not os.path.isdir(src) or old.isascii():
			continue
		slug = LEGACY_BAD.sub("-", old)
		if slug == old:
			continue
		dst = os.path.join(OUT, slug)
		if os.path.exists(dst):
			_log(f"  LEWATI normalisasi {old}: {slug} sudah ada")
			continue
		os.rename(src, dst)
		for f in os.listdir(dst):
			fp = os.path.join(dst, f)
			if not os.path.isfile(fp):
				continue
			nf = f.replace(old, slug)
			if nf != f:
				os.rename(fp, os.path.join(dst, nf))
			if nf.lower().endswith(".atlas"):
				# newline="" supaya CRLF atlas Unity tetap utuh (yang berubah
				# cuma nama halaman, bukan seluruh berkas).
				with open(os.path.join(dst, nf), encoding="utf-8", newline="") as fh:
					txt = fh.read()
				# Hanya baris nama halaman gambar yang boleh diubah; region
				# atlas boleh saja beraksara Jepang.
				lines = []
				for ln in txt.splitlines(True):
					if re.match(r"^[^\r\n]+\.(png|jpg|jpeg|webp)\s*$", ln, re.I):
						ln = ln.replace(old, slug)
					lines.append(ln)
				with open(os.path.join(dst, nf), "w", encoding="utf-8", newline="") as fh:
					fh.write("".join(lines))
		fixed[slug] = old
		_log(f"  normalisasi folder: {old} -> {slug}")
	return fixed


def main():
	ap = argparse.ArgumentParser()
	ap.add_argument("--check", action="store_true")
	ap.add_argument("--apply", action="store_true")
	ap.add_argument("--limit", type=int, default=0)
	ap.add_argument(
		"--rescan", action="store_true",
		help="pindai ULANG semua bundle dari cache (abaikan daftar scanned); "
		     "tak mengunduh ulang, berguna buat verifikasi tidak ada model yang kelewat",
	)
	a = ap.parse_args()
	if not (a.check or a.apply):
		a.check = True

	saved = load_state()
	hashes = remote_catalog_hashes(saved)
	jobs, sigs = all_bundles(saved, hashes)
	# Hash LIVE ikut masuk versi: kalau Unity merilis ulang katalog dengan isi
	# .json yang kebetulan sama, versi tetap berubah dan UI kasih titik merah.
	ver = hashlib.sha1(json.dumps(
		{"catalogs": sigs, "hashes": hashes}, sort_keys=True,
	).encode()).hexdigest()[:12]
	done = set(saved.get("scanned") or [])
	# --rescan: anggap semua job belum dipindai, tapi berkasnya tetap diambil
	# dari cache (download_all akan skip semua). Tujuan: verifikasi bahwa
	# strategi "cari Spine dari ISI bundle" tidak ada yang terlewat.
	pending = list(jobs) if a.rescan else [j for j in jobs if j[1] not in done]

	_log(f"total bundle: {len(jobs)} | sudah dipindai: {len(done)} | "
	     f"{'rescan semua' if a.rescan else 'baru'}: {len(pending)}")
	result = {
		"ok": True,
		"version": ver,
		"previous": saved.get("version") or None,
		"changed": ver != saved.get("version"),
		"rescan": bool(a.rescan),
		"total": len(jobs),
		"installed": len(done),
		"new": len(pending),
		"catalogHashes": {k: v[:12] for k, v in sorted(hashes.items())},
		"ids": [f for _, f in pending[:60]],
	}

	if a.check:
		# JANGAN simpan `version` di sini. Versi = katalog TERAKHIR YANG
		# DITERAPKAN; kalau --check menimpanya, titik merah `changed` hilang
		# setelah satu kali klik walau user belum pernah Apply.
		# Yang disimpan cuma katalog segar + checkedAt (biar --apply tak
		# mengunduh 7 MB katalog dua kali).
		saved["catalogs"] = saved.get("catalogs") or {}
		saved["checkedAt"] = int(time.time())
		save_state(saved)
		print(json.dumps(result, ensure_ascii=False, indent=1))
		return 0

	# ---- apply: rapikan folder warisan non-ASCII ---------------------------
	# Harus sebelum write_names(): nama Jepang aslinya dipindahkan ke kunci
	# slug yang dipakai server sebagai id model.
	renamed = normalize_folders()

	# ---- apply: unduh semua, scan isi, ekstrak yang ber-Spine -------------
	_log("unduh semua bundle (cache) ...")
	ok, fail, nbytes, fails = download_all(jobs)
	_log(f"unduh: ok={ok} gagal={fail} {nbytes/1e6:.0f}MB")
	for f in fails[:10]:
		_log("   GAGAL " + f)

	cand = []
	seen = set()
	for j in pending:
		# 297 nama bundle muncul di Test2 DAN Test3; isinya identik (nama
		# ber-content-hash), jadi pindai sekali saja.
		if j[1] in seen:
			continue
		seen.add(j[1])
		cand.append(j)
	if a.limit:
		cand = cand[: a.limit]
	_log(f"scan {len(cand)} bundle kandidat "
	     f"({'(RESCAN PENUH)' if a.rescan else 'baru'}) ...")
	found = scan_spine(cand)
	_log(f"ber-Spine: {len(found)}")

	os.makedirs(OUT, exist_ok=True)
	names = saved.get("names") or {}
	names.update(renamed)  # folder hasil normalisasi -> nama Jepang asli
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
	# Pakai `saved` (bukan load_state() lagi) supaya katalog segar + remoteHash
	# hasil all_bundles() ikut tersimpan; kalau dibaca ulang dari disk, katalog
	# yang baru diunduh hilang dan --check berikutnya mengunduh 7 MB lagi.
	saved.update({"version": ver, "appliedAt": int(time.time()),
	              "scanned": sorted(done), "names": names})
	save_state(saved)

	result.update({
		"added": extracted,
		"extracted": extracted,
		"normalized": len(renamed),
		"rescanned": len(cand),
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
