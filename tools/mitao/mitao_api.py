#!/usr/bin/env python3
"""蜜桃乌托邦 (Peach Utopia) asset downloader — headless, no GUI, no emulator.

Chain (reverse-engineered from 二游资源工具 v4.260923 and cross-checked against
the write-up on https://live2dhub.com/t/topic/6410):

  1. POST /resource/url           -> release_id + base_urls
  2. POST /resource/access/batch  -> signed download URL per bundle file
                                     (this is where the `sign` param comes from)
  3. GET each signed URL          -> the encrypted bundle
  4. decrypt (IDOLAB2: AES-256-CBC per 64 KiB chunk + HMAC-SHA256, HKDF)

Step 3/4 are the same for every game on this backend; only the /resource/url
body differs per game (`platform` + `resource_type`).

Usage:
    download.py --manifest manifest.json --out bundles [--limit N] [--only spine]
"""
import argparse
import hashlib
import hmac
import json
import os
import struct
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

# --- per-game API parameters (from the tool's IL; 蜜桃乌托邦) -------------------
API_BASE = "https://pxapi.jhdwxp.com"
URL_BODY = {"access_protocol": 1, "platform": "18game", "resource_type": "android_cn_release"}

# --- bundle decryption (IDOLAB2 container) -----------------------------------
MAGIC = b"IDOLAB2"
HEADER_SIZE = 0x80
CHUNK_SIZE = 0x10000
FULL_RECORD_SIZE = 0x10040
KDF_INFO = b"IdolTime/AssetBundle/v2/AES256CBC-HMACSHA256"
MASTER_KEY_HEX = "B3A755E19FD88CB176FAA283BF0839FFD4FBC0A0F81211F9FADC5C86DB4CDC91"


def log(*a):
    print(*a, flush=True)


def http_json(url, body=None, timeout=40, retries=4):
    data = None if body is None else json.dumps(body).encode()
    hdrs = {"Content-Type": "application/json", "Accept": "application/json"}
    last = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, data=data, headers=hdrs)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode("utf-8", "replace"))
        except urllib.error.HTTPError as e:
            payload = e.read().decode("utf-8", "replace")
            try:
                return json.loads(payload)
            except Exception:
                last = f"HTTP {e.code}: {payload[:200]}"
        except Exception as e:
            last = str(e)
        time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"request failed: {url} ({last})")


def get_release():
    r = http_json(f"{API_BASE}/resource/url", URL_BODY)
    if r.get("code") != 0:
        raise RuntimeError(f"/resource/url -> {r}")
    d = r["data"]
    return d["release_id"], d["base_urls"][0], d.get("upgrade_url")


def batch_urls(release_id, files, chunk=20):
    """POST /resource/access/batch. Returns {filename: url}. The server is
    happiest with <=20 names per call (the game itself sends 9)."""
    out = {}
    for i in range(0, len(files), chunk):
        part = files[i:i + chunk]
        body = {
            "platform": URL_BODY["platform"],
            "resource_type": URL_BODY["resource_type"],
            "release_id": release_id,
            "files": part,
        }
        r = http_json(f"{API_BASE}/resource/access/batch", body)
        if r.get("code") != 0:
            log(f"  ! batch rejected ({len(part)} files): {r.get('msg')}")
            # Retry one-by-one so a single bad name doesn't sink the batch.
            for f in part:
                rr = http_json(f"{API_BASE}/resource/access/batch", {**body, "files": [f]})
                if rr.get("code") == 0:
                    out.update(_flatten(rr))
                else:
                    log(f"    ! {f}: {rr.get('msg')}")
        else:
            out.update(_flatten(r))
    return out


