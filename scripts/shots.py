#!/usr/bin/env python3
"""Viewport screenshots of every section, for judging the page by eye.

    python3 scripts/shots.py                 # desktop 1440x900 + phone 390x844
    python3 scripts/shots.py 1366x640 375x667

Scrolls the way a reader does (so reveals and the light settle), then shoots what is on
screen. Output: scripts/shots/<w>x<h>-<n>-<name>.png
"""
import pathlib
import sys

from playwright.sync_api import sync_playwright

URL = "http://localhost:8231/"
OUT = pathlib.Path(__file__).resolve().parent / "shots"
STOPS = [("hero", "#top", 0), ("house", "#house", 0), ("work", "#work", 0), ("work-mid", "#work", .55),
         ("work-end", "#work", 1.05), ("people", "#people", 0), ("rows", ".rows", -.1), ("asks", ".asks", -.4),
         ("apply", "#apply", 0), ("sheet", ".sheet", -.05), ("sheet-end", ".form__end", -.6), ("foot", ".foot", -.2)]


def main():
    sizes = [tuple(map(int, a.split("x"))) for a in sys.argv[1:]] or [(1440, 900), (390, 844)]
    OUT.mkdir(exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome")
        for w, h in sizes:
            ctx = browser.new_context(viewport={"width": w, "height": h}, device_scale_factor=2 if w < 800 else 1,
                                      is_mobile=w < 800, has_touch=w < 800)
            page = ctx.new_page()
            page.on("console", lambda m: m.type in ("error", "warning") and print("   console:", m.text))
            page.goto(URL, wait_until="networkidle")
            page.evaluate("document.fonts.ready")
            for n, (name, sel, off) in enumerate(STOPS):
                page.evaluate("""([sel, off]) => { const el = document.querySelector(sel); const r = el.getBoundingClientRect();
                    window.scrollTo({ top: scrollY + r.top + off * innerHeight - (off ? 0 : 0), behavior: 'instant' }); }""", [sel, off])
                page.wait_for_timeout(1100)
                page.screenshot(path=str(OUT / f"{w}x{h}-{n:02d}-{name}.png"))
            sw = page.evaluate("[document.documentElement.scrollWidth, innerWidth]")
            print(f"{w}x{h}: scrollWidth {sw[0]} / innerWidth {sw[1]}")
            ctx.close()
        browser.close()


if __name__ == "__main__":
    main()
