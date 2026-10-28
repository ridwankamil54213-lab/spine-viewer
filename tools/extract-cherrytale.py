#!/usr/bin/env python3
"""Unduh dan ekstrak model Spine dari Cherry Tale (88kongque).

Sumber
    https://pfdd.88kongque.com/patch/files/index.txt.<md5>
    isinya JSON: {"<nama aset>": [ukuran, "<md5>"], ...}
    Berkas diunduh dari  <BASE>/<nama aset>.<md5>

    Ini menggantikan bundleMap.txt lama ("assetID|bundleName") yang sudah
    tidak dipakai server. Nama aset di index sudah memuat path-nya; prefiks
    "assets/" ditambahkan saat menyimpan.

Dekripsi (bundle UnityFS 2018.3.5f1)
    Bundle dari CDN ini diacak, bukan dienkripsi betulan. Resepnya
    (violet-wdream/.Scripts Games/CherryTale/CherryTaleDecrypt.py):

      1. tukar bytes[i] <-> bytes[len-i] untuk i di {0x3FB, 0xD99, 0x197C}
      2. tiap kemunculan b"2018.3.5f1\\0" diganti b"2020.3.41f1\\0"

    Langkah 1 memperbaiki dua field ukuran di header dan satu byte di blok
    info; langkah 2 membuat UnityPy memakai aturan flag versi baru. Setelah
    keduanya, UnityPy membaca bundle apa adanya. Lihat decrypt().

    CATATAN: komentar lama di berkas ini menyebut bundle CDN "tidak perlu
    didekripsi". Itu keliru untuk index saat ini — tanpa langkah di atas
    UnityPy gagal dengan "corrupt input" / "signed integer too large".

Jebakan: berkas ganda dalam satu bundle
    Satu bundle bisa memuat beberapa TextAsset/Texture2D dengan NAMA SAMA
    (li02_01_CG.skel 426 KB dan 2,8 KB; atlas 119 B dan 2,7 KB). Mengambil
    yang pertama menyimpan yang kecil, padahal atlas menunjuk koordinat versi
    besar — model tampil sebagai pecahan acak. Karena itu yang disimpan
    adalah yang PALING BESAR per nama, untuk teks maupun tekstur.

Pemakaian
    /srv/venv-spine/bin/python tools/extract-cherrytale.py
    /srv/venv-spine/bin/python tools/extract-cherrytale.py --limit 20
    /srv/venv-spine/bin/python tools/extract-cherrytale.py --only cg_dynamic
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.request

import UnityPy

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

BASE_URL = os.environ.get("BASE_URL", "https://pfdd.88kongque.com/patch/files/")
INDEX_NAME = os.environ.get(
    "INDEX_NAME", "index.txt.fbc81bb7c77e26c039879795b68ff239")
CACHE = os.environ.get("CACHE", os.path.join(ROOT, "cache", "cherrytale"))
OUT = os.environ.get("OUT", os.path.join(ROOT, "assets", "cherrytale"))

UA = "UnityPlayer/2020.3.41f1 (UnityWebRequest/1.0, libcurl/8.5.0-DEV)"

SWAP_OFFSETS = (0x3FB, 0xD99, 0x197C)
ENC_VER = b"2018.3.5f1\x00"
DEC_VER = b"2020.3.41f1\x00"

TEXT_ASSET = 49
TEXTURE2D = 28


def log(m):
    sys.stderr.write("[%s] %s\n" % (time.strftime("%H:%M:%S"), m))
    sys.stderr.flush()


# --------------------------------------------------------------------------
# dekripsi
# --------------------------------------------------------------------------
def decrypt(data: bytes) -> bytes:
    """Resep CherryTaleDecrypt.py: tukar 3 byte cermin + ganti versi."""
    buf = bytearray(data)
    n = len(buf)
    for idx in SWAP_OFFSETS:
        if idx < n:
            ridx = n - idx
            buf[idx], buf[ridx] = buf[ridx], buf[idx]

    out = bytearray()
    off = 0
    while True:
        i = buf.find(ENC_VER, off)
        if i == -1:
            out += buf[off:]
            break
        out += buf[off:i]
        out += DEC_VER
        # DEC_VER is one byte longer than ENC_VER (12 vs 11 with the NUL), so
        # skip one extra byte to keep every following field on its original
        # offset. This is the "+1" in CherryTaleDecrypt.py; without it the
        # i64 size field shifts and UnityPy reports "signed integer is greater
        # than maximum". That byte is a spare NUL in the header.
        off = i + len(ENC_VER) + 1
    return bytes(out)


# --------------------------------------------------------------------------
# index / unduh
# --------------------------------------------------------------------------
def fetch(name: str, dest: str) -> bool:
    if os.path.exists(dest) and os.path.getsize(dest) > 1024:
        return True
    req = urllib.request.Request(BASE_URL + name, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=300) as r:
        data = r.read()
    d = os.path.dirname(dest)
    if d:
        os.makedirs(d, exist_ok=True)
    with open(dest, "wb") as f:
        f.write(data)
    return True


def load_index() -> dict:
    path = os.path.join(CACHE, "index.txt")
    if not os.path.exists(path) or os.path.getsize(path) < 1024:
        log("unduh index")
        fetch(INDEX_NAME, path)
    with open(path, encoding="utf-8") as f:
        return json.load(f)


# --------------------------------------------------------------------------
# ekstraksi
# --------------------------------------------------------------------------
def safe(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "_", str(name)).strip("_")


def model_dirname(name: str) -> str:
    """Nama folder model: buang prefiks panjang supaya enak dibaca.

    Nama di index memuat path lengkap, mis.

        assets_resources_honly_baseassets_uiprefabs_simpleprefab_img_cg_dynamic_e004_02_teaching_cg_spine

    Kalau dipakai apa adanya, folder jadi 15 tingkat -- melewati batas
    kedalaman pemindai (8) sehingga model tak muncul di viewer. Yang dipakai
    hanya bagian ekornya, satu tingkat per model:

        cherrytale/img_cg_dynamic_e004_02_teaching_cg_spine
    """
    stem = name
    for prefix in ("assets_resources_",):
        if stem.lower().startswith(prefix):
            stem = stem[len(prefix):]
            break
    i = stem.lower().find("baseassets_")
    if i >= 0:
        stem = stem[i + len("baseassets_"):]
    for junk in ("uiprefabs_simpleprefab_", "uiprefabs_", "simpleprefab_"):
        if stem.lower().startswith(junk):
            stem = stem[len(junk):]
            break
    return stem or name


def extract(bundle_bytes: bytes, out_root: str, asset_name: str) -> tuple[str, int]:
    try:
        env = UnityPy.load(bundle_bytes)
    except Exception:
        return "parse-gagal", 0

    texts: dict[str, str] = {}
    textures: dict[str, object] = {}
    for obj in env.objects:
        try:
            t = str(obj.type)
        except Exception:
            continue
        if t == str(TEXT_ASSET):
            try:
                r = obj.read()
                nm = getattr(r, "m_Name", None)
                s = r.m_Script
                if not nm or s is None:
                    continue
                if isinstance(s, bytes):
                    s = s.decode("latin-1")
                key = safe(nm)
                if key not in texts or len(s) > len(texts[key]):
                    texts[key] = s
            except Exception:
                continue
        elif t == str(TEXTURE2D):
            try:
                r = obj.read()
                nm = getattr(r, "m_Name", None)
                if not nm:
                    continue
                key = safe(nm)
                prev = textures.get(key)
                if prev is None:
                    textures[key] = r
                else:
                    try:
                        if (r.m_Width * r.m_Height) > (prev.m_Width * prev.m_Height):
                            textures[key] = r
                    except Exception:
                        pass
            except Exception:
                continue

    if not texts:
        return "tanpa-teks", 0

    atlas_key = next((k for k in texts if k.lower().endswith(".atlas")), None)
    stem = safe(os.path.splitext(atlas_key)[0]) if atlas_key else safe(sorted(texts)[0])
    if not stem:
        return "nama-kosong", 0

    model_dir = os.path.join(out_root, model_dirname(asset_name))
    os.makedirs(model_dir, exist_ok=True)
    written = 0

    for key, s in texts.items():
        low = key.lower()
        if low.endswith(".atlas"):
            open(os.path.join(model_dir, stem + ".atlas"), "w", encoding="utf-8").write(s)
        elif low.endswith(".skel"):
            # m_Script is a str that UnityPy decoded with surrogateescape, so it
            # must be encoded back the same way -- a binary .skel is not text
            # and latin-1 chokes on the surrogate code points.
            open(os.path.join(model_dir, stem + ".skel"), "wb").write(
                s.encode("utf-8", "surrogateescape"))
        elif low.endswith(".json") or s.lstrip().startswith("{"):
            open(os.path.join(model_dir, stem + ".json"), "w", encoding="utf-8").write(s)
        else:
            continue
        written += 1

    # simpan hanya halaman tekstur yang disebut atlas
    atlas_txt = texts.get(atlas_key or "", "")
    for line in atlas_txt.splitlines():
        s = line.strip()
        if not s or s.startswith(("size:", "format:", "filter:", "repeat:",
                                  "pma:", "scale:")):
            continue
        if re.search(r"\.(png|jpg|jpeg)$", s, re.I):
            page = safe(os.path.splitext(os.path.basename(s))[0])
            tex = textures.get(page)
            if tex is None:
                continue
            try:
                tex.image.save(os.path.join(model_dir, page + ".png"))
                written += 1
            except Exception:
                continue

    return ("ok" if written else "kosong"), written


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--only", default="spine",
                    help="saring nama aset (default: spine)")
    ap.add_argument("--skip", default="",
                    help="buang nama aset yang memuat teks ini (mis. _gacha_)")
    ap.add_argument("--out", default=OUT)
    ap.add_argument("--resume", action="store_true",
                    help="lewati model yang direktorinya sudah ada")
    args = ap.parse_args()

    idx = load_index()
    names = sorted(k for k in idx if args.only.lower() in k.lower())
    if args.skip:
        names = [n for n in names if args.skip.lower() not in n.lower()]
    log("index %d entri, %d cocok dengan %r" % (len(idx), len(names), args.only))
    os.makedirs(CACHE, exist_ok=True)
    os.makedirs(args.out, exist_ok=True)

    # --resume: lewati bundle yang direktorinya sudah ada. Ekstraksi 620 bundle
    # butuh ~15 menit dan pernah mati di tengah (tanpa error di log), jadi
    # menjalankan ulang tanpa ini berarti mengulang dari nol.
    if args.resume:
        before = len(names)
        names = [n for n in names
                 if not os.path.isdir(os.path.join(args.out, model_dirname(n)))]
        log("resume: %d sudah ada, %d tersisa" % (before - len(names), len(names)))

    # --limit dipotong SETELAH resume, kalau tidak tiap putaran memeriksa
    # N model pertama yang sudah ada semua dan tidak pernah maju.
    if args.limit:
        names = names[:args.limit]

    stats: dict[str, int] = {}
    files = 0
    for i, name in enumerate(names, 1):
        entry = idx[name]
        tmp = os.path.join(CACHE, safe(name) + ".bundle")
        try:
            fetch("%s.%s" % (name, entry[1]), tmp)
        except Exception:
            stats["unduh-gagal"] = stats.get("unduh-gagal", 0) + 1
            continue
        try:
            raw = open(tmp, "rb").read()
            status, n = extract(decrypt(raw), args.out, name)
        except Exception as e:
            status, n = "gagal", 0
            log("  GAGAL %s: %s" % (name, str(e)[:120]))
        finally:
            try:
                os.remove(tmp)
            except Exception:
                pass
        stats[status] = stats.get(status, 0) + 1
        files += n
        if i % 10 == 0 or i == len(names):
            log("  %d/%d berkas=%d %s" % (i, len(names), files, stats))

    log("selesai: %d berkas, %s" % (files, stats))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