def _flatten(resp):
    """Response shape: data.files[] = {file, urls: [signed_url, ...]}.

    NB: the CDN names every bundle by its FileHash, and /resource/access/batch
    only accepts that hash form (`<FileHash>.bundle`) — the manifest's
    BundleName is rejected with RESOURCE_ACCESS_INVALID.
    """
    res = {}
    files = (resp.get("data") or {}).get("files")
    if isinstance(files, dict):
        for k, v in files.items():
            if isinstance(v, str):
                res[k] = v
            elif isinstance(v, dict):
                urls = v.get("urls") or ([v["url"]] if v.get("url") else [])
                if urls:
                    res[k] = urls[0]
        return res
    for item in files or []:
        if isinstance(item, dict):
            name = item.get("file") or item.get("name") or item.get("file_name")
            urls = item.get("urls") or ([item["url"]] if item.get("url") else [])
            if name and urls:
                res[name] = urls[0]
    return res


# --- decryption --------------------------------------------------------------
def hmac_sha256(key, data):
    return hmac.new(key, data, hashlib.sha256).digest()


def derive_keys(master_key, salt):
    prk = hmac_sha256(salt, master_key)
    enc = hmac_sha256(prk, KDF_INFO + b"\x01")
    auth = hmac_sha256(prk, enc + KDF_INFO + b"\x02")
    return enc, auth


def cipher_len(plain_len, extra=True):
    r = (plain_len + 15) & ~15
    return r + 16 if extra else r


def decrypt_bundle(blob, bundle_name, master_key):
    if len(blob) < HEADER_SIZE or blob[:7] != MAGIC:
        raise ValueError("not an IDOLAB2 container")
    if blob[8] != 2:
        raise ValueError(f"unsupported format version {blob[8]}")

    def u32(o): return struct.unpack_from("<I", blob, o)[0]
    def u64(o): return struct.unpack_from("<Q", blob, o)[0]

    if u32(0x0C) != 1:
        raise ValueError("unexpected key_id")
    if u32(0x10) != CHUNK_SIZE:
        raise ValueError("unexpected chunk size")
    if u32(0x14) != 0:
        raise ValueError("reserved != 0")

    plain_len = u64(0x18)
    salt = blob[0x20:0x40]
    name_hash = blob[0x40:0x60]
    header_tag = blob[0x60:0x80]

    if not hmac.compare_digest(name_hash, hashlib.sha256(bundle_name.encode()).digest()):
        raise ValueError("bundle name hash mismatch")

    enc_key, auth_key = derive_keys(master_key, salt)
    if not hmac.compare_digest(header_tag, hmac_sha256(auth_key, blob[:0x60])):
        raise ValueError("header auth failed (wrong master key?)")

    std = _enc_total(plain_len, True)
    compat = _enc_total(plain_len, False)
    if len(blob) == std:
        extra = True
    elif len(blob) == compat:
        extra = False
    else:
        raise ValueError(f"size mismatch: got {len(blob)}, want {std} or {compat}")

    out = bytearray()
    off = HEADER_SIZE
    idx = 0
    while len(out) < plain_len:
        rem = plain_len - len(out)
        pc = min(CHUNK_SIZE, rem)
        final = rem <= CHUNK_SIZE
        cl = cipher_len(pc, extra if final else True)
        iv = blob[off:off + 16]; off += 16
        ct = blob[off:off + cl]; off += cl
        tag = blob[off:off + 32]; off += 32
        expect = hmac_sha256(auth_key, header_tag + struct.pack("<Q", idx) + iv + ct)
        if not hmac.compare_digest(tag, expect):
            raise ValueError(f"chunk {idx} auth failed")

        from Crypto.Cipher import AES
        pt = AES.new(enc_key, AES.MODE_CBC, iv).decrypt(ct)
        pad = pt[-1]
        if not 1 <= pad <= 16 or pt[-pad:] != bytes([pad]) * pad:
            raise ValueError(f"chunk {idx} bad PKCS7 padding")
        pt = pt[:-pad]
        if len(pt) != pc:
            raise ValueError(f"chunk {idx} length {len(pt)} != {pc}")
        out.extend(pt)
        idx += 1
    return bytes(out)


