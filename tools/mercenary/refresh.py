#!/usr/bin/env python3
"""Otherworld Mercenary Corps (com.Cryptect.Mercenary) — ekstraktor aset.

Sumber: XAPK rilis Google Play lewat APKPure + CDN Addressables resmi
https://d2yyge1twff5nv.cloudfront.net/Product/Live/<versi>/Android/
XAPK-nya ~697 MB, tapi semua entrinya STORED, jadi cukup 2–3 request HTTP
Range untuk membaca central directory lalu mengunduh HANYA 3 bundle yang
dibutuhkan (~233 MB), tanpa mengunduh paket penuh. Sisanya (89 model Spine)
diunduh dari CDN: nama bundle memuat hash konten, jadi cache aman dipakai
lintas versi dan --apply ulang tidak mengunduh ulang apa pun.

Isi yang dipakai:
  assets/aa/catalog.json                       -> daftar karakter kanonik
  assets/aa/Android/duplicateassetisolation_*  -> 6 skeleton + atlas
  assets/aa/Android/local_assets_all_*         -> 3 skeleton + atlas
  assets/aa/Android/local_ui_assets_all_*      -> 92 ilustrasi slot karakter
  CDN catalog_Product.json                    -> 94 bundle prefab SpineIllust
  CDN remote_prefab_spineillust_*.bundle      -> 89 skeleton + atlas + tekstur

Keluaran:
  assets/mercenary/<slug>/<slug>.json|atlas|<page>.png   (98 model Spine 4.0.x)
  assets/mercenary-illust/<slug>.png                     (85 ilustrasi karakter)
  assets/mercenary/_names.json                           (nama + family)
  public/thumbs/mercenary/*.webp + _manifest.json + _sources.json
  data/mercenary-update-state.json

Thumbnail diambil dari GAMBAR ILUSTRASI karakter (UI_Slot_Illust_*), bukan
halaman atlas yang berisi potongan badan. Kalau karakter tidak punya slot,
dicari potret emoticon / splash art lobby / art NPC; atlas cuma fallback
terakhir. Asal tiap thumbnail tercatat di _sources.json.

Jalankan dengan interpreter service: /srv/venv-spine/bin/python
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import urllib.parse
import urllib.request
import zlib
from pathlib import Path

import UnityPy
from PIL import Image

UnityPy.config.FALLBACK_UNITY_VERSION = "2021.3.2f1"

ROOT = Path(__file__).resolve().parents[2]
ASSETS = ROOT / "assets"
THUMBS = ROOT / "public" / "thumbs"
DATA = ROOT / "data"
CACHE = Path("/srv/spine-assets/mercenary")
RAW = CACHE / "raw"
STATE = DATA / "mercenary-update-state.json"

# XAPK berisi 9 model "lokal". Sisanya (~89) diunduh dari CDN Addressables
# Product/Live/<versi>/Android/ — nama berkas bundle sudah mengandung hash
# konten, jadi cache bersama aman dipakai lintas versi.
CDN_TMPL = "https://d2yyge1twff5nv.cloudfront.net/Product/Live/{version}/Android/"
REMOTE_DIR = CACHE / "remote" / "bundles"
# Bundle UI/CDN tambahan yang cuma dipakai buat gambar ilustrasi thumbnail
# (profil, gacha, splash art lobby). Ukurannya kecil, di-cache terpisah.
ILLUST_EXTRA_DIR = CACHE / "remote" / "illust-extras"
# Bundle prefab < 100 KB cuma berisi MonoBehaviour (skeleton-nya ada di APK
# lokal), jadi tidak perlu diunduh.
REMOTE_MIN_SIZE = 100_000
CATALOG_REMOTE = "catalog_Product.json"

# Karakter yang tidak punya UI_Slot_Illust tapi punya splash art lobby di CDN.
# Batasi unduhan ke mereka saja (36 bundle lobby ada, tapi cuma ini yang perlu).
ILLUST_LOBBY_KEYS = ("holyemperor",)

LATEST = "https://d.apkpure.net/b/XAPK/com.Cryptect.Mercenary?version=latest"
SOURCE = "play.google.com/store/apps/details?id=com.Cryptect.Mercenary"
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/122 Safari/537.36"

# Prefix bundle yang diperlukan (hash di nama berkas bisa berubah tiap rilis).
WANT_BUNDLES = (
    "duplicateassetisolation_assets_all_",
    "local_assets_all_",
    "local_ui_assets_all_",
)
CATALOG = "assets/aa/catalog.json"

# Ilustrasi slot yang bukan karakter (bingkai rarity / placeholder).
SLOT_BLACKLIST = {"Beginning", "Divine", "Empty", "Epic", "Heroic", "Mythic", "World"}

# Model yang namanya beda dari berkas UI_Slot_Illust_* (salah eja di game,
# akhiran angka, atau varian kostum yang memakai ilustrasi karakter dasar).
ILLUST_ALIASES = {
    "ema_alt": "ema",
    "kei_alt": "kei",
    "albedo2": "albedo",
    "adult-kronos": "kronos",
    "bikini-eventdaphne": "bikini-daphne",
    "ninetails-roselin": "ninetales-roselin",
    "serina-serina": "serina",
    "newshoggoth": "shoggoth",
    "demonking2": "demonking",
    "citizen-slime-male": "citizen-male",
    "fallen-holyemperor": "holyemperor",
    "ts-holyemperor": "holyemperor",
}

# skeleton TextAsset -> (slug, karakter, label varian)
MODEL_MAP = {
    "ani_illust_Ada_001":     ("ada",     "Ada",     "Utama"),
    "Ani_Illust_Albedo_001": ("albedo",  "Albedo",  "Utama"),
    "ani_illust_Ema_001":    ("ema",     "Ema",     "Utama"),
    "ani_illust_Ema_01":     ("ema_alt", "Ema",     "Ilustrasi Alternatif"),
    "ani_illust_Karma_001":  ("karma",   "Karma",   "Utama"),
    "ani_illust_Kei_001":    ("kei",     "Kei",     "Utama"),
    "ani_illust_kei_01":     ("kei_alt", "Kei",     "Ilustrasi Alternatif"),
    "ani_illust_Kronos_01":  ("kronos",  "Kronos",  "Utama"),
    "ani_illust_Moa_001":    ("moa",     "Moa",     "Utama"),
}
MODEL_MAP_SLUGS = tuple(slug for slug, _, _ in MODEL_MAP.values())


def log(*a):
    print(*a, file=sys.stderr, flush=True)


# ---------------------------------------------------------------- HTTP Range
class RangeReader:
    def __init__(self, url: str, size: int):
        self.url, self.size = url, size

    def get(self, start: int, end: int) -> bytes:
        assert 0 <= start <= end < self.size, (start, end, self.size)
        req = urllib.request.Request(
            self.url, headers={"Range": f"bytes={start}-{end}", "User-Agent": UA}
        )
        last = None
        for attempt in range(4):
            try:
                with urllib.request.urlopen(req, timeout=180) as r:
                    return r.read()
            except Exception as e:  # noqa: BLE001
                last = e
        raise RuntimeError(f"Range {start}-{end} gagal: {last}")


def resolve_latest():
    """HEAD -> URL final (bertanda tangan) + ukuran + versi. 1 request."""
    req = urllib.request.Request(LATEST, method="HEAD", headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=60) as r:
        url, size = r.geturl(), int(r.headers["Content-Length"])
    q = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
    filename = urllib.parse.unquote_plus(q.get("filename", [""])[0])
    m = re.search(r"_(\d+\.\d+\.\d+)_", filename)
    version = m.group(1) if m else "unknown"
    if not m:
        full = q.get("full_size", [""])[0]
        version = f"build-{full}" if full else "unknown"
    return url, size, version


def zip_central_directory(rr: RangeReader, base: int, size: int):
    """Parse central directory ZIP yang berakhir di base+size."""
    tl = min(6 * 1024 * 1024, size)
    ts = base + size - tl
    tail = rr.get(ts, base + size - 1)
    pos = tail.rfind(b"PK\x05\x06")
    if pos < 0:
        raise RuntimeError("EOCD tidak ditemukan")
    _, _, _, n, cd_size, cd_off, _ = struct.unpack_from("<HHHHIIH", tail, pos + 4)
    cd_abs = base + cd_off
    cd = (tail[cd_abs - ts: cd_abs - ts + cd_size]
          if cd_abs >= ts else rr.get(cd_abs, cd_abs + cd_size - 1))
    out, i = [], 0
    while i + 46 <= len(cd) and cd[i:i + 4] == b"PK\x01\x02":
        (_, _, flags, method, _, _, crc, csize, usize,
         nlen, elen, clen, _, _, _, lho) = struct.unpack_from(
            "<HHHHHHIIIHHHHHII", cd, i + 4)
        name = cd[i + 46:i + 46 + nlen].decode("utf-8", "replace")
        out.append(dict(name=name, method=method, flags=flags, csize=csize,
                        usize=usize, lho=base + lho, crc=crc))
        i += 46 + nlen + elen + clen
    if len(out) != n:
        raise RuntimeError(f"central directory parsial: {len(out)}/{n}")
    return base, size, out


def entry_data_start(rr: RangeReader, lho: int) -> int:
    h = rr.get(lho, lho + 4095)
    if h[:4] != b"PK\x03\x04":
        raise RuntimeError("local header bukan ZIP")
    nlen, elen = struct.unpack_from("<HH", h, 26)
    return lho + 30 + nlen + elen


def fetch_entry(rr: RangeReader, e: dict, dest: Path) -> Path:
    """Unduh satu entri STORED/DEFLATE; cache kalau sudah ada dengan ukuran pas."""
    if dest.exists() and dest.stat().st_size == e["usize"]:
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    start = entry_data_start(rr, e["lho"])
    buf = bytearray()
    CH = 8 * 1024 * 1024
    for a in range(start, start + e["csize"], CH):
        b = min(a + CH - 1, start + e["csize"] - 1)
        buf += rr.get(a, b)
    if len(buf) != e["csize"]:
        raise RuntimeError(f"{e['name']}: {len(buf)}/{e['csize']} byte")
    data = zlib.decompress(bytes(buf), -15) if e["method"] == 8 else bytes(buf)
    if len(data) != e["usize"]:
        raise RuntimeError(f"{e['name']}: ukuran dekompresi {len(data)}/{e['usize']}")
    tmp = dest.with_suffix(dest.suffix + ".part")
    tmp.write_bytes(data)
    os.replace(tmp, dest)
    return dest


# ------------------------------------------------------- CDN Addressables
def http_get(url: str, timeout: int = 180) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def head_size(url: str) -> int:
    """Ukuran total berkas lewat satu request Range: bytes=0-0."""
    req = urllib.request.Request(url, headers={"Range": "bytes=0-0", "User-Agent": UA})
    with urllib.request.urlopen(req, timeout=60) as r:
        m = re.search(r"/(\d+)$", r.headers.get("Content-Range", ""))
        return int(m.group(1)) if m else -1


def remote_catalog(version: str) -> dict:
    """Katalog Addressables remote (hash isi beda dengan catalog.json di APK)."""
    dest = CACHE / "remote" / f"catalog-{version}.json"
    if not dest.exists() or dest.stat().st_size < 1000:
        dest.parent.mkdir(parents=True, exist_ok=True)
        raw = http_get(CDN_TMPL.format(version=version) + CATALOG_REMOTE, 180)
        tmp = dest.with_suffix(".json.part")
        tmp.write_bytes(raw)
        os.replace(tmp, dest)
    return json.loads(dest.read_text(encoding="utf-8"))


def remote_bundle_specs(version: str, catalog: dict, taken: set[str]):
    """Daftar bundle spineillust yang benar-benar membawa skeleton+atlas."""
    base = CDN_TMPL.format(version=version)
    names = sorted({x.rsplit("/", 1)[-1] for x in catalog.get("m_InternalIds", [])
                    if x.endswith(".bundle") and "spineillust" in x.lower()})
    log(f"CDN: {len(names)} bundle spineillust, cek ukuran")

    from concurrent.futures import ThreadPoolExecutor
    def measure(n):
        try:
            return n, head_size(base + n)
        except Exception:  # noqa: BLE001
            return n, -1
    with ThreadPoolExecutor(max_workers=10) as ex:
        sizes = dict(ex.map(measure, names))

    canon = sorted({m.group(1) for x in catalog.get("m_InternalIds", [])
                    if (m := re.search(r"Prefab/SpineIllust/([^/]+?)_Illust2?\.prefab$", x, re.I))})
    canon_by_key = {c.lower(): c for c in canon}
    specs, used = [], set(taken)
    for n in names:
        size = sizes.get(n, -1)
        if size < REMOTE_MIN_SIZE:
            continue
        m = re.search(r".*_spineillust_(.+?)_(illust2|illust)\.prefab_([0-9a-f]{16,})\.bundle$", n)
        if not m:
            log(f"LEWATI nama bundle tak dikenal: {n[:110]}")
            continue
        key, suffix, digest = m.group(1), m.group(2), m.group(3)
        if suffix == "illust2":
            key += "2"
        slug = re.sub(r"[^a-z0-9]+", "-", key.lower()).strip("-")
        if slug in used:
            slug = f"{slug}-{digest[:6]}"
        used.add(slug)
        char = canon_by_key.get(key.lower(), pretty(key))
        specs.append({"name": n, "size": size, "slug": slug,
                      "char": char.replace("_", " "), "key": key.lower()})
    log(f"CDN: {len(specs)} bundle self-contained dipakai")
    return specs, canon


def download_remote_bundles(version: str, specs: list[dict]):
    """Unduh bundle yang belum ada di cache. -> (paths, jumlah unduhan baru)."""
    REMOTE_DIR.mkdir(parents=True, exist_ok=True)
    base = CDN_TMPL.format(version=version)
    out, fresh = [], 0
    for s in specs:
        dest = REMOTE_DIR / s["name"]
        if not dest.exists() or dest.stat().st_size != s["size"]:
            data = http_get(base + s["name"], 300)
            if len(data) != s["size"]:
                raise RuntimeError(f"{s['name']}: {len(data)}/{s['size']} byte")
            tmp = dest.with_suffix(dest.suffix + ".part")
            tmp.write_bytes(data)
            os.replace(tmp, dest)
            fresh += 1
        out.append(dest)
    log(f"CDN: {fresh}/{len(specs)} bundle diunduh, {len(specs) - fresh} dari cache")
    return out, fresh


# ------------------------------------------------------------------ ekstraksi
def collect_one_bundle(path: Path):
    """-> (TextAsset name->bytes, Texture2D name->PIL.Image) untuk SATU bundle."""
    texts, textures = {}, {}
    env = UnityPy.load(str(path))
    for obj in env.objects:
        try:
            d = obj.read()
            n = getattr(d, "m_Name", None) or getattr(d, "name", None)
            if not n:
                continue
            if obj.type.name == "TextAsset" and n not in texts:
                b = d.m_Script
                texts[n] = b.encode("utf-8") if isinstance(b, str) else bytes(b)
            elif obj.type.name == "Texture2D" and n not in textures:
                textures[n] = d.image.copy()
        except Exception:  # noqa: BLE001 - sebagian objek native gagal dibaca
            continue
    return texts, textures


def collect_from_bundles(paths):
    """-> (texts: name->bytes, textures: name->PIL.Image)."""
    texts, textures = {}, {}
    for p in paths:
        env = UnityPy.load(str(p))
        for obj in env.objects:
            try:
                d = obj.read()
                n = getattr(d, "m_Name", None) or getattr(d, "name", None)
                if not n:
                    continue
                if obj.type.name == "TextAsset" and n not in texts:
                    b = d.m_Script
                    texts[n] = b.encode("utf-8") if isinstance(b, str) else bytes(b)
                elif obj.type.name == "Texture2D" and n not in textures:
                    textures[n] = d.image.copy()
            except Exception:  # noqa: BLE001 - sebagian objek native gagal dibaca
                continue
    return texts, textures


def atlas_pages(atlas_text: str):
    """Nama halaman PNG dari baris sebelum 'size:' di atlas."""
    pages, cur = [], None
    for line in atlas_text.replace("\ufeff", "").splitlines():
        s = line.strip()
        if not s:
            continue
        if s.lower().startswith("size:"):
            if cur:
                pages.append(cur)
                cur = None
        elif s.lower().endswith(".png") and "size:" not in s.lower():
            cur = s
    if cur:
        pages.append(cur)
    return list(dict.fromkeys(pages))


def pretty(name: str) -> str:
    return re.sub(r"\s+", " ", name.replace("_", " ").replace("-", " ")).strip().title()


def write_webp(png: Path, webp: Path):
    webp.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["/usr/bin/ffmpeg", "-loglevel", "error", "-y", "-i", str(png),
                    "-c:v", "libwebp", "-quality", "85", str(webp)],
                   check=True, capture_output=True)
    png.unlink(missing_ok=True)


# ------------------------------------------------------- peta ilustrasi
def slugify(s):
    return re.sub(r"[^a-z0-9]+", "-", str(s).lower()).strip("-")


def collect_illustrations(textures):
    """Kumpulkan SEMUA gambar ilustrasi karakter, bukan halaman atlas.

    Sumber (urutan prioritas):
      1. UI_Slot_Illust_<Karakter>_001     -> potret karakter resmi
      2. UI_Emoticon_<Karakter>_<Ekspresi> -> potret 640x640
      3. Citizen_Female_002 / Citizen_Male_001 -> art NPC utuh
      4. UI_Bg_Lobby_<Karakter>_Title_*    -> splash art karakter dari CDN
    Return (slot_map, extra_map) berisi PIL.Image dengan kunci slug karakter.
    """
    slot, extra = {}, {}
    for name, im in textures.items():
        if not isinstance(name, str):
            continue
        if name.startswith("UI_Slot_Illust_"):
            key = re.sub(r"_\d{3}$", "", name[len("UI_Slot_Illust_"):])
            if key and key not in SLOT_BLACKLIST:
                slot[slugify(key)] = im
            continue
        m = re.match(r"UI_Emoticon_(.+?)_[A-Za-z0-9]+$", name)
        if m:
            extra.setdefault(slugify(m.group(1)), im)
            continue
        if name.startswith("Citizen_") and min(im.size) >= 600:
            extra.setdefault(slugify(re.sub(r"_\d{3}$", "", name)), im)
            continue
        m = re.match(r"UI_Bg_Lobby_(.+?)_Title_", name)
        if m:
            extra.setdefault(slugify(m.group(1)), im)
    return slot, extra


def illust_candidates(slug, family_root=None):
    """Kunci kandidat ilustrasi untuk satu model, paling spesifik dulu."""
    out = [ILLUST_ALIASES.get(slug), slug]
    parts = [p for p in re.split(r"[-_]", slug) if p]
    if len(parts) > 1:
        out.append(parts[-1])
    if family_root and family_root != slug:
        out += [family_root, ILLUST_ALIASES.get(family_root)]
        rp = [p for p in re.split(r"[-_]", family_root) if p]
        if len(rp) > 1:
            out.append(rp[-1])
    seen, uniq = set(), []
    for k in out:
        if k and k not in seen:
            seen.add(k)
            uniq.append(k)
    return uniq


def resolve_illustration(slug, slot, extra, family_root=None):
    """Cari ilustrasi karakter; kembalikan (PIL.Image, sumber) / (None, None)."""
    keys = illust_candidates(slug, family_root)
    for key in keys:
        if key in slot:
            return slot[key], "slot:" + key
    for key in keys:
        if key in extra:
            return extra[key], "extra:" + key
    return None, None


def download_illust_extras(version: str, catalog: dict):
    """Ambil bundle UI tambahan (kecil) untuk ilustrasi karakter yang tidak
    punya UI_Slot_Illust. -> textures dict, cached lintas versi."""
    names = sorted({x.rsplit("/", 1)[-1] for x in catalog.get("m_InternalIds", [])
                    if x.endswith(".bundle") and (
                        "remote_profile_assets_all_" in x
                        or "remote_gacha_assets_all_" in x
                        or ("ui_bg_lobby_" in x.lower() and "_title_" in x.lower()
                            and any(k in x.lower() for k in ILLUST_LOBBY_KEYS)))})
    # Bundle yang sudah ada di cache tetap dipakai walau allowlist berubah.
    names = sorted(set(names) | {p.name for p in ILLUST_EXTRA_DIR.glob("*.bundle")})
    ILLUST_EXTRA_DIR.mkdir(parents=True, exist_ok=True)
    base = CDN_TMPL.format(version=version)
    paths, fresh = [], 0
    for n in names:
        dest = ILLUST_EXTRA_DIR / n
        if not dest.exists() or dest.stat().st_size < 1000:
            try:
                data = http_get(base + n, 180)
            except Exception as exc:  # noqa: BLE001 - opsional, jangan gagalkan apply
                log(f"LEWATI ilustrasi ekstra {n[:70]}: {exc}")
                continue
            if len(data) < 1000:
                continue
            tmp = dest.with_suffix(dest.suffix + ".part")
            tmp.write_bytes(data)
            os.replace(tmp, dest)
            fresh += 1
        paths.append(dest)
    log(f"ilustrasi ekstra: {fresh}/{len(names)} bundle diunduh, {len(paths)} dipakai")
    return collect_from_bundles(paths)[1] if paths else {}


def build_thumbnails(spine_dir: Path, thumb_dir: Path, slot, extra,
                     model_ids, fam_payload):
    """Satu pass thumbnail: SEMUA model pakai gambar ilustrasi karakter.

    Halaman atlas (kumpulan potongan badan) cuma dipakai kalau game memang
    tidak menyediakan ilustrasi untuk karakter itu. Hasil: _manifest.json
    (tetap 98 kunci) + _sources.json (asal gambar tiap thumbnail).
    """
    # model -> root family, supaya varian kostum mewarisi ilustrasi utama
    fam_root = {}
    for fam in fam_payload:
        root = fam["root"].split("/", 1)[-1]
        for m in fam["members"]:
            fam_root.setdefault(m["id"].split("/", 1)[-1], root)
    manifest, sources = {}, {}
    counts = {"slot": 0, "extra": 0, "atlas": 0}
    for mid in sorted(model_ids):
        slug = mid.split("/", 1)[-1]
        d = spine_dir / slug
        im, src = resolve_illustration(slug, slot, extra, fam_root.get(slug))
        if im is not None:
            counts["slot" if str(src).startswith("slot:") else "extra"] += 1
        else:
            # fallback terakhir: halaman atlas pertama yang sudah ditulis ke
            # folder model, diperkecil supaya tidak jadi kumpulan potongan badan
            page = None
            atlas = d / f"{slug}.atlas"
            if atlas.exists():
                pages = atlas_pages(atlas.read_text(encoding="utf-8", errors="replace"))
                if pages and (d / pages[0]).exists():
                    page = Image.open(d / pages[0]).convert("RGBA")
            if page is None:
                for p in sorted(d.glob("*.png")):
                    page = Image.open(p).convert("RGBA")
                    break
            if page is None:
                log(f"LEWATI thumbnail {slug}: tak ada sumber gambar")
                continue
            im, src = page, "atlas"
            im.thumbnail((300, 300))
            counts["atlas"] += 1
        # ilustrasi portrait tinggi: potong tengah-atas jadi hampir kotak
        # biar wajah karakter tetap kelihatan di kartu thumbnail
        im = im.convert("RGBA")
        w, h = im.size
        if h > w * 1.25:
            crop_h = int(w * 1.25)
            top = max(0, int((h - crop_h) * 0.18))
            im = im.crop((0, top, w, min(h, top + crop_h)))
        im.thumbnail((360, 450))
        png = thumb_dir / f"{slug}.png"
        im.save(png, format="PNG")
        write_webp(png, thumb_dir / f"{slug}.webp")
        manifest[mid] = f"{slug}.webp"
        sources[mid] = src
    (thumb_dir / "_sources.json").write_text(
        json.dumps({"counts": counts, "sources": sources}, ensure_ascii=False, indent=1),
        encoding="utf-8")
    log(f"thumbnail: {counts['slot']} slot + {counts['extra']} ekstra ilustrasi, "
        f"{counts['atlas']} atlas fallback")
    return manifest, counts


def build_remote_models(specs, paths, spine_dir: Path):
    """89 model Spine dari CDN. Tiap bundle self-contained (json+atlas+PNG)."""
    models, manifest, groups = {}, {}, {}
    for spec, path in zip(specs, paths):
        slug, char = spec["slug"], spec["char"]
        texts, textures = collect_one_bundle(path)
        skel_names = [n for n in texts
                      if not n.lower().endswith(".atlas") and n + ".atlas" in texts]
        if not skel_names:
            log(f"LEWATI {slug}: tak ada pasangan skeleton/atlas")
            continue
        skel_name = skel_names[0]
        skel = texts[skel_name]
        atlas = texts[skel_name + ".atlas"].decode("utf-8-sig", "replace")
        pages = atlas_pages(atlas)
        if not pages:
            log(f"LEWATI {slug}: atlas tanpa halaman")
            continue
        out = spine_dir / slug
        out.mkdir(exist_ok=True)
        (out / f"{slug}.json").write_bytes(skel)
        (out / f"{slug}.atlas").write_text(atlas, encoding="utf-8")
        missing = []
        for page in pages:
            im = textures.get(Path(page).stem) or textures.get(page) \
                or textures.get(skel_name)
            if im is None:
                missing.append(page)
                continue
            im.save(out / page, format="PNG")
        if missing:
            raise RuntimeError(f"{slug}: halaman hilang {missing}")
        models[f"mercenary/{slug}"] = {
            "name": char, "label": "Utama",
            "character": {"name": char, "source": SOURCE, "origin": "cdn"},
        }
        # Thumbnail tidak dibuat di sini: build_thumbnails() mengerjakannya
        # satu pass setelah family terbentuk, supaya semua model memakai
        # ilustrasi karakter (bukan halaman atlas potongan badan).
        # Kelompokkan varian kostum dengan karakter dasarnya, mis.
        # Bikini_Kronos / Adult_Kronos -> famili "Kronos".
        key = spec["key"]
        parts = key.split("_")
        base = parts[-1] if len(parts) > 1 else key
        groups.setdefault(base, []).append(f"mercenary/{slug}")
    log(f"model CDN: {len(models)}")
    return models, manifest, groups


def build_outputs(texts, textures, catalog_ids, version, stage: Path,
                  remote_specs=None, remote_paths=None, extra_textures=None):
    """Tulis staging lengkap; kembalikan ringkasan + names payload."""
    spine_dir = stage / "mercenary"
    illust_dir = stage / "mercenary-illust"
    thumb_dir = stage / "thumbs" / "mercenary"
    spine_dir.mkdir(parents=True, exist_ok=True)
    illust_dir.mkdir(parents=True, exist_ok=True)
    thumb_dir.mkdir(parents=True, exist_ok=True)

    # --- karakter kanonik dari katalog Addressables -------------------------
    characters = sorted({m.group(1) for x in catalog_ids
                         if (m := re.search(r"Prefab/SpineIllust/([^/]+)_Illust\.prefab$", x))})
    log(f"karakter kanonik: {len(characters)}")

    # --- 9 model Spine ------------------------------------------------------
    models, manifest, families = {}, {}, {}
    for skel_name, (slug, char, label) in MODEL_MAP.items():
        if skel_name not in texts or skel_name + ".atlas" not in texts:
            log(f"LEWATI {skel_name}: skeleton/atlas tidak ada")
            continue
        skel = texts[skel_name]
        atlas = texts[skel_name + ".atlas"].decode("utf-8-sig", "replace")
        pages = atlas_pages(atlas)
        if not pages:
            log(f"LEWATI {skel_name}: atlas tanpa halaman")
            continue
        out = spine_dir / slug
        out.mkdir(exist_ok=True)
        (out / f"{slug}.json").write_bytes(skel)
        (out / f"{slug}.atlas").write_text(atlas, encoding="utf-8")
        missing = []
        for page in pages:
            stem = Path(page).stem
            im = textures.get(stem) or textures.get(page)
            if im is None:
                missing.append(page)
                continue
            im.save(out / page, format="PNG")
        if missing:
            raise RuntimeError(f"{skel_name}: halaman hilang {missing}")
        models[f"mercenary/{slug}"] = {
            "name": char if label == "Utama" else f"{char} — {label}",
            "label": label,
            "character": {"name": char, "variant": label, "source": SOURCE},
        }
        families.setdefault(char, []).append(f"mercenary/{slug}")
        log(f"model {slug}: {len(skel)} byte skeleton, {len(pages)} halaman")

    # --- model Spine dari CDN Addressables ----------------------------------
    # Dikerjakan per-bundle karena dua bundle bisa memakai nama skeleton yang
    # sama (Bikini_Daphne / Demonking) dengan isi berbeda.
    remote_models, remote_manifest = {}, {}
    remote_groups: dict[str, list[str]] = {}
    if remote_specs and remote_paths:
        remote_models, remote_manifest, remote_groups = build_remote_models(
            remote_specs, remote_paths, spine_dir)
        models.update(remote_models)
        manifest.update(remote_manifest)

    # --- ilustrasi karakter (format image) ---------------------------------
    illust_ids = []
    for name, im in textures.items():
        if not name.startswith("UI_Slot_Illust_"):
            continue
        char = name[len("UI_Slot_Illust_"):]
        char = re.sub(r"_\d{3}$", "", char)
        if char in SLOT_BLACKLIST:
            continue
        slug = re.sub(r"[^a-z0-9]+", "-", char.lower()).strip("-")
        if not slug:
            continue
        dest = illust_dir / f"{slug}.png"
        im.save(dest, format="PNG")
        models[f"mercenary-illust/{slug}"] = {
            "name": pretty(char),
            "label": "Ilustrasi",
            "character": {"name": pretty(char), "source": SOURCE},
        }
        illust_ids.append(f"mercenary-illust/{slug}")
    log(f"ilustrasi: {len(illust_ids)}")

    # Satu kartu root per karakter; varian kostum dari CDN dan rig alternatif
    # lokal disatukan lewat picker Varian. Kunci grup = token terakhir nama
    # (Bikini_Kronos / Adult_Kronos -> "kronos").
    all_groups: dict[str, list[str]] = {}
    for key, ids in remote_groups.items():
        all_groups.setdefault(key, []).extend(ids)
    for char, ids in families.items():
        all_groups.setdefault(char.lower(), []).extend(ids)
    fam_payload = []
    for key, ids in sorted(all_groups.items()):
        ids = list(dict.fromkeys(ids))
        if len(ids) < 2:
            continue
        root_id = f"mercenary/{key}"
        root = root_id if root_id in ids else next(
            (x for x in ids if not x.endswith("_alt")), ids[0])
        local_char = next((c for c, xs in families.items()
                           if c.lower() == key and root in xs), None)
        fam_name = local_char or pretty(key)
        members = [{"id": x,
                    "label": "Utama" if x == root else "Varian Kostum"}
                   for x in ids]
        fam_payload.append({"root": root, "name": fam_name, "members": members})

    # --- thumbnail: gambar ilustrasi karakter, bukan halaman atlas ----------
    # Ambil UI_Slot_Illust_* dari bundle lokal + bundle UI tambahan CDN;
    # varian kostum mewarisi ilustrasi karakter utama lewat family picker.
    all_textures = dict(textures)
    all_textures.update(extra_textures or {})
    slot, extra = collect_illustrations(all_textures)
    log(f"peta ilustrasi: {len(slot)} slot + {len(extra)} ekstra")
    spine_ids = [k for k in models if k.startswith("mercenary/")]
    manifest, thumb_counts = build_thumbnails(
        spine_dir, thumb_dir, slot, extra, spine_ids, fam_payload)

    names = {
        "source": SOURCE,
        "gameVersion": version,
        "sig": hashlib.sha1(("\n".join(
            sorted(catalog_ids) + [s["name"] for s in (remote_specs or [])]
        )).encode()).hexdigest()[:16],
        "models": models,
        "families": fam_payload,
        "characters": characters,
    }
    (spine_dir / "_names.json").write_text(
        json.dumps(names, ensure_ascii=False, indent=1), encoding="utf-8")
    (thumb_dir / "_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")

    # --- validasi staging sebelum swap -------------------------------------
    valid = 0
    for d in spine_dir.iterdir():
        if not d.is_dir():
            continue
        stem = d.name
        if not (d / f"{stem}.json").exists() or not (d / f"{stem}.atlas").exists():
            continue
        pages = [p for p in d.iterdir() if p.suffix.lower() == ".png"]
        if pages:
            valid += 1
    if valid < 9:
        raise RuntimeError(f"staging cuma {valid} model valid (minimal 9)")
    expected = 9 + len(remote_models)
    if valid < expected:
        raise RuntimeError(f"staging {valid}/{expected} model valid")
    return dict(models=valid, illusts=len(illust_ids),
                families=len(fam_payload), names=names, manifest=manifest,
                thumbCounts=thumb_counts,
                thumbIllust=thumb_counts["slot"] + thumb_counts["extra"],
                characters=len(characters))


def swap_into_repo(stage: Path, info: dict):
    """Backup pohon lama, lalu pindahkan staging ke assets/ + thumbs/."""
    stamp = hashlib.sha1(str(os.getpid()).encode()).hexdigest()[:8]
    for rel in ("mercenary", "mercenary-illust"):
        target = ASSETS / rel
        if target.exists():
            backup = CACHE / f"backup-{stamp}" / rel
            backup.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(target), str(backup))
        shutil.move(str(stage / rel), str(target))
    tdir = THUMBS / "mercenary"
    if tdir.exists():
        shutil.rmtree(tdir)
    shutil.move(str(stage / "thumbs" / "mercenary"), str(tdir))


def local_counts():
    d = ASSETS / "mercenary"
    spine = sum(1 for x in d.iterdir() if x.is_dir()) if d.exists() else 0
    di = ASSETS / "mercenary-illust"
    ill = sum(1 for x in di.glob("*.png")) if di.exists() else 0
    return spine, ill


# ------------------------------------------------------------------- kontrak
def read_state():
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def write_state(st):
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(st, ensure_ascii=False, indent=1), encoding="utf-8")


def check() -> dict:
    url, size, version = resolve_latest()
    st = read_state()
    spine, ill = local_counts()
    previous = st.get("version") or version
    lost = spine < int(st.get("models", 0) or 0)
    # Satu GET 32 byte: hash katalog Addressables remote. Kalau developer
    # menambah/mengganti karakter tanpa menaikkan versi APK, ini yang berubah.
    try:
        cdn_hash = http_get(
            CDN_TMPL.format(version=version) + "catalog_Product.hash", 30
        ).decode("ascii", "replace").strip()
    except Exception:  # noqa: BLE001 - CDN down jangan bikin check gagal
        cdn_hash = ""
    if not st:
        write_state({"version": version, "size": size, "models": spine,
                     "illusts": ill, "sig": "", "cdnHash": cdn_hash})
        return {"ok": True, "mode": "check", "version": version,
                "previous": previous, "changed": False, "new": 0,
                "have": spine, "illusts": ill,
                "reason": "bootstrap state"}
    changed = (st.get("version") != version or st.get("size") != size
               or lost or (cdn_hash and st.get("cdnHash") != cdn_hash))
    return {"ok": True, "mode": "check", "version": version,
            "previous": previous, "changed": bool(changed), "new": 0,
            "have": spine, "illusts": ill,
            "reason": "versi/ukuran XAPK atau katalog CDN berubah" if changed
                      else "up to date"}


def apply() -> dict:
    url, size, version = resolve_latest()
    log(f"versi {version}, ukuran {size} byte")
    rr = RangeReader(url, size)

    _, _, outer = zip_central_directory(rr, 0, size)
    log(f"XAPK: {len(outer)} entri")
    base_entry = next(e for e in outer if e["name"] == "base_assets.apk")
    base = entry_data_start(rr, base_entry["lho"])
    _, _, inner = zip_central_directory(rr, base, base_entry["csize"])
    log(f"base_assets.apk: {len(inner)} entri")

    by_name = {e["name"]: e for e in inner}
    wanted = [e for e in inner
              if e["name"].startswith("assets/aa/Android/")
              and e["name"].endswith(".bundle")
              and any(Path(e["name"]).name.startswith(p) for p in WANT_BUNDLES)]
    if len(wanted) != len(WANT_BUNDLES):
        raise RuntimeError(f"bundle yang dicari cuma {len(wanted)}/{len(WANT_BUNDLES)}")
    cat = by_name.get(CATALOG)
    if not cat:
        raise RuntimeError("assets/aa/catalog.json tidak ada")

    work = RAW / version
    work.mkdir(parents=True, exist_ok=True)
    log("unduh katalog + 3 bundle lewat HTTP Range")
    cat_path = fetch_entry(rr, cat, work / "catalog.json")
    bundle_paths = []
    for e in wanted:
        p = fetch_entry(rr, e, work / Path(e["name"]).name)
        log(f"  {p.name}: {p.stat().st_size} byte")
        bundle_paths.append(p)

    catalog = json.loads(cat_path.read_text(encoding="utf-8"))
    ids = catalog.get("m_InternalIds", [])
    texts, textures = collect_from_bundles(bundle_paths)
    log(f"TextAsset {len(texts)}, Texture2D {len(textures)}")

    # --- CDN Addressables: 89 model Spine yang tidak ikut di APK -----------
    rcatalog = remote_catalog(version)
    specs, canon = remote_bundle_specs(version, rcatalog, set(MODEL_MAP_SLUGS))
    remote_paths, remote_fresh = download_remote_bundles(version, specs)
    # 3 bundle UI kecil: potret profil, gacha, dan splash art lobby. Dipakai
    # supaya thumbnail tidak ada yang jadi halaman atlas potongan badan.
    extra_textures = download_illust_extras(version, rcatalog)
    cdn_hash = ""
    try:
        cdn_hash = http_get(
            CDN_TMPL.format(version=version) + "catalog_Product.hash", 30
        ).decode("ascii", "replace").strip()
    except Exception:  # noqa: BLE001
        pass

    stage = CACHE / f"stage-{version}-{os.getpid()}"
    if stage.exists():
        shutil.rmtree(stage)
    stage.mkdir(parents=True)
    info = build_outputs(texts, textures, ids, version, stage,
                         remote_specs=specs, remote_paths=remote_paths,
                         extra_textures=extra_textures)
    swap_into_repo(stage, info)
    shutil.rmtree(stage, ignore_errors=True)

    spine, ill = local_counts()
    sig = info["names"]["sig"]
    write_state({"version": version, "size": size, "sig": sig,
                 "models": spine, "illusts": ill, "cdnHash": cdn_hash,
                 "cdnModels": len(specs), "thumbIllust": info["thumbIllust"]})
    return {"ok": True, "mode": "apply", "version": version,
            "previous": version, "changed": False, "new": 0,
            "models": spine, "illusts": ill, "families": info["families"],
            "characters": info["characters"],
            "thumbCounts": info["thumbCounts"],
            "downloaded": len(bundle_paths) + 1 + remote_fresh,
            "extracted": info["models"] + info["illusts"],
            "new_ids": [], "sig": sig, "cdnModels": len(specs),
            "cdnCached": len(specs) - remote_fresh}


if __name__ == "__main__":
    if "--check" in sys.argv:
        result = check()
    else:
        result = apply()
    print(json.dumps(result, ensure_ascii=False, indent=1))
