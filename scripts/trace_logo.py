#!/usr/bin/env python3
"""
trace_logo.py - trace the TABOUKHI raster wordmark to a production SVG and verify it.

    python3 scripts/trace_logo.py            # trace + verify
    python3 scripts/trace_logo.py --debug    # also print the structure of every contour
    python3 scripts/trace_logo.py --no-verify

Source : assets/brand/source/wordmark-black.png   (2000x227 RGBA, glyphs live in ALPHA)
Output : assets/brand/wordmark.svg                 one <path> per letter, fill=currentColor
         assets/brand/wordmark.json                bboxes, stroke thickness, cap height, verification
         assets/brand/wordmark-path-only.txt       all path data concatenated (CSS mask / inline)
         scripts/shots/trace-check*.png            3x source | trace | overlay sheets

Method
  1. alpha -> pad -> 4x Lanczos -> skimage.find_contours(0.5): sub-pixel closed contours, holes kept.
  2. every contour is resampled to uniform arc length, then split into STRAIGHT runs and CURVED runs:
       straight run = longest stretch whose total-least-squares residual stays under a tight
       tolerance (prefix sums + binary search, greedy longest-first), ends refined by max deviation.
  3. straight runs become exact lines. Lines within SNAP_DEG of an axis become perfectly
     axis-aligned (emitted as H / V) and their position is re-measured from alpha coverage.
     Axis-aligned edges that land within SHARE_TOL of each other share one coordinate; diagonal
     edges within SHARE_DEG of each other share one angle (parallel stroke sides stay parallel).
  4. two lines that meet in a raster-sharp corner are intersected: the corner is the exact vertex.
  5. everything else is a curved run: split at sharp interior corners (the B's waist) and at
     horizontal / vertical extrema (tangent forced exactly H / V there), then least-squares
     cubic Bezier fitting (Schneider) with G1 tangents taken from the neighbouring lines.
  6. verify: rasterise the SVG in Chrome at 2000 px, compare with the source alpha (MAD, IoU).
"""
import json
import math
import sys
from pathlib import Path

import numpy as np
from PIL import Image
from scipy.ndimage import gaussian_filter1d
from skimage import measure

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "assets/brand/source/wordmark-black.png"
OUT_SVG = ROOT / "assets/brand/wordmark.svg"
OUT_JSON = ROOT / "assets/brand/wordmark.json"
OUT_TXT = ROOT / "assets/brand/wordmark-path-only.txt"
SHOTS = ROOT / "scripts/shots"
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

WORD = "TABOUKHI"
IDS = ["l-t", "l-a", "l-b", "l-o", "l-u", "l-k", "l-h", "l-i"]

# ---- tuning (all lengths in source pixels) -------------------------------------------------
PAD = 8              # transparent padding so border-touching ink still closes
UP = 4               # Lanczos upsample factor before contouring
H_STEP = 0.2         # uniform arc-length resampling step
SIG_DETECT = 1.2     # contour smoothing used for line detection / tangents
SIG_FIT = 0.6        # contour smoothing for fitting small fillets (kills stair-step aliasing)
SIG_CURVE = 1.5      # contour smoothing for fitting the big curves (the source has sub-pixel steps)
MIN_LINE = 14.0      # shortest straight run we look for
RMS_TOL = 0.07       # TLS residual (rms) allowed on a straight run (on the SIG_DETECT contour)
DEV_TOL = 0.16       # max deviation that still counts as "on the line" when refining the ends
BUMP_MAX = 0.6       # a bump in an edge smaller than this ...
BUMP_LOOK = 40.0     # ...that returns to the line within this distance is bridged (source artefact)
LONG_DEV = 0.75      # a long run that strays further than this from its own line is an arc, not an edge
MIN_FINAL = 12.0     # lines shorter than this after refinement are given back to the curves
FLAT_MAX = 40.0      # a line shorter than this that is tangent to curves on BOTH sides is a flat
FLAT_DEG = 20.0      # ...spot of a curve, not a line (turn measured END_LOOK beyond each end)
END_LOOK = 6.0
CORNER_END = 35.0    # an end that turns more than this is a corner end
SNAP_RISE = 0.5      # a SHORT edge that rises less than this over its length is axis-aligned too
                     # (the K's pointed terminals rise 0.8-1.4 px towards the tip in the source: kept as drawn)
TRIM = 7.0           # a line that flows into a curve is cut back this far; the cubic takes over
BEND_DEG = 1.5       # a short run whose two ends point this far apart is an arc chord, not a line
FILLET_TRIM = 0.6    # ...but only this far next to a small rounded corner
MERGE_DEG = 2.5      # consecutive straight runs this parallel ...
MERGE_OFF = 0.9      # ...and this close to collinear are ONE edge (the source has sub-pixel steps)
MERGE_GAP = 20.0     # ...if the gap between them along the contour is shorter than this
SNAP_DEG = 0.30      # closer than this to an axis -> perfectly axis-aligned
SHARE_TOL = 0.30     # axis-aligned edges within this span share one coordinate
SHARE_SAME = 0.70    # ...this span when they are the same side of the same contour (an interrupted edge)
CAP_TOL = 1.25       # flat tops within this of the highest one are candidates for THE cap line (same for the baseline)
CAP_KEEP = 0.50      # ...and those within this of the candidates' mean are put exactly on it
SHARE_DEG = 0.35     # diagonal edges within this span share one angle
CORNER_RHO = 1.9     # a corner whose implied rounding radius is below this is SHARP (raster blur only)
CORNER_TURN = 45.0   # ...inside a curved run it must also turn at least this much
CORNER_GAP = 9.0     # ...and the gap between the two lines must be shorter than this
FIT_RMS = 0.40       # Schneider: rms error a single cubic may have ...
FIT_TOL = 1.20       # Schneider max error before a cubic is split
EXT_MARGIN = 5.0     # extrema closer than this to the end of a curved run are ignored
EXT_PAR = math.cos(math.radians(4.0))
EXT_NEAR = 15.0      # an extremum this close to a line with the same direction is redundant
EXT_HYST = 3.0       # deg: tangent must swing from -this to +this around an axis to count
EXT_REACH = 70.0     # how far along the contour either side of an extremum we look to locate it
EXT_DEPTHS = (1.0, 1.5, 2.0, 2.5, 3.0, 4.0)   # chord depths whose midpoints give the axis of the arc

DEBUG = "--debug" in sys.argv


def dbg(*a):
    if DEBUG:
        print(*a)


# =============================================================================================
# raster -> contours
# =============================================================================================
def load_alpha():
    im = Image.open(SRC).convert("RGBA")
    return np.asarray(im)[:, :, 3].astype(np.float32) / 255.0


def dense_contours(alpha):
    h, w = alpha.shape
    p = np.pad(alpha, PAD)
    big = Image.fromarray(p).resize(((w + 2 * PAD) * UP, (h + 2 * PAD) * UP), Image.LANCZOS)
    big = np.asarray(big)
    out = []
    for c in measure.find_contours(big, 0.5):
        if np.abs(c[0] - c[-1]).max() > 1e-6:
            continue                                   # open contour: cannot happen with padding
        pts = np.stack([(c[:-1, 1] + 0.5) / UP - PAD, (c[:-1, 0] + 0.5) / UP - PAD], 1)
        if abs(poly_area(pts)) < 4.0:
            continue                                   # speck
        out.append(pts)
    return out


