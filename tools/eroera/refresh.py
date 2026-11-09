#!/usr/bin/env python3
"""Sinkronkan 欲洛降临 (EroEra — youdianse.com/game/detail/456) dari CDN resmi.

Pipeline:
  1. Cek https://res-01.eepgames.com/buildCfg/<ver>/Android/Version.txt
     (dan auto-detect kenaikan versi dari https://www.youdianse.com/game/detail/456).
  2. Unduh & dekompres GameFrameworkVersion.<hash8>.dat (GFU v2 binary).
  3. Unduh 75 bundle Spine (`Spine/Pet/Pets` + `Spine/Role/*`),
     `TbData/TbDatas` (QuickDecrypt 220 byte XOR hash_code), dan
     `SpriteAtlas/Packs/Hero` ke `/srv/spine-assets/eroera/bundles/`.
  4. Parse tabel Luban ByteBuf:
     - `hero_tbheroshowgirl` -> 30 nama karakter (`10001` 白川纱世 .. `10030` 伊丝瑞拉)
     - `pet_tbpetcharacter`  -> 10 nama pet (`huoyanfeie` 卜吉/炽羽 .. `long` 墩墩) + ikon `p_kp*`
  5. Ekstrak 174 model Spine (4.1.23 / 4.1.24) ke `assets/eroera/<slug>/`:
     - Hapus BOM UTF-8 (`\ufeff`) dari `.atlas` (`c010_00.atlas`).
     - Pasangkan `<stem>.skel` (atau `.json` untuk `z10009/00`) + `<stem>.atlas` + `.png`.
  6. Ekstrak potret kartu resmi (`card_1_1`..`card_30_3`, `p_kp41001`..`p_kp45002`)
     dari `SpriteAtlas/Packs/Hero`, konversi ke WebP di `public/thumbs/eroera/` +
     `_manifest.json` (menutup 165/174 model: tất cả 30 hero + semua variannya + 10 pet).
  7. Tulis `assets/eroera/_names.json` (174 model, 43 kartu root = 30 hero + 10 pet + 3 extra).

Usage:
    /srv/venv-spine/bin/python tools/eroera/refresh.py [--limit N] [--force]
"""
from __future__ import annotations

import argparse
import collections
import concurrent.futures
import gzip
import hashlib
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path
from typing import Any

import UnityPy  # type: ignore[import-untyped]

VIEW = Path(__file__).resolve().parents[2]
OUT_MODELS = VIEW / "assets" / "eroera"
THUMBS = VIEW / "public" / "thumbs" / "eroera"
GAME_ICON = VIEW / "public" / "thumbs" / "_game" / "eroera.png"
STATE_DIR = Path(os.environ.get("EROERA_STATE", "/srv/spine-assets/eroera"))
BUNDLE_DIR = STATE_DIR / "bundles"

YOUDIANSE_URL = "https://www.youdianse.com/game/detail/456"
GAME_ICON_URL = "https://d391me9s8n5j5s.cloudfront.net/uploads/2026-04-27/711064ac683e8b7786dff700f0ed32c8.png"
CDN_HOSTS = ("https://res-01.eepgames.com", "https://res2.eepgames.com")
DEFAULT_VER_SLUG = "0_1_64"
UA = "Mozilla/5.0 (X11; Linux x86_64) spine-viewer-eroera/1.0"
WORKERS = 10


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", file=sys.stderr, flush=True)


def http_get(url: str, timeout: int = 90, retries: int = 3) -> bytes:
    last = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except Exception as exc:  # noqa: BLE001
            last = exc
            time.sleep(1.0 * (attempt + 1))
    raise RuntimeError(f"gagal mengunduh {url}: {last}")


def detect_ver_slug() -> str:
    """Deteksi versi `0_1_<N>` dari halaman youdianse (fallback `0_1_64`)."""
    try:
        html = http_get(YOUDIANSE_URL, timeout=20, retries=1).decode("utf-8", "replace")
        m = re.search(r"eroera_\d+_V(\d+)\.(\d+)\.(\d+)(?:\.\d+)?_prod\.apk", html, re.I)
        if m:
            return f"{m.group(1)}_{m.group(2)}_{m.group(3)}"
    except Exception:  # noqa: BLE001
        pass
    return DEFAULT_VER_SLUG


