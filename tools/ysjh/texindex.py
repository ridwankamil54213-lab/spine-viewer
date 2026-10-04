#!/usr/bin/env python3
"""Index native PNG 异世界后宫物语 berdasarkan DIMENSI (untuk mencocokkan halaman atlas).

UUID file native TIDAK berkorespondensi langsung dengan `uuids` config, jadi
pencocokan tekstur dilakukan lewat ukuran halaman yang tercatat di atlas:
  \\n<page>.png\\nsize: <W>,<H>\\n...
Semua .png di native/ didekripsi (XXTEA + prefix) lalu dibaca header IHDR -> (W,H).
"""
import glob
import os
import struct
import sys
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import extract_ysjh as E  # noqa


def dims_of(path):
    try:
        d = E.decode(open(path, "rb").read(), path)
        if d[:8] != b"\x89PNG\r\n\x1a\n":
            return None
        w, h = struct.unpack_from(">II", d, 16)
        return (path, w, h)
    except Exception:
        return None


def build(root, out_json, workers=8):
    files = glob.glob(os.path.join(root, "native", "*", "*.png"))
    idx = defaultdict(list)
    n = 0
    with ProcessPoolExecutor(max_workers=workers) as ex:
        for r in ex.map(dims_of, files, chunksize=64):
            if r:
                idx[f"{r[1]}x{r[2]}"].append(r[0])
                n += 1
    import json
    json.dump({k: v for k, v in idx.items()}, open(out_json, "w"))
    print(f"  indexed {n}/{len(files)} png, {len(idx)} ukuran unik")


if __name__ == "__main__":
    build(sys.argv[1], sys.argv[2], int(sys.argv[3]) if len(sys.argv) > 3 else 8)
