#!/usr/bin/env python3
"""Viewport screenshots of the page, for judging it by eye.

    python3 scripts/shots.py                 # desktop 1440x900 + phone 390x844
    python3 scripts/shots.py 1366x640 375x667

Output: scripts/shots/<w>x<h>-<n>-<name>.png
"""
import pathlib
import sys

from playwright.sync_api import sync_playwright

URL = sys.argv[-1] if sys.argv[-1].startswith("http") else "http://localhost:8231/"
OUT = pathlib.Path(__file__).resolve().parent / "shots"
STOPS = [("top", None, 0), ("sheet", "#application", 0), ("chips", "#f-disc", -.25), ("work", "[data-seg]", -.3), ("end", ".send", -.55)]


def main():
    sizes = [tuple(map(int, a.split("x"))) for a in sys.argv[1:] if "x" in a and not a.startswith("http")] or [(1440, 900), (390, 844)]
    OUT.mkdir(exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome")
        for w, h in sizes:
            mobile = w < 1080
            ctx = browser.new_context(viewport={"width": w, "height": h}, device_scale_factor=2 if w < 800 else 1, is_mobile=w < 800, has_touch=w < 800)
            page = ctx.new_page()
            page.on("console", lambda m: m.type in ("error", "warning") and print("   console:", m.text))
            page.goto(URL, wait_until="networkidle")
            page.evaluate("document.fonts.ready")
            page.wait_for_timeout(1200)
            for n, (name, sel, off) in enumerate(STOPS):
                if sel:
                    page.evaluate("""([sel, off]) => { const r = document.querySelector(sel).getBoundingClientRect();
                        window.scrollTo({ top: scrollY + r.top + off * innerHeight - (off ? 0 : 76), behavior: 'instant' }); }""", [sel, off])
                page.wait_for_timeout(700)
                page.screenshot(path=str(OUT / f"{w}x{h}-{n:02d}-{name}.png"))
            print(f"{w}x{h}: scrollWidth {page.evaluate('document.documentElement.scrollWidth')} / {w}")
            ctx.close()
        browser.close()


if __name__ == "__main__":
    main()
