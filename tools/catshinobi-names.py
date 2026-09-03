"""Build data/catshinobi-names.json: model folder -> character name.

Source: the game's own Unity Localization string tables.
    SharedTableData    : m_Id -> key   (UI_CHARACTER_NAME_<id>, UI_COSTUME_NO_<id>)
    StringTable_en/id/ja: m_Id -> text

The skeleton folders use ids the tables only partially cover. Observed shape:
    10001 / 10011 / 1900 / 1100  -> character base 1001  ("Mei Kaminari")
    10001                        -> costume 10001 or variant of 1001
The tables hold the BASE ids (1001, 2001, ... 27001) plus a handful of
costume ids. So the lookup walks outward from the folder id:
    1. exact id in characters
    2. exact id in costumes
    3. nearest lower base id in characters sharing the leading digits
       (10003 -> 1001, 19011 -> 19001 -> ... -> 1001)

Output shape matches what the viewer's name maps use: keyed by model id
(catshinobi/<folder>) with {name, costume, ja, id_local}.
"""
import json
import os
import re
import sys

import UnityPy

BUNDLE_DIR = "/srv/spine-assets/catshinobi-apk/bundles/assets/aa/Android"
ASSETS = "/srv/spine-assets/catshinobi"
OUT = "/srv/spine-viewer/data/catshinobi-names.json"
MONOBEHAVIOUR = 114

LOCALES = {"en": "(en)", "id": "(id)", "ja": "(ja)"}


def type_id(obj):
    t = obj.type
    try:
        v = getattr(t, "value", t)
        if isinstance(v, int):
            return v
        s = str(v)
        return int(s) if s.isdigit() else -1
    except Exception:
        return -1


def find_lists(tree, key, depth=0, out=None):
    if out is None:
        out = []
    if depth > 10:
        return out
    if isinstance(tree, dict):
        for k, v in tree.items():
            if k == key and isinstance(v, list):
                out.append(v)
            else:
                find_lists(v, key, depth + 1, out)
    elif isinstance(tree, (list, tuple)):
        for v in tree:
            find_lists(v, key, depth + 1, out)
    return out


def load_shared():
    env = UnityPy.load(os.path.join(BUNDLE_DIR, "localization-assets-shared_assets_all.bundle"))
    m = {}
    for obj in env.objects:
        if type_id(obj) != MONOBEHAVIOUR:
            continue
        try:
            tree = obj.read_typetree()
        except Exception:
            continue
        for lst in find_lists(tree, "m_Entries"):
            for e in lst:
                if isinstance(e, dict) and "m_Key" in e and e.get("m_Id") is not None:
                    m[int(e["m_Id"])] = str(e["m_Key"])
    del env
    return m


def load_locale(frag):
    f = [x for x in os.listdir(BUNDLE_DIR)
         if "localization-string-tables" in x and frag in x]
    if not f:
        return {}
    env = UnityPy.load(os.path.join(BUNDLE_DIR, f[0]))
    m = {}
    for obj in env.objects:
        if type_id(obj) != MONOBEHAVIOUR:
            continue
        try:
            tree = obj.read_typetree()
        except Exception:
            continue
        if not str(tree.get("m_Name", "")).startswith("StringTable"):
            continue
        for lst in find_lists(tree, "m_TableData"):
            for e in lst:
                if isinstance(e, dict) and e.get("m_Id") is not None:
                    m[int(e["m_Id"])] = e.get("m_Localized")
    del env
    return m


