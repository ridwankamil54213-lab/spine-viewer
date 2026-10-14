#!/usr/bin/env python3
"""Azur Lane Live2D — konversi Unity AnimationClip -> Cubism motion3.json.

Bundle L2D Azur Lane = Cubism SDK for Unity: motion-nya berupa Unity
`AnimationClip` berformat **muscle/clip terkompresi** (m_StreamedClip + 465
binding CRC32), BUKAN .motion3.json. Viewer hanya bisa memutar motion3.json,
jadi tanpa konversi ini tiap model cuma tampil statis (dropdown animasi = "idle").

Algoritma (diadaptasi dari MrKLLM/azurlane-assetbundle-toolkit
`scripts/extract_motions.py`, terverifikasi lawan ekspor l2d.su):
  - `m_StreamedClip.data` = deret frame: time(f32) + nKeys(i32) + nKeys×[idx,4×f32].
    Frame pertama bertime -FLT_MAX = "reference pose" (nilai dasar tiap kurva;
    JANGAN dibuang — untuk model besar frame ini bisa memuat 300-500 key).
    4 float = [unused, inSlope, outSlope, value].
  - curve index di m_StreamedClip **sejajar** dengan m_ClipBindingConstant.genericBindings.
  - genericBindings[i].path = crc32("<prefix>/<GameObject.name>") dengan prefix
    "Parameters/" (CubismParameter) atau "Parts/" (CubismPart). Nama GameObject
    diambil dari komponen CubismParameter/CubismPart (m_Name komponen KOSONG;
    nama asli ada di GameObject-nya).
  - Segmen linear: [type=0, time, value]. (Resep tervalidasi = LINEAR; kontrol
    bezier Unity tak bisa dipakai langsung sebagai tangent Hermite.)

Keluaran: <model>/motions/<clip>.motion3.json  (dibaca server/viewer apa adanya).

Pakai:
    /srv/venv-spine/bin/python tools/azurlane/extract-azurlane-motions.py <bundle_dir> <out_dir> [--only NAME]
"""
import argparse
import binascii
import io
import json
import os
import struct
import sys
import time

import UnityPy

UnityPy.config.FALLBACK_UNITY_VERSION = "2022.3.62f3"

PARAM_PREFIX = "Parameters/"
PART_PREFIX = "Parts/"
REF_POSE_EPS = 1e30  # Unity reference-pose frame time = -FLT_MAX


def _crc(s):
    return binascii.crc32(s.encode("utf-8")) & 0xFFFFFFFF


def collect_binding_lookup(env):
    """crc32(path) -> (Target, Id) untuk tiap CubismParameter / CubismPart."""
    go_name = {}
    for obj in env.objects:
        if obj.type.name == "GameObject":
            try:
                go_name[obj.path_id] = obj.read().m_Name
            except Exception:
                pass

    comp = {"CubismParameter": set(), "CubismPart": set()}
    for obj in env.objects:
        if obj.type.name != "MonoBehaviour":
            continue
        try:
            data = obj.read()
            sr = getattr(data, "m_Script", None)
            sname = getattr(sr.read(), "m_Name", "") if sr else ""
        except Exception:
            continue
        if sname not in comp:
            continue
        try:
            tt = obj.read_typetree()
            goid = tt.get("m_GameObject", {}).get("m_PathID")
        except Exception:
            continue
        nm = go_name.get(goid)
        if nm:
            comp[sname].add(nm)

    lookup = {}
    for nm in comp["CubismParameter"]:
        lookup[_crc(PARAM_PREFIX + nm)] = ("Parameter", nm)
    for nm in comp["CubismPart"]:
        lookup[_crc(PART_PREFIX + nm)] = ("PartOpacity", nm)
    return lookup


def parse_streamed(streamed_clip):
    data = getattr(streamed_clip, "data", None) or []
    if not data:
        return []
    buf = b"".join(struct.pack("<I", v & 0xFFFFFFFF) for v in data)
    frames, pos = [], 0
    while pos + 8 <= len(buf):
        t = struct.unpack_from("<f", buf, pos)[0]
        pos += 4
        if t == float("inf"):
            break
        n = struct.unpack_from("<i", buf, pos)[0]
        pos += 4
        if n < 0 or pos + n * 20 > len(buf):
            break
        keys = []
        for _ in range(n):
            idx = struct.unpack_from("<i", buf, pos)[0]
            _c1, in_s, out_s, val = struct.unpack_from("<4f", buf, pos + 4)
            pos += 20
            keys.append((idx, val, in_s, out_s))
        frames.append((t, keys))
    return frames