def fetch_version_info() -> dict:
    slug = detect_ver_slug()
    candidates = [slug] if slug == DEFAULT_VER_SLUG else [slug, DEFAULT_VER_SLUG]
    last_err = None
    for s in candidates:
        for host in CDN_HOSTS:
            url = f"{host}/buildCfg/{s}/Android/Version.txt"
            try:
                raw = http_get(url, timeout=25, retries=2)
                info = json.loads(raw.decode("utf-8-sig"))
                info["_verSlug"] = s
                info["_versionUrl"] = url
                return info
            except Exception as exc:  # noqa: BLE001
                last_err = exc
    raise RuntimeError(f"Version.txt tidak bisa diambil: {last_err}")


def parse_gfu_version_list(raw_gz: bytes) -> dict:
    raw = gzip.decompress(raw_gz) if raw_gz[:2] == b"\x1f\x8b" else raw_gz
    if raw[:3] != b"GFU":
        raise RuntimeError(f"magic GameFrameworkVersion bukan GFU: {raw[:8]!r}")
    pos = 4
    enc = raw[pos:pos + 4]
    pos += 4

    def read_7bit_int() -> int:
        nonlocal pos
        val = 0
        shift = 0
        while True:
            b = raw[pos]
            pos += 1
            val |= (b & 0x7F) << shift
            if (b & 0x80) == 0:
                return val
            shift += 7

    def read_enc_str() -> str:
        nonlocal pos
        n = read_7bit_int()
        b = bytes(raw[pos + i] ^ enc[i & 3] for i in range(n))
        pos += n
        return b.decode("utf-8", "replace")

    app_ver = read_enc_str()
    internal_res_ver = read_7bit_int()
    asset_count = read_7bit_int()
    assets = []
    for _ in range(asset_count):
        aname = read_enc_str()
        dep_cnt = read_7bit_int()
        deps = [read_7bit_int() for _ in range(dep_cnt)]
        assets.append((aname, deps))

    res_count = read_7bit_int()
    resources = []
    for _ in range(res_count):
        rname = read_enc_str()
        rvariant = read_enc_str()
        rext = read_enc_str()
        load_type = raw[pos]
        pos += 1
        length = read_7bit_int()
        hash_code = struct.unpack_from("<I", raw, pos)[0]
        pos += 4
        comp_len = read_7bit_int()
        comp_hash = struct.unpack_from("<I", raw, pos)[0]
        pos += 4
        acnt = read_7bit_int()
        aidxs = [read_7bit_int() for _ in range(acnt)]
        resources.append({
            "name": rname,
            "variant": rvariant,
            "ext": rext,
            "loadType": load_type,
            "length": length,
            "hash": hash_code,
            "compLen": comp_len,
            "compHash": comp_hash,
            "assets": [assets[i][0] for i in aidxs],
        })

    return {
        "appVersion": app_ver,
        "internalResourceVersion": internal_res_ver,
        "assetCount": asset_count,
        "resources": resources,
    }


def fetch_catalog() -> tuple[dict, dict, str]:
    """Kembalikan (ver_info, gfu_dict, sig16)."""
    vinfo = fetch_version_info()
    prefix = vinfo["UpdatePrefixUri"].rstrip("/") + "/"
    h_hex = f"{int(vinfo['VersionListHashCode']) & 0xFFFFFFFF:08x}"
    gfu_url = f"{prefix}GameFrameworkVersion.{h_hex}.dat"
    raw_gz = http_get(gfu_url, timeout=60)
    gfu = parse_gfu_version_list(raw_gz)
    sig = hashlib.sha256(
        f"{vinfo.get('LatestGameVersion')}|{vinfo.get('InternalResourceVersion')}|{h_hex}".encode()
    ).hexdigest()[:16]
    return vinfo, gfu, sig


