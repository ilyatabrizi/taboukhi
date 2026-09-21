#!/usr/bin/env python3
"""End-to-end checks, through system Chrome.

    python3 e2e.py                                   # against the local server (:8231)
    python3 e2e.py https://ilyatabrizi.github.io/taboukhi/

Asserts geometry and behaviour, not class names: what a visitor would see or be told.
"""
import pathlib
import re
import sys
import tempfile

from playwright.sync_api import sync_playwright

URL = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8231/"
ROOT = pathlib.Path(__file__).resolve().parent
results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(f"  {'ok  ' if ok else 'FAIL'}  {name}" + (f"   [{detail}]" if detail and not ok else ""))


def fresh(browser, w=1440, h=900, mobile=False, **kw):
    ctx = browser.new_context(viewport={"width": w, "height": h}, device_scale_factor=2 if mobile else 1,
                              is_mobile=mobile, has_touch=mobile, **kw)
    page = ctx.new_page()
    page.errors = []
    page.on("pageerror", lambda e: page.errors.append(str(e)))
    page.on("console", lambda m: m.type == "error" and page.errors.append(m.text))
    return ctx, page


def goto(page, suffix=""):
    page.goto(URL + suffix, wait_until="networkidle")
    page.evaluate("document.fonts.ready")
    page.wait_for_function("window.__tbk === true")


def fill_valid(page, link=True):
    page.fill("#f-name", "Test Candidate")
    page.fill("#f-email", "candidate@example.com")
    page.select_option("#f-disc", "atelier")
    if link:
        page.fill("#f-url", "example.com/portfolio")
    page.check("#f-consent")


