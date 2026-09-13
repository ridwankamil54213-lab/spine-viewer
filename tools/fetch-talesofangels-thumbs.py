#!/usr/bin/env python3
"""Generate per-model thumbnails for Tales of Angels by rendering the models.

Why not read the atlas: a Spine atlas is a *texture packing*, not a layout.
Each attachment rectangle sits wherever it fits on the page, so stitching
`bounds:` back into a canvas produces a scrambled collage, not the character.
The only faithful picture is the assembled skeleton, so this script drives the
viewer itself in a headless browser and screenshots the stage canvas.

Framing rules learned the hard way:
  * The viewer's `fit` (key "0") fits the *setup pose*. A running animation can
    push the character past that, so a plain fit still crops hats and arms.
    Pause first, then zoom out one step at a time until nothing touches an edge.
  * The grid (key "g") and the stats HUD (#hud) are DOM overlays drawn inside
    the canvas rectangle. Hide them before shooting or they leak into the crop
    and stretch the bounding box.

Requirements:
    pip install playwright Pillow

Usage:
    python3 tools/fetch-talesofangels-thumbs.py [--limit N] [--size 256] [--force]

Writes public/thumbs/talesofangels/icons/<model>.png and merges
public/thumbs/talesofangels/_manifest.json ({ "<game>/<model>": "<game>/icons/<file>.png" }),
the shape /api/thumbnails already serves.
"""

import argparse
import json
import os
import sys
import time

from PIL import Image, ImageChops

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(REPO, "public", "thumbs", "talesofangels", "icons")
MANIFEST = os.path.join(REPO, "public", "thumbs", "talesofangels", "_manifest.json")
CHROME = "/root/.cache/ms-playwright/chromium-1234/chrome-linux64/chrome"
URL = "http://127.0.0.1:3000/"
GAME_TEXT = "Tales of Angels"
GAME_SLUG = "talesofangels"
STAGE_BG = (20, 22, 28)
TOL = 20
ZOOM_OUT_STEPS = 3


def slug(model_id: str) -> str:
    return model_id.replace("/", "_").replace("#", "_")


def content_bbox(im, tol=TOL):
    diff = ImageChops.difference(im.convert("RGB"), Image.new("RGB", im.size, STAGE_BG)).convert("L")
    return diff.point(lambda v: 255 if v > tol else 0).getbbox()


def touches_edge(bb, im):
    if not bb:
        return True
    x0, y0, x1, y1 = bb
    return x0 <= 1 or y0 <= 1 or x1 >= im.width - 2 or y1 >= im.height - 2


def crop_and_fit(img, size):
    bb = content_bbox(img)
    if not bb:
        return None
    img = img.crop(bb)
    if img.width < 8 or img.height < 8:
        return None
    scale = min(size / img.width, size / img.height)
    img = img.resize((max(1, round(img.width * scale)), max(1, round(img.height * scale))), Image.LANCZOS)
    card = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    card.alpha_composite(img.convert("RGBA"), ((size - img.width) // 2, (size - img.height) // 2))
    return card


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="stop after N new icons")
    ap.add_argument("--size", type=int, default=256)
    ap.add_argument("--force", action="store_true", help="re-render icons that already exist")
    args = ap.parse_args()

    from playwright.sync_api import sync_playwright

    os.makedirs(OUT_DIR, exist_ok=True)
    manifest = {}
    if os.path.exists(MANIFEST):
        try:
            manifest = json.load(open(MANIFEST, encoding="utf8"))
        except Exception:
            manifest = {}

    ok = skip = fail = 0
    t0 = time.time()

    with sync_playwright() as p:
        browser = p.chromium.launch(
            executable_path=CHROME,
            args=["--no-sandbox", "--use-gl=swiftshader", "--enable-unsafe-swiftshader"],
        )
        pg = browser.new_page(viewport={"width": 1400, "height": 900}, device_scale_factor=1)
        pg.goto(URL, wait_until="networkidle")
        pg.wait_for_selector(".game", timeout=30000)
        pg.locator(".game", has_text=GAME_TEXT).first.click()
        pg.wait_for_timeout(1500)
        # grid + HUD would otherwise be part of the screenshot
        pg.evaluate("()=>{for(const id of ['grid','hud']){const e=document.getElementById(id);if(e)e.style.visibility='hidden';}}")

        while True:
            count = pg.locator(".model").count()
            for i in range(count):
                btn = pg.locator(".model").nth(i)
                mid = btn.get_attribute("data-id") or ""
                if not mid.startswith(GAME_SLUG + "/"):
                    continue
                name = mid.split("/", 1)[1]
                dest = os.path.join(OUT_DIR, slug(mid) + ".png")
                if not args.force and os.path.exists(dest):
                    skip += 1
                    continue

                btn.click()
                try:
                    pg.wait_for_function(
                        "()=>{const l=document.querySelector('#loading');return !l||l.hidden;}", timeout=30000
                    )
                except Exception:
                    pass
                pg.evaluate("()=>{for(const id of ['grid','hud']){const e=document.getElementById(id);if(e)e.style.visibility='hidden';}}")

                # pause (boot starts playing), fit, then zoom out a little so a
                # mid-animation pose can't poke past the frame. Because the shot
                # is cropped to the content afterwards, the zoom level only
                # affects resolution — so a small fixed zoom-out is enough and
                # avoids probing (and avoids looping forever on full-screen
                # background scenes, which always touch every edge).
                pg.keyboard.press(" ")
                pg.keyboard.press("0")
                pg.wait_for_timeout(200)
                for _ in range(ZOOM_OUT_STEPS):
                    pg.keyboard.press("-")
                pg.wait_for_timeout(250)
                box = pg.locator("canvas").first.bounding_box()

                pg.screenshot(path="/tmp/_toa_shot.png", clip=box)
                card = crop_and_fit(Image.open("/tmp/_toa_shot.png"), args.size)
                if card is None:
                    fail += 1
                    print(f"  FAIL {mid} box={box} (blank canvas?)", flush=True)
                else:
                    card.save(dest, "PNG", optimize=True)
                    manifest[f"{GAME_SLUG}/{name}"] = f"{GAME_SLUG}/icons/{slug(mid)}.png"
                    ok += 1
                pg.keyboard.press(" ")  # resume playback for the next model

                if (ok + fail) % 25 == 0:
                    print(f"  ok={ok} skip={skip} fail={fail}  {time.time()-t0:.0f}s", flush=True)
                if args.limit and ok >= args.limit:
                    break

            if args.limit and ok >= args.limit:
                break
            nxt = pg.locator("#pager button", has_text="›")
            if nxt.count() == 0 or nxt.first.is_disabled():
                break
            nxt.first.click()
            pg.wait_for_timeout(700)

        browser.close()

    with open(MANIFEST, "w", encoding="utf8") as fh:
        json.dump(manifest, fh, indent=1, ensure_ascii=False)
    print(f"\nicons: ok={ok} skip={skip} fail={fail}  ({time.time()-t0:.0f}s)")
    print(f"manifest: {MANIFEST} ({len(manifest)} entries)")


if __name__ == "__main__":
    sys.exit(main())