def sync_bundles(vinfo: dict, resources: list[dict]) -> tuple[dict[str, Path], int]:
    prefix = vinfo["UpdatePrefixUri"].rstrip("/") + "/"
    BUNDLE_DIR.mkdir(parents=True, exist_ok=True)
    wanted = [
        r for r in resources
        if r["name"].startswith("Spine/")
        or r["name"] in ("SpriteAtlas/Packs/Hero", "TbData/TbDatas")
    ]
    paths: dict[str, Path] = {}
    dl_count = 0

    def one(r: dict) -> tuple[str, Path, bool]:
        ext = r["ext"] or "dat"
        rel = f"{r['name']}.{r['hash']:08x}.{ext}"
        dest = BUNDLE_DIR / rel
        if dest.is_file() and dest.stat().st_size == r["compLen"]:
            return r["name"], dest, False
        dest.parent.mkdir(parents=True, exist_ok=True)
        data = http_get(prefix + rel, timeout=120)
        if r["loadType"] == 2:
            # GameFramework QuickDecrypt: 220 byte pertama di-XOR 4-byte hash_code LE
            ba = bytearray(data)
            k = struct.pack("<I", r["hash"])
            for i in range(min(220, len(ba))):
                ba[i] ^= k[i & 3]
            data = bytes(ba)
        dest.write_bytes(data)
        return r["name"], dest, True

    with concurrent.futures.ThreadPoolExecutor(max_workers=WORKERS) as pool:
        for rname, dest, downloaded in pool.map(one, wanted):
            paths[rname] = dest
            if downloaded:
                dl_count += 1
    return paths, dl_count


def parse_text_asset(raw: bytes) -> tuple[str, bytes]:
    n = struct.unpack_from("<I", raw, 0)[0]
    name = raw[4:4 + n].decode("utf-8", "replace")
    pos = (4 + n + 3) & ~3
    sz = struct.unpack_from("<I", raw, pos)[0]
    return name, raw[pos + 4:pos + 4 + sz]


class LubanBuf:
    def __init__(self, data: bytes) -> None:
        self.b = data
        self.p = 0

    def read_int(self) -> int:
        b0 = self.b[self.p]
        if b0 < 0x80:
            self.p += 1
            return b0
        if b0 < 0xC0:
            v = ((b0 & 0x3F) << 8) | self.b[self.p + 1]
            self.p += 2
            return v
        if b0 < 0xE0:
            v = ((b0 & 0x1F) << 16) | (self.b[self.p + 1] << 8) | self.b[self.p + 2]
            self.p += 3
            return v
        if b0 < 0xF0:
            v = (
                ((b0 & 0x0F) << 24)
                | (self.b[self.p + 1] << 16)
                | (self.b[self.p + 2] << 8)
                | self.b[self.p + 3]
            )
            self.p += 4
            return v
        v = struct.unpack_from(">i", self.b, self.p + 1)[0]
        self.p += 5
        return v

    def read_str(self) -> str:
        n = self.read_int()
        s = self.b[self.p:self.p + n].decode("utf-8", "replace")
        self.p += n
        return s


def load_luban_names(tb_bundle: Path) -> tuple[dict[int, str], dict[str, dict]]:
    env = UnityPy.load(str(tb_bundle))
    tables = dict(
        parse_text_asset(o.get_raw_data())
        for o in env.objects
        if o.type.name == "TextAsset"
    )
    heroes: dict[int, str] = {}
    buf = LubanBuf(tables["hero_tbheroshowgirl"])
    for _ in range(buf.read_int()):
        _rid = buf.read_int()
        hid = buf.read_int()
        hname = buf.read_str()
        for _ in range(buf.read_int()):
            buf.read_int()
        _def_pic = buf.read_int()
        heroes[hid] = hname

    pets: dict[str, dict] = collections.OrderedDict()
    buf = LubanBuf(tables["pet_tbpetcharacter"])
    for _ in range(buf.read_int()):
        _pid = buf.read_int()
        pname = buf.read_str()
        buf.read_int()
        buf.read_int()
        buf.read_int()
        _pdesc = buf.read_str()
        _s1 = buf.read_str()
        buf.read_int()
        buf.read_int()
        buf.read_int()
        card_img = buf.read_str()
        head_img = buf.read_str()
        spine_path = buf.read_str()
        pfolder = spine_path.split("/")[0]
        slug = pfolder if pfolder.startswith("pet_") else f"pet_{pfolder}"
        info = pets.setdefault(slug, {"names": [], "card": card_img, "head": head_img})
        if pname not in info["names"]:
            info["names"].append(pname)

    return heroes, pets


