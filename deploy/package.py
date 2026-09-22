#!/usr/bin/env python3
"""Build the taboukhi.com upload package (Limoo cPanel).

    python3 deploy/package.py        # -> dist/taboukhi-com.zip (+ a copy in ~/Claude Code/output)

The repo and GitHub Pages stay the demo-mode, noindexed preview. The package is the same
site, built for the real domain:
  * config.js in endpoint mode: POSTs to /api/apply.php on the same origin (no CORS),
    fallbackEmail = info@taboukhi.com (completes the consent sentence)
  * no robots noindex; canonical, og:url and og:image on https://taboukhi.com
  * 404.html addressed from the domain root, not /taboukhi/
  * .htaccess from deploy/htaccess, with the inline script's CSP hash filled in
  * api/ (the PHP receiver) from deploy/api; robots.txt and sitemap.xml
Only files the page actually uses are shipped. Everything is asserted before the zip is
written, and the zip is root-level (a wrapper folder would strand index.html).
"""
import base64
import hashlib
import pathlib
import re
import shutil
import tempfile
import zipfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
DOMAIN = "https://taboukhi.com"
MAIL = "info@taboukhi.com"
CONSENT_VERSION = "2026-09-22"
OUT = ROOT / "dist" / "taboukhi-com.zip"
COPY_TO = pathlib.Path.home() / "Claude Code" / "output" / "2026-09" / "taboukhi-com" / "taboukhi-com.zip"

SHIP = [
    "index.html", "404.html", "css/main.css",
    "js/main.js", "js/apply.js", "js/adapter.js", "js/config.js",
    "assets/og.jpg", "assets/fonts/inter.woff2",
    "assets/brand/favicon.svg", "assets/brand/favicon-48.png", "assets/brand/apple-touch-icon.png", "assets/brand/k.svg",
    "assets/media/film-1920.mp4", "assets/media/film-1280.mp4", "assets/media/film-1920.webp", "assets/media/film-1280.webp",
]


def sub1(pattern, repl, s, flags=0):
    out, n = re.subn(pattern, repl, s, count=1, flags=flags)
    assert n == 1, f"pattern not found: {pattern[:60]}"
    return out


def build(stage):
    for f in SHIP:
        (stage / f).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / f, stage / f)
    shutil.copytree(ROOT / "deploy" / "api", stage / "api")

    p = stage / "index.html"
    s = p.read_text()
    s = sub1(r"<!-- PREVIEW:.*?-->\n<meta name=\"robots\" content=\"noindex\">\n", "", s, re.S)
    s = sub1(r'<meta property="og:type" content="website">',
             f'<link rel="canonical" href="{DOMAIN}/">\n<meta property="og:type" content="website">\n<meta property="og:url" content="{DOMAIN}/">', s)
    s = s.replace("https://ilyatabrizi.github.io/taboukhi/assets/og.jpg", f"{DOMAIN}/assets/og.jpg")
    p.write_text(s)

    p = stage / "js" / "config.js"
    c = p.read_text()
    c = sub1(r"mode: 'demo',", "mode: 'endpoint',", c)
    c = sub1(r"endpoint: '',", "endpoint: '/api/apply.php',", c)
    c = sub1(r"fallbackEmail: '',", f"fallbackEmail: '{MAIL}',", c)
    c = sub1(r"consentVersion: '[^']*',", f"consentVersion: '{CONSENT_VERSION}',", c)
    p.write_text(c)

    p = stage / "404.html"
    p.write_text(p.read_text().replace("/taboukhi/", "/"))

    inline = re.findall(r"<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>", s, re.S)
    assert len(inline) == 1, "exactly one inline script is expected"
    digest = "sha256-" + base64.b64encode(hashlib.sha256(inline[0].encode()).digest()).decode()
    h = (ROOT / "deploy" / "htaccess").read_text().replace("__INLINE_SCRIPT_HASH__", digest)
    (stage / ".htaccess").write_text(h)

    (stage / "robots.txt").write_text(f"User-agent: *\nAllow: /\nDisallow: /api/\n\nSitemap: {DOMAIN}/sitemap.xml\n")
    (stage / "sitemap.xml").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        f"  <url><loc>{DOMAIN}/</loc></url>\n</urlset>\n")
    return digest


def check(stage, digest):
    index = (stage / "index.html").read_text()
    assert "noindex" not in index, "the real site must be indexable"
    assert f'<link rel="canonical" href="{DOMAIN}/">' in index
    assert f"{DOMAIN}/assets/og.jpg" in index
    cfg = (stage / "js" / "config.js").read_text()
    assert "mode: 'endpoint'" in cfg and "endpoint: '/api/apply.php'" in cfg and MAIL in cfg
    assert digest in (stage / ".htaccess").read_text() and "__INLINE" not in (stage / ".htaccess").read_text()
    for f in stage.rglob("*"):
        if f.is_file() and f.suffix in (".html", ".js", ".css", ".txt", ".xml", ".php", ""):
            t = f.read_text(errors="ignore")
            assert "github.io" not in t and "/taboukhi/" not in t, f"preview address left in {f.relative_to(stage)}"
    # every local reference in the page and the stylesheet ships
    refs = re.findall(r'(?:href|src)="([^"#:]+?)"', index)
    refs += [r.split()[0] for r in re.findall(r'srcset="([^"]+)"', index) for r in r.split(",")]
    refs += [re.sub(r"^\.\./", "", u) for u in re.findall(r'url\("([^")]+)"\)', (stage / "css/main.css").read_text())]
    for r in {r.strip() for r in refs if r.strip() and not r.startswith(("http", "data:", "mailto:"))}:
        assert (stage / r).exists(), f"missing from the package: {r}"
    for f in ("api/apply.php", "api/.htaccess", "api/.user.ini", ".htaccess", "robots.txt", "sitemap.xml"):
        assert (stage / f).exists(), f
    for bad in ("e2e.py", "serve.py", "scripts", "deploy", "assets/media/source", "assets/brand/source", ".git"):
        assert not (stage / bad).exists(), f"should not ship: {bad}"


def main():
    with tempfile.TemporaryDirectory() as tmp:
        stage = pathlib.Path(tmp)
        digest = build(stage)
        check(stage, digest)
        OUT.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED) as z:
            for f in sorted(stage.rglob("*")):
                if f.is_file():
                    z.write(f, f.relative_to(stage).as_posix())
    names = zipfile.ZipFile(OUT).namelist()
    assert "index.html" in names and ".htaccess" in names and "api/apply.php" in names, "zip must be root-level"
    COPY_TO.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(OUT, COPY_TO)
    print(f"{OUT.relative_to(ROOT)}  {OUT.stat().st_size / 1024:.0f} KB  {len(names)} files  (copy: {COPY_TO})")


if __name__ == "__main__":
    main()
