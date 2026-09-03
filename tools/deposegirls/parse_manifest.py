#!/usr/bin/env python3
"""Parse Depose Girls AssetList.txt into a JSON bundle index.

The asset list is a line-oriented text file with "directory blocks":

    <dirname>          <- no '|', a bare directory name
    <count>            <- number of entries that follow
    <entry>|...        <- count lines, each with '|' separators
    ...

Only the `common` block holds game assets (Arabic/ChineseSimplified/Japanese
hold localisation text). Each entry line is:

    name|flag|hash|size[|contained files]

Entry names are lowercased, and the download URL is:

    {BaseUrl}/{directory}/{hash}{name}

The bundle name on disk keeps its original casing, which is why the entry
list is stored verbatim and only the URL is assembled here.
"""
import json
import re
import sys

INT_RE = re.compile(r"\d+")


def is_int(s):
    return bool(INT_RE.fullmatch(s.strip())) if s else False


def parse(path):
    lines = open(path, encoding="utf-8", errors="replace").read().splitlines()
    blocks = {}
    i = 0
    while i < len(lines) - 2:
        line = lines[i]
        if "|" not in line and is_int(lines[i + 1]):
            count = int(lines[i + 1])
            if (
                count > 0
                and i + 2 < len(lines)
                and "|" in lines[i + 2]
                and i + 1 + count < len(lines)
                and "|" in lines[i + 1 + count]
            ):
                blocks[line] = lines[i + 2 : i + 2 + count]
                i = i + 1 + count
                continue
        i += 1
    return blocks


def entries(block, directory, base_url):
    out = []
    for line in block:
        parts = line.split("|")
        if len(parts) < 4:
            continue
        name, _flag, hash16, size = parts[0], parts[1], parts[2], parts[3]
        try:
            size = int(size)
        except ValueError:
            size = 0
        out.append(
            {
                "name": name,
                "dir": directory,
                "hash": hash16,
                "size": size,
                "url": f"{base_url}/{directory}/{hash16}{name}",
            }
        )
    return out


def main():
    manifest = sys.argv[1] if len(sys.argv) > 1 else "/tmp/AssetList.txt"
    base_url = sys.argv[2]
    out_path = sys.argv[3]
    blocks = parse(manifest)
    common = blocks.get("common", [])
    ents = entries(common, "common", base_url)
    # Only Spine character/scene bundles. The game's Spine assets are all
    # named spine_* and carry the skeleton in a .prefab bundle.
    spine = [e for e in ents if e["name"].startswith("spine_")]
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(spine, f, ensure_ascii=False)
    print(f"total common : {len(ents)}")
    print(f"spine bundles: {len(spine)}")
    print(f"bytes        : {sum(e['size'] for e in spine):,}")


if __name__ == "__main__":
    main()