def slug_for(rel: str) -> tuple[str, str, str, int]:
    """Kembalikan (slug, root_slug, variant_label, sort_order)."""
    if rel.startswith("pet/"):
        pname = rel.split("/", 1)[1]
        slug = pname if pname.startswith("pet_") else f"pet_{pname}"
        return slug, slug, "Utama", 0

    for extra in ("c010", "t001", "t002"):
        if rel.startswith(f"role/{extra}/"):
            sub = rel.split("/")[2]
            root = f"role_{extra}"
            if sub == "00":
                return root, root, "Utama", 0
            if sub == "aim":
                return f"{root}_aim", root, "Aim", 10
            if sub == "cover":
                return f"{root}_cover", root, "Cover", 11

    if rel.startswith("role/20001_b/"):
        sub = rel.split("/")[2]
        root = "hero_10013"
        act_map = {
            "show": ("hero_10013_act_show", "Activity — Show", 20),
            "ing": ("hero_10013_act_ing", "Activity — Action", 21),
            "end": ("hero_10013_act_end", "Activity — End", 22),
            "dianji": ("hero_10013_act_click", "Activity — Click", 23),
            "texiao": ("hero_10013_act_fx", "Activity — FX", 24),
        }
        s, l, o = act_map[sub]
        return s, root, l, o

    m_r = re.match(r"role/r00([12])_h/(aim|cover|skill)$", rel)
    if m_r:
        hid = 10000 + int(m_r.group(1))
        sub = m_r.group(2)
        root = f"hero_{hid}"
        lbl, order = {"aim": ("Aim", 10), "cover": ("Cover", 11), "skill": ("Skill Cut", 12)}[sub]
        return f"{root}_{sub}", root, lbl, order

    m_200 = re.match(r"role/200(\d{2})/(stand|base|adv)$", rel)
    if m_200:
        hid = 10000 + int(m_200.group(1))
        sub = m_200.group(2)
        root = f"hero_{hid}"
        if sub == "stand":
            return root, root, "Utama", 0
        if sub == "base":
            return f"{root}_h_base", root, "H Scene — Base (初级)", 1
        if sub == "adv":
            return f"{root}_h_adv", root, "H Scene — Adv (高级)", 2

    m_400 = re.match(r"role/400(\d{2})(?:/stand)?$", rel)
    if m_400:
        hid = 10000 + int(m_400.group(1))
        root = f"hero_{hid}"
        return f"{root}_interaction", root, "Interaction (调教)", 3

    m_z = re.match(r"role/z100(\d{2})(_h)?/(00|aim|cover|skill|skillcut)$", rel)
    if m_z:
        hid = 10000 + int(m_z.group(1))
        is_h = bool(m_z.group(2))
        sub = m_z.group(3)
        root = f"hero_{hid}"
        if sub == "00":
            return root, root, "Utama", 0
        if sub == "aim":
            return f"{root}_aim", root, "Aim", 10
        if sub == "cover":
            return f"{root}_cover", root, "Cover", 11
        if sub == "skill":
            return f"{root}_skill", root, "Skill Cut", 12
        if sub == "skillcut":
            if hid == 10013 and not is_h:
                return f"{root}_skillcut", root, "Skill Cut 2", 13
            return f"{root}_skill", root, "Skill Cut", 12

    fallback = re.sub(r"[^0-9A-Za-z._-]", "_", rel)
    return fallback, fallback, "Utama", 0


