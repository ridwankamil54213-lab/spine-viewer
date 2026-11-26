#!/usr/bin/env python3
"""Ekstrak state kamera LoveTalk (CG) dari bundle Ark Re:Code.

CG "LoveTalk" (mis. A0016) bukan animasi karakter: 20 state di
H015_LoveTalk_03_Controller semuanya menggerakkan TRANSFORM node Spine
(posisi + rotasi + skala) — itulah "kamera"-nya. Animasi 01_Idle_ani dst.
adalah animasi Spine biasa dan sudah tampil di viewer.

Keluaran: data/arkrecode-lovetalk.json
    { "<model id>": { "unit": <skeleton unit per local unit>,
                      "states": [ {name, pos, rot, scale, dur} ] } }

`unit` dipakai viewer untuk mengubah posisi lokal node menjadi unit skeleton:
    q = p / unit      (lihat README "LoveTalk")

Pemakaian
    /srv/venv-spine/bin/python tools/extract-arkrecode-lovetalk.py --only A0016
"""
from __future__ import annotations

import argparse
import io
import json
import os
import re
import ssl
import urllib.request
import zlib

import UnityPy

UnityPy.config.FALLBACK_UNITY_VERSION = "2022.3.62f2"

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT = os.path.join(ROOT, "data", "arkrecode-lovetalk.json")
CATALOG = os.path.join(ROOT, "cache", "arkrecode", "catalog_116310.json")
CACHE = os.path.join(ROOT, "cache", "arkrecode", "lovetalk")
CDN = "https://erdpu.gzxhcjz.com/GamePatch/Android/"
UA = {"User-Agent": "UnityPlayer/2022.3.28f1 (UnityWebRequest/1.0, libcurl/8.5.0-DEV)"}
CTX = ssl._create_unverified_context()

# Transform binding: 1 = pos.xyz, 2 = rot.xyz (customType 4), 3 = scale.xyz
POS, ROT, SCALE = 1, 2, 3


def fetch(url: str) -> bytes:
    os.makedirs(CACHE, exist_ok=True)
    dest = os.path.join(CACHE, os.path.basename(url))
    if os.path.exists(dest) and os.path.getsize(dest) > 1024:
        return open(dest, "rb").read()
    req = urllib.request.Request(url, headers=UA)
    data = urllib.request.urlopen(req, timeout=180, context=CTX).read()
    open(dest, "wb").write(data)
    return data


def bundle_for(ids: list[str], model: str) -> str | None:
    """Bundle CG gabungan untuk satu model (yang memuat .skel + controller)."""
    stem = f"/game/cg/{model.lower()}_"
    hits = [
        i for i in ids
        if i.startswith("http") and i.endswith(".bundle")
        and stem in i.lower() and "/img" not in i.lower()
    ]
    if not hits:
        return None
    return sorted(hits, key=len)[0].replace("http://PatchDomain/Android/", CDN)


def state_name(nid: int, clip_names: list[str]) -> str:
    for n in clip_names:
        if zlib.crc32(n.encode()) & 0xFFFFFFFF == nid:
            return n
    return str(nid)


def parse_controller(ctrl, clip_names: list[str]) -> list[dict]:
    """Satu state = satu node blend tree dengan satu clip (tanpa transisi)."""
    out = []
    for sm in ctrl.m_Controller.m_StateMachineArray:
        sm = sm.data
        for st in sm.m_StateConstantArray:
            st = st.data
            nodes = st.m_BlendTreeConstantArray[0].data.m_NodeArray if st.m_BlendTreeConstantArray else []
            if not nodes:
                continue
            node = nodes[0].data
            clip = clip_names[node.m_ClipID] if node.m_ClipID < len(clip_names) else None
            if not clip:
                continue
            out.append({
                "name": state_name(st.m_NameID, clip_names),
                "clip": clip,
                "dur": round(node.m_Duration, 3),
                "stateID": st.m_NameID,
            })
    return out


