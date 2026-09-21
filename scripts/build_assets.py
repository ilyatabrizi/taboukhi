#!/usr/bin/env python3
"""Everything derived from the traced wordmark, in one pass.

    python3 scripts/build_assets.py

  assets/brand/o-ring.svg, o-face.svg   masks for Fig. 2: the whole O, and the O inset by a
                                        chamfer's width, so the ring reads as a bevelled object
  assets/brand/favicon.svg              the K's two detached strokes, bone on onyx
  assets/brand/favicon-48.png, apple-touch-icon.png
  assets/noise.png                      96px dither tile laid over near-black gradients
  assets/og.png                         1200x630 share card: the name on onyx under the band

PNG renders go through system Chrome (Playwright), the same engine the page is judged in.
"""
import pathlib
import re

import numpy as np
from PIL import Image
from playwright.sync_api import sync_playwright

ROOT = pathlib.Path(__file__).resolve().parent.parent
BRAND = ROOT / "assets" / "brand"
ONYX, BONE = "#020202", "#F4F2ED"

svg = (BRAND / "wordmark.svg").read_text()
paths = dict(re.findall(r'<path id="(l-\w)" d="([^"]+)"', svg))
assert len(paths) == 8, "the trace must carry eight letters"
O, K = paths["l-o"], paths["l-k"]
assert K.count("M") == 2, "the K is two detached strokes"
O_BOX = "782.03 0 283.07 224.66"
CHAMFER = 4.2          # viewBox units eaten from each edge of the ring's face


def write(name, text):
    (BRAND / name).write_text(text)
    print(f"  {name:24} {len(text):6} B")


write("o-ring.svg", f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{O_BOX}" preserveAspectRatio="none">'
                    f'<path fill-rule="evenodd" d="{O}"/></svg>')
write("o-face.svg", f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{O_BOX}" preserveAspectRatio="none">'
                    f'<defs><mask id="m" maskUnits="userSpaceOnUse" x="770" y="-10" width="310" height="250">'
                    f'<path fill="#fff" fill-rule="evenodd" d="{O}"/>'
                    f'<path fill="none" stroke="#000" stroke-width="{CHAMFER * 2}" d="{O}"/></mask></defs>'
                    f'<rect x="770" y="-10" width="310" height="250" mask="url(#m)"/></svg>')

# Favicon: the K sits in a 320 square with optical breathing room. K bbox 1403.08 4.1 205.84 215.68.
k_icon = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 320 320"><rect width="320" height="320" fill="{ONYX}"/>'
          f'<g transform="translate({160 - 1403.08 - 205.84 / 2:.2f} {160 - 4.1 - 215.68 / 2:.2f})" fill="{BONE}"><path d="{K}"/></g></svg>')
write("favicon.svg", k_icon)

rng = np.random.default_rng(7)
noise = rng.integers(0, 256, (96, 96), dtype=np.uint8)
Image.merge("LA", (Image.fromarray(noise), Image.fromarray(np.full((96, 96), 255, np.uint8)))).convert("L").save(ROOT / "assets" / "noise.png", optimize=True)
print(f"  {'noise.png':24} {(ROOT / 'assets' / 'noise.png').stat().st_size:6} B")

word = "".join(f'<path d="{d}"/>' for d in paths.values())
og = f"""<!doctype html><meta charset="utf-8"><style>
html,body{{margin:0;width:1200px;height:630px;background:radial-gradient(120% 90% at 50% 55%,#151514 0%,{ONYX} 70%);overflow:hidden}}
svg{{position:absolute;left:96px;top:258px;width:1008px;overflow:visible}}
i{{position:absolute;background:#2B2B29}} .h{{left:0;right:0;height:1px}} .v{{top:0;width:1px;height:373px}}
p{{position:absolute;left:96px;margin:0;font:500 15px/1 'Jost';letter-spacing:.24em;text-transform:uppercase;color:#8E8D89}}
@font-face{{font-family:Jost;src:url('{(ROOT / "assets/fonts/jost.woff2").as_uri()}');font-weight:400 500}}
</style>
<i class="h" style="top:260.5px"></i><i class="h" style="top:368.3px"></i>
{''.join(f'<i class="v" style="left:{96 + 1008 * x / 100:.1f}px"></i>' for x in (0, 10.176, 25.389, 39.1015, 55.5505, 70.154, 82.5635, 98.738))}
<svg viewBox="0 0 2000 227"><defs><linearGradient id="g" gradientUnits="userSpaceOnUse" x1="-1400" y1="0" x2="3400" y2="0" gradientTransform="translate(-312 0) rotate(32.1 1000 113)">
<stop offset="0" stop-color="#9F9E99"/><stop offset=".36" stop-color="#9F9E99"/><stop offset=".45" stop-color="#C3C2BD"/><stop offset=".5" stop-color="{BONE}"/><stop offset=".55" stop-color="#C3C2BD"/><stop offset=".64" stop-color="#9F9E99"/><stop offset="1" stop-color="#9F9E99"/></linearGradient></defs>
<g fill="url(#g)" fill-rule="evenodd">{word}</g></svg>
<p style="top:452px">Eyewear &nbsp;—&nbsp; Founding appointments</p>"""

with sync_playwright() as p:
    browser = p.chromium.launch(channel="chrome")
    for name, size in (("favicon-48.png", 48), ("apple-touch-icon.png", 180)):
        page = browser.new_page(viewport={"width": size, "height": size}, device_scale_factor=1)
        page.set_content(f'<style>html,body{{margin:0}}svg{{display:block;width:{size}px;height:{size}px}}</style>{k_icon}')
        page.screenshot(path=str(BRAND / name))
        page.close()
        print(f"  {name:24} {(BRAND / name).stat().st_size:6} B")
    page = browser.new_page(viewport={"width": 1200, "height": 630}, device_scale_factor=1)
    page.set_content(og)
    page.evaluate("document.fonts.ready")
    page.wait_for_timeout(300)
    page.screenshot(path=str(ROOT / "assets" / "og.png"))
    print(f"  {'og.png':24} {(ROOT / 'assets' / 'og.png').stat().st_size:6} B")
    browser.close()
