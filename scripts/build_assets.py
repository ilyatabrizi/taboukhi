#!/usr/bin/env python3
"""Everything derived from the traced wordmark and the supplied still, in one pass.

    python3 scripts/build_assets.py

  assets/brand/k.svg                    the K alone, the mask for the glass mark
  assets/brand/favicon.svg              the K's two detached strokes, bone on onyx
  assets/brand/favicon-48.png, apple-touch-icon.png
  assets/og.jpg                         1200x630 share card, cut from their own still
"""
import pathlib
import re

from PIL import Image, ImageEnhance
from playwright.sync_api import sync_playwright

ROOT = pathlib.Path(__file__).resolve().parent.parent
BRAND = ROOT / "assets" / "brand"
ONYX, BONE = "#020202", "#F4F2ED"

svg = (BRAND / "wordmark.svg").read_text()
paths = dict(re.findall(r'<path id="(l-\w)" d="([^"]+)"', svg))
assert len(paths) == 8, "the trace must carry eight letters"
K = paths["l-k"]
assert K.count("M") == 2, "the K is two detached strokes"
K_BOX = (1403.08, 4.1, 205.84, 215.68)


def write(name, text):
    (BRAND / name).write_text(text)
    print(f"  {name:24} {len(text):6} B")


write("k.svg", f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{" ".join(map(str, K_BOX))}"><path d="{K}"/></svg>')

# Favicon: the K sits in a 320 square with optical breathing room.
k_icon = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 320 320"><rect width="320" height="320" fill="{ONYX}"/>'
          f'<g transform="translate({160 - K_BOX[0] - K_BOX[2] / 2:.2f} {160 - K_BOX[1] - K_BOX[3] / 2:.2f})" fill="{BONE}"><path d="{K}"/></g></svg>')
write("favicon.svg", k_icon)

# Share card: their still, cropped around the engraving. The name is already on the metal.
still = Image.open(ROOT / "assets/media/source/temple-still.webp").convert("RGB")
crop = still.crop((0, 940 - 525, 2000, 940 + 525)).resize((1200, 630), Image.LANCZOS)
ImageEnhance.Brightness(crop).enhance(1.04).save(ROOT / "assets/og.jpg", quality=84, optimize=True, progressive=True)
print(f"  {'og.jpg':24} {(ROOT / 'assets/og.jpg').stat().st_size:6} B")

with sync_playwright() as p:
    browser = p.chromium.launch(channel="chrome")
    for name, size in (("favicon-48.png", 48), ("apple-touch-icon.png", 180)):
        page = browser.new_page(viewport={"width": size, "height": size}, device_scale_factor=1)
        page.set_content(f'<style>html,body{{margin:0}}svg{{display:block;width:{size}px;height:{size}px}}</style>{k_icon}')
        page.screenshot(path=str(BRAND / name))
        page.close()
        print(f"  {name:24} {(BRAND / name).stat().st_size:6} B")
    browser.close()