def poly_area(p):
    x, y = p[:, 0], p[:, 1]
    return 0.5 * float(np.sum(x * np.roll(y, -1) - np.roll(x, -1) * y))


def resample_closed(p, step):
    q = np.vstack([p, p[:1]])
    seg = np.hypot(*np.diff(q, axis=0).T)
    s = np.concatenate([[0], np.cumsum(seg)])
    n = int(round(s[-1] / step))
    t = np.arange(n) * (s[-1] / n)
    return np.stack([np.interp(t, s, q[:, 0]), np.interp(t, s, q[:, 1])], 1), s[-1] / n


def smooth_closed(p, sigma_px, h):
    sg = sigma_px / h
    return np.stack([gaussian_filter1d(p[:, 0], sg, mode="wrap"),
                     gaussian_filter1d(p[:, 1], sg, mode="wrap")], 1)


def point_in_poly(pt, poly):
    x, y = pt
    px, py = poly[:, 0], poly[:, 1]
    qx, qy = np.roll(px, -1), np.roll(py, -1)
    cond = (py > y) != (qy > y)
    xi = px + (y - py) * (qx - px) / np.where(qy == py, 1e-12, (qy - py))
    return bool(np.sum(cond & (x < xi)) % 2)


# =============================================================================================
# small geometry helpers
# =============================================================================================
def tls(pts):
    """total least squares line: centroid, unit direction"""
    c = pts.mean(0)
    _, _, vt = np.linalg.svd(pts - c, full_matrices=False)
    return c, vt[0]


def unit(v):
    v = np.asarray(v, float)
    n = math.hypot(v[0], v[1])
    return v / n if n else v


def perp(d):
    return np.array([-d[1], d[0]])


def ang_deg(d):
    return math.degrees(math.atan2(d[1], d[0]))


def ang_between(a, b):
    return math.degrees(math.acos(max(-1.0, min(1.0, float(np.dot(a, b))))))


def intersect(c1, d1, c2, d2):
    m = np.array([[d1[0], -d2[0]], [d1[1], -d2[1]]])
    t = np.linalg.solve(m, np.asarray(c2) - np.asarray(c1))
    return np.asarray(c1) + t[0] * np.asarray(d1)


def corner_rho(dist, turn_deg):
    """radius of the fillet that would put the contour `dist` away from the sharp vertex"""
    phi = math.radians(max(1.0, 180.0 - turn_deg))         # interior angle
    k = 1.0 / math.sin(phi / 2) - 1.0
    return dist / max(k, 1e-6)


# =============================================================================================
# straight-run detection
# =============================================================================================
def detect_lines(ps, h):
    """greedy longest-first straight runs on the closed, uniformly sampled contour ps"""
    n = len(ps)
    q = ps - ps.mean(0)
    x = np.concatenate([q, q, q[:1]])

    def cs(v):
        return np.concatenate([[0.0], np.cumsum(v)])

    sx, sy = cs(x[:, 0]), cs(x[:, 1])
    sxx, syy, sxy = cs(x[:, 0] ** 2), cs(x[:, 1] ** 2), cs(x[:, 0] * x[:, 1])

    def lam(i, ln):
        j = i + ln
        m = ln.astype(float)
        mx, my = (sx[j] - sx[i]) / m, (sy[j] - sy[i]) / m
        cxx = (sxx[j] - sxx[i]) / m - mx * mx
        cyy = (syy[j] - syy[i]) / m - my * my
        cxy = (sxy[j] - sxy[i]) / m - mx * my
        tr = cxx + cyy
        det = cxx * cyy - cxy * cxy
        return np.maximum(tr / 2 - np.sqrt(np.maximum(tr * tr / 4 - det, 0)), 0)

    lmin = int(MIN_LINE / h)
    if n <= lmin + 2:
        return []
    tol2 = RMS_TOL ** 2
    i = np.arange(n)
    ok0 = lam(i, np.full(n, lmin)) <= tol2
    lo = np.full(n, lmin)
    hi = np.full(n, n - 2)
    for _ in range(18):
        mid = (lo + hi + 1) // 2
        good = lam(i, mid) <= tol2
        lo = np.where(good, mid, lo)
        hi = np.maximum(np.where(good, hi, mid - 1), lo)
    ln = np.where(ok0, lo, 0)

    runs = []
    ks = np.arange(1, n)
    while True:
        i0 = int(np.argmax(ln))
        l0 = int(ln[i0])
        if l0 < lmin:
            break
        runs.append([i0, i0 + l0 - 1])
        ln[(i0 + np.arange(l0)) % n] = 0
        s = (i0 - ks) % n
        ln[s] = np.minimum(ln[s], ks)
    return runs


def _walk(dev, h):
    """how far (in samples) we may walk along |dev| before leaving the line for good.
    A sub-pixel bump that comes back onto the line is bridged; a curve that departs is not."""
    k = 0
    m = len(dev)
    while True:
        bad = np.where(dev[k:] > DEV_TOL)[0]
        if not len(bad):
            return m - 1
        k = k + int(bad[0]) - 1                                # last sample still on the line
        look = dev[k + 1:k + 1 + int(BUMP_LOOK / h)]
        over = np.where(look > BUMP_MAX)[0]
        if len(over):
            look = look[:over[0]]
        back = np.where(look < 0.6 * DEV_TOL)[0]
        if not len(back):
            return max(k, 0)
        k = k + 1 + int(back[-1])                              # bridge the bump, keep walking


def refine_run(ps, i0, i1, h):
    """grow / shrink a run until the (smoothed) contour leaves the fitted line by DEV_TOL"""
    n = len(ps)
    ext = int(60.0 / h)
    for _ in range(4):
        m = i1 - i0 + 1
        a, b = i0 + int(0.15 * m), i1 - int(0.15 * m)
        c, d = tls(ps[np.arange(a, b + 1) % n])
        nr = perp(d)
        mid = (i0 + i1) // 2
        kr = np.arange(mid, min(i1 + ext, i0 + n - 2) + 1)
        n1 = mid + _walk(np.abs((ps[kr % n] - c) @ nr), h)
        kl = np.arange(mid, max(i0 - ext, i1 - n + 2) - 1, -1)
        n0 = mid - _walk(np.abs((ps[kl % n] - c) @ nr), h)
        if (n0, n1) == (i0, i1):
            break
        i0, i1 = n0, n1
        if i1 - i0 < 5:
            break
    return i0, i1


class Line:
    def __init__(self, i0, i1):
        self.i0, self.i1 = i0, i1          # unwrapped sample indices, i1 > i0
        self.c = None                      # a point on the line
        self.d = None                      # unit direction, along contour travel
        self.axis = None                   # 'H' (y constant) | 'V' (x constant) | None
        self.contour = None
        self.j0 = self.j1 = None           # trimmed indices actually used as nodes
        self.p0 = self.p1 = None           # final start / end nodes
        self.head = self.tail = None       # (c, d) of the first / last un-merged piece

    def length(self, h):
        return (self.i1 - self.i0) * h

    def project(self, p):
        return self.c + np.dot(np.asarray(p) - self.c, self.d) * self.d


