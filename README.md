# TABOUKHI — founding appointments

One-page site for TABOUKHI, the first eyewear brand established by Ilya Taboukhi. Its only
job for now: make exceptional people want to join, and let them apply on the page.

Static HTML + CSS + ES modules. No framework, no build step, no third-party requests.

    python3 serve.py            # http://localhost:8231
    python3 e2e.py              # end-to-end checks through system Chrome
    python3 e2e.py https://ilyatabrizi.github.io/taboukhi/

## The idea — "Elevation"

The wordmark is the building. It is drawn on onyx the way an architect draws a facade, and
the left edge of each of its eight letters is a column line (the Name Grid, `--x-a … --x-i`
in `css/main.css`) that the whole page hangs from. There is no photography, so there is one
light instead: a single slanted band, parallel to the A's left leg, that crosses the hero
letters, turns on the machined O (Fig. 2) and ends resting on the engraved name in the
footer. It moves only when the reader scrolls (`js/light.js`); nothing loops.

- Onyx `#020202`, Bone `#F4F2ED` (one token — `#FFFFFF` gives the palette file's literal
  white), and a titanium-grey scale `--ti-50 … --ti-900` in place of the burnt red.
  **"Titanium" is a colour name in the code only. It never appears in copy, alt text or
  meta tags, where it would read as a claim about the product.** `e2e.py` enforces this.
- Newsreader (one serif, three optical sizes) says everything the house says; Jost carries
  only labels, markers and buttons. `--font-caption` makes serif-only a one-line change.
- Hard cuts between grounds. No radius, no shadow, no blur.

## The form

`js/config.js` is the one switch. In `demo` mode nothing leaves the browser, the sheet shows
its PREVIEW flag, success says that nothing was sent, and `index.html` keeps `noindex`.

Going live: set `mode: 'endpoint'` and `endpoint` to a receiver on the house's own host
(multipart POST with the fields below + `cv` file; reply JSON `{ "ok": true, "reference"? }`;
`413` too large, `429` rate-limited, `422 { fieldErrors }` invalid), remove the robots meta
line, set `maxFileMB` to what the host really accepts. No interface change is needed.

Fields: `full_name`* `email`* `phone` `location` `discipline`* `current_role`
`portfolio_url` / `cv` (one of the two)* `message` `consent`* + `consent_version`, `meta`
(`elapsed_ms`, honeypot flag — the server should quarantine, never silently drop).

`?demo=fail`, `?demo=slow`, `?demo=offline` force each state in demo mode.

## Placeholders awaiting the owner

- The nine disciplines and their one-line descriptions, and the three "What we ask" items.
- Process promises: "We read every application with care and in confidence, and we write
  back to those we would like to meet", the "Read in confidence…" note, and the consent
  sentence. Personal data (CVs) will need a privacy notice and a retention period.
- Not stated because not known: where the house is based, whether roles are remote or
  paid, a contact email. The page says these are "the first thing we will discuss".

## Scripts

- `scripts/trace_logo.py` — the supplied 2000px PNG → `assets/brand/wordmark.svg` (2 KB,
  exact straight edges, 0.36% mean pixel difference, the K kept as two detached strokes).
  If vector artwork exists, it should replace the trace.
- `scripts/build_assets.py` — O masks for Fig. 2, K favicon, dither tile, share card.
- `scripts/fetch_fonts.py` — self-hosted, subset, weight-cut variable fonts + fallback metrics.
- `scripts/shots.py` — viewport screenshots of every section.