def _enc_total(plain_len, final_extra):
    if plain_len == 0:
        return HEADER_SIZE
    total = HEADER_SIZE
    remaining = plain_len
    i = 0
    while remaining > 0:
        cur = min(CHUNK_SIZE, remaining)
        if i < (plain_len // CHUNK_SIZE):
            total += FULL_RECORD_SIZE
        else:
            total += 16 + cipher_len(cur, final_extra) + 32
        remaining -= cur
        i += 1
    return total


def is_container(blob):
    return len(blob) >= HEADER_SIZE and blob[:7] == MAGIC


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", default="manifest.json")
    ap.add_argument("--out", default="bundles")
    ap.add_argument("--only", default=None, help="substring filter on bundle name")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--skip-existing", action="store_true")
    ap.add_argument("--list", action="store_true", help="only resolve+list URLs")
    args = ap.parse_args()

    m = json.load(open(args.manifest))
    bundles = m["Bundles"]
    if args.only:
        bundles = [b for b in bundles if args.only.lower() in b["BundleName"].lower()]
    if args.limit:
        bundles = bundles[:args.limit]

    release_id, base_url, apk = get_release()
    log(f"release_id : {release_id}")
    log(f"base_url   : {base_url}")
    log(f"apk        : {apk}")
    log(f"bundles    : {len(bundles)}\n")

    os.makedirs(args.out, exist_ok=True)
    master_key = bytes.fromhex(MASTER_KEY_HEX)

    # The CDN stores bundles under <FileHash>.bundle and /resource/access/batch
    # only accepts that form, so resolve URLs by hash and keep a hash->bundle map.
    names = [f"{b['FileHash']}.bundle" for b in bundles]
    by_hash_name = {f"{b['FileHash']}.bundle": b for b in bundles}

    resolved = batch_urls(release_id, names)
    log(f"URL bertanda tangan diperoleh: {len(resolved)}/{len(names)}\n")
    if resolved:
        sample = next(iter(resolved.items()))
        log(f"contoh URL:\n  {sample[0]}\n  {sample[1][:150]}...\n")
    if args.list:
        for n, u in list(resolved.items())[:20]:
            log(f"  {n}\n    {u}")
        return

    ok = fail = skipped = 0
    for i, cdn_name in enumerate(names, 1):
        b = by_hash_name[cdn_name]
        # Save under the human-readable BundleName so the tree is usable.
        dest = os.path.join(args.out, b["BundleName"])
        if args.skip_existing and os.path.exists(dest) and os.path.getsize(dest) == b["FileSize"]:
            skipped += 1
            continue
        url = resolved.get(cdn_name)
        if not url:
            log(f"[{i}/{len(names)}] SKIP (no url) {cdn_name}")
            fail += 1
            continue
        try:
            with urllib.request.urlopen(url, timeout=120) as r:
                blob = r.read()
        except Exception as e:
            log(f"[{i}/{len(names)}] DL FAIL {cdn_name}: {e}")
            fail += 1
            continue

        # CDN copies are IDOLAB2 containers; APK copies are plain UnityFS.
        # The container authenticates the header against the BundleName, so
        # decrypt with that — not the `<FileHash>.bundle` name used on the CDN.
        try:
            if is_container(blob):
                plain = decrypt_bundle(blob, b["BundleName"], master_key)
            else:
                plain = blob
        except Exception as e:
            log(f"[{i}/{len(names)}] DECRYPT FAIL {cdn_name}: {e}")
            fail += 1
            continue

        open(dest, "wb").write(plain)
        ok += 1
        if i % 10 == 0 or i == len(names):
            log(f"[{i}/{len(names)}] ok={ok} fail={fail} skip={skipped}  ({b['BundleName']}, {len(plain)} B)")

    log(f"\nSELESAI  ok={ok}  fail={fail}  skip={skipped}  -> {args.out}")


if __name__ == "__main__":
    main()