def referenced_pages(atlas_text: str) -> list[str]:
    out = []
    for line in atlas_text.splitlines():
        s = line.strip()
        if not s or line.startswith(" "):
            continue
        if s.lower().endswith((".png", ".webp", ".jpg", ".jpeg")):
            if s not in out:
                out.append(s)
    return out


def extract_models(bundle_paths: dict[str, Path], limit: int = 0,
                   force: bool = False) -> tuple[dict[str, dict], dict]:
    spine_bundles = [p for k, p in sorted(bundle_paths.items()) if k.startswith("Spine/")]
    by_dir: dict[str, dict] = collections.defaultdict(lambda: {"skels": [], "atlases": [], "texs": []})

    for bp in spine_bundles:
        env = UnityPy.load(str(bp))
        pid_to_path = {obj.path_id: path_str for path_str, obj in env.container.items()}
        for o in env.objects:
            cpath = pid_to_path.get(o.path_id) or getattr(o, "container", "") or ""
            if not cpath:
                continue
            cdir = os.path.dirname(cpath)
            fname = os.path.basename(cpath)
            if o.type.name == "TextAsset":
                nm, data = parse_text_asset(o.get_raw_data())
                if fname.endswith((".skel.bytes", ".skel", ".json")):
                    by_dir[cdir]["skels"].append((fname, nm, data))
                elif fname.endswith((".atlas.txt", ".atlas")):
                    by_dir[cdir]["atlases"].append((fname, nm, data))
            elif o.type.name == "Texture2D":
                by_dir[cdir]["texs"].append((fname, o))

    valid_dirs = [
        (cdir, info) for cdir, info in sorted(by_dir.items())
        if info["skels"] and info["atlases"] and info["texs"]
    ]
    if limit:
        valid_dirs = valid_dirs[:limit]

    OUT_MODELS.mkdir(parents=True, exist_ok=True)
    counts = {"skip": 0, "extracted": 0, "fail": 0}
    extracted_meta: dict[str, dict] = {}

    for cdir, info in valid_dirs:
        rel = cdir.replace("assets/gamemain/spine/", "")
        slug, root_slug, lbl, order = slug_for(rel)
        dest = OUT_MODELS / slug

        sfname, snm, sbytes = info["skels"][0]
        _, anm, abytes_raw = info["atlases"][0]
        # Hapus BOM UTF-8 dari .atlas (mis. c010_00.atlas)
        atlas_text = abytes_raw.decode("utf-8-sig", "replace")
        abytes = atlas_text.encode("utf-8")
        pages = referenced_pages(atlas_text)

        is_json = sfname.lower().endswith(".json") or sbytes.lstrip().startswith(b"{")
        ext = ".json" if is_json else ".skel"
        stem = slug
        skel_file = dest / f"{stem}{ext}"
        atlas_file = dest / f"{stem}.atlas"

        extracted_meta[slug] = {
            "rel": rel,
            "slug": slug,
            "root": root_slug,
            "label": lbl,
            "order": order,
        }

        if (
            not force
            and skel_file.is_file()
            and atlas_file.is_file()
            and pages
            and all((dest / pg).is_file() for pg in pages)
        ):
            counts["skip"] += 1
            continue

        dest.mkdir(parents=True, exist_ok=True)
        skel_file.write_bytes(sbytes)
        atlas_file.write_bytes(abytes)
        for tfname, tobj in info["texs"]:
            d = tobj.read()
            tname = getattr(d, "m_Name", "") or os.path.splitext(tfname)[0]
            out_png = tname if tname.lower().endswith(".png") else f"{tname}.png"
            d.image.save(str(dest / out_png))
        counts["extracted"] += 1

    return extracted_meta, counts