def clean(v):
    if not isinstance(v, str):
        return None
    t = re.sub(r"<[^>]*>", "", v)
    t = re.sub(r"\{[^{}]*\}", "", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t or None


def strip_affix(name):
    """'Ryo Nakatsukami "Summer Violet"' -> ('Ryo Nakatsukami', 'Summer Violet').

    Also normalises the two orderings the table uses inconsistently: some
    entries are "Given Family" (Hisui Nanagi) and some "Family Given"
    (Hino Madoka). Left as-is -- flipping them would need a name list, and a
    wrong flip is worse than a slightly odd order. We only trim the trailing
    dash from entries like 'Hisui Nanagi –' that lost their costume half.
    """
    if not name:
        return None, None
    name = re.sub(r"[\s–—-]+$", "", name)          # trailing dash / whitespace
    m = re.match(r'^(.*?)\s*["「”“\'](.+?)["」”’\']\s*$', name)
    if m:
        return m.group(1).strip(), m.group(2).strip()
    m = re.match(r'^(.*?)\s*[–—-]\s*["「](.+?)["」]\s*$', name)
    if m:
        return m.group(1).strip(), m.group(2).strip()
    return name.strip(), None


def main():
    shared = load_shared()
    locales = {c: load_locale(f) for c, f in LOCALES.items()}
    print("shared:", len(shared), "| locales:", {c: len(m) for c, m in locales.items()})

    chars, costumes = {}, {}
    for i, key in shared.items():
        vals = {c: clean(m.get(i)) for c, m in locales.items()}
        if not vals.get("en"):
            continue
        m = re.match(r"^UI_CHARACTER_NAME_(\d+)$", key)
        if m:
            chars[m.group(1)] = vals
            continue
        m = re.match(r"^UI_COSTUME_NO_(\d+)$", key)
        if m:
            costumes[m.group(1)] = vals

    print("karakter:", len(chars), "| costume:", len(costumes))

    base_ids = sorted(chars, key=lambda x: int(x))

    def resolve(n):
        """Folder id -> (character entry, costume entry, how).

        Only two matches are trustworthy:
          exact-char  -- the folder id IS a UI_CHARACTER_NAME_<id>
          base(...)   -- the folder id shares the character's leading digits
                         (10003/10011/10020 all belong to base 10001)

        Everything else is left unnamed. A previous version also fell back to
        "nearest lower base id with the same leading digit", which invented
        names: Char_10100 was labelled a character it has nothing to do with.
        A wrong name is worse than no name -- the folder id is already shown
        in the UI, so an unmapped model is still identifiable.
        """
        if n in chars:
            return chars[n], costumes.get(n), "exact-char"
        cost = costumes.get(n)
        if cost:
            for b in (n, n[:-1], n[:4], n[:3]):
                if b in chars:
                    return chars[b], cost, "costume->base"
            return None, cost, "costume-only"
        # Share the character's base id: 10003/10011/10020 all belong to
        # 10001. The rule is the first THREE digits must match, so 10100
        # (a different sub-series) does NOT inherit Mei Kaminari -- it stays
        # unnamed rather than being given a name it has no claim to.
        for b in base_ids:
            if len(b) == len(n) and b != n and b.endswith("01") and b[:3] == n[:3]:
                return chars[b], None, f"base({b})"
        return None, None, None

    folders = sorted(os.listdir(ASSETS))
    out_models = {}
    stats = {"exact-char": 0, "costume->base": 0, "costume-only": 0, "base": 0,
             "nearest": 0, "none": 0}

    for f in folders:
        m = re.search(r"(\d{3,6})", f)
        entry = None
        how = None
        if m:
            ch, co, how = resolve(m.group(1))
            # Only the Char_* family (and its Char_SD_*/Char_LD_* variants)
            # uses character ids. In cat_battle_mode_* / cat_front_mode_* /
            # cat_ninja_* / monster_* the number is an animation or monster
            # index, NOT a character id.
            #
            # It collides by accident: 34001 exists in the character table, so
            # cat_battle_mode_34001..34011 -- eleven different cat animations
            # -- all claimed the name "Enma Yozakura". A wrong name is worse
            # than no name, so these families are left unnamed.
            if ch and not re.match(r"^Char(_(SD|LD))?_", f):
                ch, how = None, "family-mismatch"
            if ch:
                name, costume_from_name = strip_affix(ch.get("en"))
                ja_name, _ = strip_affix(ch.get("ja"))
                costume = (co or {}).get("en") or costume_from_name
                entry = {
                    "name": name,
                    "costume": costume,
                    "ja": ja_name,
                    "id_local": ch.get("id"),
                    "match": how,
                }
                key = how.split("(")[0]
                stats[key if key in stats else "none"] = stats.get(
                    key if key in stats else "none", 0) + 1
            else:
                stats["none"] += 1
        else:
            stats["none"] += 1
        if entry:
            out_models[f"catshinobi/{f}"] = entry

    print("\n=== statistik pencocokan ===")
    for k, v in stats.items():
        print(f"  {v:5d}  {k}")
    print(f"\nmodel diberi nama: {len(out_models)} / {len(folders)}")

    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump({
            "source": "com.cookapps.catshinobi Unity Localization string tables",
            "locales": sorted(LOCALES),
            "characters": chars,
            "costumes": costumes,
            "models": out_models,
        }, fh, ensure_ascii=False, indent=1)
    print("disimpan:", OUT)

    print("\n=== contoh ===")
    for k in list(out_models)[:15]:
        e = out_models[k]
        print(f"   {k.split('/')[1]:24s} -> {e['name']}" +
              (f"  [{e['costume']}]" if e.get("costume") else "") +
              f"   ({e['match']})")


if __name__ == "__main__":
    main()
