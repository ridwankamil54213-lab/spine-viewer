#!/usr/bin/env python3
"""Parser SSRA untuk Chaos Zero Nightmare (Yuna engine) — murni Python.

Format (dari akioukun/Chaos-Zero-Nightmare-ASSet-Ripper, archive/SSRArchive.cpp):

  header (64 B, little-endian):
    char magic[4]="SSRA"; u32 version; u32 unk0; u32 chunk_count; u32 file_count;
    u32 flags; u64 string_table_offset; u64 string_table_size;
    u64 chunk_table_offset; u64 file_table_offset; u64 extra

  chunk table (32 B/entry):
    u32 chunk_id; u16 group_idx; u16 unk; u64 uncomp_sz; u64 comp_sz; u64 checksum

  file table (40 B/entry):
    u32 path_hash; u32 unk; u64 chunk_file_off; u32 comp_sz; u32 uncomp_sz;
    u32 unk; u32 name_off; u8 is_compressed; u8 is_encrypted; u16 group_idx;
    u32 flags   (bit0 = tombstone/hapus)

  GRPS block (setelah string table, opsional):
    "GRPS"; u32 group_count; u32 sec_str_size; 4 B reserved;
    group_count * 24 B entri (u16 group_idx, u32 name_off, 18 B sisa);
    lalu string table kedua untuk nama grup.

  Isi chunk: potongan virtual per grup. Offset file = chunk_file_off GLOBAL per
  grup; tiap chunk punya global_offset dalam grup; chunk fisik = file .ssrc.
  File di-zstd (kadang bingkai legacy 0x25..0x27) atau mentah; beberapa AES-128
  (belum didukung → dikembalikan mentah).

Pakai:
    ssra.py --manifest manifest.ssra --list [pola]
    ssra.py --manifest manifest.ssra --tree /path/di/pack
    ssra.py --manifest manifest.ssra --extract <path-di-arsip> --out DIR
    ssra.py --manifest manifest.ssra --extract-tree <dir> --out DIR
"""
import argparse
import os
import struct
import sys
from pathlib import Path

try:
    from compression import zstd as _zstd          # Python >= 3.14 (stdlib)
except Exception:                                   # pragma: no cover
    import zstandard as _zstd                       # fallback kalau ada


def zstd_decompress(buf: bytes, max_size: int | None = None) -> bytes:
    """Dukung bingkai zstd legacy (0x25..0x27 -> 0x28) & ukuran output diketahui."""
    if len(buf) >= 4 and buf[1] == 0xB5 and buf[2] == 0x2F and buf[3] == 0xFD \
            and 0x25 <= buf[0] <= 0x27:
        buf = bytes([0x28]) + buf[1:]
    try:
        d = _zstd.ZstdDecompressor()
        return d.decompress(buf, max_output_size=max_size) if max_size else d.decompress(buf)
    except TypeError:
        return _zstd.decompress(buf)


def _cstr(blob: bytes, off: int) -> str:
    if off < 0 or off >= len(blob):
        return ""
    end = blob.find(b"\0", off)
    if end < 0:
        end = len(blob)
    return blob[off:end].decode("utf-8", "replace")


