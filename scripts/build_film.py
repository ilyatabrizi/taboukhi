#!/usr/bin/env python3
"""The background film: a seamless, slower loop from the supplied 5-second shot.

    python3 scripts/build_film.py

The shot starts almost still and accelerates, so a plain loop jumps and a plain
reverse bounces at the fast end. Instead the first SEG source frames are eased
out and back (1 - cos): velocity is zero at both turns, peak speed sits mid-way,
and every in-between frame is synthesised from optical flow rather than repeated
or cross-blended. The second half is the first half played backwards, so the
loop closes on itself exactly.

Writes, per size in SIZES:
  assets/media/film-<w>.mp4    H.264, no audio, fast-start (moov first)
  assets/media/film-<w>.webp   first frame, the poster
No ffmpeg on this Mac: OpenCV's bundled FFmpeg encodes, avconvert remuxes.
"""
import math
import pathlib
import subprocess
import tempfile

import cv2
import numpy as np

ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC = ROOT / "assets/media/source/film-original.mp4"
OUT = ROOT / "assets/media"
SEG = 90             # source frames used (0..90 of 121): the slower first 3.75 s
HALF = 192           # output frames per direction: 8 s at 24 fps, 16 s round trip
SIZES = (1920, 1280)
FLOW_W = 960


def read_source():
    cap = cv2.VideoCapture(str(SRC))
    frames = []
    while len(frames) <= SEG:
        ok, f = cap.read()
        if not ok:
            break
        frames.append(f)
    assert len(frames) == SEG + 1, len(frames)
    return frames


def flows(frames):
    """Forward flow k -> k+1 for every pair, at FLOW_W."""
    dis = cv2.DISOpticalFlow_create(cv2.DISOPTICAL_FLOW_PRESET_MEDIUM)
    grey = [cv2.cvtColor(cv2.resize(f, (FLOW_W, FLOW_W), interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2GRAY) for f in frames]
    return [dis.calc(grey[k], grey[k + 1], None) for k in range(SEG)]


def between(a, b, flow, t, w):
    """Frame at fraction t between a and b: pull a back and b forward along the flow."""
    if t < 1e-3:
        return a
    if t > 1 - 1e-3:
        return b
    f = cv2.resize(flow, (w, w), interpolation=cv2.INTER_LINEAR) * (w / FLOW_W)
    gx, gy = np.meshgrid(np.arange(w, dtype=np.float32), np.arange(w, dtype=np.float32))
    wa = cv2.remap(a, gx - t * f[..., 0], gy - t * f[..., 1], cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
    wb = cv2.remap(b, gx + (1 - t) * f[..., 0], gy + (1 - t) * f[..., 1], cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
    return cv2.addWeighted(wa, 1 - t, wb, t, 0)


def main():
    frames = read_source()
    fl = flows(frames)
    # Source position for each output frame of the outbound half, eased at both ends.
    pos = [SEG * (1 - math.cos(math.pi * i / HALF)) / 2 for i in range(HALF + 1)]
    print(f"peak speed {max(b - a for a, b in zip(pos, pos[1:])):.3f} source frames per output frame")
    for w in SIZES:
        scaled = [cv2.resize(f, (w, w), interpolation=cv2.INTER_AREA) for f in frames]
        half = []
        for p in pos:
            k = min(int(p), SEG - 1)
            half.append(between(scaled[k], scaled[k + 1], fl[k], p - k, w))
        seq = half + half[-2:0:-1]          # out and back; the turns are not doubled
        tmp = pathlib.Path(tempfile.mkdtemp()) / "film.mp4"
        vw = cv2.VideoWriter(str(tmp), cv2.VideoWriter_fourcc(*"avc1"), 24, (w, w))
        for f in seq:
            vw.write(f)
        vw.release()
        dest = OUT / f"film-{w}.mp4"
        subprocess.run(["avconvert", "--preset", "PresetPassthrough", "--source", str(tmp), "--output", str(dest), "--replace"],
                       check=True, capture_output=True)
        cv2.imwrite(str(OUT / f"film-{w}.webp"), seq[0], [cv2.IMWRITE_WEBP_QUALITY, 80])
        print(f"  film-{w}.mp4  {dest.stat().st_size / 1024:7.0f} KB   {len(seq)} frames, {len(seq) / 24:.1f} s"
              f"   poster {(OUT / f'film-{w}.webp').stat().st_size / 1024:.0f} KB")


if __name__ == "__main__":
    main()
