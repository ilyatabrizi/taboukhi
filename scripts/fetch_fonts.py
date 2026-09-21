#!/usr/bin/env python3
"""Newsreader + Jost, self-hosted.

The wordmark is the only large sans on the page, so everything the house SAYS is
one serif: Newsreader, whose optical-size axis (6-72) makes the 80px headline and
the 17px paragraph genuinely different drawings. Jost 400-500 carries only the
functional caption layer (labels, markers, buttons) in tracked capitals, where a
serif at 11px starts to read as a law firm. It sits behind --font-caption, so
going serif-only is a one-line change.

Google serves one file per unicode range; the page is English, so only the latin
range is taken, then re-subset to what the page can render. Variable axes kept.

    python3 scripts/fetch_fonts.py

Also prints metric-matched fallback @font-face blocks (size-adjust + overrides
measured against Georgia / Arial) so the font swap causes no layout shift.
"""
import pathlib
import re
import subprocess

from fontTools.ttLib import TTFont

OUT = pathlib.Path(__file__).resolve().parent.parent / "assets" / "fonts"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36")
# ASCII, Latin-1, dashes, curly quotes, bullet, ellipsis, arrows, minus, hair/thin space.
GLYPHS = ("U+0020-007E,U+00A0-00FF,U+2009,U+200A,U+2013,U+2014,U+2018,U+2019,U+201C,U+201D,"
          "U+2022,U+2026,U+2190-2193,U+2212")
FACES = [
    ("newsreader", "Newsreader:opsz,wght@6..72,300..500", "wght=300:500"),
    ("newsreader-italic", "Newsreader:ital,opsz,wght@1,6..72,300..500", "wght=300:500"),
    ("jost", "Jost:wght@400..500", "wght=400:500"),
]
# English letter frequencies (per mille, space included) for the width comparison.
FREQ = {" ": 182, "e": 102, "t": 75, "a": 65, "o": 62, "i": 57, "n": 57, "s": 53, "r": 50,
        "h": 50, "l": 33, "d": 33, "u": 23, "c": 22, "m": 20, "f": 18, "w": 17, "g": 16,
        "p": 15, "y": 15, "b": 12, "v": 8, "k": 6, ",": 10, ".": 10}
FALLBACKS = {
    "newsreader": [("Georgia", "/System/Library/Fonts/Supplemental/Georgia.ttf")],
    "jost": [("Arial", "/System/Library/Fonts/Supplemental/Arial.ttf")],
}


def get(url):
    """curl, not urllib: this Mac's Python SSL times out on the Google handshake."""
    return subprocess.run(["curl", "-sSfL", "-m", "40", "--retry", "3", "-A", UA, url],
                          check=True, capture_output=True).stdout


def latin_url(query):
    css = get(f"https://fonts.googleapis.com/css2?family={query}&display=swap").decode()
    urls = re.findall(r"url\((https://[^)]+\.woff2)\)", css)
    if not urls:
        raise SystemExit(f"no woff2 in payload for {query}")
    return urls[-1]


def avg_width(font):
    cmap, hmtx, upm = font.getBestCmap(), font["hmtx"], font["head"].unitsPerEm
    total = sum(hmtx[cmap[ord(ch)]][0] * w for ch, w in FREQ.items())
    return total / sum(FREQ.values()) / upm


def fallback_block(name, dest):
    web = TTFont(dest)
    upm, hhea = web["head"].unitsPerEm, web["hhea"]
    for local, path in FALLBACKS.get(name, []):
        if not pathlib.Path(path).exists():
            continue
        adj = avg_width(web) / avg_width(TTFont(path))
        print(f"""@font-face {{
  font-family: "{name.title()} Fallback";
  src: local("{local}");
  size-adjust: {adj * 100:.2f}%;
  ascent-override: {hhea.ascent / upm / adj * 100:.2f}%;
  descent-override: {abs(hhea.descent) / upm / adj * 100:.2f}%;
  line-gap-override: {hhea.lineGap / upm / adj * 100:.2f}%;
}}""")


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    for name, query, limits in FACES:
        raw = OUT / f"{name}.raw.woff2"
        raw.write_bytes(get(latin_url(query)))
        dest = OUT / f"{name}.woff2"
        # Google ships the whole weight axis whatever the query asks for; the page
        # uses 300-500, so the rest of the axis is cut before subsetting.
        cut = OUT / f"{name}.cut.ttf"
        subprocess.run(["python3", "-m", "fontTools.varLib.instancer", str(raw), limits,
                        "-o", str(cut)], check=True, capture_output=True)
        raw.unlink()
        raw = cut
        subprocess.run(["python3", "-m", "fontTools.subset", str(raw), f"--unicodes={GLYPHS}",
                        "--layout-features=kern,liga,calt,lnum,tnum,onum,pnum,case,smcp,c2sc",
                        "--flavor=woff2", f"--output-file={dest}"], check=True)
        raw.unlink()
        axes = [f"{a.axisTag} {a.minValue:g}-{a.maxValue:g}" for a in TTFont(dest)["fvar"].axes]
        print(f"  {dest.name:26} {dest.stat().st_size / 1024:6.1f} KB   {', '.join(axes)}")
    for name, *_ in FACES:
        fallback_block(name, OUT / f"{name}.woff2")


if __name__ == "__main__":
    main()
