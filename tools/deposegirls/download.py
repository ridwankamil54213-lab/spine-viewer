#!/usr/bin/env python3
"""Download + decrypt Depose Girls Spine bundles.

Ports the C# DeposeGirls_AssetDecDL downloader to Python so it runs on this
box (no .NET 10 / Windows WPF here). Three things the original does, kept
identical so the bytes match:

1. AssetList.txt is LZ4-compressed -> lz4.frame.decompress
2. Every downloaded file is wrapped in the "8Jdn" container:
       b'8Jdn' | 1 unknown byte | int32 LE size | RC4(size bytes) | rest
   RC4 key is the 16-byte constant from DecryptAsset.cs.
3. Files NOT carrying the 8Jdn signature are stored as-is (the original
   returns null from Jdn_Decrypt and the caller keeps the raw download).

Downloads are concurrent and resumable: a bundle whose output file already
exists with the expected size is skipped, so re-running after a failure only
fetches what's missing.
"""
import argparse
import asyncio
import json
import os
import struct
import sys

import aiohttp

# From DecryptAsset.cs — RC4 key for the 8Jdn container.
RC4_KEY = bytes(
    [
        0xEB, 0x45, 0x8B, 0xA5, 0x2B, 0x05, 0xCB, 0x65,
        0x6B, 0xC5, 0x0B, 0x25, 0xAB, 0x85, 0x4B, 0xE5,
    ]
)
SIGN = b"8Jdn"


def arc4(data: bytes, key: bytes) -> bytes:
    """RC4 (ARC4) — byte-for-byte identical to DecryptAsset.ARC4.Decrypt."""
    S = list(range(256))
    j = 0
    for i in range(256):
        j = (j + S[i] + key[i % len(key)]) & 0xFF
        S[i], S[j] = S[j], S[i]
    out = bytearray(len(data))
    i = j = 0
    for k in range(len(data)):
        i = (i + 1) & 0xFF
        j = (j + S[i]) & 0xFF
        t = S[(S[i] + S[j]) & 0xFF]
        out[k] = data[k] ^ t
    return bytes(out)


def jdn_decrypt(data: bytes):
    """Strip the 8Jdn wrapper. Returns None when the file isn't encrypted."""
    if len(data) < 9 or data[:4] != SIGN:
        return None
    size = struct.unpack_from("<i", data, 5)[0]
    if size < 0 or len(data) < 9 + size:
        return None
    return arc4(data[9 : 9 + size], RC4_KEY) + data[9 + size :]


async def fetch(session, entry, dest, sem, results):
    out = os.path.join(dest, entry["name"])
    # Resume: a complete file is already on disk.
    if os.path.exists(out) and os.path.getsize(out) == entry["size"]:
        results["skip"] += 1
        return
    async with sem:
        for attempt in range(3):
            try:
                async with session.get(entry["url"]) as r:
                    if r.status != 200:
                        raise aiohttp.ClientError(f"HTTP {r.status}")
                    data = await r.read()
                dec = jdn_decrypt(data)
                payload = dec if dec is not None else data
                tmp = out + ".part"
                with open(tmp, "wb") as f:
                    f.write(payload)
                os.replace(tmp, out)
                results["ok"] += 1
                results["bytes"] += len(payload)
                return
            except Exception as e:
                if attempt == 2:
                    results["fail"] += 1
                    results["errors"].append(f"{entry['name']}: {e}")
                else:
                    await asyncio.sleep(1.5 * (attempt + 1))
        return


async def main_async(args):
    entries = json.load(open(args.index, encoding="utf-8"))
    if args.limit:
        entries = entries[: args.limit]
    os.makedirs(args.out, exist_ok=True)
    results = {"ok": 0, "skip": 0, "fail": 0, "bytes": 0, "errors": []}
    sem = asyncio.Semaphore(args.concurrency)
    timeout = aiohttp.ClientTimeout(total=300, connect=30)
    conn = aiohttp.TCPConnector(limit=args.concurrency, ssl=False)

    async with aiohttp.ClientSession(timeout=timeout, connector=conn) as session:
        tasks = [fetch(session, e, args.out, sem, results) for e in entries]
        done = 0
        for coro in asyncio.as_completed(tasks):
            await coro
            done += 1
            if done % 25 == 0 or done == len(tasks):
                print(
                    f"  {done}/{len(tasks)}  ok={results['ok']} "
                    f"skip={results['skip']} fail={results['fail']} "
                    f"{results['bytes']/1e6:.0f} MB",
                    flush=True,
                )

    print(
        f"\nDONE ok={results['ok']} skip={results['skip']} "
        f"fail={results['fail']} {results['bytes']/1e6:.0f} MB"
    )
    if results["errors"]:
        with open(args.out + "/_errors.txt", "w", encoding="utf-8") as f:
            f.write("\n".join(results["errors"]))
        print(f"errors written to {args.out}/_errors.txt")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--index", required=True, help="bundle index JSON")
    ap.add_argument("--out", required=True, help="download directory")
    ap.add_argument("--concurrency", type=int, default=24)
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()
    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()
