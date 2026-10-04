#!/usr/bin/env python3
"""Decoder SCT/SCT2 (Yuna engine: Chaos Zero Nightmare, Epic Seven) -> RGBA.

Format (dari formagGinoo/SCTParser + akioukun/Chaos-Zero-Nightmare-ASSet-Ripper):

  SCT2 header (36 B):
    0  int32  signature  "SCT2"
    4  int32  total_size
    8  int32  unknown
    12 int32  data_offset
    16 int32  unknown
    20 int32  pixel_format
    24 u16    width
    26 u16    height
    28 u16    texture_width  (dengan padding)
    30 u16    texture_height
    32 int32  flags  (bit0 has_alpha, bit1 crop, bit4 raw, bit7 compressed)

  SCT header (9 B):
    0  "SC" + byte; 4: u8 pixel_format; 5: u16 w; 7: u16 h; data @ 9

  Data gambar (mulai data_offset): kadang LZ4 blok dengan prefix [u32 dec][u32 comp],
  lalu piksel dalam format: 19=ETC2_RGBA8, 40=ASTC_4x4, 44=ASTC_6x6, 47=ASTC_8x8,
  17..26=RGBA mentah, 4=RGB565_LE, 16=RGB565, 6=RGB, 102=L8.

ASTC di-decode via `texture2ddecoder` (decode_astc) lalu kanal R/B ditukar.
"""
import struct

try:
    import lz4.block as _lz4
except Exception:
    _lz4 = None

try:
    import texture2ddecoder as _t2d
except Exception:
    _t2d = None


def lz4_decompress_block(data: bytes) -> bytes:
    dec_len, comp_len = struct.unpack_from("<ii", data, 0)
    payload = data[8:8 + comp_len]
    if _lz4 is not None:
        return _lz4.decompress(payload, uncompressed_size=dec_len)
    raise RuntimeError("lz4 tidak tersedia")


def parse_header(d: bytes):
    if d[:4] == b"SCT2":
        doff, = struct.unpack_from("<i", d, 12)
        pf, = struct.unpack_from("<i", d, 20)
        w, h, tw, th, flags = struct.unpack_from("<HHHHI", d, 24)
        return dict(kind="SCT2", data_off=doff, pixfmt=pf, w=w, h=h,
                    tw=tw, th=th, flags=flags, raw=bool(flags & 0x10),
                    has_alpha=bool(flags & 1), compressed=bool(flags & 0x80))
    if len(d) >= 9 and d[:2] == b"SC":
        pf = d[4]
        w, h = struct.unpack_from("<HH", d, 5)
        return dict(kind="SCT", data_off=9, pixfmt=pf, w=w, h=h, tw=w, th=h,
                    flags=0, raw=False, has_alpha=False, compressed=True)
    raise ValueError("bukan SCT/SCT2")


def _astc(raw: bytes, w: int, h: int, bw: int, bh: int) -> bytes:
    if _t2d is None:
        raise RuntimeError("texture2ddecoder tidak tersedia")
    try:
        return _t2d.decode_astc(raw, w, h, bw, bh)
    except TypeError:
        buf = bytearray(w * h * 4)
        _t2d.decode_astc(raw, w, h, bw, bh, buf)
        return bytes(buf)


def _etc2a8(raw: bytes, w: int, h: int) -> bytes:
    try:
        return _t2d.decode_etc2a8(raw, w, h)
    except TypeError:
        buf = bytearray(w * h * 4)
        _t2d.decode_etc2a8(raw, w, h, buf)
        return bytes(buf)


def _rgb565(raw: bytes, w: int, h: int, swap: bool) -> bytes:
    out = bytearray(w * h * 4)
    for i in range(w * h):
        v = raw[i * 2] | (raw[i * 2 + 1] << 8)
        r = (v >> 11) & 0x1F
        g = (v >> 5) & 0x3F
        b = v & 0x1F
        r = (r << 3) | (r >> 2)
        g = (g << 2) | (g >> 4)
        b = (b << 3) | (b >> 2)
        o = i * 4
        out[o], out[o + 1], out[o + 2], out[o + 3] = (b, g, r, 255) if swap else (r, g, b, 255)
    return bytes(out)


def decode_to_rgba(d: bytes):
    """Kembalikan (width, height, bytes RGBA)."""
    hdr = parse_header(d)
    w, h, pf = hdr["w"], hdr["h"], hdr["pixfmt"]
    img = d[hdr["data_off"]:]

    # ---- decompress bila perlu ----
    def _try_lz4(b):
        try:
            return lz4_decompress_block(b)
        except Exception:
            return None

    want_px = None
    if pf in (40, 44, 47):
        bw = 4 if pf == 40 else (6 if pf == 44 else 8)
        want_px = ((w + bw - 1) // bw) * ((h + bw - 1) // bw) * 16
    elif pf == 19:
        want_px = ((w + 3) // 4) * ((h + 3) // 4) * 16
    elif pf in (4, 16):
        want_px = w * h * 2
    elif pf == 102:
        want_px = w * h
    elif 17 <= pf <= 26:
        want_px = w * h * 4

    if want_px and len(img) != want_px:
        dec = _try_lz4(img)
        if dec:
            img = dec
    if hdr["kind"] == "SCT" or (want_px and len(img) != want_px):
        dec = _try_lz4(img)
        if dec:
            img = dec

    # ---- decode piksel ----
    if pf == 40:
        rgba = _astc(img, w, h, 4, 4)
    elif pf == 44:
        rgba = _astc(img, w, h, 6, 6)
    elif pf == 47:
        rgba = _astc(img, w, h, 8, 8)
    elif pf == 19:
        rgba = _etc2a8(img, w, h)
    elif pf == 4:
        rgba = _rgb565(img, w, h, swap=True)
    elif pf == 16:
        rgba = _rgb565(img, w, h, swap=False)
    elif pf == 6:
        out = bytearray(w * h * 4)
        for i in range(w * h):
            out[i * 4:i * 4 + 3] = img[i * 3:i * 3 + 3]
            out[i * 4 + 3] = 255
        rgba = bytes(out)
    elif pf == 102:
        out = bytearray(w * h * 4)
        for i in range(w * h):
            v = img[i]
            out[i * 4] = out[i * 4 + 1] = out[i * 4 + 2] = v
            out[i * 4 + 3] = 255
        rgba = bytes(out)
    elif 17 <= pf <= 26:
        rgba = img[:w * h * 4]
    else:
        raise ValueError(f"pixfmt belum didukung: {pf}")

    # ASTC: texture2ddecoder mengembalikan BGRA -> tukar R/B
    if pf in (40, 44, 47):
        b = bytearray(rgba)
        b[0::4], b[2::4] = rgba[2::4], rgba[0::4]
        rgba = bytes(b)
    return w, h, rgba
