#!/usr/bin/env python3
"""Stitch original.png + candidate.png (from render_compare.js) into side-by-side bands.

Usage:
    python stitch.py OUTDIR [bandHeight=1000]

Reads OUTDIR/original.png (left) and OUTDIR/candidate.png (right) and writes
OUTDIR/compare_000.png, compare_001.png ... each covering `bandHeight` px.
Magenta padding marks where one side is shorter than the other.
Requires Pillow (`pip install pillow`).
"""
import sys, os
from PIL import Image


def main():
    if len(sys.argv) < 2:
        print(__doc__); sys.exit(1)
    outdir = sys.argv[1]
    band = int(sys.argv[2]) if len(sys.argv) > 2 else 1000
    ref = Image.open(os.path.join(outdir, "original.png")).convert("RGB")
    new = Image.open(os.path.join(outdir, "candidate.png")).convert("RGB")
    W = max(ref.width, new.width)
    H = max(ref.height, new.height)
    n = (H + band - 1) // band
    def safe_crop(im, y0, y1):
        y1 = min(y1, im.height)
        if y0 >= im.height or y1 <= y0:
            return Image.new("RGB", (im.width, 1), (255, 0, 255))
        return im.crop((0, y0, im.width, y1))

    for i in range(n):
        y0, y1 = i * band, min((i + 1) * band, H)
        rs = safe_crop(ref, y0, y1)
        ns = safe_crop(new, y0, y1)
        h = max(rs.height, ns.height)
        c = Image.new("RGB", (W * 2 + 12, h), (255, 0, 255))
        c.paste(rs, (0, 0)); c.paste(ns, (W + 12, 0))
        c.save(os.path.join(outdir, f"compare_{i:03d}.png"))
    print(f"[ok] {n} comparison band(s) written to {outdir}/compare_*.png")


if __name__ == "__main__":
    main()
