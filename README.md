# TABOUKHI — founding appointments

One-page site for TABOUKHI, the first eyewear brand established by Ilya Taboukhi. Its only
job for now: make exceptional people want to join, and let them apply on the page.

Static HTML + CSS + ES modules. No framework, no build step, no third-party requests.

    python3 serve.py            # http://localhost:8231
    python3 e2e.py              # end-to-end checks through system Chrome
    python3 e2e.py https://ilyatabrizi.github.io/taboukhi/

## The design — v2, "glass over their film" (2026-09-22)

v1 ("Elevation", a serif editorial page with a drawn wordmark and a metal O) was rejected
on sight: *"more minimal, really iOS, glassmorphism, less context, focused on the form."*
Ilya kept one thing from it: **the K** — the stemless K of the wordmark, two detached strokes.

- **Their film runs behind everything.** `assets/media/source/film-original.mp4` (their
  5 s temple-arm shot) → `scripts/build_film.py` → a 16 s seamless loop: the first 3.75 s
  eased out and back with optical-flow in-betweens, so it never jumps or bounces.
  1920 (desktop) / 1280 (phone), H.264, no audio, fast-start. A still loads first.
- **Everything in front of it is glass** (iOS 26): floating capsule controls, a glass sheet,
  a scroll-edge blur under the controls. Blur + saturate + a brightness clamp; an opaque
  fallback where backdrop-filter is missing.
- **The K, in liquid glass**, placed on the moving metal: the metal always crosses 38–56%
  of the frame's height, so the K is positioned from that geometry (see `css/main.css`).
- **The phone's own typeface**: SF Pro on Apple devices; Inter self-hosted for the rest.
- **The form is the page.** On desktop it is on the first screen; on a phone one tap on
  Apply. Grouped rows like iOS Settings, discipline chips, a Link/File segmented control,
  a consent switch.
- Onyx, bone, titanium greys. **"Titanium" is a colour name in the code only** — never in
  copy, alt text or meta tags, where it would read as a claim about the product. `e2e.py`
  enforces it.

## The form

`js/config.js` is the one switch. In `demo` mode nothing leaves the browser, the sheet shows
its PREVIEW flag, success says that nothing was sent, and `index.html` keeps `noindex`.

Going live: set `mode: 'endpoint'` and `endpoint` to a receiver on the house's own host
(multipart POST with the fields below + `cv` file; reply JSON `{ "ok": true, "reference"? }`;
`413` too large, `429` rate-limited, `422 { fieldErrors }` invalid), remove the robots meta
line, set `maxFileMB` to what the host really accepts. No interface change is needed.

The page is served from `https://ilyatabrizi.github.io` (or the final domain), so the
receiver is cross-origin: **every** response, 4xx and 5xx included, must carry
`Access-Control-Allow-Origin` for that origin. Without it the browser reports a network
failure even though the POST arrived, and a retry stores a duplicate. No preflight is sent.
Treat a repeat of the same email + discipline within a few minutes as one application.
`fieldErrors` keys the form can mark: `full_name email phone discipline portfolio_url
consent cv`; any other key's message is appended to the alert.

Fields: `full_name`* `email`* `phone` `location` `discipline`* `current_role`
`portfolio_url` / `cv` (one of the two)* `message` `consent`* + `consent_version`, `meta`
(`elapsed_ms`, honeypot flag — the server should quarantine, never silently drop).
All eight text fields are always present, empty if unused; `discipline` is the option slug
(e.g. `optics-fit`); `phone` arrives with ASCII digits; `consent` is the string `true`.
Set `fallbackEmail` in `js/config.js` before going live: it completes the consent sentence
("…deleted at any time by writing to …") and appears after a second failed send.

`?demo=fail`, `?demo=slow`, `?demo=offline` force each state in demo mode.

## Placeholders awaiting the owner

- The nine disciplines.
- Process promises: "We read every application with care and in confidence, and we write
  back to those we would like to meet", the "Read in confidence…" note, and the consent
  sentence. Personal data (CVs) will need a privacy notice and a retention period.
- Not stated because not known: where the house is based, whether roles are remote or
  paid, a contact email. The page says these are "the first thing we will discuss".

## Scripts

- `scripts/trace_logo.py` — the supplied 2000px PNG → `assets/brand/wordmark.svg` (2 KB,
  exact straight edges, 0.36% mean pixel difference, the K kept as two detached strokes).
  If vector artwork exists, it should replace the trace.
- `scripts/build_film.py` — the background loop, from their film.
- `scripts/build_assets.py` — the K mask, favicons, share card (cut from their still).
- `scripts/fetch_fonts.py` — Inter, subset and weight-cut, + fallback metrics.
- `scripts/shots.py` — viewport screenshots of every section.
