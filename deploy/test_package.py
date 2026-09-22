#!/usr/bin/env python3
"""Test the taboukhi.com package as it will run, minus PHP.

    python3 deploy/package.py && python3 deploy/test_package.py

Unzips dist/taboukhi-com.zip, serves it with the Content-Security-Policy from its own
.htaccess, and stands in for api/apply.php with every reply the real receiver can give
(200, 422, 413, 429, 500, a non-JSON page). There is no PHP on this Mac; the receiver
itself is proven on the host (see the deploy prompt), this proves everything around it.
"""
import cgi
import http.server
import io
import json
import pathlib
import re
import socketserver
import sys
import tempfile
import threading
import zipfile

from playwright.sync_api import sync_playwright

ROOT = pathlib.Path(__file__).resolve().parent.parent
ZIP = ROOT / "dist" / "taboukhi-com.zip"
PORT = 8232
STATE = {"mode": "ok", "last": None}
results = []


def until(pg, expr, timeout=6000):
    """Poll from outside the page: the page's CSP forbids the eval behind wait_for_function."""
    for _ in range(timeout // 100):
        if pg.evaluate(expr):
            return True
        pg.wait_for_timeout(100)
    raise TimeoutError(expr)


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(f"  {'ok  ' if ok else 'FAIL'}  {name}" + (f"   [{detail}]" if detail and not ok else ""))


def serve(docroot, csp):
    class H(http.server.SimpleHTTPRequestHandler):
        extensions_map = {**http.server.SimpleHTTPRequestHandler.extensions_map, ".js": "text/javascript", ".woff2": "font/woff2", ".webp": "image/webp", ".mp4": "video/mp4", ".svg": "image/svg+xml"}

        def __init__(self, *a, **k):
            super().__init__(*a, directory=str(docroot), **k)

        def log_message(self, *a):
            pass

        def end_headers(self):
            path = self.path.split("?")[0]
            if path in ("/", "/index.html"):
                self.send_header("Content-Security-Policy", csp)
            self.send_header("Cache-Control", "no-store")
            super().end_headers()

        def do_GET(self):
            if self.path.startswith("/__mode/"):
                STATE["mode"] = self.path.split("/")[-1]
                self.send_response(204); self.end_headers(); return
            target = docroot / self.path.split("?")[0].lstrip("/")
            if self.path.split("?")[0] != "/" and not target.exists():
                body = (docroot / "404.html").read_bytes()
                self.send_response(404); self.send_header("Content-Type", "text/html"); self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body); return
            super().do_GET()

        def do_POST(self):
            if self.path != "/api/apply.php":
                self.send_response(404); self.end_headers(); return
            form = cgi.FieldStorage(fp=self.rfile, headers=self.headers, environ={"REQUEST_METHOD": "POST", "CONTENT_TYPE": self.headers["Content-Type"]})
            fields = {k: (form[k].filename and f"<file {form[k].filename} {len(form[k].value)}>") or form[k].value for k in form.keys()}
            STATE["last"] = {"fields": fields, "origin": self.headers.get("Origin"), "accept": self.headers.get("Accept")}
            mode = STATE["mode"]
            code, body, ctype, extra = {
                "ok": (200, {"ok": True, "reference": "TBK-TEST01"}, "application/json", {}),
                "invalid": (422, {"ok": False, "error": "invalid", "fieldErrors": {"full_name": "Please enter your name.", "cv": "This file could not be received. Please try again, or share a link instead.", "location": "Server-side note."}}, "application/json", {}),
                "big": (413, {"ok": False, "error": "too_large"}, "application/json", {}),
                "many": (429, {"ok": False, "error": "rate_limited"}, "application/json", {"Retry-After": "600"}),
                "down": (500, {"ok": False, "error": "server"}, "application/json", {}),
                "html": (200, "<html>host error page</html>", "text/html", {}),
            }[mode]
            raw = (json.dumps(body) if not isinstance(body, str) else body).encode()
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            for k, v in extra.items():
                self.send_header(k, v)
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

    class S(socketserver.ThreadingTCPServer):
        allow_reuse_address = True
        daemon_threads = True

    srv = S(("127.0.0.1", PORT), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def main():
    tmp = pathlib.Path(tempfile.mkdtemp())
    zipfile.ZipFile(ZIP).extractall(tmp)
    csp = re.search(r'Content-Security-Policy "([^"]+)"', (tmp / ".htaccess").read_text()).group(1)
    srv = serve(tmp, csp)
    url = f"http://127.0.0.1:{PORT}/"
    pdf = tmp / "cv-test.pdf"; pdf.write_bytes(b"%PDF-1.4\n" + b"0" * 4096)

    with sync_playwright() as p:
        b = p.chromium.launch(channel="chrome")

        def page(w=1440, h=900, mobile=False):
            ctx = b.new_context(viewport={"width": w, "height": h}, is_mobile=mobile, has_touch=mobile, device_scale_factor=2 if mobile else 1)
            pg = ctx.new_page()
            pg.problems = []
            pg.on("console", lambda m: m.type in ("error", "warning") and pg.problems.append(m.text))
            pg.on("pageerror", lambda e: pg.problems.append(str(e)))
            pg.goto(url, wait_until="networkidle")
            until(pg, "window.__tbk === true && !document.querySelector('[data-submit]').disabled")
            return ctx, pg

        def fill(pg, file=False):
            pg.fill("#f-name", "Test Candidate"); pg.fill("#f-email", "candidate@example.com")
            pg.fill("#f-phone", "+971 50 123 4567"); pg.fill("#f-loc", "Dubai, UAE")
            pg.click("label.chip:has(input[value=atelier])")
            pg.fill("#f-url", "example.com/work"); pg.fill("#f-role", "Senior designer, Studio X")
            pg.fill("#f-msg", "A line about the work.")
            if file:
                pg.click("label.seg__opt:has(input[value=file])"); pg.set_input_files("#f-cv", str(pdf)); pg.wait_for_timeout(150)
            pg.check("#f-consent")

        def send(pg, mode):
            pg.request.get(url + f"__mode/{mode}")
            pg.click("[data-submit]")

        print("Package, as the real domain")
        ctx, pg = page()
        until(pg, "document.querySelector('[data-film]').classList.contains('is-on')", 8000)
        check("no CSP violations or errors under the real policy", not pg.problems, "; ".join(pg.problems))
        check("indexable, with a canonical on taboukhi.com", pg.locator("meta[name=robots]").count() == 0 and pg.get_attribute("link[rel=canonical]", "href") == "https://taboukhi.com/")
        check("no preview flags in endpoint mode", pg.locator("[data-demo-only]:visible").count() == 0)
        check("the consent sentence names info@taboukhi.com", "deleted at any time by writing to info@taboukhi.com" in pg.inner_text(".row--switch"))
        fill(pg, file=True)
        send(pg, "ok")
        until(pg, "!document.querySelector('[data-done]').hidden")
        done = pg.inner_text("[data-done]")
        check("success shows the server's reference, and no preview line", "Reference TBK-TEST01" in done and "nothing was sent" not in done.lower(), done)
        last = STATE["last"]
        f = last["fields"] if last else {}
        want = {"full_name", "email", "phone", "location", "discipline", "current_role", "portfolio_url", "message", "consent", "consent_version", "meta", "cv"}
        check("the POST carries exactly the fields the receiver reads", set(f) == want, str(sorted(f)))
        check("values arrive trimmed and normalised", f.get("discipline") == "atelier" and f.get("consent") == "true" and f.get("consent_version") == "2026-09-22"
              and f.get("portfolio_url") == "https://example.com/work" and f.get("cv", "").startswith("<file cv-test.pdf"), str(f))
        check("same origin: nothing to negotiate", (last or {}).get("origin") in (None, url.rstrip("/")) and "application/json" in ((last or {}).get("accept") or ""))
        ctx.close()

        for mode, want_text in (("big", "too large to be received"), ("many", "several attempts"), ("down", "was not sent"), ("html", "was not sent")):
            ctx, pg = page()
            fill(pg); send(pg, mode)
            until(pg, "document.querySelector('[data-alert]').textContent.length > 0", 6000)
            check(f"a {mode} reply reads: '{want_text}'", want_text in pg.inner_text("[data-alert]").lower(), pg.inner_text("[data-alert]"))
            check(f"  and nothing typed is lost", pg.input_value("#f-name") == "Test Candidate" and pg.is_checked("#f-consent"))
            ctx.close()

        ctx, pg = page()
        fill(pg, file=True); send(pg, "invalid")
        until(pg, "document.querySelector('[data-alert]').textContent.length > 0", 6000)
        check("a 422 marks the fields the server named", pg.get_attribute("#f-name", "aria-invalid") == "true" and "could not be received" in pg.inner_text("#f-cv-err"))
        check("  and a message for a field the form lacks joins the alert", "server-side note" in pg.inner_text("[data-alert]").lower() and "marked above" in pg.inner_text("[data-alert]").lower())
        ctx.close()

        ctx, pg = page(390, 844, True)
        check("phone: renders under the real policy", not pg.problems and pg.locator(".kglass").is_visible(), "; ".join(pg.problems))
        ctx.close()

        ctx, pg = page()
        r = pg.goto(url + "no-such-page", wait_until="load")
        check("unknown paths get the 404 page, addressed from the root", r.status == 404 and pg.get_attribute("a", "href") == "/" and pg.get_attribute("link[rel=icon]", "href") == "/assets/brand/favicon.svg")
        ctx.close()
        b.close()
    srv.shutdown()
    print(f"\n{sum(results)}/{len(results)} passed")
    sys.exit(0 if all(results) else 1)


if __name__ == "__main__":
    main()
