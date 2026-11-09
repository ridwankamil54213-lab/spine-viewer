#!/usr/bin/env python3
"""Pembaru 明日方舟 (Arknights) — Spine 3.8 dari Ark-Models + aset EN.

Sumber (semuanya publik, tanpa auth):
  metadata  github.com/isHarryh/Ark-Models  -> models_data.json (3200 entri)
  model     codeload.github.com/.../main.zip (1,1 GB; .skel + .atlas + .png)
  nama EN   ArknightsAssets/ArknightsGameData -> skin_table.json +
            enemy_handbook_table.json
  ilustrasi yuanyan3060/ArknightsGameResource -> portrait/, avatar/, enemy/,
            skin/ (thumbnail WebP, BUKAN halaman atlas)

Kenapa folder di-sanitasi: nama aslinya mengandung `#` (589 folder), sementara
server men-slug `rel.replace(/[^\\w.\\-/]+/g, "-")` dan viewer menyusun URL
dari id itu -> folder `002_amiya_epoque#4` akan 404. Semua nama folder DAN
berkas (termasuk baris halaman di .atlas) dibuat ASCII, id model tetap stabil.

Pemakaian:
    /srv/venv-spine/bin/python tools/arknights/update.py --check
    /srv/venv-spine/bin/python tools/arknights/update.py --apply
    /srv/venv-spine/bin/python tools/arknights/update.py --apply --offline
"""
import argparse
import base64
import collections
import concurrent.futures as cf
import hashlib
import io
import json
import os
import re
import shutil
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUT = os.environ.get("ARK_OUT", os.path.join(ROOT, "assets", "arknights"))
DATA = os.path.join(ROOT, "data")
THUMBS = os.environ.get("ARK_THUMBS", os.path.join(ROOT, "public", "thumbs", "arknights"))
CACHE = os.environ.get("ARK_CACHE", "/srv/spine-assets/arknights")
STATE_FILE = os.path.join(CACHE, "state.json")
NAMES_FILE = os.path.join(DATA, "arknights-names.json")
FAMILY_FILE = os.path.join(DATA, "arknights-family.json")
MANIFEST_FILE = os.path.join(THUMBS, "_manifest.json")

RAW = "https://raw.githubusercontent.com"
JSDELIVR = "https://cdn.jsdelivr.net/gh"
META_URL = f"{RAW}/isHarryh/Ark-Models/main/models_data.json"
ZIP_URL = "https://codeload.github.com/isHarryh/Ark-Models/zip/refs/heads/main"
SKIN_URL = f"{RAW}/ArknightsAssets/ArknightsGameData/master/en/gamedata/excel/skin_table.json"
ENEMY_URL = f"{RAW}/ArknightsAssets/ArknightsGameData/master/en/gamedata/excel/enemy_handbook_table.json"
TREE_URL = "https://api.github.com/repos/yuanyan3060/ArknightsGameResource/git/trees/main?recursive=1"
ART_URL = f"{JSDELIVR}/yuanyan3060/ArknightsGameResource@main"

UA = "spine-viewer-arknights-updater/1.0"
ZIP_PREFIX = "Ark-Models-main/"
BAD = re.compile(r"[^A-Za-z0-9_.\-]+")
PAGE_RE = re.compile(r"\.(png|webp|jpe?g)$", re.I)
WORKERS = 16
MODEL_DIRS = ("models", "models_enemies", "models_illust")


def _log(m):
	sys.stderr.write("[%s] %s\n" % (time.strftime("%H:%M:%S"), m))
	sys.stderr.flush()


def http_get(url, tries=3, timeout=180):
	last = None
	for i in range(tries):
		try:
			req = urllib.request.Request(url, headers={"User-Agent": UA})
			with urllib.request.urlopen(req, timeout=timeout) as r:
				return r.read()
		except urllib.error.HTTPError as e:
			if e.code in (403, 404, 429):
				last = e
				break
			last = e
		except Exception as e:  # noqa: BLE001
			last = e
		time.sleep(1.2 * (i + 1))
	raise RuntimeError(f"GET gagal {url}: {last}")


def cached(name, url, offline=False):
	"""Ambil berkas kecil dari cache; --offline tidak pernah menyentuh jaringan."""
	p = os.path.join(CACHE, name)
	if offline:
		with open(p, "rb") as f:
			return f.read()
	raw = http_get(url)
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


