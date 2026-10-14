#!/usr/bin/env python3
"""Ekstrak Spine dari CDN Peachhan (asset.peachhan.com, m1productionasset).

Sumber : https://asset.peachhan.com/mgameasset/m1productionasset/Android/
         - version.json  = {version, assetBundleMetadatas:{<key>:{hash,fileSizeInMB}}}
         - <key>          = berkas UnityFS (AssetBundle) TANPA ekstensi
         CDN-nya TERBUKA (tanpa login/signed URL) — ditemukan dari daftar CDN
         hasil bongkar '二游资源工具.exe' (lihat tools/game-cdn-list.md).

Isi bundle spine: TextAsset "<name>.skel" + "<name>.atlas" (+ varian CG1/CG2)
+ Texture2D halaman. Satu bundle = satu model (folder), beberapa .skel =
varian (dipakai apa adanya oleh keluarga model di viewer).

Pakai:  /srv/venv-spine/bin/python tools/peachhan/extract-peachhan.py [prefix ...]
        (default: herospine, spineasset, battle/effectspine)
"""
import concurrent.futures as cf
import json
import os
import re
import struct
import subprocess
import sys

import UnityPy

UnityPy.config.FALLBACK_UNITY_VERSION = "2022.3.62f3"
BASE = "https://asset.peachhan.com/mgameasset/m1productionasset/Android"
OUT = "/opt/spine-viewer/assets/peachhan"
CACHE = "/opt/peachhan/bundles"
PREFIXES = ["herospine/", "spineasset/", "battle/effectspine/"]
UA = "spine-viewer-peachhan/1.0"


def parse_text_asset(raw: bytes):
    """Layout TextAsset Unity: int32 name_len, name (align 4), int32 size, data.

    WAJIB via obj.get_raw_data(): UnityPy mendekode TextAsset.m_Script jadi `str`
    dan itu MERUSAK .skel biner (byte >= 0x80 tak bisa round-trip encoding apa
    pun -> berubah jadi '?'). get_raw_data() mengembalikan byte apa adanya.
    """
    try:
        n = struct.unpack("<i", raw[0:4])[0]
        if not (0 < n < 512):
            return None, None
        name = raw[4:4 + n].decode("utf-8", "replace")
        pos = 4 + n
        pos += (4 - (pos % 4)) % 4
        size = struct.unpack("<i", raw[pos:pos + 4])[0]
        if not (0 <= size <= len(raw) - pos - 4):
            return name, None
        return name, raw[pos + 4:pos + 4 + size]
    except Exception:
        return None, None


def http(url, dest=None, timeout=120):
    cmd = ["curl", "-s", "--max-time", str(timeout), "-A", UA]
    if dest:
        r = subprocess.run(cmd + ["-o", dest, "-w", "%{http_code}", url],
                           capture_output=True, text=True)
        return r.stdout.strip()
    return subprocess.run(cmd + [url], capture_output=True).stdout


def main():
    wanted = sys.argv[1:] or PREFIXES
    ver = json.loads(http(BASE + "/version.json"))
    meta = ver.get("assetBundleMetadatas", {})
    keys = [k for k in meta if any(k.startswith(p) for p in wanted)]
    print(f"version {ver.get('version')}: {len(keys)} bundle cocok {wanted}")
    os.makedirs(OUT, exist_ok=True)
    os.makedirs(CACHE, exist_ok=True)

    def work(key):
        fp = os.path.join(CACHE, key.replace("/", "_"))
        if not os.path.exists(fp) or os.path.getsize(fp) < 100:
            code = http(BASE + "/" + key, dest=fp)
            if code != "200":
                return (key, 0, f"http {code}")
        folder = os.path.join(OUT, key.replace("/", "_"))
        try:
            env = UnityPy.load(open(fp, "rb").read())
        except Exception as e:
            return (key, 0, f"load {e}")
        os.makedirs(folder, exist_ok=True)
        n = 0
        for o in env.objects:
            try:
                if o.type.name == "TextAsset":
                    nm, data = parse_text_asset(o.get_raw_data())
                    if nm is None or data is None:
                        continue
                    with open(os.path.join(folder, nm if "." in nm else nm + ".txt"), "wb") as f:
                        f.write(data)
                    n += 1
                elif o.type.name == "Texture2D":
                    d = o.read()
                    d.image.save(os.path.join(folder, d.m_Name + ".png"))
                    n += 1
            except Exception:
                pass
        return (key, n, None)

    ok = 0
    models = []
    errors = []
    with cf.ThreadPoolExecutor(max_workers=8) as ex:
        for key, n, err in ex.map(work, keys):
            if err:
                errors.append(f"{key}: {err}")
            else:
                ok += 1
                models.append(key)
    print(f"SELESAI {ok}/{len(keys)} bundle -> {OUT}")
    for e in errors[:10]:
        print("  ERR", e)


if __name__ == "__main__":
    main()
