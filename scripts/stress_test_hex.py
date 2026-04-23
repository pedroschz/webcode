#!/usr/bin/env python3
"""Stress-test the hex decoder against perspective warps, color casts,
shading gradients, blur, JPEG artifacts, rotation, and combinations.

Usage:
    python3 scripts/stress_test_hex.py              # full run
    python3 scripts/stress_test_hex.py --quick      # subset
"""
from __future__ import annotations

import math
import random
import sys
import pathlib
from io import BytesIO

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import numpy as np
from PIL import Image, ImageFilter

import webcode_hex as wc


URLS = [
    "https://github.com/anthropics/claude-code",
    "https://www.apple.com/iphone-15/",
    "https://en.wikipedia.org/wiki/QR_code",
]


# -------------------------------------------------------------------------
# Distortion primitives
# -------------------------------------------------------------------------
def _homography(src, dst):
    A, b = [], []
    for (sx, sy), (dx, dy) in zip(src, dst):
        A.append([sx, sy, 1, 0, 0, 0, -dx*sx, -dx*sy]); b.append(dx)
        A.append([0, 0, 0, sx, sy, 1, -dy*sx, -dy*sy]); b.append(dy)
    h, *_ = np.linalg.lstsq(np.array(A), np.array(b), rcond=None)
    return np.array([[h[0], h[1], h[2]], [h[3], h[4], h[5]], [h[6], h[7], 1.0]])


def warp_perspective(img: Image.Image, strength: float = 0.2) -> Image.Image:
    """Simulate photographing the code from an oblique angle. Pads first so
    the warped hex stays safely inside the output canvas (mimics a real-world
    framing where the code occupies ~60% of the frame)."""
    W, H = img.size
    margin = int(max(W, H) * (strength + 0.1))
    padded = Image.new("RGB", (W + 2*margin, H + 2*margin), (255, 255, 255))
    padded.paste(img, (margin, margin))
    Wp, Hp = padded.size
    rng = random.Random(hash((W, H, strength)) & 0xFFFF)
    corners_src = [(0, 0), (Wp, 0), (Wp, Hp), (0, Hp)]
    def jitter(c):
        dx = rng.uniform(-strength, strength) * Wp
        dy = rng.uniform(-strength, strength) * Hp
        return (c[0] + dx, c[1] + dy)
    corners_dst = [jitter(c) for c in corners_src]
    H_mat = _homography(corners_dst, corners_src)
    coeffs = tuple(H_mat.flatten()[:8])
    return padded.transform(
        (Wp, Hp), Image.PERSPECTIVE, coeffs,
        resample=Image.BICUBIC, fillcolor=(255, 255, 255),
    )


def color_cast(img: Image.Image, rgb_mul: tuple) -> Image.Image:
    arr = np.asarray(img.convert("RGB"), dtype=np.float32)
    arr[..., 0] *= rgb_mul[0]
    arr[..., 1] *= rgb_mul[1]
    arr[..., 2] *= rgb_mul[2]
    return Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))


def shading_gradient(img: Image.Image, strength: float = 0.4) -> Image.Image:
    """Linear brightness gradient from top-left bright to bottom-right dim."""
    arr = np.asarray(img.convert("RGB"), dtype=np.float32)
    H, W = arr.shape[:2]
    yy, xx = np.meshgrid(np.linspace(0, 1, H), np.linspace(0, 1, W), indexing="ij")
    factor = 1.0 - strength * (xx + yy) / 2.0
    arr = arr * factor[..., None]
    return Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))


def gaussian_blur(img: Image.Image, radius: float = 1.5) -> Image.Image:
    return img.filter(ImageFilter.GaussianBlur(radius=radius))


def jpeg_compress(img: Image.Image, quality: int = 40) -> Image.Image:
    buf = BytesIO()
    img.convert("RGB").save(buf, format="JPEG", quality=quality)
    buf.seek(0)
    return Image.open(buf).convert("RGB")


def rotate(img: Image.Image, degrees: float) -> Image.Image:
    return img.rotate(degrees, resample=Image.BICUBIC, fillcolor=(255, 255, 255), expand=True)


def add_noise(img: Image.Image, sigma: float = 8.0) -> Image.Image:
    arr = np.asarray(img.convert("RGB"), dtype=np.float32)
    rng = np.random.default_rng(abs(hash((arr.shape, sigma))) % (2**31))
    arr = arr + rng.normal(0.0, sigma, size=arr.shape)
    return Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))