def classify_axis(ln, p, h, alpha, force=None):
    """perfectly axis-aligned if within SNAP_DEG; position re-measured from alpha coverage"""
    ang = ang_deg(ln.d) % 180.0
    ln.axis = force
    if ln.axis is None:
        ln_len = ln.length(h)
        for axis, tilt in (("H", min(ang, 180 - ang)), ("V", abs(ang - 90))):
            if tilt < SNAP_DEG or (ln_len < FLAT_MAX and ln_len * math.sin(math.radians(tilt)) < SNAP_RISE
                                   and tilt < 5.0):
                ln.axis = axis
    if ln.axis:
        k = 0 if ln.axis == "V" else 1
        v = float(ln.c[k])
        cov = coverage_edge(alpha, ln, p, h)
        if cov is not None and abs(cov - v) < 0.25:
            v = cov
        ln.c = ln.c.copy()
        ln.c[k] = v
        sgn = 1.0 if ln.d[1 - k] > 0 else -1.0
        ln.d = np.array([sgn, 0.0]) if ln.axis == "H" else np.array([0.0, sgn])


def make_line(p, a, b, h, alpha):
    n = len(p)
    ln = Line(a, b)
    sh = int(1.5 / h)
    c, d = tls(p[np.arange(a + sh, b - sh + 1) % n])       # final fit on the RAW contour
    if np.dot(p[(b - sh) % n] - p[(a + sh) % n], d) < 0:
        d = -d
    ln.c, ln.d = c, d
    classify_axis(ln, p, h, alpha)
    ln.head = ln.tail = (ln.c.copy(), ln.d.copy())          # local geometry at either end
    return ln


def merge_lines(p, a, b, wrap, h, alpha):
    n = len(p)
    ln = Line(a.i0, b.i1 + wrap)
    sh = int(1.5 / h)
    c, d = tls(p[np.arange(ln.i0 + sh, ln.i1 - sh + 1) % n])
    ln.c, ln.d = c, (d if np.dot(d, a.d) > 0 else -d)
    classify_axis(ln, p, h, alpha, force=a.axis if (a.axis and a.axis == b.axis) else None)
    ln.head, ln.tail = a.head, b.tail
    return ln


def find_lines(p, ps, h, alpha):
    n = len(p)
    runs = detect_lines(ps, h)
    runs = [list(refine_run(ps, a, b, h)) for a, b in runs]
    runs = [r for r in runs if r[1] - r[0] > 5]

    def norm(items, get, put):
        for it in items:
            k = get(it)[0] // n
            put(it, get(it)[0] - k * n, get(it)[1] - k * n)

    norm(runs, lambda r: r, lambda r, a, b: r.__setitem__(slice(0, 2), [a, b]))
    runs.sort()
    # runs that turned out to be the same line -> one run; small overlaps at corners -> clipped
    changed = True
    while changed and len(runs) > 1:
        changed = False
        for k in range(len(runs)):
            a, b = runs[k], runs[(k + 1) % len(runs)]
            wrap = n if (k + 1) == len(runs) else 0
            b0, b1 = b[0] + wrap, b[1] + wrap
            if a[1] >= b0:
                if a[1] - b0 + 1 > 0.5 * min(a[1] - a[0], b1 - b0):
                    runs[k] = list(refine_run(ps, a[0], max(a[1], b1), h))
                    runs.pop((k + 1) % len(runs))
                    norm(runs, lambda r: r, lambda r, x, y: r.__setitem__(slice(0, 2), [x, y]))
                    runs.sort()
                    changed = True
                    break
                cut = (a[1] + b0) // 2
                a[1] = cut
                b[0] = cut + 1 - wrap
    lines = [make_line(p, a, b, h, alpha) for a, b in runs if (b - a) * h >= MIN_FINAL]
    # the source has sub-pixel steps / kinks along edges that are obviously one straight edge
    merged = True
    while merged and len(lines) > 1:
        merged = False
        for k in range(len(lines)):
            a, b = lines[k], lines[(k + 1) % len(lines)]
            wrap = n if (k + 1) == len(lines) else 0
            gap = (b.i0 + wrap - a.i1) * h
            if gap > MERGE_GAP or ang_between(a.d, b.d) > MERGE_DEG:
                continue
            off = max(abs(float(np.dot(p[b.i0 % n] - a.c, perp(a.d)))),
                      abs(float(np.dot(p[a.i1 % n] - b.c, perp(b.d)))))
            if off > MERGE_OFF:
                continue
            dbg("    merge collinear runs len %.1f + %.1f (offset %.2f, angle %.2f)"
                % (a.length(h), b.length(h), off, ang_between(a.d, b.d)))
            lines[k] = merge_lines(p, a, b, wrap, h, alpha)
            lines.pop((k + 1) % len(lines))
            norm(lines, lambda l: (l.i0, l.i1), lambda l, x, y: (setattr(l, "i0", x), setattr(l, "i1", y)))
            lines.sort(key=lambda l: l.i0)
            merged = True
            break
    # short runs only: chords of arcs and (clipped) flat spots of curves are not lines
    keep = []
    look = int(END_LOOK / h)
    for ln in lines:
        t0 = unit(ps[(ln.i0 - look + 3) % n] - ps[(ln.i0 - look - 3) % n])
        t1 = unit(ps[(ln.i1 + look + 3) % n] - ps[(ln.i1 + look - 3) % n])
        e0, e1 = ang_between(t0, ln.d), ang_between(t1, ln.d)
        m = (ln.i1 - ln.i0) // 3
        _, d0 = tls(ps[np.arange(ln.i0, ln.i0 + m + 1) % n])
        _, d1 = tls(ps[np.arange(ln.i1 - m, ln.i1 + 1) % n])
        bend = ang_between(d0, d1 if np.dot(d0, d1) > 0 else -d1)
        if ln.length(h) < FLAT_MAX:
            if e0 < FLAT_DEG and e1 < FLAT_DEG:
                dbg("    drop flat spot len %.1f at" % ln.length(h), np.round(ln.c, 1))
                continue
            if min(e0, e1) < CORNER_END and bend > BEND_DEG:
                dbg("    drop arc chord len %.1f bend %.1f at" % (ln.length(h), bend), np.round(ln.c, 1))
                continue
        else:
            # long (usually merged) run: a real edge with sub-pixel steps stays within BUMP_MAX of its line,
            # a chain of chords along a big arc does not
            dev = np.abs((ps[np.arange(ln.i0, ln.i1 + 1) % n] - ln.c) @ perp(ln.d))
            if dev.max() > LONG_DEV:
                dbg("    drop long arc len %.1f maxdev %.2f at" % (ln.length(h), dev.max()), np.round(ln.c, 1))
                continue
        keep.append(ln)
    return keep