def main():
    pdf = pathlib.Path(tempfile.mkdtemp()) / "portfolio.pdf"
    pdf.write_bytes(b"%PDF-1.4\n" + b"0" * 2048)
    fake = pdf.with_name("not-really.pdf"); fake.write_bytes(b"GIF89a" + b"0" * 2048)
    exe = pdf.with_name("tool.exe"); exe.write_bytes(b"MZ" + b"0" * 2048)
    big = pdf.with_name("big.pdf"); big.write_bytes(b"%PDF-1.4\n" + b"0" * (11 * 1024 * 1024))

    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome")

        print("Document")
        ctx, page = fresh(browser)
        goto(page)
        html = page.content()
        check("no console or page errors on load", not page.errors, "; ".join(page.errors))
        check("exactly one h1, and it names the house", page.locator("h1").count() == 1 and page.locator("h1 [aria-label='TABOUKHI']").count() == 1)
        check("lang=en", page.get_attribute("html", "lang") == "en")
        visible = page.evaluate("document.body.innerText").lower()
        meta = " ".join(page.locator("meta[content]").evaluate_all("els => els.map(e => e.content)")).lower()
        attrs = " ".join(page.locator("[aria-label],[alt],[title]").evaluate_all("els => els.map(e => (e.getAttribute('aria-label')||'')+(e.getAttribute('alt')||'')+(e.getAttribute('title')||''))")).lower()
        for word in ("titanium", "luxury", "luxurious"):
            check(f"'{word}' appears nowhere a visitor or crawler reads", word not in visible and word not in meta and word not in attrs)
        check("the founder fact is stated verbatim", "taboukhi is the first eyewear brand established by ilya taboukhi" in visible)
        check("no year is printed", not re.search(r"\b(19|20)\d\d\b", visible))
        check("no email address is printed", "@" not in visible)
        demo = page.evaluate("import('./js/adapter.js').then(m => m.isDemo)")
        check("noindex stands exactly while the form is in demo mode", (page.locator("meta[name=robots][content*=noindex]").count() == 1) == demo)
        check("the preview flag shows exactly while in demo mode", page.locator(".sheet__flag").is_visible() == demo)
        k = page.evaluate("document.querySelector('#p-k').getAttribute('d')")
        check("the K is two detached strokes", k.count("M") == 2 and k.count("Z") == 2)
        rows = page.locator("[data-discipline]").evaluate_all("els => els.map(e => [e.dataset.discipline, e.querySelector('.row__name').textContent.trim()])")
        opts = page.locator("#f-disc option:not([disabled])").evaluate_all("els => els.map(e => [e.value, e.textContent.trim()])")
        check("discipline rows and select options are the same list", rows == opts and len(rows) >= 2, f"{rows} vs {opts}")
        for href in page.locator("a[href^='#']").evaluate_all("els => [...new Set(els.map(e => e.getAttribute('href')))]"):
            check(f"anchor {href} has a target", page.locator(href).count() == 1)
        for f in page.evaluate("[...document.querySelectorAll('link[href],script[src]')].map(e => e.href || e.src)"):
            check(f"loads {f.split('/')[-1]}", page.request.get(f).ok)
        check("no third-party requests", all(u.startswith(URL.split('/')[0] + '//' + URL.split('/')[2]) for u in page.evaluate("performance.getEntriesByType('resource').map(r => r.name)")))
        ctx.close()

        print("Layout")
        for w, h, mobile in ((375, 667, True), (390, 844, True), (768, 1024, True), (1366, 640, False), (1440, 900, False), (2560, 1440, False)):
            ctx, page = fresh(browser, w, h, mobile)
            goto(page)
            sw = page.evaluate("document.documentElement.scrollWidth")
            check(f"{w}x{h}: no horizontal scroll", sw <= w, f"scrollWidth {sw}")
            g = page.evaluate("""() => { const r = s => document.querySelector(s).getBoundingClientRect();
                const m = r('.hero__mark'), s = r('.hero__statement'), c = r('.hero__cta'), b = r('.hero .btn'), f = r('.hero__foot'), k = r('.hero__kicker');
                return { mark: [m.top, m.bottom], say: [s.top, c.bottom], btn: [b.top, b.bottom], foot: [f.top, f.bottom], kick: k.bottom, vh: innerHeight }; }""")
            check(f"{w}x{h}: hero stacks without overlap", g["kick"] <= g["mark"][0] and g["mark"][1] < g["say"][0] and g["say"][1] <= g["foot"][0] + 1, str(g))
            if mobile and w < 720:
                check(f"{w}x{h}: Apply is above the fold", g["btn"][1] <= g["vh"], str(g))
            lines = page.evaluate("""() => { const say = document.querySelector('.hero__statement').getBoundingClientRect();
                return [...document.querySelectorAll('.hero__lines i')].map(i => i.getBoundingClientRect()).every(r => r.bottom < say.top); }""")
            check(f"{w}x{h}: no construction line runs through the statement", lines)
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            page.wait_for_timeout(250)
            check(f"{w}x{h}: still no horizontal scroll at the foot", page.evaluate("document.documentElement.scrollWidth") <= w)
            ctx.close()

        print("Masthead")
        ctx, page = fresh(browser)
        goto(page)
        check("over the hero: clear, no small wordmark", page.evaluate("getComputedStyle(document.querySelector('.mast')).backgroundColor") in ("rgba(0, 0, 0, 0)", "transparent")
              and not page.locator(".mast__brand").is_visible())
        page.evaluate("document.querySelector('#house').scrollIntoView({behavior:'instant'})"); page.mouse.wheel(0, 300); page.wait_for_timeout(700)
        check("moving down: it steps aside", page.evaluate("document.querySelector('.mast').getBoundingClientRect().bottom") <= 1)
        page.mouse.wheel(0, -120); page.wait_for_timeout(800)
        bg, ink = page.evaluate("(() => { const s = getComputedStyle(document.querySelector('.mast')); return [s.backgroundColor, s.color]; })()")
        check("moving up over bone: back, bone-backed, onyx ink, wordmark docked", bg == "rgb(244, 242, 237)" and ink == "rgb(2, 2, 2)" and page.locator(".mast__brand").is_visible(), f"{bg} {ink}")
        ctx.close()
        ctx, page = fresh(browser)
        goto(page, "#apply"); page.wait_for_timeout(900)
        under = page.evaluate("(() => { const y = document.querySelector('.mast').offsetHeight / 2; return [...document.querySelectorAll('main > [data-ground], footer')].find(e => { const r = e.getBoundingClientRect(); return r.top <= y && r.bottom > y; }).dataset.ground; })()")
        check("deep link to #apply: the masthead already matches the ground under it", page.evaluate("document.querySelector('.mast').dataset.on") == under and page.evaluate("document.querySelector('.mast').hasAttribute('data-docked')"), under)
        check("deep link to #apply: the heading is not under the masthead", page.evaluate("document.querySelector('#apply .marker').getBoundingClientRect().top") >= 0)
        ctx.close()

        print("Light")
        ctx, page = fresh(browser)
        goto(page)
        t0 = page.evaluate("document.querySelector('#ti-metal').getAttribute('gradientTransform')")
        page.mouse.wheel(0, 500); page.wait_for_timeout(900)
        t1 = page.evaluate("document.querySelector('#ti-metal').getAttribute('gradientTransform')")
        check("the band crosses the name as the first screen scrolls", t0 != t1, f"{t0} -> {t1}")
        page.wait_for_timeout(1500)
        t2 = page.evaluate("document.querySelector('#ti-metal').getAttribute('gradientTransform')")
        page.wait_for_timeout(500)
        check("and then comes to rest (nothing loops)", t2 == page.evaluate("document.querySelector('#ti-metal').getAttribute('gradientTransform')"))
        ctx.close()
        ctx, page = fresh(browser, reduced_motion="reduce")
        goto(page)
        t0 = page.evaluate("document.querySelector('#ti-metal').getAttribute('gradientTransform')")
        page.mouse.wheel(0, 500); page.wait_for_timeout(600)
        check("reduced motion: the light stays where the markup put it", t0 == page.evaluate("document.querySelector('#ti-metal').getAttribute('gradientTransform')"))
        check("reduced motion: nothing waits to be revealed", page.evaluate("[...document.querySelectorAll('[data-reveal]')].every(e => getComputedStyle(e).opacity !== '0')"))
        ctx.close()
        print("Application")
        ctx, page = fresh(browser)
        goto(page)
        page.locator("[data-discipline='optics-fit']").click(); page.wait_for_timeout(900)
        check("a discipline row writes itself into the form", page.input_value("#f-disc") == "optics-fit")
        check("and into the letterhead", "optics & fit" in page.inner_text("[data-letterhead]").lower())
        check("and the sheet is on screen", page.evaluate("(() => { const r = document.querySelector('#apply').getBoundingClientRect(); return r.top < innerHeight && r.bottom > 0; })()"))
        ctx.close()

        ctx, page = fresh(browser)
        goto(page, "#apply")
        page.click("[data-submit]")
        page.wait_for_timeout(200)
        status = page.inner_text("[data-status]")
        check("empty send: says how many fields need attention", "5 fields need your attention" in status, status)
        check("empty send: focus goes to the first of them", page.evaluate("document.activeElement.id") == "f-name")
        check("empty send: each is marked for assistive tech", page.locator("[aria-invalid='true']").count() == 4)
        check("empty send: the link-or-file rule speaks once", "add a link or attach a file" in page.inner_text("#pair-err").lower())
        page.fill("#f-name", "Test Candidate"); page.wait_for_timeout(50)
        check("an error clears the moment it is fixed", page.inner_text("#f-name-err") == "")
        page.fill("#f-email", "someone@gmial.com"); page.locator("#f-email").blur(); page.wait_for_timeout(50)
        check("a common email typo is offered, not auto-corrected", "did you mean someone@gmail.com" in page.inner_text("#f-email-err").lower() and page.input_value("#f-email") == "someone@gmial.com")
        page.locator("#f-email-err button").click()
        check("accepting the suggestion fixes the address", page.input_value("#f-email") == "someone@gmail.com")
        page.fill("#f-phone", "abc"); page.locator("#f-phone").blur()
        check("a bad telephone number is caught, gently", "leave the field empty" in page.inner_text("#f-phone-err"))
        page.fill("#f-phone", "")
        page.fill("#f-url", "example.com/work"); page.locator("#f-url").blur()
        check("a bare link gains https://", page.input_value("#f-url") == "https://example.com/work")

        page.set_input_files("#f-cv", str(exe)); page.wait_for_timeout(150)
        check("a wrong file type is refused with a sentence", "pdf or a word" in page.inner_text("#f-cv-err").lower() and not page.locator("[data-file]").is_visible())
        page.set_input_files("#f-cv", str(fake)); page.wait_for_timeout(150)
        check("a PDF that is not a PDF is refused", "pdf or a word" in page.inner_text("#f-cv-err").lower())
        page.set_input_files("#f-cv", str(big)); page.wait_for_timeout(300)
        check("an oversized file is refused, with its size", "limit is 10 MB" in page.inner_text("#f-cv-err"), page.inner_text("#f-cv-err"))
        page.set_input_files("#f-cv", str(pdf)); page.wait_for_timeout(150)
        check("a good PDF is typeset into the sheet", page.locator("[data-file]").is_visible() and "portfolio.pdf" in page.inner_text("[data-file-name]"))
        page.click("[data-file-remove]")
        check("and can be removed", page.locator("[data-drop]").is_visible() and not page.locator("[data-file]").is_visible())

        page.reload(wait_until="networkidle"); page.wait_for_function("window.__tbk === true")
        check("a reload keeps the draft", page.input_value("#f-name") == "Test Candidate" and "kept your draft" in page.inner_text("[data-status]").lower())
        check("but never the consent", not page.is_checked("#f-consent"))
        ctx.close()

        ctx, page = fresh(browser)
        logs = []
        page.on("console", lambda m: logs.append(m.text))
        posts = []
        page.on("request", lambda r: r.method != "GET" and posts.append(r.url))
        goto(page, "#apply")
        fill_valid(page)
        h0 = page.evaluate("document.querySelector('[data-sheet]').offsetHeight")
        page.click("[data-submit]"); page.wait_for_timeout(250)
        check("sending: the button says so and the form is busy", "sending" in page.inner_text("[data-submit]").lower() and page.get_attribute("[data-form]", "aria-busy") == "true")
        h1 = page.evaluate("document.querySelector('[data-sheet]').offsetHeight")
        page.wait_for_selector("[data-done]:not([hidden])", timeout=6000)
        check("success: the confirmation replaces the form", not page.locator("[data-form]").is_visible())
        check("success: focus moves to its heading", page.evaluate("document.activeElement.hasAttribute('data-done-title')"))
        check("success: the address is read back", "candidate@example.com" in page.inner_text("[data-done]"))
        check("success: the letterhead carries the name and discipline", "from test" in page.inner_text("[data-letterhead]").lower() and "atelier" in page.inner_text("[data-letterhead]").lower())
        check("success in demo: it says plainly that nothing was sent", (not demo) or "nothing was sent" in page.inner_text("[data-done]").lower())
        check("demo: nothing leaves the browser", (not demo) or not posts, str(posts))
        check("demo: the console summary names fields, never values", not any("candidate@example.com" in l for l in logs))
        check("the sheet does not jump while sending", abs(h1 - h0) <= 2, f"{h0} -> {h1}")
        check("success: the draft is gone", page.evaluate("sessionStorage.getItem('taboukhi.apply.v1')") is None)
        ctx.close()

        if demo:
            ctx, page = fresh(browser)
            goto(page, "?demo=fail#apply")
            fill_valid(page); page.click("[data-submit]")
            page.wait_for_function("document.querySelector('[data-alert]').textContent.length > 0", timeout=6000)
            check("failure: says nothing was lost", "nothing you entered has been lost" in page.inner_text("[data-alert]").lower())
            check("failure: everything is still there", page.input_value("#f-name") == "Test Candidate" and page.is_checked("#f-consent"))
            check("failure: focus returns to the button", page.evaluate("document.activeElement.hasAttribute('data-submit')"))
            ctx.close()

            ctx, page = fresh(browser)
            goto(page, "#apply")
            fill_valid(page, link=False)
            page.set_input_files("#f-cv", str(pdf)); page.wait_for_timeout(150)
            page.click("[data-submit]")
            page.wait_for_selector("[data-done]:not([hidden])", timeout=6000)
            check("a file alone satisfies the link-or-file rule", True)
            ctx.close()

        print("Phone")
        ctx, page = fresh(browser, 390, 844, True)
        goto(page, "#apply")
        sizes = page.locator(".form input:not([type=checkbox]):not([type=file]):not([tabindex='-1']), .form select, .form textarea").evaluate_all("els => els.map(e => parseFloat(getComputedStyle(e).fontSize))")
        check("every field is 16px or more (no iOS zoom)", min(sizes) >= 16, str(sizes))
        small = page.evaluate("""() => [...document.querySelectorAll('.form button, .form select, .form input:not([type=file]):not([type=checkbox]):not([tabindex="-1"]), .drop, .check, .row, .mast a, .hero .btn, .hero__cta .link')]
            .filter(e => e.offsetParent !== null).map(e => [e.className || e.id, Math.round(e.getBoundingClientRect().height)]).filter(([, h]) => h < 44)""")
        check("every control offers a 44px target", not small, str(small))
        c = page.evaluate("(() => { const r = document.querySelector('.check input').getBoundingClientRect(), t = document.querySelector('.check span').getBoundingClientRect(); return [r.right, t.left, r.top, t.top]; })()")
        check("the consent box sits beside its sentence", c[0] <= c[1] and abs(c[2] - c[3]) < 12, str(c))
        ctx.close()

        ctx, page = fresh(browser, java_script_enabled=False)
        page.goto(URL, wait_until="load")
        check("without JavaScript: nothing is left invisible", page.locator("[data-reveal]").evaluate_all("els => els.every(e => getComputedStyle(e).opacity !== '0')"))
        check("without JavaScript: the form says what it needs", page.locator("noscript").count() >= 1)
        ctx.close()
        browser.close()

    real = [r for r in results if r is not None]
    print(f"\n{sum(real)}/{len(real)} passed")
    sys.exit(0 if all(real) else 1)


if __name__ == "__main__":
    main()