def safe(s):
	return BAD.sub("_", s).strip("._") or "m"


def safe_names(keys):
	"""Peta nama asli -> nama ASCII, unik (md5 kalau sanitasi bikin tabrakan)."""
	cnt = collections.Counter(safe(k) for k in keys)
	out = {}
	for k in keys:
		s = safe(k)
		if cnt[s] > 1:
			s = f"{s}_{hashlib.md5(k.encode('utf-8','surrogateescape')).hexdigest()[:6]}"
		out[k] = s
	return out


def rewrite_atlas(raw, ren):
	"""Ganti baris HALAMAN gambar ke nama berkas yang sudah disanitasi.

	Ark-Models punya beberapa atlas yang nama halamannya beda dengan berkas
	aslinya (beda huruf besar/kecil, atau masih memakai `#` sementara berkas
	sudah memakai `_`), jadi cocokkan lewat alias case-insensitive + sanitasi.
	Nama region yang kebetulan berakhiran `.png` (mis. `F_Mouth_Sp_3.png`)
	JANGAN diubah: baris halaman selalu diikuti properti `size:`.
	"""
	txt = raw.decode("utf-8", "replace")
	nl = "\r\n" if "\r\n" in txt else "\n"
	lines = txt.splitlines()
	alias = {}
	for orig, final in ren.items():
		for k in (orig, orig.lower(), safe(orig), safe(orig).lower()):
			alias.setdefault(k, final)
	out = []
	for i, ln in enumerate(lines):
		s = ln.strip()
		if PAGE_RE.search(s) and not ln[:1].isspace():
			nxt = next((lines[j].strip() for j in
			            range(i + 1, min(len(lines), i + 4)) if lines[j].strip()), "")
			if re.match(r"^size:", nxt, re.I):
				hit = next((alias[c] for c in
				            (s, s.lower(), safe(s), safe(s).lower()) if c in alias), None)
				if hit:
					ln = ln.replace(s, hit)
		out.append(ln)
	tail = ("\r\n" if nl == "\r\n" and txt.endswith("\r\n") else
	        "\n" if txt.endswith("\n") else "")
	return (nl.join(out) + tail).encode("utf-8")


def zip_folders(z):
	"""{folder_asli: {nama_berkas: path_di_zip}} untuk 3 direktori model."""
	out = {}
	for n in z.namelist():
		if n.endswith("/") or not n.startswith(ZIP_PREFIX):
			continue
		parts = n[len(ZIP_PREFIX):].split("/")
		if len(parts) != 3 or parts[0] not in MODEL_DIRS:
			continue
		out.setdefault(parts[1], {})[parts[2]] = n
	return out


def art_tree(offline=False):
	"""Daftar path gambar ilustrasi (portrait/avatar/enemy/skin)."""
	p = os.path.join(CACHE, "art-tree.json")
	if offline:
		with open(p, encoding="utf-8") as f:
			return json.load(f)
	tree = json.loads(http_get(TREE_URL, timeout=120))["tree"]
	paths = [x["path"] for x in tree
	         if x.get("type") == "blob" and
	         x["path"].split("/")[0] in ("portrait", "avatar", "enemy", "skin") and
	         PAGE_RE.search(x["path"])]
	with open(p + ".part", "w", encoding="utf-8") as f:
		json.dump(paths, f)
	os.replace(p + ".part", p)
	return paths


def resolve_art(key, typ, pathset):
	base = key.replace("dyn_illust_", "", 1) if typ == "DynIllust" else key
	if typ == "Operator":
		cands = [f"portrait/char_{key}_1.png", f"portrait/char_{key}.png",
		         f"portrait/char_{key}_1+.png", f"portrait/char_{key}_2.png",
		         f"avatar/char_{key}.png", f"avatar/char_{key}_1.png",
		         f"skin/char_{key}.png"]
	elif typ == "Enemy":
		cands = [f"enemy/enemy_{key}.png", f"enemy/enemy_{key}_1.png",
		         f"enemy/enemy_{key}_2.png", f"avatar/enemy_{key}.png",
		         f"avatar/enemy_{key}_1.png", f"avatar/char_{key}.png"]
	else:
		cands = [f"portrait/char_{base}_1.png", f"portrait/char_{base}.png",
		         f"portrait/char_{base}_2.png", f"portrait/char_{base}_1+.png",
		         f"avatar/char_{base}.png"]
	for c in cands:
		if c in pathset:
			return c
	return None