# =============================================================================================
# snapping / sharing
# =============================================================================================
def coverage_edge(alpha, ln, p, h):
    """re-measure an axis-aligned edge from alpha coverage (exact for symmetric AA kernels)"""
    n = len(p)
    sh = int(min(4.0, 0.25 * ln.length(h)) / h)
    pts = p[np.arange(ln.i0 + sh, ln.i1 - sh + 1) % n]
    hh, ww = alpha.shape
    a = np.pad(alpha, 8)                                   # zeros outside the image
    if ln.axis == "V":
        x0 = float(np.mean(pts[:, 0]))
        ya, yb = sorted([pts[0, 1], pts[-1, 1]])
        r0, r1 = int(math.ceil(ya)), int(math.floor(yb))
        xi = int(round(x0))
        win = a[r0 + 8:r1 + 8, xi - 5 + 8:xi + 5 + 8]
        if win.shape[0] < 3:
            return None
        left, right = win[:, 0].mean(), win[:, -1].mean()
        if min(left, right) > 0.02 or max(left, right) < 0.98:
            return None
        s = win.sum(1).mean()
        return (xi + 5 - s) if right > left else (xi - 5 + s)
    y0 = float(np.mean(pts[:, 1]))
    xa, xb = sorted([pts[0, 0], pts[-1, 0]])
    c0, c1 = int(math.ceil(xa)), int(math.floor(xb))
    yi = int(round(y0))
    win = a[yi - 5 + 8:yi + 5 + 8, c0 + 8:c1 + 8]
    if win.shape[1] < 3:
        return None
    top, bot = win[0].mean(), win[-1].mean()
    if min(top, bot) > 0.02 or max(top, bot) < 0.98:
        return None
    s = win.sum(0).mean()
    return (yi + 5 - s) if bot > top else (yi - 5 + s)


def _share(lines, k, tol):
    """greedy span-limited clusters of coordinate k; every cluster takes its length-weighted mean"""
    ls = sorted(lines, key=lambda l: l.c[k])
    i = 0
    while i < len(ls):
        j = i
        while j + 1 < len(ls) and ls[j + 1].c[k] - ls[i].c[k] <= tol:
            j += 1
        grp = ls[i:j + 1]
        w = np.array([l.i1 - l.i0 for l in grp], float)
        v = round(float(np.sum(w * np.array([l.c[k] for l in grp])) / w.sum()), 2)
        for l in grp:
            l.c[k] = v
        i = j + 1


def snap_lines(all_lines, alpha, contours, h):
    for axis, k in (("V", 0), ("H", 1)):
        ax = [l for l in all_lines if l.axis == axis]
        # 1. one edge interrupted by a crossbar (the H's inner stem edges): same contour, same ink side
        for ci in sorted({l.contour for l in ax}):
            for sgn in (-1.0, 1.0):
                _share([l for l in ax if l.contour == ci and l.d[1 - k] * sgn > 0], k, SHARE_SAME)
        # 2. the cap line and the baseline: flat tops / flat bottoms of all letters
        if axis == "H":
            tops = [l for l in ax if l.d[0] > 0]             # travelling +x = ink below = a top edge
            bots = [l for l in ax if l.d[0] < 0]
            for grp, ext in ((tops, min), (bots, max)):
                if not grp:
                    continue
                y0 = ext(l.c[1] for l in grp)
                cand = [l for l in grp if abs(l.c[1] - y0) <= CAP_TOL]
                w = np.array([l.i1 - l.i0 for l in cand], float)
                mean = float(np.sum(w * np.array([l.c[1] for l in cand])) / w.sum())
                # a terminal that sits clearly off the common line (the K's pointed feet) keeps its own level
                _share([l for l in cand if abs(l.c[1] - mean) <= CAP_KEEP], 1, 2 * CAP_KEEP)
        # 3. anything else that lands on the same coordinate anyway
        _share(ax, k, SHARE_TOL)
    # shared angles for diagonals (parallel stroke sides)
    ds = sorted([l for l in all_lines if not l.axis], key=lambda l: ang_deg(l.d) % 180.0)
    i = 0
    while i < len(ds):
        j = i
        while j + 1 < len(ds) and (ang_deg(ds[j + 1].d) % 180.0) - (ang_deg(ds[i].d) % 180.0) <= SHARE_DEG:
            j += 1
        grp = ds[i:j + 1]
        if len(grp) > 1:
            w = np.array([l.i1 - l.i0 for l in grp], float)
            a = float(np.sum(w * np.array([ang_deg(l.d) % 180.0 for l in grp])) / w.sum())
            nd = np.array([math.cos(math.radians(a)), math.sin(math.radians(a))])
            for l in grp:
                l.d = nd if np.dot(nd, l.d) > 0 else -nd
        i = j + 1


# =============================================================================================
# Bezier fitting (Schneider, with optional free end tangents)
# =============================================================================================
def bez(ctrl, t):
    t = np.asarray(t)[:, None]
    mt = 1 - t
    return (mt ** 3) * ctrl[0] + 3 * (mt ** 2) * t * ctrl[1] + 3 * mt * (t ** 2) * ctrl[2] + (t ** 3) * ctrl[3]


def bez_d1(ctrl, t):
    t = np.asarray(t)[:, None]
    mt = 1 - t
    return 3 * (mt ** 2) * (ctrl[1] - ctrl[0]) + 6 * mt * t * (ctrl[2] - ctrl[1]) + 3 * (t ** 2) * (ctrl[3] - ctrl[2])


def bez_d2(ctrl, t):
    t = np.asarray(t)[:, None]
    return 6 * (1 - t) * (ctrl[2] - 2 * ctrl[1] + ctrl[0]) + 6 * t * (ctrl[3] - 2 * ctrl[2] + ctrl[1])


def solve_cubic(pts, u, p0, p3, t1, t2):
    """least-squares inner control points. An end with a tangent has ONE unknown (the handle length),
    a free end has two. Handles never reach past the point where the two end tangents meet: beyond it a
    convex arc grows an inflection (a hump)."""
    b0, b1 = (1 - u) ** 3, 3 * (1 - u) ** 2 * u
    b2, b3 = 3 * (1 - u) * u ** 2, u ** 3
    base = pts - np.outer(b0 + b1, p0) - np.outer(b2 + b3, p3)
    chord = float(np.hypot(*(p3 - p0)))
    cap = [2.5 * chord, 2.5 * chord]
    if t1 is not None and t2 is not None:
        m = np.array([[t1[0], -t2[0]], [t1[1], -t2[1]]])
        if abs(np.linalg.det(m)) > 1e-6:
            ab = np.linalg.solve(m, p3 - p0)
            if ab[0] > 0 and ab[1] > 0:
                cap = [min(cap[0], 0.9 * ab[0]), min(cap[1], 0.9 * ab[1])]
    fixed = [None, None]
    for _ in range(3):
        rhs = base.copy()
        cols, kinds = [], []
        for e, (bb, t) in enumerate(((b1, t1), (b2, t2))):
            if t is None:
                cols.append(np.stack([bb, np.zeros_like(bb)], 1).reshape(-1))
                cols.append(np.stack([np.zeros_like(bb), bb], 1).reshape(-1))
                kinds.append((e, 2))
            elif fixed[e] is not None:
                rhs = rhs - np.outer(bb, fixed[e] * t)
            else:
                cols.append(np.stack([bb * t[0], bb * t[1]], 1).reshape(-1))
                kinds.append((e, 1))
        sol = np.linalg.lstsq(np.stack(cols, 1), rhs.reshape(-1), rcond=None)[0] if cols else []
        k, again = 0, False
        vec = [None, None]
        for e, width in kinds:
            if width == 2:
                vec[e] = np.array(sol[k:k + 2])
            else:
                al = float(sol[k])
                if al < 1e-3 * chord:
                    fixed[e], again = chord / 3.0 if cap[e] > chord / 3.0 else cap[e], True
                elif al > cap[e]:
                    fixed[e], again = cap[e], True
                else:
                    vec[e] = al * (t1 if e == 0 else t2)
            k += width
        if not again:
            break
    for e, t in enumerate((t1, t2)):
        if vec[e] is None:
            vec[e] = fixed[e] * t
    return np.array([p0, p0 + vec[0], p3 + vec[1], p3])


