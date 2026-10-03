#!/usr/bin/env python3
"""Parse a YooAsset PackageManifest (the `.bytes` file shipped in the APK).

Schema published by whomepack on https://live2dhub.com/t/topic/6410 for
蜜桃乌托邦 (Unity + YooAsset). Every field is little-endian; strings are
[uint16 length][utf-8 bytes].

    sign             : 4 bytes
    FileVersion      : string
    EnableAddressable: bool (uint8)
    LocationToLower  : bool
    IncludeAssetGUID : bool
    OutputNameStyle  : int32
    PackageName      : string
    PackageVersion   : string
    AssetCount       : int32
      per asset: Address, AssetPath, AssetGUID (strings),
                 AssetTags[string], BundleID int32,
                 DependIDs[int32]
    BundleCount      : int32
      per bundle: BundleName, UnityCRC uint32, FileHash string,
                  FileCRC string, FileSize int64, IsRawFile bool,
                  LoadMethod uint8, Tags[string], ReferenceIDs[int32]

Usage:
    python3 parse-manifest.py <manifest.bytes> [--json out.json]
"""
import json
import struct
import sys
from io import BytesIO


class BinaryReader:
    def __init__(self, data: bytes):
        self.s = BytesIO(data)

    def tell(self):
        return self.s.tell()

    def remaining(self):
        cur = self.s.tell()
        self.s.seek(0, 2)
        end = self.s.tell()
        self.s.seek(cur)
        return end - cur

    def read_bytes(self, n):
        b = self.s.read(n)
        if len(b) != n:
            raise EOFError(f"need {n} bytes, offset {self.tell()}, left {self.remaining()}")
        return b

    def u8(self):
        return struct.unpack("<B", self.read_bytes(1))[0]

    def boolean(self):
        return self.u8() != 0

    def u16(self):
        return struct.unpack("<H", self.read_bytes(2))[0]

    def i32(self):
        return struct.unpack("<i", self.read_bytes(4))[0]

    def u32(self):
        return struct.unpack("<I", self.read_bytes(4))[0]

    def i64(self):
        return struct.unpack("<q", self.read_bytes(8))[0]

    def string(self):
        n = self.u16()
        if n == 0:
            return ""
        return self.read_bytes(n).decode("utf-8", errors="replace")


def parse(data: bytes) -> dict:
    """Try both known header variants, return the one that parses cleanly."""
    r = BinaryReader(data)

    # Variant A: leading 4-byte sign (what the live2dhub snippet documents).
    sign = r.read_bytes(4)
    m = {"sign": sign.hex()}
    m["FileVersion"] = r.string()
    m["EnableAddressable"] = r.boolean()
    m["LocationToLower"] = r.boolean()
    m["IncludeAssetGUID"] = r.boolean()
    m["OutputNameStyle"] = r.i32()
    m["PackageName"] = r.string()
    m["PackageVersion"] = r.string()

    n_assets = r.i32()
    if not (0 <= n_assets <= 1_000_000):
        raise ValueError(f"sanity: AssetCount={n_assets} looks wrong — header layout mismatch")

    assets = []
    for _ in range(n_assets):
        a = {
            "Address": r.string(),
            "AssetPath": r.string(),
            "AssetGUID": r.string(),
        }
        a["AssetTags"] = [r.string() for _ in range(r.u16())]
        a["BundleID"] = r.i32()
        a["DependIDs"] = [r.i32() for _ in range(r.u16())]
        assets.append(a)
    m["Assets"] = assets

    n_bundles = r.i32()
    if not (0 <= n_bundles <= 200_000):
        raise ValueError(f"sanity: BundleCount={n_bundles} looks wrong")

    bundles = []
    for _ in range(n_bundles):
        b = {
            "BundleName": r.string(),
            "UnityCRC": r.u32(),
            "FileHash": r.string(),
            "FileCRC": r.string(),
            "FileSize": r.i64(),
            "IsRawFile": r.boolean(),
            "LoadMethod": r.u8(),
        }
        b["Tags"] = [r.string() for _ in range(r.u16())]
        b["ReferenceIDs"] = [r.i32() for _ in range(r.u16())]
        bundles.append(b)
    m["Bundles"] = bundles
    m["RemainingBytes"] = r.remaining()
    return m


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    path = sys.argv[1]
    data = open(path, "rb").read()
    print(f"file      : {path}")
    print(f"size      : {len(data)} bytes")

    try:
        m = parse(data)
    except Exception as e:
        print(f"PARSE FAILED: {e}")
        sys.exit(1)

    print(f"PackageName   : {m['PackageName']}")
    print(f"PackageVersion: {m['PackageVersion']}")
    print(f"FileVersion   : {m['FileVersion']}")
    print(f"assets        : {len(m['Assets'])}")
    print(f"bundles       : {len(m['Bundles'])}")
    print(f"remaining     : {m['RemainingBytes']}")

    # Spine detection: skeleton extensions show up in asset paths.
    spine_assets = [
        a for a in m["Assets"]
        if a["AssetPath"].lower().endswith((".skel", ".atlas", ".json", ".png"))
        and any(k in a["AssetPath"].lower() for k in ("spine", "skel", "atlas", "char", "chara", "spine_"))
    ]
    print(f"\nbundles (first 12):")
    for b in m["Bundles"][:12]:
        print(f"  {b['BundleName']:<48} size={b['FileSize']:>10} hash={b['FileHash'][:16]} tags={b['Tags']}")

    print(f"\nasset path sample (first 15):")
    for a in m["Assets"][:15]:
        print(f"  {a['AssetPath']}")

    if "--json" in sys.argv:
        out = sys.argv[sys.argv.index("--json") + 1]
        json.dump(m, open(out, "w"), ensure_ascii=False, indent=1)
        print(f"\nwritten: {out}")


if __name__ == "__main__":
    main()