class SSRA:
    def __init__(self, manifest: str):
        self.manifest = Path(manifest)
        self.chunks_dir = self.manifest.parent / "chunks"
        self.data = self.manifest.read_bytes()
        self._parse()

    def _parse(self):
        d = self.data
        (magic, self.version, self.unk0, chunk_count, file_count, flags,
         st_off, st_sz, ct_off, ft_off, extra) = struct.unpack_from("<4sIIIIIQQQQQ", d, 0)
        assert magic == b"SSRA", f"magic bukan SSRA: {magic!r}"
        self.chunk_count, self.file_count = chunk_count, file_count
        self.string_table = d[st_off:st_off + st_sz]

        # --- GRPS (nama grup) ---
        self.group_names = {}
        g = st_off + st_sz
        if g + 16 <= len(d) and d[g:g + 4] == b"GRPS":
            gc, ssz = struct.unpack_from("<II", d, g + 4)
            ent = g + 16
            sec = ent + gc * 24
            sec_tab = d[sec:sec + ssz]
            for i in range(gc):
                gi, = struct.unpack_from("<H", d, ent + i * 24)
                no, = struct.unpack_from("<I", d, ent + i * 24 + 4)
                nm = _cstr(sec_tab, no)
                if nm:
                    self.group_names[gi] = nm

        # --- chunk table ---
        self.chunks = []
        for i in range(chunk_count):
            o = ct_off + i * 32
            if o + 32 > len(d):
                break
            cid, gi, _unk, unc, cmp_, csum = struct.unpack_from("<IHHQQQ", d, o)
            self.chunks.append(dict(index=i, chunk_id=cid, group=gi,
                                    uncomp=unc, comp=cmp_, checksum=csum,
                                    name=self._chunk_name(cid, gi), path=None))
        self._resolve_chunks()

        # --- file table ---
        self.files = {}
        for i in range(file_count):
            o = ft_off + i * 40
            if o + 40 > len(d):
                break
            (ph, _u4, off, csz, usz, _u18, noff,
             icomp, ienc, gi, fl) = struct.unpack_from("<IIQIIIIBBHI", d, o)
            if fl & 1:
                continue                        # tombstone
            name = _cstr(self.string_table, noff)
            if not name:
                continue
            clean = name.replace("\\", "/").strip("/")
            if not clean:
                continue
            rec = dict(path=clean, group=gi, offset=off, comp_sz=csz, size=usz,
                       compressed=bool(icomp), encrypted=bool(ienc))
            self.files[clean] = rec

    def _chunk_name(self, cid, gi):
        if gi == 0xFFFF:
            return f"hotfix_{cid:04d}.ssrc"
        nm = self.group_names.get(gi)
        if nm:
            return f"{nm}_b{cid:02d}_0.ssrc"
        return f"group_{gi}_{cid:04d}.ssrc"

    def _resolve_chunks(self):
        """Petakan chunk -> file .ssrc fisik.

        Nama file fisik TIDAK 1:1 dengan chunk_id manifest: game memecah chunk
        besar (mis. `base_b28_0` + `base_b28_1`) dan memberi nama yang menggeser
        entri berikutnya. Yang benar: urutkan chunk manifest per grup (menurut
        chunk_id) dan file fisik per grup (natural sort), lalu zip posisi demi
        posisi. Ukuran `comp` dicocokkan sebagai verifikasi.
        """
        import re
        phys = []
        if self.chunks_dir.is_dir():
            phys = [f for f in self.chunks_dir.iterdir()
                    if f.is_file() and f.suffix == ".ssrc"]

        def natkey(s):
            return [int(t) if t.isdigit() else t for t in re.split(r"(\d+)", s)]

        # grup nama -> file fisik (prefix "<nama>_", termasuk varian *_large_*)
        by_group = {}
        for gidx, gname in self.group_names.items():
            pre = gname + "_"
            gfiles = sorted([f for f in phys if f.name.startswith(pre)],
                            key=lambda p: natkey(p.name))
            by_group[gidx] = gfiles
        # hotfix (group 0xFFFF)
        hot = sorted([f for f in phys if f.name.startswith("hotfix_")],
                     key=lambda p: natkey(p.name))
        if hot:
            by_group.setdefault(0xFFFF, []).extend(hot)

        self._size_warn = []
        for gidx, gfiles in by_group.items():
            mchunks = sorted([c for c in self.chunks if c["group"] == gidx],
                             key=lambda c: c["chunk_id"])
            for c, f in zip(mchunks, gfiles):
                c["path"] = f
                if f.stat().st_size != c["comp"]:
                    self._size_warn.append(
                        f"{c['name']}: manifest comp={c['comp']} != fisik "
                        f"{f.name} {f.stat().st_size}")

        # offset global per grup (urut chunk_id)
        from collections import defaultdict
        grp = defaultdict(list)
        for c in self.chunks:
            grp[c["group"]].append(c)
        for g, lst in grp.items():
            lst.sort(key=lambda x: x["chunk_id"])
            off = 0
            for c in lst:
                c["goff"] = off
                off += c["uncomp"]

    @property
    def missing_chunks(self):
        return [c for c in self.chunks if not c["path"]]

    def read(self, path: str, max_bytes: int | None = None) -> bytes:
        rec = self.files.get(path)
        if not rec:
            raise KeyError(path)
        if rec["encrypted"]:
            raise NotImplementedError(f"terenkripsi (AES): {path}")
        group = rec["group"]
        goff = rec["offset"]
        need = rec["comp_sz"] if rec["compressed"] else rec["size"]
        if max_bytes:
            need = min(need, max_bytes)
        gc = sorted([c for c in self.chunks if c["group"] == group],
                    key=lambda c: c["goff"])
        out = bytearray()
        voff = goff
        while len(out) < need:
            cur = next((c for c in gc if c["goff"] <= voff < c["goff"] + c["uncomp"]), None)
            if not cur:
                raise IOError(f"chunk tak ketemu utk offset {voff} grup {group}")
            if not cur["path"]:
                raise IOError(f"file chunk hilang: {cur['name']}")
            local = voff - cur["goff"]
            seg = min(need - len(out), cur["uncomp"] - local)
            with open(cur["path"], "rb") as fh:
                fh.seek(local)
                out += fh.read(seg)
            voff += seg
        if rec["compressed"]:
            return zstd_decompress(bytes(out), rec["size"])
        return bytes(out)

    def tree(self, prefix=""):
        out = []
        for p in sorted(self.files):
            if p.startswith(prefix):
                out.append(p)
        return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--list", nargs="?", const="", metavar="POLA")
    ap.add_argument("--tree", metavar="PREFIX")
    ap.add_argument("--extract", metavar="PATH")
    ap.add_argument("--extract-tree", metavar="PREFIX")
    ap.add_argument("--out", default=".")
    ap.add_argument("--info", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    a = SSRA(args.manifest)

    if args.info:
        print(f"manifest      : {a.manifest} ({len(a.data)} B)")
        print(f"version/unk   : {a.version} / {a.unk0}")
        print(f"chunk_count   : {a.chunk_count}   file_count: {a.file_count}")
        print(f"chunk hilang  : {len(a.missing_chunks)}")
        print(f"file di indeks: {len(a.files)}")
        print(f"grup          : {a.group_names}")
        from collections import Counter
        ext = Counter(Path(p).suffix.lower() for p in a.files)
        print("ekstensi top :", ext.most_common(20))
        return

    if args.tree is not None:
        paths = a.tree(args.tree)
        if args.limit:
            paths = paths[:args.limit]
        for p in paths:
            print(p)
        print(f"# {len(paths)} file", file=sys.stderr)
        return

    if args.list is not None:
        pat = args.list.lower()
        paths = [p for p in sorted(a.files) if pat in p.lower()] if pat else sorted(a.files)
        if args.limit:
            paths = paths[:args.limit]
        for p in paths:
            print(p)
        print(f"# {len(paths)} file", file=sys.stderr)
        return

    if args.extract:
        root = Path(args.out)
        for p in [args.extract] if args.extract in a.files else a.tree(args.extract):
            dest = root / p
            dest.parent.mkdir(parents=True, exist_ok=True)
            try:
                dest.write_bytes(a.read(p))
                print("ok  ", p)
            except Exception as e:
                print("GAGAL", p, "->", type(e).__name__, e)
        return

    if args.extract_tree:
        root = Path(args.out)
        paths = a.tree(args.extract_tree)
        n = 0
        for p in paths:
            dest = root / p
            dest.parent.mkdir(parents=True, exist_ok=True)
            try:
                dest.write_bytes(a.read(p))
                n += 1
                if n % 50 == 0:
                    print(f"  {n}/{len(paths)}", flush=True)
            except Exception as e:
                print("GAGAL", p, "->", type(e).__name__, e)
        print(f"selesai {n} file -> {root}")
        return

    ap.print_help()


if __name__ == "__main__":
    main()