def extract_thumbs(hero_atlas_bundle: Path, extracted_meta: dict[str, dict],
                   pets_info: dict[str, dict]) -> tuple[int, dict[str, str]]:
    THUMBS.mkdir(parents=True, exist_ok=True)
    ffmpeg = shutil.which("ffmpeg") or "/usr/bin/ffmpeg"
    env = UnityPy.load(str(hero_atlas_bundle))
    sprites: dict[str, Any] = {}
    for o in env.objects:
        if o.type.name == "Sprite":
            d = o.read()
            nm = getattr(d, "m_Name", "")
            r = getattr(d, "m_Rect", None)
            w = int(r.width) if r else 0
            # Kalau nama duplikat (head_1_1 100x100 vs 95x96), pilih yang lebih besar
            if nm not in sprites or w >= 100:
                sprites[nm] = d

    def ensure_webp(sprite_name: str) -> str | None:
        if sprite_name not in sprites:
            return None
        out_name = f"{sprite_name}.webp"
        out_path = THUMBS / out_name
        if out_path.is_file() and out_path.stat().st_size > 128:
            return out_name
        fd, tmp_png = tempfile.mkstemp(prefix="eroth-", suffix=".png")
        os.close(fd)
        try:
            sprites[sprite_name].image.save(tmp_png)
            subprocess.run(
                [ffmpeg, "-y", "-loglevel", "error", "-i", tmp_png,
                 "-c:v", "libwebp", "-lossless", "0", "-q:v", "88", str(out_path)],
                check=True, timeout=30,
            )
            return out_name if out_path.is_file() else None
        finally:
            if os.path.exists(tmp_png):
                os.unlink(tmp_png)

    manifest: dict[str, str] = {}
    for slug, info in sorted(extracted_meta.items()):
        mid = f"eroera/{slug}"
        root = info["root"]
        if root.startswith("hero_"):
            num = int(root.split("_")[1]) - 10000
            if slug.endswith(("_h_adv", "_interaction")):
                cands = [f"card_{num}_3", f"card_{num}_2", f"card_{num}_1"]
            elif slug.endswith("_h_base") or "_act_" in slug:
                cands = [f"card_{num}_2", f"card_{num}_1"]
            else:
                cands = [f"card_{num}_1"]
            for c in cands:
                w = ensure_webp(c)
                if w:
                    manifest[mid] = w
                    break
        elif root.startswith("pet_"):
            pinfo = pets_info.get(root) or {}
            for c in (pinfo.get("card"), pinfo.get("head")):
                if c:
                    w = ensure_webp(c)
                    if w:
                        manifest[mid] = w
                        break

    (THUMBS / "_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=1, sort_keys=True),
        encoding="utf-8",
    )
    webp_files = sum(1 for f in THUMBS.iterdir() if f.is_file() and f.suffix == ".webp")
    return webp_files, manifest


def ensure_game_icon() -> bool:
    if GAME_ICON.is_file() and GAME_ICON.stat().st_size > 256:
        return True
    try:
        raw = http_get(GAME_ICON_URL, timeout=30)
        GAME_ICON.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix="eroicon-", suffix=".png")
        os.close(fd)
        try:
            Path(tmp).write_bytes(raw)
            ffmpeg = shutil.which("ffmpeg") or "/usr/bin/ffmpeg"
            subprocess.run(
                [ffmpeg, "-y", "-loglevel", "error", "-i", tmp,
                 "-vf", "scale=128:128:force_original_aspect_ratio=decrease",
                 str(GAME_ICON)],
                check=True, timeout=30,
            )
            return GAME_ICON.is_file()
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)
    except Exception:  # noqa: BLE001
        return False


