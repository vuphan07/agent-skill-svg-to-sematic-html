#!/usr/bin/env python3
"""Extract embedded base64 images from an SVG (or HTML-wrapped SVG) export.

Usage:
    python extract_assets.py INPUT.(html|svg) OUTDIR

Writes deduplicated images to OUTDIR/assets/imgN.<ext> and prints a JSON map
of {pattern_id|image_id|hash -> filename} so you know which raster goes where.
"""
import sys, os, re, base64, hashlib, json
import xml.etree.ElementTree as ET

XLINK = "http://www.w3.org/1999/xlink"
SVG = "http://www.w3.org/2000/svg"
NS = {"svg": SVG, "xlink": XLINK}


def load_svg(path):
    txt = open(path, encoding="utf-8").read().replace("\r\n", "\n")
    if "<svg" in txt:
        txt = txt[txt.find("<svg"): txt.rfind("</svg>") + len("</svg>")]
    return ET.fromstring(txt)


def q(tag):
    return tag.split("}")[1] if "}" in tag else tag


def href(el):
    return el.get(f"{{{XLINK}}}href") or el.get("href")


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)
    inp, outdir = sys.argv[1], sys.argv[2]
    assets = os.path.join(outdir, "assets")
    os.makedirs(assets, exist_ok=True)
    root = load_svg(inp)

    hash_file, counter, mapping = {}, [0], {}

    def save(data_uri):
        m = re.match(r"data:image/([\w.+-]+);base64,(.*)", data_uri or "", re.S)
        if not m:
            return None
        ext, data = m.group(1), m.group(2)
        ext = {"svg+xml": "svg", "jpeg": "jpg"}.get(ext, ext)
        raw = base64.b64decode(data)
        h = hashlib.md5(raw).hexdigest()
        if h in hash_file:
            return hash_file[h]
        counter[0] += 1
        fn = f"assets/img{counter[0]}.{ext}"
        open(os.path.join(outdir, fn), "wb").write(raw)
        hash_file[h] = fn
        return fn

    # standalone <image id=...> and patterns that reference them
    standalone = {}
    for el in root.iter():
        if q(el.tag) == "image" and href(el) and href(el).startswith("data:"):
            fn = save(href(el))
            if el.get("id"):
                standalone[el.get("id")] = fn
            mapping.setdefault("images", []).append({"id": el.get("id"), "file": fn,
                                                     "w": el.get("width"), "h": el.get("height")})
    for el in root.iter():
        if q(el.tag) == "pattern":
            pid = el.get("id")
            img = el.find("svg:image", NS)
            use = el.find("svg:use", NS)
            if img is not None and href(img):
                mapping.setdefault("patterns", {})[pid] = {"file": save(href(img)), "mode": "stretch"}
            elif use is not None:
                ref = (href(use) or "").lstrip("#")
                mapping.setdefault("patterns", {})[pid] = {"file": standalone.get(ref), "mode": "cover"}

    print(json.dumps(mapping, ensure_ascii=False, indent=2))
    print(f"\n[ok] {counter[0]} unique image(s) written to {assets}/", file=sys.stderr)


if __name__ == "__main__":
    main()