def build_motion(clip, targets):
    muscle = getattr(clip, "m_MuscleClip", None)
    if not muscle or not getattr(muscle, "m_Clip", None):
        return None
    cdata = muscle.m_Clip.data
    streamed = getattr(cdata, "m_StreamedClip", None)
    frames = parse_streamed(streamed) if streamed else []
    if not frames:
        return None

    base, series = {}, {}
    for t, keys in frames:
        if t < -REF_POSE_EPS:
            for idx, v, _i, _o in keys:
                base.setdefault(idx, v)
            continue
        tt = 0.0 if abs(t) < 1e-6 else t
        for idx, v, _i, _o in keys:
            series.setdefault(idx, []).append((tt, v))

    curves, total_seg, total_pts = [], 0, 0
    for idx in sorted(series.keys()):
        tgt = targets[idx] if idx < len(targets) else None
        if not tgt:
            continue
        target, pid = tgt
        pts = sorted(series[idx], key=lambda x: x[0])
        if not pts:
            continue
        if pts[0][0] > 1e-6 and idx in base:
            pts.insert(0, (0.0, base[idx]))
        segs, n_pts = [pts[0][0], pts[0][1]], 1
        for t, v in pts[1:]:
            t0, v0 = segs[-2], segs[-1]
            if t - t0 <= 1e-6:
                continue
            segs.extend([0, t, v])  # linear
            total_seg += 1
            n_pts += 1
        if len(segs) < 4:
            continue
        total_pts += n_pts
        curves.append({"Target": target, "Id": pid, "Segments": segs})

    if not curves:
        return None

    real_t = [t for t, _ in frames if t >= -REF_POSE_EPS]
    duration = round(max(real_t) if real_t else 0.0, 3)
    if duration <= 0:
        st = getattr(muscle, "m_StartTime", 0.0) or 0.0
        sp = getattr(muscle, "m_StopTime", 0.0) or 0.0
        duration = round(sp - st, 3) if sp > st else 0.0

    return {
        "Version": 3,
        "Meta": {
            "Duration": duration,
            "Fps": float(getattr(clip, "m_SampleRate", 0.0) or 30.0),
            "Loop": bool(getattr(muscle, "m_LoopTime", False)),
            "AreBeziersRestricted": True,
            "CurveCount": len(curves),
            "TotalSegmentCount": total_seg,
            "TotalPointCount": total_pts,
            "UserDataCount": 0,
            "TotalUserDataSize": 0,
        },
        "Curves": curves,
        "UserData": [],
        "Physics": None,
    }


def extract_one(path, out_root, verbose=False):
    name = os.path.basename(path)
    data = open(path, "rb").read()
    o = data.rfind(b"UnityFS")
    if o < 0 or b"MOC3" not in data:
        return False, "not a Cubism bundle", 0
    env = UnityPy.load(io.BytesIO(data[o:]))
    lookup = collect_binding_lookup(env)

    target_file = os.path.join(out_root, name)
    motion_dir = os.path.join(target_file, "motions")
    os.makedirs(motion_dir, exist_ok=True)

    ok = fail = 0
    for obj in env.objects:
        if obj.type.name != "AnimationClip":
            continue
        try:
            clip = obj.read()
        except Exception:
            continue
        cname = getattr(clip, "m_Name", "")
        if not cname:
            continue
        targets = []
        bc = getattr(clip, "m_ClipBindingConstant", None)
        for b in list(getattr(bc, "genericBindings", None) or []) if bc else []:
            targets.append(lookup.get(getattr(b, "path", 0) & 0xFFFFFFFF))
        try:
            motion = build_motion(clip, targets)
        except Exception as e:
            if verbose:
                print(f"    [!] {cname}: {e}")
            motion = None
        if not motion:
            fail += 1
            continue
        with open(os.path.join(motion_dir, f"{cname}.motion3.json"), "w", encoding="utf-8") as f:
            json.dump(motion, f, ensure_ascii=False)
        ok += 1
        if verbose:
            m = motion["Meta"]
            print(f"    {cname:<22} curves={m['CurveCount']:<5} dur={m['Duration']:<8} loop={m['Loop']}")
    return ok > 0, f"{ok} motion (gagal {fail})", ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src")
    ap.add_argument("out")
    ap.add_argument("--only")
    ap.add_argument("--verbose", action="store_true")
    a = ap.parse_args()
    files = sorted(f for f in os.listdir(a.src) if os.path.isfile(os.path.join(a.src, f)))
    if a.only:
        files = [f for f in files if f == a.only]
    os.makedirs(a.out, exist_ok=True)
    t0, ok = time.time(), 0
    for i, fn in enumerate(files, 1):
        good, msg, n = extract_one(os.path.join(a.src, fn), a.out, verbose=a.verbose)
        if good:
            ok += 1
        else:
            print(f"  [-] {fn}: {msg}", flush=True)
        if i % 20 == 0 or a.only:
            print(f"  ..{i}/{len(files)} ok={ok} ({time.time()-t0:.0f}s)", flush=True)
    print(f"  SELESAI {len(files)} model, {ok} dapat motion ({time.time()-t0:.0f}s)")


if __name__ == "__main__":
    main()
