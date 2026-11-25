#!/usr/bin/env python3
"""Susun data adegan H-scene CherryTale untuk viewer.

Adopsi cara repo CherryTale_Standalone: sumber urutan, voice, SFX, dan teks
adalah skrip asli `StoryHData.txt` (kolom `spineAnimName`, `charSound`,
`sceneSound`, `sceneSoundInterval`, `music`, `text`), dengan terjemahan EN di
`dump/hscene_en/storyhdata_EN_full.txt` yang dipasangkan per indeks baris.

Tiap fase = satu pergantian animasi; semua baris dialog di antaranya ikut
fase itu (voice, SFX loop, teks). Skin + animasi lapisan tetap diambil dari
tabel `SecretHCGClickGameScenesData` supaya fase memakai kostum yang benar.

Keluaran: data/cherrytale-scenes.json
    { "<model id>": { "phases": [{label, anim, skins, mix, seconds,
                                  lines: [{text, textZh, speaker, voice, seconds}]}],
                      "bgm": url|null, "audio": {lang, tracks} } }

Pemakaian
    /srv/venv-spine/bin/python tools/build-cherrytale-scenes.py
    /srv/venv-spine/bin/python tools/build-cherrytale-scenes.py --only a007_04
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import sys
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
_spec = importlib.util.spec_from_file_location("ex", os.path.join(HERE, "extract-cherrytale.py"))
_ex = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_ex)
BASE_URL, UA, decrypt = _ex.BASE_URL, _ex.UA, _ex.decrypt

import UnityPy  # noqa: E402

IDX = os.path.join(ROOT, "cache", "cherrytale", "idx")
INDEX_FILE = "index.txt.da878ac4b4769f289fed678c3fe8d3a2"
SCENE_CACHE = os.path.join(ROOT, "cache", "cherrytale", "storyshow")
ASSETS = os.path.join(ROOT, "assets", "cherrytale")
OUT = os.path.join(ROOT, "data", "cherrytale-scenes.json")
MODELS = os.path.join(ROOT, "cache", "models-cherrytale.json")

STORY = os.environ.get("STORY_DATA", "/opt/cherrytale/dump/textassets/StoryHData.txt")
STORY_EN = os.environ.get(
    "STORY_EN", "/opt/cherrytale/dump/hscene_en/storyhdata_EN_full.txt"
)
SCENES_DATA = os.environ.get(
    "SCENES_DATA", "/opt/cherrytale/dump/textassets/SecretHCGClickGameScenesData.txt"
)

DEFAULT_SECONDS = 2.0
MIN_LINE_SECONDS = 2.2
MAX_LINE_SECONDS = 12.0
TAIL_ORDER = ("Finishing", "Finished", "Cum", "End")
ROLE_COLS = (("Idle", 3, 4, None), ("Spasm", 5, 4, None),
             ("Insert", 6, 7, 8), ("Thrust", 9, 10, 11))
BGM_DIR = "__bgm"


# --------------------------------------------------------------------------
# util
# --------------------------------------------------------------------------
def scene_of(model_id: str) -> tuple[str, str, str] | None:
    m = re.match(
        r"^cherrytale/img_(?:hcg|cg)_dynamic_(.+?)(?:_hcg(\d+)(?:_(\d+))?)?_spine$",
        model_id,
    )
    if not m:
        return None
    return m.group(1), m.group(2) or "", m.group(3) or ""


def story_keys(base: str, hcg: str) -> list[str]:
    if not hcg:
        return [f"{base}_sh", f"{base}_cg_sh"]
    return [f"{base}_hcg{int(hcg):02d}_sh", f"{base}_hcg{int(hcg)}_sh", f"{base}_sh"]


def clip_url(dirname: str, clip: str) -> str:
    safe = re.sub(r"[^\w.\-]", "_", clip)
    return "/cherrytale-audio/" + dirname + "/" + safe + ".opus"


def humanize(anim: str) -> str:
    return anim.replace("_", " ")


def invalidate_model_cache() -> None:
    for name in ("models-cache.json", "models-cache.json.tmp"):
        try:
            os.remove(os.path.join(ROOT, "data", name))
        except OSError:
            pass


# --------------------------------------------------------------------------
# baca sumber
# --------------------------------------------------------------------------
def load_story() -> dict[str, list[dict]]:
    """scene id -> baris dialog (teks EN dipasangkan per indeks)."""
    raw = open(STORY, encoding="utf-8", errors="ignore").read().splitlines()
    head = [h.strip().rstrip("┤") for h in raw[0].split("|")]
    idx = {name: head.index(name) for name in
           ("id", "text", "speakerNote", "charSound", "music",
            "sceneSound", "sceneSoundTimes", "sceneSoundInterval", "spineAnimName")}
    en = []
    try:
        en = open(STORY_EN, encoding="utf-8", errors="ignore").read().splitlines()
    except OSError:
        print(f"terjemahan EN tidak ada ({STORY_EN}); teks EN dikosongkan", file=sys.stderr)

    out: dict[str, list[dict]] = {}
    for i, line in enumerate(raw[1:]):
        parts = line.split("|")
        if len(parts) <= idx["spineAnimName"]:
            continue
        sid = parts[idx["id"]].strip().lower()
        text_zh = parts[idx["text"]].strip()
        text_en = en[i].strip() if i < len(en) else ""
        if not text_zh and not text_en:
            continue
        anims = [a for a in parts[idx["spineAnimName"]].split("$") if a and a.strip() != "-1"]
        voice = parts[idx["charSound"]].strip()
        out.setdefault(sid, []).append({
            "text": text_en or text_zh,
            "textZh": text_zh,
            "speaker": (
                "" if parts[idx["speakerNote"]].strip() in ("", "-1")
                else re.sub(r"<[^>]+>", "", parts[idx["speakerNote"]]).strip()
            ),
            "voice": None if voice in ("", "-1") else voice,
            "anims": [a.strip() for a in anims],
            "bgm": None if parts[idx["music"]].strip() in ("", "-1") else parts[idx["music"]].strip(),
        })
    return out


def load_scenes_table(path: str) -> dict[str, list[str]]:
    rows: dict[str, list[str]] = {}
    try:
        lines = open(path, encoding="utf-8", errors="ignore").read().splitlines()
    except OSError:
        print(f"tabel adegan tidak ada ({path}); skin tidak terisi", file=sys.stderr)
        return rows
    for line in lines[1:]:
        parts = line.split("|")
        if len(parts) > 11 and parts[2]:
            key = re.sub(r"_hcg\d+$", "", re.sub(r"_sh$", "", parts[2].lower()))
            rows.setdefault(key, parts)
    return rows


def cells(row: list[str], i: int | None) -> list[str]:
    if i is None or i >= len(row):
        return []
    raw = row[i].strip()
    if raw in ("", "-1"):
        return []
    return [v for v in (x.strip() for x in raw.split("$")) if v]


def verify_clip(env: "UnityPy.environment.Environment", wants: set[str]) -> str | None:
    for obj in env.objects:
        if str(obj.type) != "83":
            continue
        name = getattr(obj.read(), "m_Name", "")
        if name in wants:
            return name
    return None


def clip_durations(clips: dict[str, float]) -> dict[str, float]:
    return clips


def fetch(url: str, dest: str) -> bytes:
    if os.path.exists(dest) and os.path.getsize(dest) > 1024:
        return open(dest, "rb").read()
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    data = urllib.request.urlopen(req, timeout=120).read()
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    open(dest, "wb").write(data)
    return data


def storyshow_clips(base: str, hcg: str, var: str, index: dict) -> dict[str, float]:
    """Durasi AnimationClip per nama (untuk panjang fase)."""
    stem = (f"assets_resources_versionshare_baseassets_storyobject_animator_"
            f"storyshow_{base}_hcg{int(hcg):02d}")
    for name in ([stem, f"{stem}_{var}"] if var else [stem]):
        entry = index.get(name)
        if not entry:
            continue
        try:
            raw = fetch(f"{BASE_URL}{name}.{entry[1]}", os.path.join(SCENE_CACHE, name))
        except Exception:
            continue
        env = None
        for blob in (raw, decrypt(raw)):
            try:
                env = UnityPy.load(blob)
                break
            except Exception:
                continue
        if env is None:
            continue
        out: dict[str, float] = {}
        for obj in env.objects:
            if str(obj.type) != "74":
                continue
            try:
                rr, tt = obj.read(), obj.read_typetree()
            except Exception:
                continue
            stop = tt.get("m_MuscleClip", {}).get("m_StopTime")
            if rr.m_Name and isinstance(stop, float) and stop > 0:
                out[rr.m_Name] = round(stop, 3)
        if out:
            return out
    return {}


# --------------------------------------------------------------------------
# perakitan
# --------------------------------------------------------------------------
def phase_for_anim(anims: list[str], row: list[str] | None,
                   used_roles: dict[str, int]) -> tuple[list[str], list[str], list[str]]:
    """(skins, mix, sisa anim) untuk satu pergantian animasi."""
    primary, *rest = anims
    if not row:
        return [], rest, []
    idle, click, fever = cells(row, 4), cells(row, 7), cells(row, 10)
    click_mix, fever_mix = cells(row, 8), cells(row, 11)
    pairs = {
        cells(row, 3)[0] if cells(row, 3) else None: (idle, []),
        cells(row, 5)[0] if cells(row, 5) else None: (idle, []),
        cells(row, 6)[0] if cells(row, 6) else None: (click, [m for m in click_mix]),
        cells(row, 9)[0] if cells(row, 9) else None: (fever, [m for m in fever_mix]),
    }
    if primary in pairs:
        skins, mix = pairs[primary]
    else:
        # Animasi di luar tabel (mis. Manbody_02): pakai skin menurut
        # kelompoknya, bukan skin kosong.
        if primary.startswith("Insert"):
            skins, mix = click, click_mix
        elif primary.startswith(TAIL_ORDER):
            skins, mix = fever, fever_mix
        else:
            skins, mix = idle, []
    used_roles[primary] = used_roles.get(primary, 0) + 1
    return skins, mix, rest


def main() -> None:
    global STORY, STORY_EN
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", help="substring id model")
    ap.add_argument("--story", default=STORY)
    ap.add_argument("--story-en", default=STORY_EN)
    ap.add_argument("--scenes-data", default=SCENES_DATA)
    args = ap.parse_args()

    STORY, STORY_EN = args.story, args.story_en

    index = json.load(open(os.path.join(IDX, INDEX_FILE), encoding="utf-8"))
    story = load_story()
    scenes = load_scenes_table(args.scenes_data)
    models = {m["id"]: m for m in json.load(open(MODELS, encoding="utf-8"))["models"]}
    meta = {}
    try:
        meta = json.load(open(os.path.join(ASSETS, "__audio-meta.json"), encoding="utf-8"))
    except OSError:
        pass

    targets = [mid for mid in models if models[mid].get("animations")]
    if args.only:
        targets = [m for m in targets if args.only in m]

    out: dict[str, dict] = {}
    for mid in targets:
        model = models[mid]
        anims = set(model.get("animations") or [])
        sc = scene_of(mid)
        if not sc:
            # Model yang tidak memakai pola img_*_dynamic_* (mainui, slot):
            # tetap dapat timeline dari daftar animasinya.
            sc = (re.sub(r"_spine$", "", mid.split("/", 1)[1]), "", "")
        lines = next((story[k] for k in story_keys(sc[0], sc[1]) if k in story), None)
        row = scenes.get(re.sub(r"_hcg\d+$", "", f"{sc[0]}_hcg{int(sc[1]):02d}")) if sc[1] else None
        clips = storyshow_clips(*sc, index) if sc[1] else {}

        # Voice: berkas hasil extractor beraudio berurutan sesuai nomor klip.
        tracks_meta: dict[str, float] = {}
        voice_meta_path = os.path.join(ASSETS, mid.split("/", 1)[1], "audio", "_index.json")
        if os.path.exists(voice_meta_path):
            try:
                for t in json.load(open(voice_meta_path)).get("tracks", []):
                    n = re.search(r"(\d+)", t.get("voice") or t.get("file") or "")
                    if n:
                        tracks_meta[n.group(1)] = float(t.get("seconds") or 0)
            except Exception:
                tracks_meta = {}

        phases: dict[str, dict] = {}
        order: list[str] = []
        current: str | None = None
        used_roles: dict[str, int] = {}
        bgm = None
        for ln in lines or []:
            anims_line = [a for a in ln["anims"] if a in anims]
            voice = None
            if ln["voice"]:
                n = re.search(r"_(\d+)$", ln["voice"])
                if n and n.group(1) in tracks_meta:
                    voice = n.group(1)
            seconds = default_line_seconds(ln, tracks_meta.get(voice or "")) if voice or ln["text"] else 0
            if anims_line:
                primary = anims_line[0]
                if primary != current:
                    current = primary
                    if primary not in phases:
                        skins, mix, _rest = phase_for_anim(anims_line, row, used_roles)
                        phases[primary] = {
                            "label": humanize(primary),
                            "anim": primary,
                            "skins": skins,
                            "mix": [m for m in mix if m in anims],
                            "lines": [],
                            "seconds": 0.0,
                        }
                        order.append(primary)
                    elif primary == current:
                        # Animasi sama muncul lagi: pakai skin fase berikutnya.
                        skins, mix, _ = phase_for_anim(anims_line, row, used_roles)
                        if skins:
                            phases[primary]["skins"] = skins
                    if _rest:
                        phases[primary]["mix"] = list(
                            dict.fromkeys(phases[primary]["mix"] + [a for a in _rest if a in anims])
                        )
            if current is None:
                # Prolog sebelum animasi pertama: fase Idle dari tabel bila ada.
                idle = cells(row, 3)[0] if row else ""
                if idle and idle in anims:
                    current = idle
                    phases.setdefault(idle, {
                        "label": humanize(idle), "anim": idle,
                        "skins": cells(row, 4), "mix": [], "lines": [], "seconds": 0.0,
                    })
                    order.append(idle)
                else:
                    current = "__prolog__"
                    phases[current] = {"label": "Prolog", "anim": "", "skins": [],
                                       "mix": [], "lines": [], "seconds": 0.0}
                    order.append(current)
            phases[current]["lines"].append({
                "text": ln["text"], "textZh": ln["textZh"], "speaker": ln["speaker"],
                "voice": f"/cherrytale-audio/{mid.split('/', 1)[1]}/audio/{voice}.opus" if voice else None,
                "seconds": seconds,
            })
            bgm = bgm or (clip_url(BGM_DIR, ln["bgm"]) if ln["bgm"] in (meta.get("bgm") or {}) else None)

        # Model tanpa baris ber-anim tetap butuh fase dari tabel.
        if not order and row:
            for role, ai, si, mi in ROLE_COLS:
                anim = (cells(row, ai) or [""])[0]
                if not anim or anim not in anims:
                    continue
                order.append(anim)
                phases[anim] = {
                    "label": humanize(anim), "anim": anim,
                    "skins": cells(row, si),
                    "mix": [m for m in cells(row, mi) if m in anims],
                    "lines": [], "seconds": clips.get(anim, DEFAULT_SECONDS),
                }
        if not order:
            # Model CG / HCG tanpa skrip: bangun fase dari daftar animasi
            # skeleton sendiri (urutan data asli), lewati animasi penanda
            # `_mark` tapi mainkan sebagai lapisan kalau ada pendampingnya.
            ordered = [a for a in (model.get("animations") or []) if a in anims]
            base_anims = [a for a in ordered if not a.endswith("_mark")][:16]
            for anim in base_anims:
                order.append(anim)
                phases[anim] = {
                    "label": humanize(anim), "anim": anim,
                    "skins": [], "mix": [f"{anim}_mark"] if f"{anim}_mark" in anims else [],
                    "lines": [], "seconds": 3.0,
                }
        if not order:
            continue

        phase_list = []
        for key in order:
            ph = phases[key]
            if not ph["anim"] and len(order) == 1:
                # Prolog sendirian: pakai animasi pertama yang ada di skeleton.
                ph["anim"] = next(iter(sorted(anims)), "")
                ph["label"] = humanize(ph["anim"])
            if not ph["anim"]:
                continue
            voice_seconds = sum(ln["seconds"] for ln in ph["lines"])
            ph["seconds"] = max(
                clips.get(ph["anim"], 0) or 0,
                voice_seconds,
                DEFAULT_SECONDS,
            )
            ph["seconds"] = round(min(ph["seconds"], 60.0), 3)
            phase_list.append(ph)
        if not phase_list:
            continue

        tracks = [
            f"/cherrytale-audio/{mid.split('/', 1)[1]}/audio/{n}.opus"
            for n in sorted(tracks_meta, key=lambda x: int(x))
        ]
        touch: list[str] = []
        touch_meta = os.path.join(ASSETS, mid.split("/", 1)[1], "audio", "touch", "_index.json")
        if os.path.exists(touch_meta):
            try:
                for t in json.load(open(touch_meta)).get("tracks", []):
                    if t.get("file"):
                        touch.append(
                            f"/cherrytale-audio/{mid.split('/', 1)[1]}/audio/touch/{t['file']}"
                        )
            except Exception:
                touch = []
        out[mid] = {
            "phases": phase_list,
            "bgm": bgm,
            "audio": {"lang": "JP", "tracks": tracks} if tracks else None,
            "touch": touch,
            "source": "story" if lines else ("scenes" if row else "anims"),
        }

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(out, open(OUT, "w"), ensure_ascii=False, separators=(",", ":"))
    invalidate_model_cache()
    lines_total = sum(len(p["lines"]) for v in out.values() for p in v["phases"])
    voiced = sum(1 for v in out.values() for p in v["phases"] for ln in p["lines"] if ln["voice"])
    print(f"{len(out)} scene, {lines_total} baris ({voiced} voice), "
          f"{sum(1 for v in out.values() if v['touch'])} bertouch-voice, "
          f"{sum(1 for v in out.values() if v['bgm'])} ber-BGM -> {OUT}")


def default_line_seconds(line: dict, voice_seconds: float | None) -> float:
    if voice_seconds:
        return round(min(MAX_LINE_SECONDS, max(MIN_LINE_SECONDS, voice_seconds + 0.6)), 2)
    est = len(line.get("text") or "") * 0.045
    return round(min(MAX_LINE_SECONDS, max(MIN_LINE_SECONDS, est)), 2)


if __name__ == "__main__":
    main()