def clip_transform(clip) -> dict | None:
    """Nilai konstan tiap kurva transform. Clip dense (transisi) dilewati."""
    cd = clip.m_MuscleClip.m_Clip.data
    const = cd.m_ConstantClip.data if cd.m_ConstantClip else None
    if not const or cd.m_DenseClip.m_FrameCount > 2:
        return None
    vals = list(const)
    binds = clip.m_ClipBindingConstant.genericBindings
    pos = rot = scale = None
    for i, b in enumerate(binds):
        v = vals[i * 3:i * 3 + 3]
        if len(v) < 3:
            break
        if b.attribute == POS:
            pos = [round(x, 3) for x in v]
        elif b.attribute == ROT and b.customType == 4:
            rot = [round(x, 3) for x in v]
        elif b.attribute == SCALE:
            scale = [round(x, 3) for x in v]
    if pos is None and scale is None:
        return None
    return {"pos": pos or [0, 0, 0], "rot": rot or [0, 0, 0], "scale": scale or [1, 1, 1]}


def do_model(model: str, ids: list[str]) -> dict | None:
    url = bundle_for(ids, model)
    if not url:
        print(f"  {model}: bundle tidak ada di katalog")
        return None
    env = UnityPy.load(io.BytesIO(fetch(url)))

    clips, ctrls, skel_scale, node_scale = {}, [], None, None
    for o in env.objects:
        t = o.type.name
        if t == "AnimationClip":
            d = o.read()
            clips.setdefault(d.m_Name, d)
        elif t == "AnimatorController":
            d = o.read()
            if "LoveTalk" in d.m_Name or "Love_Talk" in d.m_Name:
                ctrls.append(d)
        elif t == "MonoBehaviour":
            tt = o.read_typetree()
            if "skeletonJSON" in tt and skel_scale is None:
                skel_scale = tt.get("scale")
        elif t == "Transform":
            d = o.read()
            if d.m_LocalScale.x > 1.5 and node_scale is None:
                node_scale = round(d.m_LocalScale.x, 4)

    if not ctrls:
        print(f"  {model}: tidak ada controller LoveTalk")
        return None

    order = [c.read().m_Name for c in ctrls[0].m_AnimationClips]
    states = []
    for st in parse_controller(ctrls[0], order):
        tr = clip_transform(clips[st["clip"]])
        if not tr:
            continue
        states.append({"name": st["name"], "dur": st["dur"], **tr})

    # Rantai asli: A0016_LoveTalk -> HCG(1,25) -> Align_Object(di-animasi)
    # -> Spine(26) -> skeleton(0,01). Skala HCG ada di ATAS Align, jadi tidak
    # mengubah hubungan skeleton<->Align: satu unit skeleton = 26*0,01 unit
    # Align. Viewer menerapkan pos/scale Align sebagai skala-di-origin + geser.
    # Controller A0016 punya "Normal" dua kali (state 0 dan 20) — tombol
    # kembar tidak berguna, ambil yang pertama.
    seen, uniq = set(), []
    for s in states:
        if s["name"] in seen:
            continue
        seen.add(s["name"])
        uniq.append(s)
    # Viewer meniru rantai aslinya, bukan menebak pusat anatomis: Animator
    # menggerakkan Align_Object (induk node Spine berskala 26), jadi pos/rot/
    # scale cukup diterapkan ke kontainer model apa adanya.
    # `unit` = 26 * skel_scale: satu unit skeleton = unit pixel lokal Align.
    unit = round((node_scale or 1) * (skel_scale or 1), 4)
    print(f"  {model}: {len(uniq)} state kamera, unit={unit}")
    return {"unit": unit, "states": uniq}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only")
    ap.add_argument("--all", action="store_true")
    args = ap.parse_args()
    if not args.only and not args.all:
        raise SystemExit("pakai --only <model> atau --all")

    cat = json.load(open(CATALOG, encoding="utf-8"))
    ids = [str(x) for x in cat["m_InternalIds"]]
    models = (
        [args.only.upper()]
        if args.only
        else sorted({
            m.group(1).upper()
            for i in ids
            if (m := re.search(r"/game/cg/([a-z0-9]+)/", i.lower()))
            and any("lovetalk" in x.lower() for x in ids if m.group(1) in x.lower())
        })
    )

    out = {}
    if os.path.exists(OUT):
        out = json.load(open(OUT))
    for m in models:
        got = do_model(m, ids)
        if got:
            out[f"arkrecode/{m}"] = got
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(out, open(OUT, "w"), ensure_ascii=False, separators=(",", ":"))
    print(f"{len(out)} model -> {OUT}")


if __name__ == "__main__":
    main()