def reparam(ctrl, pts, u):
    q = bez(ctrl, u) - pts
    d1, d2 = bez_d1(ctrl, u), bez_d2(ctrl, u)
    num = np.sum(q * d1, 1)
    den = np.sum(d1 * d1, 1) + np.sum(q * d2, 1)
    den = np.where(np.abs(den) < 1e-12, 1e-12, den)
    return np.clip(u - num / den, 0, 1)


def local_tangent(pts, i, halfwin):
    a, b = max(0, i - halfwin), min(len(pts), i + halfwin + 1)
    w = pts[a:b]
    c, d = tls(w)
    if np.dot(w[-1] - w[0], d) < 0:
        d = -d
    nr = perp(d)
    uu, vv = (w - c) @ d, (w - c) @ nr
    if len(w) >= 7:
        co = np.polyfit(uu, vv, 2)                          # tangent of the local parabola at pts[i]
        ui = float((pts[i] - c) @ d)
        slope = 2 * co[0] * ui + co[1]
        pos = c + ui * d + float(np.polyval(co, ui)) * nr
        return unit(d + slope * nr), pos
    return d, pts[i]


def fit_cubics(pts, p0, p3, t1, t2, step, depth=0, tol=None, max_depth=5):
    """pts: interior samples (not including p0/p3). t1 points into the curve, t2 points back into it."""
    p0, p3 = np.asarray(p0, float), np.asarray(p3, float)
    chord = float(np.hypot(*(p3 - p0)))
    if len(pts) < 3:
        a = t1 if t1 is not None else unit(p3 - p0)
        b = t2 if t2 is not None else unit(p0 - p3)
        return [np.array([p0, p0 + a * chord / 3, p3 + b * chord / 3, p3])]
    full = np.vstack([p0, pts, p3])
    s = np.concatenate([[0], np.cumsum(np.hypot(*np.diff(full, axis=0).T))])
    u = (s / s[-1])[1:-1]
    ctrl = None
    err, imax = 1e9, 0
    for _ in range(12):
        ctrl = solve_cubic(pts, u, p0, p3, t1, t2)
        u = reparam(ctrl, pts, u)
        dist = np.hypot(*(bez(ctrl, u) - pts).T)
        imax = int(np.argmax(dist))
        err = float(dist[imax])
    rms = float(np.sqrt(np.mean(dist ** 2)))
    tol = FIT_TOL if tol is None else tol
    # the source is stair-stepped where a curve runs nearly horizontal / vertical (steps up to ~0.7 px):
    # judge the fit by rms, and only let the max veto it when it is clearly beyond a stair step
    if (rms <= FIT_RMS and err <= tol) or depth >= max_depth or len(pts) < 40:
        return [ctrl]
    imax = int(min(max(imax, 0.25 * len(pts)), 0.75 * len(pts)))
    tc, pc = local_tangent(pts, imax, int(10.0 / step))
    return (fit_cubics(pts[:imax], p0, pc, t1, -tc, step, depth + 1, tol, max_depth)
            + fit_cubics(pts[imax + 1:], pc, p3, tc, t2, step, depth + 1, tol, max_depth))


# =============================================================================================
# curved runs
# =============================================================================================
def tangent_angles(ps_run):
    d = np.gradient(ps_run, axis=0)
    return np.degrees(np.unwrap(np.arctan2(d[:, 1], d[:, 0])))


def find_corners(p, pf, ia, ib, h):
    """sharp interior corners of the curved run [ia, ib] (unwrapped indices)"""
    n = len(p)
    near, far = int(0.6 / h), int(3.0 / h)
    idx = np.arange(ia + far, ib - far + 1)
    if len(idx) < 3:
        return []
    a = pf[(idx - near) % n] - pf[(idx - far) % n]
    b = pf[(idx + far) % n] - pf[(idx + near) % n]
    cosv = np.sum(a * b, 1) / (np.hypot(*a.T) * np.hypot(*b.T) + 1e-12)
    turn = np.degrees(np.arccos(np.clip(cosv, -1, 1)))
    out = []
    nms = int(5.0 / h)
    t = turn.copy()
    while True:
        k = int(np.argmax(t))
        if t[k] < CORNER_TURN:
            break
        i = int(idx[k])
        t[max(0, k - nms):k + nms + 1] = 0
        w0, w1 = int(1.0 / h), int(3.5 / h)
        ca, da = tls(p[np.arange(i - w1, i - w0 + 1) % n])
        cb, db = tls(p[np.arange(i + w0, i + w1 + 1) % n])
        if np.dot(p[(i - w0) % n] - p[(i - w1) % n], da) < 0:
            da = -da
        if np.dot(p[(i + w1) % n] - p[(i + w0) % n], db) < 0:
            db = -db
        if ang_between(da, db) < 20:
            continue
        x = intersect(ca, da, cb, db)
        loc = p[np.arange(i - w1, i + w1 + 1) % n]
        dist = float(np.min(np.hypot(*(loc - x).T)))
        rho = corner_rho(dist, ang_between(da, db))
        dbg("    corner candidate turn %.0f deg, vertex-contour %.2f, rho %.2f" % (ang_between(da, db), dist, rho),
            np.round(x, 2))
        if rho < CORNER_RHO and ang_between(da, db) >= CORNER_TURN:
            out.append((i, x))
    return sorted(out, key=lambda c: c[0])


