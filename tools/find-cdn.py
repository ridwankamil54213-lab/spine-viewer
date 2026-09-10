#!/usr/bin/env python3
"""Temukan endpoint CDN aset dari sebuah APK Unity/IL2CPP.

Tool ini TIDAK mengunduh dan TIDAK mengekstrak aset. Ia hanya menjawab satu
pertanyaan: "game ini ambil asetnya dari mana?" — supaya kita tahu host dan
pola path yang harus dijadikan target extractor/downloader.

Kenapa perlu tool sendiri
-------------------------
Endpoint aset hampir tidak pernah tertulis sebagai URL utuh di satu tempat.
Biasanya tersebar dalam empat bentuk, dan masing-masing butuh penanganan
berbeda:

1. **Addressables** (`assets/aa/settings.json`, `catalog.json`)
   `settings.json` sering berisi *placeholder*, bukan host sungguhan:
       http://10.100.5.199:HostingServicePort/catalog_1.0.0.hash
   `10.100.5.199` dan `HostingServicePort` adalah token yang Unity ganti saat
   runtime lewat profile. Jadi URL ini tidak bisa di-fetch apa adanya — tapi
   keberadaannya memberitahu kita game ini pakai Addressables dan pola path
   katalognya (`catalog_<version>.hash` / `catalog.json`).
   Katalognya sendiri (`catalog.json`, sering beberapa MB) berisi internal id
   per bundle, sering juga placeholder — path-nya yang berguna.

2. **DEX** (`classes*.dex`)
   String konfigurasi Java/Kotlin: base URL API, host CDN, nama bucket.
   Di sinilah host yang *bisa dipakai* biasanya berada.

3. **IL2CPP** (`lib/*/libil2cpp.so`)
   Kode game yang di-compile. Banyak URL di sini, tapi juga sangat banyak
   noise: string HTML/CSS dari parser bawaan Unity ("http://encoding=",
   "http://www.w3.org/..."). Tanpa filter, hasilnya tidak bisa dipakai.

4. **AssetBundle / UnityFS**
   Beberapa game menaruh config di dalam bundle, bukan di APK.

Yang dilakukan tool ini
-----------------------
- Scan keempat sumber di atas (plus `res/`, `boot.config`, file `.json`/`.xml`
  di `assets/`, dan `META-INF/`).
- Kumpulkan URL, host, dan host "mentah" (tanpa skema) yang tampak seperti
  endpoint aset.
- Saring noise: namespace XML, URL library standar, string HTML/CSS,
  placeholder build (`10.x.x.x`, `localhost`, `example.com`, `{...}`).
- **Verifikasi**: HEAD/GET tiap kandidat host untuk melapor mana yang benar-
  benar merespons. Ini yang membedakan "string yang mirip URL" dari "endpoint
  yang nyata".
- Kalau ada katalog Addressables, ikut cetak contoh entry bundle supaya pola
  path-nya kelihatan.

Keluaran
--------
Tiga bagian:
  A. Kandidat endpoint (dikelompokkan: terferivikasi / merespons / placeholder / mentah)
  B. Path aset contoh dari katalog Addressables
  C. Endpoint yang sudah dikenal dari extractor lain di tools/ (kalau ada)

Pemakaian
---------
    /srv/venv-spine/bin/python tools/find-cdn.py <apk> [<apk> ...]
    /srv/venv-spine/bin/python tools/find-cdn.py game.apk --no-verify   # skip HTTP
    /srv/venv-spine/bin/python tools/find-cdn.py game.apk --json out.json

Catatan: verifikasi butuh jaringan. Kalau mesinnya tidak bisa keluar, pakai
`--no-verify` — hasil scan statis tetap berguna.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import re
import sys
import urllib.request
import urllib.error
import zipfile
from collections import defaultdict

# ---------------------------------------------------------------- noise ----

# Namespace XML dan URL standar library. Selalu muncul, tidak pernah endpoint.
NS_NOISE = (
    "schemas.android.com", "schemas.microsoft.com", "www.w3.org",
    "ns.adobe.com", "xml.org", "java.sun.com", "javax.xml",
    "schemas.xmlsoap.org", "www.xml.org", "relaxng.org",
    "docbook.org", "schemas.openxmlformats.org", "purl.org",
    "www.unicode.org", "www.ietf.org", "tools.ietf.org",
    "maven.apache.org", "gradle.org", "junit.org",
    "bouncycastle.org", "www.sqlite.org", "www.gnu.org",
    "www.apache.org", "xmlns.com", "schemas.google.com",
    "schemas.microsoft.com", "go.microsoft.com", "www.google.com",
)

# Pola yang hampir pasti string HTML/CSS/JS dari engine, bukan endpoint.
HTML_NOISE = re.compile(
    r"(encoding=|style=|text-align|font-weight|<div|dtd|doctype|"
    r"w3c|css|html4|loose|strict|frameset|adobe|"
    r"UA-Compatible|X-UA|description|keywords|addEventListener|"
    r"margin-top|text-decoration|background-color|float:|"
    r"http://www\.[a-z]+$|http://[a-z]+$|"           # "http://www.css"
    r"^[a-z]+$)",                                    # host tunggal sisa potong
    re.I,
)

# Placeholder build-time: hostnya belum diisi saat APK dibuat.
PLACEHOLDER = re.compile(
    r"(^\{|\{$|HostingServicePort|UnityEngine\.|10\.\d+\.\d+\.\d+|"
    r"127\.0\.0\.1|localhost|0\.0\.0\.0|example\.(com|org)|"
    r"your[_-]?(server|host|domain)|placeholder|"
    r"%%|\$\{|<[a-z_]+>)",
    re.I,
)

# Ekstensi aset — dipakai untuk menandai URL yang *jelas* endpoint aset.
ASSET_EXT = re.compile(
    r"\.(bundle|assetbundle|unity3d|ab|apk|obb|zip|json|hash|"
    r"skel|atlas|png|jpg|webp|moc3|model3?|bin|dat|pak|txt|csv)(\?|$)",
    re.I,
)

# Kata kunci yang sering menandai host CDN bila tidak ada ekstensi aset.
CDN_HINT = re.compile(
    r"(cdn|static|asset|patch|res(ource)?|download|bundle|hotfix|"
    r"update|file|game|media|patch|pkg|data)[-.\d]",
    re.I,
)

# Host yang nyaris pasti CDN walau namanya acak (hash subdomain).
# Unity/Addressables dan banyak game Cina memakai ini: subdomain acak di
# atas domain CDN papan atas — tidak ada kata kunci di namanya, jadi
# CDN_HINT tidak akan pernah cocok.
KNOWN_CDN = (
    "cloudfront.net", "akamai", "akamaized.net", "cloudflare",
    "fastly", "fastlylb.net", "cdn77", "jsdelivr", "unpkg",
    "myqcloud.com", "qcloud", "aliyuncs.com", "aliyuncdn",
    "qiniu", "qiniudn", "qbox.me", "clouddn.com",
    "upyun", "b-cdn.net", "hwcdn.net", "azureedge.net",
    "googleapis.com", "gstatic.com", "storage.googleapis.com",
    "amazonaws.com", "s3.", "cloudfront",
    "byteimg.com", "bdydns", "ksyun", "wangsu", "chinacache",
    "tl88.cyou", "pddpic", "gtimg.com", "tenpay",
)

# URL yang jelas bukan endpoint aset walau host-nya terkenal.
# (mis. dokumentasi library, OAuth, analytics)
NEVER_ASSET = re.compile(
    r"(/docs?/|/reference/|/api/|oauth|/auth|/login|/token|"
    r"analytics|adjust|appsflyer|firebase|sentry|crash|"
    r"\.wikipedia|\.gnu\.org|\.apache\.org|googlesource|"
    r"bug|bugtracker|/bugs|github\.com|gitlab|stackoverflow)",
    re.I,
)

URL_RE = re.compile(rb"https?://[\x21-\x7e]{4,}")
# Host tanpa skema: dipakai banyak config JSON ("host": "cdn.foo.com").
BARE_HOST_RE = re.compile(
    rb"(?<![A-Za-z0-9._-])((?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+"
    rb"(?:com|net|org|io|co|cc|xyz|dev|app|game|cn|jp|kr|tw|hk|sg|ru|"
    rb"cloud|top|site|online|fun|live|store|tech|info|biz|me|tv)"
    rb"(?::\d{1,5})?)(?![A-Za-z0-9._-])",
    re.I,
)

UA = "UnityPlayer/2022.3.28f1 (UnityWebRequest/1.0, libcurl/8.5.0-DEV)"


# ------------------------------------------------------------- helpers ----

def decode(b: bytes) -> str:
    return b.decode("ascii", "replace").rstrip(".,;\"'<>)]}\\" + "' ")


def host_of(url: str) -> str:
    m = re.match(r"https?://([^/:?#]+)(?::(\d+))?", url)
    return m.group(1).lower() if m else ""


def looks_like_noise(url: str) -> bool:
    """True kalau URL ini jelas-jelas bukan endpoint aset."""
    h = host_of(url)
    if not h or "." not in h:
        return True
    if any(n in h for n in NS_NOISE):
        return True
    if HTML_NOISE.search(url):
        return True
    # Host tanpa TITIK di path dan tanpa hint CDN -> kemungkinan potongan string.
    return False


def classify(url: str) -> str:
    """placeholder | asset | cdn | other"""
    if PLACEHOLDER.search(url):
        return "placeholder"
    h = host_of(url)
    # Host CDN papan atas dideteksi duluan: subdomain-nya acak (hash), jadi
    # CDN_HINT tidak akan cocok, padahal ini justru kandidat terkuat.
    if any(k in h for k in KNOWN_CDN):
        if NEVER_ASSET.search(url):
            return "other"
        return "asset"
    if NEVER_ASSET.search(url):
        return "other"
    if ASSET_EXT.search(url):
        return "asset"
    if CDN_HINT.search(h) or CDN_HINT.search(url):
        return "cdn"
    return "other"


def strings_blob(data: bytes, minlen: int = 10):
    """Ambil string ASCII printable dari blob biner."""
    return re.findall(rb"[\x20-\x7e]{%d,}" % minlen, data)


# --------------------------------------------------------------- scan ----

def scan_apk(path: str) -> dict:
    """Kumpulkan kandidat URL dari satu APK. Tidak ada I/O jaringan."""
    hits: dict[str, set[str]] = defaultdict(set)   # url -> {sumber}
    addr: list[dict] = []                          # info Addressables
    notes: list[str] = []

    try:
        z = zipfile.ZipFile(path)
    except Exception as e:
        return {"path": path, "error": str(e), "hits": {}, "addressables": [],
                "notes": []}

    names = z.namelist()
    base = os.path.basename(path)

    # --- file yang wajar di-scan utuh (kecil, teks/konfigurasi) ---------
    TEXTISH = (
        ".json", ".xml", ".txt", ".config", ".cfg", ".ini", ".properties",
        ".yaml", ".yml", ".csv", ".js", ".plist", ".bytes",
    )

    for n in names:
        low = n.lower()
        if z.getinfo(n).is_dir():
            continue
        textish = low.endswith(TEXTISH) or "catalog" in low or "settings" in low

        # Batasi: file besar tetap di-scan tapi cuma sebagian awal.
        try:
            size = z.getinfo(n).file_size
        except Exception:
            continue

        # DEX / IL2CPP / bundle: selalu scan, tapi potong yang sangat besar.
        is_dex = low.endswith(".dex")
        is_native = low.endswith(".so")
        is_bundle = ".bundle" in low
        cap = None
        if is_native or is_bundle:
            cap = 60 * 1024 * 1024
        elif is_dex:
            cap = size
        elif textish:
            cap = 8 * 1024 * 1024
        if cap is None:
            continue
        if size > cap and not is_dex and not textish:
            continue

        try:
            with z.open(n) as f:
                data = f.read(cap)
        except Exception:
            continue

        src = os.path.basename(n) or n

        for m in URL_RE.findall(data):
            u = decode(m)
            if not looks_like_noise(u):
                hits[u].add(src)
        for s in strings_blob(data):
            for m in URL_RE.findall(s):
                u = decode(m)
                if not looks_like_noise(u):
                    hits[u].add(src)

        # Host tanpa skema — hanya dari file teks (di .so terlalu banyak noise)
        if textish and size < 2 * 1024 * 1024:
            for m in BARE_HOST_RE.findall(data):
                h = decode(m)
                if not h or any(x in h for x in NS_NOISE):
                    continue
                if h.startswith(("schemas.", "www.w3", "ns.", "java.", "javax.")):
                    continue
                hits["//" + h].add(src)

    # --- Addressables --------------------------------------------------
    for cand in ("assets/aa/settings.json", "assets/aa/catalog.json"):
        if cand in names:
            try:
                raw = z.read(cand)
                addr.append(probe_addressables(cand, raw))
            except Exception as e:
                notes.append(f"{cand}: gagal dibaca ({e})")

    return {"path": path, "hits": {k: sorted(v) for k, v in hits.items()},
            "addressables": addr, "notes": notes}


def probe_addressables(name: str, raw: bytes) -> dict:
    """Ambil info kunci dari settings.json / catalog.json Addressables."""
    info = {"file": name, "size": len(raw), "remote_urls": [],
            "placeholder": False, "sample_bundles": []}
    try:
        txt = raw.decode("utf8", "replace")
    except Exception:
        return info
    if name.endswith("settings.json"):
        try:
            doc = json.loads(txt)
        except Exception:
            return info
        for loc in doc.get("m_CatalogLocations", []):
            iid = loc.get("m_InternalId", "")
            if isinstance(iid, str) and iid.startswith("http"):
                info["remote_urls"].append(iid)
                if PLACEHOLDER.search(iid):
                    info["placeholder"] = True
        prof = doc.get("m_ProfileVariables") or doc.get("m_SettingsHash")
        if prof:
            info["hash"] = doc.get("m_SettingsHash")
    elif name.endswith("catalog.json"):
        try:
            doc = json.loads(txt)
        except Exception:
            # Katalog kadang bukan JSON murni; cari internal id lewat regex.
            info["sample_bundles"] = [
                decode(m) for m in
                re.findall(rb'"m_InternalId"\s*:\s*"([^"]{10,200})"', raw)
                if b"http" in m or b".bundle" in m
            ][:12]
            return info
        for loc in (doc.get("m_Locations") or []):
            for iid in (loc.get("m_InternalId") or []) if isinstance(loc.get("m_InternalId"), list) else [loc.get("m_InternalId")]:
                if isinstance(iid, str) and (".bundle" in iid or iid.startswith("http")):
                    info["sample_bundles"].append(iid)
            if len(info["sample_bundles"]) >= 12:
                break
        info["total_locations"] = len(doc.get("m_Locations") or [])
        ids = doc.get("m_InternalIds") or []
        if ids:
            b = [i for i in ids if isinstance(i, str) and ".bundle" in i]
            info["total_bundles"] = len(b)
            if not info["sample_bundles"]:
                info["sample_bundles"] = b[:12]
    return info


# ------------------------------------------------------------ verify ----

def probe(url: str, timeout: int = 12) -> dict:
    """HEAD lalu GET range kecil. Tidak mengunduh isi."""
    out = {"url": url, "ok": False, "status": None, "ctype": None,
           "len": None, "err": None}
    for method, headers in (("HEAD", {}), ("GET", {"Range": "bytes=0-255"})):
        try:
            req = urllib.request.Request(url, headers={**headers,
                                                       "User-Agent": UA},
                                         method=method)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                out.update(ok=True, status=r.status,
                           ctype=(r.headers.get("Content-Type") or "").split(";")[0],
                           len=r.headers.get("Content-Length"))
                return out
        except urllib.error.HTTPError as e:
            out.update(status=e.code,
                       ctype=(e.headers.get("Content-Type") or "").split(";")[0] if e.headers else None)
            # 403/404 berarti host-nya ada dan merespons — itu sudah cukup
            # sebagai bukti endpoint, walau filenya tidak bisa diambil.
            if e.code in (401, 403, 404, 405, 416):
                out["ok"] = True
                return out
            out["err"] = f"HTTP {e.code}"
            if method == "GET":
                return out
        except Exception as e:
            out["err"] = type(e).__name__ + ": " + str(e)[:80]
            if method == "GET":
                return out
    return out


def verify(urls, workers: int = 12, timeout: int = 12) -> list[dict]:
    if not urls:
        return []
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
        return list(ex.map(lambda u: probe(u, timeout), urls))


# -------------------------------------------------------------- output ----

def norm(u: str) -> str:
    return u[2:] if u.startswith("//") else u


def report(res: dict, verified: list[dict], show_raw: bool) -> None:
    print("=" * 74)
    print("APK:", res["path"])
    print("=" * 74)
    for n in res.get("notes", []):
        print("  !", n)
    if res.get("error"):
        print("  ERROR:", res["error"])
        return

    hits = res["hits"]
    if not hits:
        print("\n  Tidak ada kandidat URL yang lolos filter.\n")
    else:
        groups = defaultdict(list)
        for u, srcs in hits.items():
            groups[classify(norm(u))].append((u, srcs))

        labels = [("asset", "ENDPOINT ASET (punya ekstensi aset)"),
                  ("cdn", "KANDIDAT CDN (host-nya mengandung hint)"),
                  ("other", "URL LAIN"),
                  ("placeholder", "PLACEHOLDER (belum bisa dipakai)")]
        for key, title in labels:
            rows = sorted(groups.get(key, []))
            if not rows:
                continue
            print(f"\n--- {title}  [{len(rows)}] ---")
            for u, srcs in rows[:40]:
                print(f"    {u}")
                print(f"        dari: {', '.join(srcs[:4])}")
            if len(rows) > 40:
                print(f"    ... {len(rows) - 40} lagi")

    # ---- Addressables ----
    for a in res.get("addressables", []):
        print(f"\n--- ADDRESSABLES: {a['file']} ({a['size']:,} byte) ---")
        if a.get("hash"):
            print("    settings hash:", a["hash"])
        for u in a.get("remote_urls", []):
            tag = "  [PLACEHOLDER]" if a.get("placeholder") else ""
            print("    remote:", u, tag)
        if a.get("placeholder"):
            print("    -> Unity mengisi host ini saat runtime. Path-nya yang")
            print("       berguna (pola katalog), bukan host-nya.")
        if a.get("total_bundles"):
            print(f"    bundle di katalog: {a['total_bundles']:,}")
        if a.get("total_locations"):
            print(f"    lokasi di katalog: {a['total_locations']:,}")
        if a.get("sample_bundles"):
            print("    contoh entry bundle:")
            for b in a["sample_bundles"][:10]:
                print("      ", b[:150])

    # ---- hasil verifikasi ----
    if verified:
        live = [v for v in verified if v["ok"]]
        print(f"\n--- VERIFIKASI HTTP  ({len(live)}/{len(verified)} merespons) ---")
        for v in sorted(verified, key=lambda x: (not x["ok"], x["url"])):
            if v["ok"]:
                sz = f"  {int(v['len']):,} B" if v["len"] and v["len"].isdigit() else ""
                print(f"    OK   {v['status']:<4} {v['ctype'] or '-':<24} {v['url']}{sz}")
        dead = [v for v in verified if not v["ok"]]
        if dead and show_raw:
            print("    -- tidak merespons --")
            for v in dead[:15]:
                print(f"    .    {v['err'] or v['status']}  {v['url']}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("apk", nargs="+", help="berkas .apk (atau .apks/.xapk)")
    ap.add_argument("--no-verify", action="store_true",
                    help="jangan lakukan HTTP; hanya scan statis")
    ap.add_argument("--timeout", type=int, default=12)
    ap.add_argument("--json", metavar="FILE", help="tulis hasil ke JSON")
    args = ap.parse_args()

    results = []
    for p in args.apk:
        if not os.path.exists(p):
            print(f"Tidak ada: {p}", file=sys.stderr)
            continue
        print(f"\n[*] memindai {p} ...", file=sys.stderr)
        r = scan_apk(p)
        results.append(r)

        verified: list[dict] = []
        if not args.no_verify:
            cands = [norm(u) for u in r["hits"]
                     if classify(norm(u)) in ("asset", "cdn")
                     and not u.startswith("//")]
            # Satu URL per host cukup untuk membuktikan host merespons;
            # menguji semua ratusan URL katalog cuma buang waktu dan kena rate limit.
            seen = set()
            uniq = []
            for u in cands:
                h = host_of(u)
                if h in seen:
                    continue
                seen.add(h)
                uniq.append(u)
            uniq.sort()
            if uniq:
                print(f"[*] memverifikasi {len(uniq)} host ...", file=sys.stderr)
                verified = verify(uniq, timeout=args.timeout)
        report(r, verified, show_raw=False)

    if args.json:
        with open(args.json, "w") as f:
            json.dump([{k: v for k, v in r.items() if k != "hits"} |
                       {"hits": r.get("hits", {})} for r in results], f, indent=2)
        print(f"\nJSON ditulis: {args.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
