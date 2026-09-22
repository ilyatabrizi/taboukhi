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
    page.wait_for_function("window.__tbk === true && !document.querySelector('[data-submit]').disabled")


def fill_valid(page, link=True):
    page.fill("#f-name", "Test Candidate")
    page.fill("#f-email", "candidate@example.com")
    page.click("label.chip:has(input[value=atelier])")
    if link:
        page.fill("#f-url", "example.com/portfolio")
    page.check("#f-consent")


GLASS_ANCESTORS = """() => [...document.querySelectorAll('*')].filter(e => {
    const s = getComputedStyle(e); return (s.backdropFilter && s.backdropFilter !== 'none') || (s.webkitBackdropFilter && s.webkitBackdropFilter !== 'none'); })
  .flatMap(e => { const bad = []; for (let a = e.parentElement; a; a = a.parentElement) { const s = getComputedStyle(a);
      if (s.transform !== 'none' || s.filter !== 'none' || s.perspective !== 'none' || parseFloat(s.opacity) < 1 || s.mixBlendMode !== 'normal')
        bad.push((e.className || e.tagName) + ' <- ' + (a.className || a.tagName)); } return bad; })"""


def main():
    tmp = pathlib.Path(tempfile.mkdtemp())
    pdf = tmp / "portfolio.pdf"; pdf.write_bytes(b"%PDF-1.4\n" + b"0" * 2048)
    fake = tmp / "not-really.pdf"; fake.write_bytes(b"GIF89a" + b"0" * 2048)
    exe = tmp / "tool.exe"; exe.write_bytes(b"MZ" + b"0" * 2048)
    big = tmp / "big.pdf"; big.write_bytes(b"%PDF-1.4\n" + b"0" * (11 * 1024 * 1024))

    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome")

        print("Document")
        ctx, page = fresh(browser)
        goto(page)
        check("no console or page errors on load", not page.errors, "; ".join(page.errors))
        check("exactly one h1", page.locator("h1").count() == 1)
        check("lang=en", page.get_attribute("html", "lang") == "en")
        visible = page.evaluate("document.body.innerText").lower()
        meta = " ".join(page.locator("meta[content]").evaluate_all("els => els.map(e => e.content)")).lower()
        attrs = " ".join(page.locator("[aria-label],[alt],[title],[placeholder]").evaluate_all("els => els.map(e => ['aria-label','alt','title','placeholder'].map(a => e.getAttribute(a)||'').join(' '))")).lower()
        for word in ("titanium", "luxury", "luxurious"):
            check(f"'{word}' appears nowhere a visitor or crawler reads", word not in visible and word not in meta and word not in attrs)
        check("the founder fact is stated verbatim", "taboukhi is the first eyewear brand established by ilya taboukhi" in visible)
        check("no year is printed", not re.search(r"\b(19|20)\d\d\b", visible))
        check("no email address is printed", "@" not in visible.replace("name@example.com", ""))
        demo = page.evaluate("import('./js/adapter.js').then(m => m.isDemo)")
        check("noindex stands exactly while the form is in demo mode", (page.locator("meta[name=robots][content*=noindex]").count() == 1) == demo)
        check("the preview flag shows exactly while in demo mode", page.locator(".sheet__head .flag").is_visible() == demo)
        k = page.evaluate("document.querySelector('#p-k').getAttribute('d')")
        check("the K is two detached strokes", k.count("M") == 2 and k.count("Z") == 2)
        slugs = page.locator("input[name=discipline]").evaluate_all("els => els.map(e => e.value)")
        check("nine disciplines, each a real choice", len(slugs) == 9 and len(set(slugs)) == 9 and "open" in slugs, str(slugs))
        for href in page.locator("a[href^='#']").evaluate_all("els => [...new Set(els.map(e => e.getAttribute('href')))]"):
            check(f"anchor {href} has a target", page.locator(href).count() == 1)
        for f in page.evaluate("[...document.querySelectorAll('link[href],script[src],source[src],img[src]')].map(e => e.href || e.src)"):
            check(f"loads {f.split('/')[-1]}", page.request.get(f).ok)
        origin = URL.split("/")[0] + "//" + URL.split("/")[2]
        check("no third-party requests", all(u.startswith(origin) for u in page.evaluate("performance.getEntriesByType('resource').map(r => r.name)")))
        ctx.close()

        print("Film")
        ctx, page = fresh(browser)
        goto(page)
        page.wait_for_function("document.querySelector('[data-film]').classList.contains('is-on')", timeout=8000)
        geo = page.evaluate("(() => { const v = document.querySelector('[data-film]').getBoundingClientRect(); return [v.left <= 0, v.top <= 0, v.right >= innerWidth, v.bottom >= innerHeight]; })()")
        check("the film covers the whole screen", all(geo), str(geo))
        check("the film has no sound to play", page.evaluate("(() => { const v = document.querySelector('[data-film]'); return v.muted && (v.mozHasAudio === undefined ? !(v.webkitAudioDecodedByteCount > 0) : !v.mozHasAudio); })()"))
        a = page.screenshot(clip={"x": 0, "y": 0, "width": 1440, "height": 900})
        page.wait_for_timeout(1200)
        b = page.screenshot(clip={"x": 0, "y": 0, "width": 1440, "height": 900})
        from PIL import Image, ImageChops
        import io
        diff = ImageChops.difference(Image.open(io.BytesIO(a)).convert("L"), Image.open(io.BytesIO(b)).convert("L"))
        mean = sum(i * n for i, n in enumerate(diff.histogram())) / (1440 * 900)
        check("the film is visibly moving on screen", mean > 0.15, f"mean diff {mean:.3f}")
        page.click("[data-film-toggle]")
        page.wait_for_timeout(200)
        check("the film can be paused, and the button says so", page.evaluate("document.querySelector('[data-film]').paused") and page.get_attribute("[data-film-toggle]", "aria-label") == "Play the film")
        page.click("[data-film-toggle]")
        page.wait_for_timeout(300)
        check("and played again", not page.evaluate("document.querySelector('[data-film]').paused"))
        ctx.close()

        print("Glass")
        for w, h, mobile in ((390, 844, True), (1440, 900, False)):
            ctx, page = fresh(browser, w, h, mobile)
            goto(page)
            bad = page.evaluate(GLASS_ANCESTORS)
            check(f"{w}: no glass sits under a backdrop root (transform, filter, opacity, blend)", not bad, "; ".join(bad[:4]))
            bf = page.evaluate("['.sheet', '.home', '.round', '.kglass__body'].map(s => getComputedStyle(document.querySelector(s)).backdropFilter)")
            check(f"{w}: sheet, controls and the K are real glass", all(x and x != "none" for x in bf), str(bf))
            ctx.close()

        print("Layout")
        for w, h, mobile in ((375, 667, True), (390, 844, True), (768, 1024, True), (1080, 800, False), (1366, 640, False), (1440, 900, False), (2560, 1440, False)):
            ctx, page = fresh(browser, w, h, mobile)
            goto(page)
            sw = page.evaluate("document.documentElement.scrollWidth")
            check(f"{w}x{h}: no horizontal scroll", sw <= w, f"scrollWidth {sw}")
            g = page.evaluate("""() => { const r = s => document.querySelector(s).getBoundingClientRect();
                const k = r('.kglass'), say = r('.intro__say'), bar = r('.bar'), sheet = r('.sheet'), t = r('.title');
                return { k: [k.left, k.top, k.right, k.bottom], say: [say.left, say.top], barB: r('.home').bottom, sheetTop: sheet.top, sheetL: sheet.left, titleB: t.bottom, vh: innerHeight, vw: innerWidth }; }""")
            check(f"{w}x{h}: the K clears the controls and the words start below it",
                  g["k"][1] >= g["barB"] + 8 and g["say"][1] >= g["k"][3] - 1, str(g))
            check(f"{w}x{h}: the K is aligned with the words", abs(g["k"][0] - g["say"][0]) <= 1, str(g))
            if w >= 1080:
                check(f"{w}x{h}: the form is on the first screen", g["sheetTop"] < g["vh"] * .25 and g["sheetL"] > g["vw"] * .4, str(g))
                first = page.evaluate("document.querySelector('#f-name').getBoundingClientRect().bottom")
                check(f"{w}x{h}: the first answer can be typed without scrolling", first < h, str(first))
            else:
                cta = page.evaluate("document.querySelector('.intro__cta').getBoundingClientRect().bottom")
                check(f"{w}x{h}: the headline and Apply are on the first screen", g["titleB"] < h and cta <= h, f"{g['titleB']} {cta}")
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            page.wait_for_timeout(200)
            check(f"{w}x{h}: still no horizontal scroll at the foot", page.evaluate("document.documentElement.scrollWidth") <= w)
            ctx.close()

        print("Controls")
        ctx, page = fresh(browser, 390, 844, True)
        goto(page)
        check("the scroll edge is off at the top", page.evaluate("!document.querySelector('[data-edge]').hasAttribute('data-on')"))
        page.evaluate("scrollTo(0, 600)"); page.wait_for_timeout(300)
        check("and on once the sheet slides beneath the controls", page.evaluate("document.querySelector('[data-edge]').hasAttribute('data-on')"))
        page.evaluate("scrollTo(0, 0)"); page.wait_for_timeout(200)
        page.click(".intro__cta"); page.wait_for_timeout(1200)
        top = page.evaluate("document.querySelector('#application').getBoundingClientRect().top")
        check("Apply brings the sheet up, clear of the controls", 56 < top < 110, str(top))
        small = page.evaluate("""() => [...document.querySelectorAll('.form button, .chip span, .seg__opt, .row, .row--switch, .control, .pill, .attach')]
            .filter(e => e.offsetParent !== null).map(e => [e.className || e.tagName, Math.round(e.getBoundingClientRect().height)]).filter(([, h]) => h < 38)""")
        check("every control offers a finger-sized target", not small, str(small))
        sizes = page.locator(".form input:not([type=checkbox]):not([type=radio]):not([type=file]):not([tabindex='-1']), .form textarea").evaluate_all("els => els.map(e => parseFloat(getComputedStyle(e).fontSize))")
        check("every field is 16px or more (no iOS zoom)", min(sizes) >= 16, str(sizes))
        ctx.close()

        print("Application")
        ctx, page = fresh(browser)
        goto(page)
        page.click("[data-submit]"); page.wait_for_timeout(200)
        status = page.inner_text("[data-status]")
        check("empty send: says how many answers need attention", "5 answers need your attention" in status, status)
        check("empty send: focus goes to the first of them", page.evaluate("document.activeElement.id") == "f-name")
        inv = page.locator("[aria-invalid='true']").evaluate_all("els => els.map(e => e.id)")
        check("empty send: each is marked for assistive tech", sorted(inv) == sorted(["f-name", "f-email", "f-disc", "f-url", "f-consent"]), str(inv))
        check("empty send: the link-or-file message is carried by both of its controls", all("pair-err" in (page.get_attribute(s, "aria-describedby") or "") for s in ("#f-url", "#f-cv")))
        page.fill("#f-name", "Test Candidate"); page.wait_for_timeout(50)
        check("an error clears the moment it is fixed", page.inner_text("#f-name-err") == "")
        page.focus("#f-name"); page.keyboard.press("Enter")
        check("Enter in a field moves to the next one, it does not send", page.evaluate("document.activeElement.id") == "f-email" and page.get_attribute("[data-form]", "aria-busy") != "true")
        page.fill("#f-email", "someone@gmial.com"); page.locator("#f-email").blur(); page.wait_for_timeout(50)
        check("a common email typo is offered, not auto-corrected", "did you mean someone@gmail.com" in page.inner_text("#f-email-err").lower() and page.input_value("#f-email") == "someone@gmial.com")
        page.locator("#f-email-err button").click()
        check("accepting the suggestion fixes the address", page.input_value("#f-email") == "someone@gmail.com")
        page.fill("#f-phone", "abc"); page.locator("#f-phone").blur()
        check("a bad telephone number is caught, gently", "leave it empty" in page.inner_text("#f-phone-err"))
        page.fill("#f-phone", "۰۹۱۲ ۳۴۵ ۶۷۸۹"); page.locator("#f-phone").blur()
        check("a telephone number in Persian digits is accepted", page.inner_text("#f-phone-err") == "")
        page.fill("#f-phone", "")
        page.click("label.chip:has(input[value=optics-fit])")
        check("a discipline chip is chosen with one tap", page.evaluate("document.forms['application-form'].elements.discipline.value") == "optics-fit" and page.get_attribute("#f-disc", "aria-invalid") == "false")
        page.fill("#f-url", "example.com/work"); page.locator("#f-url").blur()
        check("a bare link gains https://", page.input_value("#f-url") == "https://example.com/work")

        page.click("label.seg__opt:has(input[value=file])"); page.wait_for_timeout(450)
        check("the segmented control swaps Link for File", page.locator("[data-pane=file]").is_visible() and not page.locator("[data-pane=link]").is_visible()
              and page.evaluate("getComputedStyle(document.querySelector('.seg__thumb')).transform") != "none")
        page.set_input_files("#f-cv", str(exe)); page.wait_for_timeout(150)
        check("a wrong file type is refused with a sentence", "pdf or a word" in page.inner_text("#f-cv-err").lower() and not page.locator("[data-file]").is_visible())
        page.set_input_files("#f-cv", str(fake)); page.wait_for_timeout(150)
        check("a PDF that is not a PDF is refused", "pdf or a word" in page.inner_text("#f-cv-err").lower())
        page.set_input_files("#f-cv", str(big)); page.wait_for_timeout(300)
        check("an oversized file is refused, naming the limit", "10 mb limit" in page.inner_text("#f-cv-err").lower() or "10 mb limit" in page.inner_text("#f-cv-err").lower(), page.inner_text("#f-cv-err"))
        page.set_input_files("#f-cv", str(pdf)); page.wait_for_timeout(150)
        check("a good PDF shows in the row", page.locator("[data-file]").is_visible() and "portfolio.pdf" in page.inner_text("[data-file-name]"))
        check("its size reads in KB when small", page.inner_text("[data-file-size]").endswith("KB"), page.inner_text("[data-file-size]"))
        page.set_input_files("#f-cv", str(exe)); page.wait_for_timeout(150)
        check("a refused second pick keeps the file already attached", page.locator("[data-file]").is_visible() and "we kept portfolio.pdf" in page.inner_text("#f-cv-err").lower())
        page.focus("#f-url") if page.locator("#f-url").is_visible() else None
        page.click("[data-file-remove]")
        check("and it can be removed", page.locator("[data-drop]").is_visible() and not page.locator("[data-file]").is_visible() and page.inner_text("#f-cv-err") == "")

        page.reload(wait_until="networkidle"); page.wait_for_function("window.__tbk === true")
        check("a reload keeps the draft, including the chip and the pane",
              page.input_value("#f-name") == "Test Candidate" and page.is_checked("input[name=discipline][value=optics-fit]")
              and page.locator("[data-pane=file]").is_visible() and "kept your draft" in page.inner_text("[data-status]").lower())
        check("but never the consent", not page.is_checked("#f-consent"))
        ctx.close()

        ctx, page = fresh(browser)
        logs, posts = [], []
        page.on("console", lambda m: logs.append(m.text))
        page.on("request", lambda r: r.method != "GET" and posts.append(r.url))
        goto(page, "#application")
        fill_valid(page)
        page.click("[data-submit]"); page.wait_for_timeout(250)
        check("sending: the button says so and the form is busy", "sending" in page.inner_text("[data-submit]").lower() and page.get_attribute("[data-form]", "aria-busy") == "true")
        check("sending: nothing else can be changed", page.evaluate("document.querySelector('[data-field=consent]').inert && document.querySelector('[data-clear]').disabled"))
        page.wait_for_selector("[data-done]:not([hidden])", timeout=6000)
        check("success: the confirmation replaces the form", not page.locator("[data-form]").is_visible())
        check("success: focus moves to its heading", page.evaluate("document.activeElement.hasAttribute('data-done-title')"))
        done = page.inner_text("[data-done]")
        check("success: the address is read back, and the name", "candidate@example.com" in done and "test" in done.lower())
        check("success in demo: it says plainly that nothing was sent", (not demo) or "nothing was sent" in done.lower())
        check("demo: nothing leaves the browser", (not demo) or not posts, str(posts))
        check("demo: the console summary names fields, never values", not any("candidate@example.com" in line for line in logs))
        check("success: the draft is gone", page.evaluate("sessionStorage.getItem('taboukhi.apply.v2')") is None)
        page.evaluate("dispatchEvent(new Event('pagehide'))")
        page.reload(wait_until="networkidle"); page.wait_for_function("window.__tbk === true")
        check("a sent application does not come back as a draft", page.input_value("#f-name") == "" and "kept your draft" not in page.inner_text("[data-status]").lower())
        ctx.close()

        if demo:
            ctx, page = fresh(browser)
            goto(page, "?demo=fail#application")
            fill_valid(page); page.click("[data-submit]")
            page.wait_for_function("document.querySelector('[data-alert]').textContent.length > 0", timeout=6000)
            check("failure: says nothing was lost", "nothing you entered has been lost" in page.inner_text("[data-alert]").lower())
            check("failure: everything is still there", page.input_value("#f-name") == "Test Candidate" and page.is_checked("#f-consent"))
            check("failure: focus returns to the button", page.evaluate("document.activeElement.hasAttribute('data-submit')"))
            ctx.close()

            ctx, page = fresh(browser)
            goto(page, "#application")
            fill_valid(page, link=False)
            page.click("label.seg__opt:has(input[value=file])")
            page.set_input_files("#f-cv", str(pdf)); page.wait_for_timeout(150)
            page.click("[data-submit]")
            page.wait_for_selector("[data-done]:not([hidden])", timeout=6000)
            check("a file alone satisfies the link-or-file rule", True)
            ctx.close()

        print("Keyboard and assistive tech")
        ctx, page = fresh(browser)
        goto(page, "#application")
        page.focus("#f-role"); page.keyboard.press("Shift+Tab"); page.keyboard.press("Tab"); page.wait_for_timeout(400)
        ring = page.evaluate("getComputedStyle(document.querySelector('#f-role').closest('.row')).boxShadow")
        check("a keyboard-focused row shows it", page.evaluate("document.activeElement.id") == "f-role" and ring != "none", ring)
        page.focus("input[name=discipline][value=atelier]"); page.keyboard.press("ArrowRight")
        check("chips move with the arrow keys, like any radio group", page.evaluate("document.activeElement.value") == "precious-materials" and page.is_checked("input[name=discipline][value=precious-materials]"))
        chip = page.evaluate("getComputedStyle(document.activeElement.nextElementSibling).outlineStyle")
        check("and the focused chip is outlined", chip == "solid", chip)
        check("the discipline group is named and required", page.get_attribute("#f-disc", "role") == "radiogroup" and page.get_attribute("#f-disc", "aria-required") == "true")
        check("consent is a switch", page.get_attribute("#f-consent", "role") == "switch")
        check("the file control's name includes its visible words", "f-cv-cta" in page.get_attribute("#f-cv", "aria-labelledby"))
        check("nothing is announced as invalid before anyone has typed", page.locator("[aria-invalid='true']").count() == 0)
        ctx.close()

        ctx, page = fresh(browser, java_script_enabled=False)
        page.goto(URL, wait_until="load")
        check("without JavaScript: the form says what it needs", page.locator("noscript").count() >= 1)
        check("without JavaScript: the form cannot be sent natively", page.is_disabled("[data-submit]"))
        check("without JavaScript: the still of the film is there", page.evaluate("document.querySelector('.film__still').complete && document.querySelector('.film__still').naturalWidth > 0"))
        ctx.close()
        browser.close()

    print(f"\n{sum(results)}/{len(results)} passed")
    sys.exit(0 if all(results) else 1)


if __name__ == "__main__":
    main()