def display_name(key, rec, skins, enemies):
	"""Nama tampilan Inggris (0 aksara Tionghoa)."""
	typ = (rec or {}).get("type") or ("Enemy" if key[0].isdigit() else "Operator")
	app = (rec or {}).get("appellation")
	skin_rec = skins.get("char_" + key.replace("dyn_illust_", "", 1))
	ds = (skin_rec or {}).get("displaySkin") or {}
	base = ds.get("modelName") or app
	skin = ds.get("skinName")
	if typ == "Enemy":
		e = enemies.get("enemy_" + key) or enemies.get(key)
		en = (e or {}).get("name")
		return en or re.sub(r"[_\-]+", " ", key).strip().title(), typ, None, None
	if not base:
		base = re.sub(r"[_\-]+", " ", key).strip().title()
	if typ == "DynIllust":
		return f"{base} — Dynamic Illust" + (f" · {skin}" if skin else ""), typ, base, skin
	if skin and (rec or {}).get("style") != "BuildingDefault":
		return f"{base} — {skin}", typ, base, skin
	if (rec or {}).get("style") == "BuildingSkin":
		tag = key.split("#")[-1] if "#" in key else "Skin"
		return f"{base} — Skin {tag}", typ, base, skin
	return str(base), typ, base, skin


def main():
	ap = argparse.ArgumentParser()
	ap.add_argument("--check", action="store_true")
	ap.add_argument("--apply", action="store_true")
	ap.add_argument("--offline", action="store_true",
	                help="pakai semua berkas yang sudah ada di CACHE (refresh)")
	a = ap.parse_args()
	if not (a.check or a.apply):
		a.check = True

	os.makedirs(CACHE, exist_ok=True)
	saved = load_state()
	meta = cached("models_data.json", META_URL, a.offline)
	if not a.offline:
		# Nama Inggris ikut menentukan versi: kalau game-data EN berubah,
		# --check harus menyuruh apply ulang walau models_data.json sama.
		skin_raw = cached("skin_table.json", SKIN_URL, False)
		enemy_raw = cached("enemy_handbook_table.json", ENEMY_URL, False)
	else:
		skin_raw = cached("skin_table.json", SKIN_URL, True)
		enemy_raw = cached("enemy_handbook_table.json", ENEMY_URL, True)
	ver = hashlib.sha1(meta + skin_raw + enemy_raw).hexdigest()[:12]

	md = json.loads(meta)
	data = md["data"]
	skins = json.loads(skin_raw).get("charSkins", {})
	# game-data EN: satu skin bisa punya beberapa id (building/avatar/portrait).
	skin_by_asset = {}
	for v in skins.values():
		for field in ("buildingId", "avatarId", "portraitId"):
			x = v.get(field)
			if x and x not in skin_by_asset:
				skin_by_asset[x] = v
	enemy_data = json.loads(enemy_raw).get("enemyData", {})

	installed = set(saved.get("installed") or [])
	expected = len(saved.get("installed") or []) or len(data)
	result = {
		"ok": True,
		"version": ver,
		"previous": saved.get("version") or None,
		"changed": ver != saved.get("version"),
		"expected": expected,
		"have": len(installed),
		"new": max(0, expected - len(installed)),
		"source": "isHarryh/Ark-Models + ArknightsGameData EN",
	}
	if a.check:
		saved["checkedAt"] = int(time.time())
		save_state(saved)
		print(json.dumps(result, ensure_ascii=False, indent=1))
		return 0

	# ---- apply ----------------------------------------------------------
	zip_path = os.path.join(CACHE, "Ark-Models-main.zip")
	if not os.path.exists(zip_path) and a.offline:
		raise SystemExit("--offline tapi zip belum ada di cache")
	# Kalau zip sudah ada tapi state belum pernah menyimpan zipVersion
	# (bootstrap / cache dipanaskan manual), anggap zip itu yang terbaru.
	need_zip = (not os.path.exists(zip_path) or
	            bool(saved.get("zipVersion") and saved["zipVersion"] != ver))
	if not a.offline and need_zip:
		_log("unduh Ark-Models main.zip (1,1 GB) ...")
		raw = http_get(ZIP_URL, tries=2, timeout=900)
		tmp = zip_path + ".part"
		with open(tmp, "wb") as f:
			f.write(raw)
		os.replace(tmp, zip_path)
		_log(f"zip {len(raw)/1e6:.0f} MB tersimpan")

	paths = set(art_tree(a.offline))
	_log(f"pohon ilustrasi: {len(paths)} berkas")

	names, families, manifest, art_jobs = {}, collections.defaultdict(list), {}, {}
	new_ids = []
	with zipfile.ZipFile(zip_path) as z:
		folders = zip_folders(z)
		dest = safe_names(folders.keys())
		_log(f"ekstrak {len(folders)} folder model ...")
		for key in sorted(folders):
			files = folders[key]
			d = dest[key]
			target = os.path.join(OUT, d)
			# Tulis ulang dari nol: refresh deterministik, dan sisa berkas dari
			# rilis lama (mis. skeleton tanpa ekstensi) tidak menumpuk.
			if os.path.isdir(target):
				shutil.rmtree(target)
			os.makedirs(target, exist_ok=True)
			ren = safe_names(files.keys())
			# 15 folder Ark-Models menyimpan skeleton JSON TANPA ekstensi
			# (mis. `build_char_450_necras`). Server cuma mengenali .skel/.json,
			# jadi berkas itu harus diberi akhiran .json.
			for orig, zpath in files.items():
				if "." not in orig and z.read(zpath)[:64].lstrip().startswith(b'{"skeleton"'):
					ren[orig] = ren[orig] + ".json"
			# Tulis ulang .atlas supaya nama halaman cocok dengan berkas baru.
			for orig, zpath in files.items():
				raw = z.read(zpath)
				if orig.lower().endswith(".atlas"):
					raw = rewrite_atlas(raw, ren)
				with open(os.path.join(target, ren[orig]), "wb") as fh:
					fh.write(raw)
			stems = sorted(set(
				re.sub(r"\.(skel|json)$", "", f, flags=re.I)
				for f in ren.values()
				if re.search(r"\.(skel|json)$", f, re.I)))
			has_atlas = any(f.lower().endswith(".atlas") for f in ren.values())
			# Folder tanpa pasangan skeleton/atlas tak akan jadi model di server;
			# jangan masukkan ke new_ids maupun manifest thumbnail.
			ids = ([f"arknights/{d}#{s}" for s in stems] if len(stems) > 1
			       else [f"arknights/{d}"]) if stems and has_atlas else []
			rec = data.get(key)
			label, typ, char, skin = display_name(key, rec, skin_by_asset, enemy_data)
			names[d] = {
				"name": label,
				"character": char or label,
				"skin": skin,
				"type": typ,
				"rarity": next((int(t.split("_")[1]) for t in
				                ((rec or {}).get("sortTags") or [])
				                if re.fullmatch(r"Rarity_\d+", t)), None),
				"source": "Ark-Models + ArknightsGameData EN",
			}
			for mid in ids:
				new_ids.append(mid)
			art = resolve_art(key, typ, paths)
			if art:
				art_jobs[d] = art
				for mid in ids:
					manifest[mid] = f"{d}.webp"
			if typ in ("Operator", "DynIllust") and ids:
				sr = skin_by_asset.get("char_" + key.replace("dyn_illust_", "", 1))
				cid = (sr or {}).get("charId")
				if not cid:
					b = key.replace("dyn_illust_", "", 1).split("#")[0].split("_")
					cid = "_".join(b[:2])
				families[cid].append({
					"id": ids[0], "label": skin or ("Default" if
					     (rec or {}).get("style") == "BuildingDefault" else "Varian"),
					"default": (rec or {}).get("style") == "BuildingDefault",
					"name": char or label,
				})

	# ---- nama + family ---------------------------------------------------
	os.makedirs(DATA, exist_ok=True)
	for p, payload in ((NAMES_FILE, names), (FAMILY_FILE, {"families": []})):
		tmp = p + ".part"
		with open(tmp, "w", encoding="utf-8") as f:
			json.dump(payload, f, ensure_ascii=False, indent=1, sort_keys=True)
		os.replace(tmp, p)
	fam_list = []
	for cid, mem in sorted(families.items()):
		if len(mem) < 2:
			continue
		mem.sort(key=lambda x: (not x["default"], x["id"]))
		root = mem[0]["id"]
		fam_list.append({"root": root, "name": mem[0]["name"],
		                 "members": [{"id": x["id"], "label": x["label"]} for x in mem]})
	with open(FAMILY_FILE + ".part", "w", encoding="utf-8") as f:
		json.dump({"families": fam_list}, f, ensure_ascii=False, indent=1, sort_keys=True)
	os.replace(FAMILY_FILE + ".part", FAMILY_FILE)

	# ---- thumbnail ilustrasi (WebP) --------------------------------------
	os.makedirs(THUMBS, exist_ok=True)
	from PIL import Image  # noqa: PLC0415

	def one(item):
		d, art = item
		out = os.path.join(THUMBS, d + ".webp")
		if os.path.exists(out) and os.path.getsize(out) > 0:
			return ("skip", None)
		url = ART_URL + "/" + urllib.parse.quote(art, safe="/")
		try:
			try:
				raw = http_get(url, tries=2, timeout=60)
			except Exception:  # noqa: BLE001
				raw = http_get(f"{RAW}/yuanyan3060/ArknightsGameResource/main/" +
				               urllib.parse.quote(art, safe="/"), tries=2, timeout=60)
			im = Image.open(io.BytesIO(raw)).convert("RGBA")
			im.thumbnail((320, 420), Image.Resampling.LANCZOS)
			tmp = out + ".part"
			im.save(tmp, "WEBP", quality=82, method=4)
			os.replace(tmp, out)
			return ("ok", None)
		except Exception as e:  # noqa: BLE001
			return ("fail", f"{d}: {str(e)[:70]}")

	okn = skip = 0
	fails = []
	with cf.ThreadPoolExecutor(max_workers=WORKERS) as ex:
		for i, (state, err) in enumerate(ex.map(one, sorted(art_jobs.items())), 1):
			if state == "ok":
				okn += 1
			elif state == "skip":
				skip += 1
			else:
				fails.append(err)
			if i % 500 == 0:
				_log(f"  thumbnail {i}/{len(art_jobs)} ok={okn} skip={skip} gagal={len(fails)}")
	# Manifest hanya untuk thumbnail yang benar-benar ada.
	manifest = {k: v for k, v in manifest.items()
	            if os.path.exists(os.path.join(THUMBS, v))}
	with open(MANIFEST_FILE + ".part", "w", encoding="utf-8") as f:
		json.dump(manifest, f, ensure_ascii=False, indent=1, sort_keys=True)
	os.replace(MANIFEST_FILE + ".part", MANIFEST_FILE)
	# Hapus WebP yang tak lagi dipakai (mis. model hilang di rilis baru).
	used = set(manifest.values())
	for f in os.listdir(THUMBS):
		if f.endswith(".webp") and f not in used:
			os.remove(os.path.join(THUMBS, f))

	installed = sorted(dest.values())
	saved.update({
		"version": ver, "zipVersion": ver, "appliedAt": int(time.time()),
		"installed": installed, "folders": len(folders),
		"names": len(names), "families": len(fam_list),
		"thumbs": len(used),
	})
	save_state(saved)
	result.update({
		"expected": len(installed), "have": len(installed), "new": 0,
		"added": len(new_ids), "extracted": len(folders),
		"new_ids": new_ids, "new_models": [x.split("/", 1)[1] for x in new_ids],
		"names": len(names), "families": len(fam_list),
		"thumbs": len(used), "thumbFails": len(fails),
		"thumbJobs": len(art_jobs),
	})
	if fails:
		_log("  contoh gagal thumbnail: " + " | ".join(fails[:5]))
	_log(f"=== selesai: {len(folders)} model, {len(names)} nama, "
	     f"{len(fam_list)} family, {len(used)} thumbnail, gagal={len(fails)}")
	print(json.dumps(result, ensure_ascii=False, indent=1))
	return 0


if __name__ == "__main__":
	sys.exit(main())