def find_extrema(p, ps, ia, ib, h):
    """indices in (ia, ib) where the tangent is exactly horizontal / vertical, with the precise node.
    Hysteresis: the tangent has to get from EXT_HYST on one side of the axis to EXT_HYST on the other;
    the extremum is the middle of that stretch (robust to the flat steps the source is full of)."""
    n = len(p)
    idx = np.arange(ia, ib + 1)
    m = int(EXT_MARGIN / h)
    if len(idx) < 2 * m + 3:
        return []
    th = tangent_angles(ps[idx % n])
    events = []
    for level in range(int(math.floor(th.min() / 90.0)), int(math.ceil(th.max() / 90.0)) + 1):
        s = th - 90.0 * level
        definite = np.where(np.abs(s) > EXT_HYST)[0]
        if len(definite) < 2:
            continue
        sg = np.sign(s[definite])
        flips = np.where(sg[:-1] != sg[1:])[0]
        for f in flips:
            c = int((definite[f] + definite[f + 1]) // 2)
            if m <= c < len(idx) - m:
                events.append((c, 90.0 * level))
    res = []
    for c, a in sorted(events):
        d = np.round(np.array([math.cos(math.radians(a)), math.sin(math.radians(a))]))   # exactly axis-aligned
        nr = perp(d)
        node = ps[idx[c] % n].copy()
        # precise node. Along the tangent: the axis of symmetry of the arc = mean midpoint of the chords
        # cut at several small depths (far more stable than the vertex of a parabola on a nearly flat,
        # stair-stepped top). Across the tangent: the vertex height of a parabola about that axis.
        lo, hi = max(int(1.0 / h), c - int(EXT_REACH / h)), min(len(idx) - 1 - int(1.0 / h), c + int(EXT_REACH / h))
        wp = ps[idx[lo:hi + 1] % n]
        uu, vv = (wp - node) @ d, (wp - node) @ nr
        k0 = c - lo
        sgn = 1.0 if (vv[0] + vv[-1]) / 2 > vv[k0] else -1.0   # which way the arc falls away
        vv = vv * sgn
        vext = float(vv[max(0, k0 - int(8 / h)):k0 + int(8 / h) + 1].min())
        mids = []
        for depth in EXT_DEPTHS:
            li = np.where(vv[:k0] - vext >= depth)[0]
            ri = np.where(vv[k0:] - vext >= depth)[0]
            if not len(li) or not len(ri):
                break
            i, j = int(li[-1]), k0 + int(ri[0])
            ul = np.interp(vext + depth, [vv[i + 1], vv[i]], [uu[i + 1], uu[i]])
            ur = np.interp(vext + depth, [vv[j - 1], vv[j]], [uu[j - 1], uu[j]])
            mids.append(0.5 * (ul + ur))
        if len(mids) >= 2:
            u0 = float(np.mean(mids))
            near = (vv - vext) < 1.5
            rp = p[idx[lo:hi + 1] % n][near]
            ru, rv = (rp - node) @ d - u0, ((rp - node) @ nr) * sgn
            am = np.stack([ru ** 2, np.ones_like(ru)], 1)
            sol, *_ = np.linalg.lstsq(am, rv, rcond=None)
            node = node + u0 * d + float(sol[1]) * sgn * nr
        res.append((int(idx[c]), node, d))
    return res


def curve_run(cont, ia, ib, start, end, h, fillet=False):
    """start/end = (point, tangent along travel or None). returns list of 4x2 control arrays"""
    p, ps, pf = cont["p"], cont["ps"], cont["pf"]
    pfit = pf if fillet else cont["pc"]
    n = len(p)
    corners = [] if fillet else find_corners(p, pf, ia, ib, h)
    # breakpoints: (index, point, tangent_in (arriving), tangent_out (leaving), is_corner)
    bps = [(ia, start[0], None, start[1], start[2])]
    for i, x in corners:
        bps.append((i, x, None, None, True))
    bps.append((ib, end[0], end[1], None, end[2]))
    bps.sort(key=lambda b: b[0])
    full = []
    for k in range(len(bps) - 1):
        a, b = bps[k], bps[k + 1]
        ex = find_extrema(p, ps, a[0], b[0], h)
        full.append(a)
        for i, node, d in ex:
            # an extremum right next to an end that already leaves / arrives with that very tangent is the
            # same flat again (a stair step of the source), not a new node
            if a[3] is not None and abs(float(np.dot(a[3], d))) > EXT_PAR and (i - a[0]) * h < EXT_NEAR:
                continue
            if b[2] is not None and abs(float(np.dot(b[2], d))) > EXT_PAR and (b[0] - i) * h < EXT_NEAR:
                continue
            full.append((i, node, d, d, False))
    full.append(bps[-1])
    out = []
    sub = max(1, int(round(0.4 / h)))
    for k in range(len(full) - 1):
        a, b = full[k], full[k + 1]
        skip = 1.2 if fillet else 2.5 * SIG_CURVE             # samples smeared by a sharp corner
        ca = int((skip if a[4] else 0.4) / h)
        cb = int((skip if b[4] else 0.4) / h)
        idx = np.arange(a[0] + ca, b[0] - cb + 1)[::sub]
        pts = pfit[idx % n] if len(idx) else np.zeros((0, 2))
        t1 = a[3]
        t2 = -b[2] if b[2] is not None else None
        segs = fit_cubics(pts, a[1], b[1], t1, t2, sub * h, tol=(0.5 if fillet else None),
                          max_depth=(1 if fillet else 5))
        dbg("      %s (%.1f, %.1f) -> (%.1f, %.1f): %d samples -> %d cubic(s)"
            % ("fillet" if fillet else "curve ", a[1][0], a[1][1], b[1][0], b[1][1], len(pts), len(segs)))
        out.extend(segs)
    return out


# =============================================================================================
# contour -> segments
# =============================================================================================
def build_contour(cont, h):
    p, ps = cont["p"], cont["ps"]
    n = len(p)
    lines = cont["lines"]
    segs = []                                              # ('L', Line) | ('C', ctrl)
    if not lines:
        # closed curve: start at the first extremum so every node is a clean H/V tangent node
        ex = find_extrema(p, ps, 0, n + int(2 * EXT_MARGIN / h) + 2, h)
        if not ex:
            raise RuntimeError("closed curve without extrema")
        i0, node, d = ex[0]
        i0 %= n
        cubs = curve_run(cont, i0, i0 + n, (node, d, False), (node, d, False), h)
        return [("C", c) for c in cubs], node
    m = len(lines)
    # classify every junction line[k] -> line[k+1]:  corner | fillet (small rounded corner) | curve
    junc = []
    for k in range(m):
        a, b = lines[k], lines[(k + 1) % m]
        b0 = b.i0 + (n if (k + 1) >= m else 0)
        gap = (b0 - a.i1) * h
        kind = "curve"
        if a is not b and gap < CORNER_GAP and ang_between(a.d, b.d) > 12:
            (ca, da), (cb, db) = a.tail, b.head                # local pieces: merged edges carry offsets
            x = intersect(ca, da, cb, db)
            loc = p[np.arange(a.i1 - int(2 / h), b0 + int(2 / h) + 1) % n]
            dist = float(np.min(np.hypot(*(loc - x).T)))
            rho = corner_rho(dist, ang_between(da, db))
            kind = "corner" if rho < CORNER_RHO else "fillet"
            dbg("    junction at (%.1f, %.1f) gap %.1f turn %.0f vertex-contour %.2f rho %.2f -> %s"
                % (x[0], x[1], gap, ang_between(a.d, b.d), dist, rho, kind))
        else:
            e = p[a.i1 % n]
            dbg("    junction after (%.1f, %.1f) gap %.1f -> curve" % (e[0], e[1], gap))
        junc.append(kind)
    for k in range(m):
        a = lines[k]
        prev_kind, next_kind = junc[(k - 1) % m], junc[k]
        for side, kind in (("0", prev_kind), ("1", next_kind)):
            other = lines[(k - 1) % m] if side == "0" else lines[(k + 1) % m]
            if kind == "corner":
                pt = intersect(other.c, other.d, a.c, a.d)
                if a.axis == "V" or other.axis == "V":         # exact shared coordinates
                    pt[0] = (a if a.axis == "V" else other).c[0]
                if a.axis == "H" or other.axis == "H":
                    pt[1] = (a if a.axis == "H" else other).c[1]
                j = a.i0 if side == "0" else a.i1
            else:
                t = FILLET_TRIM if kind == "fillet" else TRIM
                trim = int(min(t, 0.25 * a.length(h)) / h)
                j = a.i0 + trim if side == "0" else a.i1 - trim
                pt = a.project(ps[j % n])
            if side == "0":
                a.j0, a.p0 = j, pt
            else:
                a.j1, a.p1 = j, pt
    start = lines[0].p0
    for k in range(m):
        a, b = lines[k], lines[(k + 1) % m]
        segs.append(("L", a))
        if junc[k] != "corner":
            b0 = b.j0 + (n if (k + 1) >= m else 0)
            cubs = curve_run(cont, a.j1, b0, (a.p1, a.d, False), (b.p0, b.d, False), h,
                             fillet=(junc[k] == "fillet"))
            segs.extend(("C", c) for c in cubs)
    return segs, start


# =============================================================================================
# output
# =============================================================================================
def fmt(v):
    s = "%.2f" % v
    s = s.rstrip("0").rstrip(".") if "." in s else s
    return "0" if s in ("-0", "") else s


def clamp(pt, w, h):
    return np.array([min(max(pt[0], 0.0), w), min(max(pt[1], 0.0), h)])


def contour_path(segs, start, w, h):
    out = ["M%s %s" % (fmt(start[0]), fmt(start[1]))]
    for s in segs:
        if s[0] == "L":
            ln = s[1]
            e = clamp(ln.p1, w, h)
            if ln.axis == "H":
                out.append("H" + fmt(e[0]))
            elif ln.axis == "V":
                out.append("V" + fmt(e[1]))
            else:
                out.append("L%s %s" % (fmt(e[0]), fmt(e[1])))
        else:
            c = [clamp(q, w, h) for q in s[1]]
            out.append("C%s %s %s %s %s %s" % tuple(fmt(v) for q in c[1:] for v in q))
    out.append("Z")
    d = "".join(out)
    return d.replace(" -", "-")


def sample_segs(segs, start, per=24):
    pts = [np.asarray(start, float)]
    t = np.linspace(0, 1, per + 1)[1:]
    for s in segs:
        if s[0] == "L":
            pts.append(np.asarray(s[1].p1, float))
        else:
            pts.extend(list(bez(s[1], t)))
    return np.array(pts)


def quality(segs_by_contour):
    """geometric sanity of the fitted outline: inflections inside cubics, tangent breaks at smooth joins"""
    infl, worst_join, tiny = 0, 0.0, 0
    for segs, start in segs_by_contour:
        tang = []                                              # (tangent in, tangent out) per segment
        cur = np.asarray(start, float)
        for sg in segs:
            if sg[0] == "L":
                d = unit(sg[1].p1 - cur)
                tang.append((d, d))
                if np.hypot(*(sg[1].p1 - cur)) < 2.0:
                    tiny += 1
                cur = np.asarray(sg[1].p1, float)
            else:
                c = sg[1]
                t = np.linspace(0.02, 0.98, 97)
                d1, d2 = bez_d1(c, t), bez_d2(c, t)
                k = (d1[:, 0] * d2[:, 1] - d1[:, 1] * d2[:, 0]) / (np.hypot(*d1.T) ** 3 + 1e-12)
                if k.min() < -2e-4 and k.max() > 2e-4:
                    infl += 1
                a = c[1] - c[0] if np.hypot(*(c[1] - c[0])) > 1e-6 else c[2] - c[0]
                b = c[3] - c[2] if np.hypot(*(c[3] - c[2])) > 1e-6 else c[3] - c[1]
                tang.append((unit(a), unit(b)))
                if np.hypot(*(c[3] - c[0])) < 2.0:
                    tiny += 1
                cur = c[3]
        for i in range(len(tang)):
            turn = ang_between(tang[i][1], tang[(i + 1) % len(tang)][0])
            if turn < 25.0:                                    # anything sharper is an intended corner
                worst_join = max(worst_join, turn)
    return {"cubics_with_inflection": infl, "max_tangent_break_at_smooth_joins_deg": round(worst_join, 3),
            "segments_shorter_than_2px": tiny}


# =============================================================================================
# verification
# =============================================================================================
def chrome_alpha(svg_text, width, height):
    from playwright.sync_api import sync_playwright
    html = ("<!doctype html><html><body style='margin:0;background:transparent'>"
            "<div style='width:%dpx;height:%dpx;color:#000;line-height:0'>%s</div></body></html>"
            % (width, height, svg_text.replace("<svg ", "<svg width='%d' height='%d' " % (width, height), 1)))
    with sync_playwright() as pw:
        br = pw.chromium.launch(executable_path=CHROME, headless=True)
        pg = br.new_page(viewport={"width": width, "height": height}, device_scale_factor=1)
        pg.set_content(html)
        png = pg.screenshot(omit_background=True, clip={"x": 0, "y": 0, "width": width, "height": height})
        br.close()
    import io
    return np.asarray(Image.open(io.BytesIO(png)).convert("RGBA"))[:, :, 3].astype(np.float32) / 255.0


def verify(svg_text, alpha):
    h, w = alpha.shape
    ren = chrome_alpha(svg_text, w, h)
    mad = float(np.mean(np.abs(ren - alpha)))
    a, b = alpha >= 0.5, ren >= 0.5
    iou = float((a & b).sum() / (a | b).sum())
    res = {"renderer": "Google Chrome via Playwright, %dx%d, transparent background" % (w, h),
           "mean_abs_diff_pct": round(100 * mad, 4),
           "iou_at_0.5": round(iou, 5),
           "max_abs_diff": round(float(np.abs(ren - alpha).max()), 4),
           "pixels_flipped_at_0.5": int((a ^ b).sum()),
           "ink_pixels_source": int(a.sum())}
    return res, ren


def check_sheets(svg_text, alpha, letters_bbox):
    """3x source | trace | overlay. red = source only, cyan = trace only."""
    h, w = alpha.shape
    z = 3
    ren = chrome_alpha(svg_text, w * z, h * z)
    src = np.asarray(Image.fromarray((alpha * 255).astype(np.uint8)).resize((w * z, h * z), Image.LANCZOS)
                     ).astype(np.float32) / 255.0

    def grey(a):
        v = ((1 - a) * 255).astype(np.uint8)
        return np.stack([v, v, v], 2)

    over = np.stack([(1 - ren) * 255, (1 - src) * 255, (1 - src) * 255], 2).astype(np.uint8)
    gap = np.full((12, w * z, 3), 200, np.uint8)
    sheet = np.vstack([grey(src), gap, grey(ren), gap, over])
    SHOTS.mkdir(parents=True, exist_ok=True)
    Image.fromarray(sheet).save(SHOTS / "trace-check.png", optimize=True)
    # per-pair crops that stay legible when viewed
    pairs = [("ta", 0, 1), ("bo", 2, 3), ("uk", 4, 5), ("hi", 6, 7)]
    for name, i, j in pairs:
        x0 = max(0, int(letters_bbox[i][0]) - 8) * z
        x1 = min(w, int(letters_bbox[j][0] + letters_bbox[j][2]) + 8) * z
        Image.fromarray(sheet[:, x0:x1]).save(SHOTS / ("trace-check-%s.png" % name), optimize=True)


# =============================================================================================
def main():
    alpha = load_alpha()
    hh, ww = alpha.shape
    raw = dense_contours(alpha)
    conts = []
    for c in raw:
        p, h = resample_closed(c, H_STEP)
        conts.append({"p": p, "h": h, "raw": c,
                      "bbox": (c[:, 0].min(), c[:, 1].min(), c[:, 0].max(), c[:, 1].max())})
    # holes / outers
    for i, c in enumerate(conts):
        c["hole"] = any(j != i and point_in_poly(c["raw"][0], o["raw"]) for j, o in enumerate(conts))
    outers = sorted([c for c in conts if not c["hole"]], key=lambda c: c["bbox"][0])
    letters = []
    for c in outers:
        if letters:
            l0 = min(o["bbox"][0] for o in letters[-1])
            l1 = max(o["bbox"][2] for o in letters[-1])
            ov = min(l1, c["bbox"][2]) - max(l0, c["bbox"][0])
            if ov > 0.5 * min(l1 - l0, c["bbox"][2] - c["bbox"][0]):
                letters[-1].append(c)
                continue
        letters.append([c])
    for grp in letters:
        for hole in [c for c in conts if c["hole"]]:
            if any(point_in_poly(hole["raw"][0], o["raw"]) for o in grp):
                grp.append(hole)
    assert len(letters) == len(WORD), "expected %d letters, found %d" % (len(WORD), len(letters))
    assert sum(len(g) for g in letters) == len(conts)

    # consistent winding: outers clockwise on screen, holes counter-clockwise (evenodd AND nonzero work)
    order = []
    for grp in letters:
        for c in grp:
            area = poly_area(c["p"])                       # >0 = clockwise on screen (y down)
            if (area > 0) == c["hole"]:
                c["p"] = c["p"][::-1].copy()
            h = c["h"]
            c["ps"] = smooth_closed(c["p"], SIG_DETECT, h)
            c["pf"] = smooth_closed(c["p"], SIG_FIT, h)
            c["pc"] = smooth_closed(c["p"], SIG_CURVE, h)
            order.append(c)
    all_lines = []
    for ci, c in enumerate(order):
        dbg("contour %d bbox %s hole=%s" % (ci, np.round(c["bbox"], 1), c["hole"]))
        c["lines"] = find_lines(c["p"], c["ps"], c["h"], alpha)
        for ln in c["lines"]:
            ln.contour = ci
            all_lines.append(ln)
    snap_lines(all_lines, alpha, order, order[0]["h"])
    if DEBUG:
        for ci, c in enumerate(order):
            for ln in c["lines"]:
                print("  c%-2d line len %6.1f  angle %8.3f  axis %-4s at (%.2f, %.2f)"
                      % (ci, ln.length(c["h"]), ang_deg(ln.d), ln.axis, ln.c[0], ln.c[1]))

    paths, bboxes, n_l, n_c = [], [], 0, 0
    built = []
    for li, grp in enumerate(letters):
        d = ""
        pts = []
        for c in grp:
            dbg("letter %s contour bbox %s" % (WORD[li], np.round(c["bbox"], 1)))
            segs, start = build_contour(c, c["h"])
            n_l += sum(1 for s in segs if s[0] == "L")
            n_c += sum(1 for s in segs if s[0] == "C")
            d += contour_path(segs, clamp(start, ww, hh), ww, hh)
            pts.append(np.clip(sample_segs(segs, start), [0, 0], [ww, hh]))
            c["segs"] = segs
            built.append((segs, start))
        pts = np.vstack(pts)
        x0, y0, x1, y1 = pts[:, 0].min(), pts[:, 1].min(), pts[:, 0].max(), pts[:, 1].max()
        bboxes.append([round(float(x0), 2), round(float(y0), 2), round(float(x1 - x0), 2), round(float(y1 - y0), 2)])
        paths.append(d)

    svg = ['<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 %d %d" fill="currentColor" '
           'fill-rule="evenodd" role="img" aria-labelledby="tbk-t"><title id="tbk-t">%s</title>' % (ww, hh, WORD)]
    for lid, d in zip(IDS, paths):
        svg.append('<path id="%s" d="%s"/>' % (lid, d))
    svg.append("</svg>")
    svg_text = "".join(svg) + "\n"
    OUT_SVG.write_text(svg_text)
    OUT_TXT.write_text("".join(paths) + "\n")

    # ---- metrics -----------------------------------------------------------------------------
    def vx(c, minlen):
        return sorted(l.c[0] for l in c["lines"] if l.axis == "V" and l.length(c["h"]) > minlen)

    def hy(c, minlen):
        return sorted(l.c[1] for l in c["lines"] if l.axis == "H" and l.length(c["h"]) > minlen)

    def pairs(grp, axis, minlen=60.0):
        k = 0 if axis == "V" else 1
        vals = sorted({round(float(l.c[k]), 2) for c in grp for l in c["lines"]
                       if l.axis == axis and l.length(c["h"]) > minlen})
        return [round(vals[i + 1] - vals[i], 2) for i in range(0, len(vals) - 1, 2)]

    stems = {lid: pairs(grp, "V") for lid, grp in zip(IDS, letters)}
    bars = {lid: pairs(grp, "H") for lid, grp in zip(IDS, letters)}
    stems["l-i"] = []                                          # the I is cut by the right edge of the source crop
    ivals = sorted(l.c[0] for l in letters[7][0]["lines"] if l.axis == "V")
    flat = [v for lid in IDS for v in stems[lid]]
    flat_b = [v for lid in IDS for v in bars[lid]]
    t_h = sorted(l.c[1] for l in letters[0][0]["lines"] if l.axis == "H")
    stroke = {
        "t_stem": stems["l-t"][0] if stems["l-t"] else None,
        "vertical_stems": {k: v for k, v in stems.items() if v},
        "vertical_stem_mean": round(float(np.mean(flat)), 2) if flat else None,
        "horizontal_bars": {k: v for k, v in bars.items() if v},
        "horizontal_bar_mean": round(float(np.mean(flat_b)), 2) if flat_b else None,
        "i_stem_as_cropped_in_source": round(ivals[-1] - ivals[0], 2) if len(ivals) >= 2 else None,
    }
    t_all_y = t_h
    all_x = [b[0] for b in bboxes] + [b[0] + b[2] for b in bboxes]
    all_y = [b[1] for b in bboxes] + [b[1] + b[3] for b in bboxes]
    meta = {
        "source": str(SRC.relative_to(ROOT)),
        "viewBox": [0, 0, ww, hh],
        "viewBox_offset_from_source": [0, 0],
        "units": "source pixels",
        "letters": {lid: bb for lid, bb in zip(IDS, bboxes)},
        "ink_bbox": [round(min(all_x), 2), round(min(all_y), 2),
                     round(max(all_x) - min(all_x), 2), round(max(all_y) - min(all_y), 2)],
        "stroke_thickness": stroke["t_stem"],
        "stroke": stroke,
        "cap_top_y": round(t_all_y[0], 2),
        "baseline_y": round(t_all_y[-1], 2),
        "cap_height": round(t_all_y[-1] - t_all_y[0], 2),
        "segments": {"lines": n_l, "cubics": n_c},
        "outline_quality": quality(built),
        "svg_bytes": len(svg_text.encode()),
    }
    print("outline quality:", meta["outline_quality"])
    print("letters: %d   contours: %d   line segs: %d   cubic segs: %d   svg bytes: %d"
          % (len(letters), len(conts), n_l, n_c, len(svg_text.encode())))

    if "--no-verify" not in sys.argv:
        res, _ = verify(svg_text, alpha)
        meta["verification"] = res
        print(json.dumps(res, indent=1))
        check_sheets(svg_text, alpha, bboxes)
        ok = res["mean_abs_diff_pct"] < 1.0 and res["iou_at_0.5"] > 0.985
        print("PASS" if ok else "FAIL")
    OUT_JSON.write_text(json.dumps(meta, indent=2) + "\n")
    print(json.dumps({k: meta[k] for k in ("letters", "ink_bbox", "stroke", "cap_top_y", "baseline_y", "cap_height")}, indent=1))


if __name__ == "__main__":
    main()