def zap_cells(img: Image.Image, n: int = 25, seed: int = 0) -> Image.Image:
    """Randomly replace cells' pixels with random palette colors to simulate
    partial occlusion or reflections obliterating individual tris."""
    arr = np.array(img.convert("RGB"))
    rng = random.Random(seed)
    Hh, Ww = arr.shape[:2]
    R = Ww * 0.47
    cx, cy = Ww / 2, Hh / 2
    tris = wc.all_triangles(cx, cy, R)
    idxs = [i for i in range(wc.N_MODULES) if i not in wc._OUTER_RING]
    for i in rng.sample(idxs, min(n, len(idxs))):
        tri = tris[i][3]
        x0 = int(min(p[0] for p in tri)); x1 = int(max(p[0] for p in tri))
        y0 = int(min(p[1] for p in tri)); y1 = int(max(p[1] for p in tri))
        fake = wc.PALETTE[rng.randrange(8)]
        cxp = (x0 + x1) // 2; cyp = (y0 + y1) // 2
        arr[max(0, cyp-2):cyp+3, max(0, cxp-2):cxp+3] = fake
    return Image.fromarray(arr)


# -------------------------------------------------------------------------
# Test runner
# -------------------------------------------------------------------------
def make_test_suite(quick: bool):
    """Yield (label, transform) pairs."""
    yield "baseline", lambda im: im
    yield "rotate-8°", lambda im: rotate(im, 8)
    yield "rotate-25°", lambda im: rotate(im, 25)
    yield "perspective-0.05", lambda im: warp_perspective(im, 0.05)
    yield "perspective-0.12", lambda im: warp_perspective(im, 0.12)
    yield "warm-cast", lambda im: color_cast(im, (1.10, 0.95, 0.80))
    yield "cool-cast", lambda im: color_cast(im, (0.80, 0.95, 1.15))
    yield "heavy-cast", lambda im: color_cast(im, (1.25, 0.70, 0.65))
    yield "shading-0.3", lambda im: shading_gradient(im, 0.30)
    yield "shading-0.5", lambda im: shading_gradient(im, 0.50)
    yield "blur-1.0", lambda im: gaussian_blur(im, 1.0)
    yield "blur-2.0", lambda im: gaussian_blur(im, 2.0)
    yield "jpeg-60", lambda im: jpeg_compress(im, 60)
    yield "jpeg-30", lambda im: jpeg_compress(im, 30)
    yield "gauss-noise", lambda im: add_noise(im, 12.0)
    yield "zap-25", lambda im: zap_cells(im, 25, seed=7)
    if quick:
        return
    # Combinations.
    yield "perspective+cast", lambda im: color_cast(warp_perspective(im, 0.08), (1.15, 0.9, 0.85))
    yield "rotate+shading", lambda im: shading_gradient(rotate(im, 15), 0.35)
    yield "blur+jpeg", lambda im: jpeg_compress(gaussian_blur(im, 1.2), 50)
    yield "all-mild", lambda im: add_noise(
        jpeg_compress(
            shading_gradient(
                color_cast(
                    warp_perspective(rotate(im, 6), 0.05),
                    (1.08, 0.96, 0.92),
                ),
                0.2,
            ),
            70,
        ),
        6.0,
    )


def run_once(url: str, label: str, transform) -> tuple[bool, str]:
    path = f"/tmp/webcode_stress_{abs(hash((url, label))) & 0xFFFF}.png"
    wc.encode_url(url, path)
    img = Image.open(path)
    distorted = transform(img)
    out_path = path.replace(".png", f"_{label.replace('/', '_')}.png")
    distorted.save(out_path)
    try:
        decoded = wc.decode_image(out_path)
        return decoded == url, decoded
    except Exception as e:
        return False, f"<err: {e}>"


def main():
    quick = "--quick" in sys.argv
    cases = list(make_test_suite(quick))
    rows = []
    print(f"Running {len(cases)} distortion cases × {len(URLS)} URLs = {len(cases)*len(URLS)} trials\n")
    total = 0; ok = 0
    for url in URLS:
        short = url[:50] + ("…" if len(url) > 50 else "")
        print(f"\n--- {short} ---")
        for label, tf in cases:
            total += 1
            success, decoded = run_once(url, label, tf)
            ok += int(success)
            mark = "PASS" if success else "FAIL"
            print(f"  [{mark}] {label:24s}  {decoded if not success else ''}".rstrip())
            rows.append((url, label, success))
    print(f"\n==========  {ok}/{total} trials passed  ({100*ok/total:.1f}%)  ==========")
    # Per-distortion summary.
    by_label: dict[str, tuple[int,int]] = {}
    for _u, lab, s in rows:
        a, b = by_label.get(lab, (0, 0))
        by_label[lab] = (a + int(s), b + 1)
    print("\nPer-distortion pass rate:")
    for lab in [c[0] for c in cases]:
        a, b = by_label[lab]
        print(f"  {lab:24s}  {a}/{b}")


if __name__ == "__main__":
    main()