def build_names_and_families(extracted_meta: dict[str, dict],
                             heroes: dict[int, str],
                             pets: dict[str, dict],
                             ver_info: dict,
                             sig: str) -> dict:
    by_root: dict[str, list[dict]] = collections.defaultdict(list)
    for slug, info in extracted_meta.items():
        by_root[info["root"]].append(info)

    extra_names = {
        "role_c010": "拉毗 (c010)",
        "role_t001": "特战队员 T001",
        "role_t002": "特战队员 T002",
    }

    models_meta: dict[str, dict] = {}
    families_meta: list[dict] = []

    for root_slug in sorted(by_root.keys()):
        items = sorted(by_root[root_slug], key=lambda x: (x["order"], x["slug"]))
        if root_slug.startswith("hero_"):
            hid = int(root_slug.split("_")[1])
            cname = heroes.get(hid, root_slug)
            card_title = f"{cname} ({hid})"
            cat = "Hero"
        elif root_slug.startswith("pet_"):
            pinfo = pets.get(root_slug) or {}
            cname = " / ".join(pinfo.get("names") or [root_slug])
            card_title = f"Pet · {cname} ({root_slug.removeprefix('pet_')})"
            cat = "Pet"
        else:
            cname = extra_names.get(root_slug, root_slug)
            card_title = cname
            cat = "Extra"

        members = []
        for idx, it in enumerate(items):
            mid = f"eroera/{it['slug']}"
            lbl = "Utama" if idx == 0 else it["label"]
            members.append({"id": mid, "label": lbl})
            models_meta[mid] = {
                "name": card_title if idx == 0 else f"{cname} — {lbl}",
                "label": lbl,
                "character": {
                    "name": cname,
                    "title": card_title,
                    "category": cat,
                    "variant": None if idx == 0 else lbl,
                    "squad": f"{cat} · {root_slug}",
                    "source": "youdianse.com/game/detail/456",
                },
            }

        families_meta.append({
            "root": f"eroera/{root_slug}",
            "name": card_title,
            "category": cat,
            "members": members,
        })

    return {
        "source": YOUDIANSE_URL,
        "gameVersion": ver_info.get("LatestGameVersion"),
        "resourceVersion": ver_info.get("InternalResourceVersion"),
        "sig": sig,
        "families": families_meta,
        "models": models_meta,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    t0 = time.time()
    log("Memeriksa Version.txt & GameFrameworkVersion untuk 欲洛降临 (EroEra)…")
    ver_info, gfu, sig = fetch_catalog()
    log(
        f"Versi {ver_info.get('LatestGameVersion')} (res v{ver_info.get('InternalResourceVersion')}) · "
        f"{len(gfu['resources'])} resource · sig={sig}"
    )

    bundle_paths, dl_bundles = sync_bundles(ver_info, gfu["resources"])
    log(f"Bundle tersinkron: {len(bundle_paths)} berkas (unduh baru: {dl_bundles})")

    heroes, pets = load_luban_names(bundle_paths["TbData/TbDatas"])
    extracted_meta, m_counts = extract_models(bundle_paths, limit=args.limit, force=args.force)
    log(f"Model Spine: {len(extracted_meta)} model (extracted={m_counts['extracted']}, skip={m_counts['skip']})")

    if args.limit:
        print(json.dumps({
            "ok": True,
            "limit": args.limit,
            "models": m_counts,
        }, indent=1))
        return 0

    names_payload = build_names_and_families(extracted_meta, heroes, pets, ver_info, sig)
    (OUT_MODELS / "_names.json").write_text(
        json.dumps(names_payload, ensure_ascii=False, indent=1),
        encoding="utf-8",
    )
    thumb_files, manifest = extract_thumbs(bundle_paths["SpriteAtlas/Packs/Hero"], extracted_meta, pets)
    ensure_game_icon()

    res = {
        "ok": True,
        "sig": sig,
        "gameVersion": ver_info.get("LatestGameVersion"),
        "resourceVersion": ver_info.get("InternalResourceVersion"),
        "bundles": len(bundle_paths),
        "bundlesDownloaded": dl_bundles,
        "models": m_counts,
        "totalModels": len(extracted_meta),
        "roots": len(names_payload["families"]),
        "heroes": len(heroes),
        "pets": len(pets),
        "thumbFiles": thumb_files,
        "manifestEntries": len(manifest),
        "seconds": round(time.time() - t0, 1),
    }
    print(json.dumps(res, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
