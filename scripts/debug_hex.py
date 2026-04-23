#!/usr/bin/env python3
"""Quick targeted diagnostic for a single distortion case."""
from __future__ import annotations
import sys, pathlib
ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import numpy as np
from PIL import Image
import webcode_hex as wc

sys.path.insert(0, str(ROOT / "scripts"))
from stress_test_hex import (color_cast, shading_gradient, warp_perspective,
                             add_noise, rotate)

URL = "https://github.com/anthropics/claude-code"
path = "/tmp/debug_hex.png"
wc.encode_url(URL, path)

CASES = {
    "warm-cast": lambda im: color_cast(im, (1.10, 0.95, 0.80)),
    "shading-0.3": lambda im: shading_gradient(im, 0.30),
    "shading-0.5": lambda im: shading_gradient(im, 0.50),
    "persp-0.12": lambda im: warp_perspective(im, 0.12),
    "gauss": lambda im: add_noise(im, 12.0),
}

case = sys.argv[1] if len(sys.argv) > 1 else "warm-cast"
tf = CASES[case]
distorted = tf(Image.open(path))
out = f"/tmp/debug_{case}.png"
distorted.save(out)

# Monkey-patch decode_image to dump intermediate state.
import webcode_hex as wh
orig = wh.decode_image

def traced(p):
    img = Image.open(p)
    arr = np.asarray(img.convert("RGB"), dtype=np.float32)
    H_img, W_img = arr.shape[:2]
    import math
    corners = wh._find_hex_corners(img)
    print(f"corners: {corners}")
    R_can = 200.0
    canon_corners = [(R_can * math.cos(math.radians(30 + s * 60)),
                     -R_can * math.sin(math.radians(30 + s * 60))) for s in range(6)]
    tris = wh.all_triangles(0.0, 0.0, R_can)
    cents_canon = np.array([[sum(p[0] for p in tri)/3, sum(p[1] for p in tri)/3]
                            for (_s,_k,_t,tri) in tris], dtype=np.float64)
    tri_verts = [np.array(tri, dtype=np.float64) for (_s,_k,_t,tri) in tris]
    L = wh.layout()
    cal_map = dict(L['fixed'])
    white_idxs = []
    for idx in L['shim']:
        if idx not in wh._OUTER_RING:
            cal_map[idx] = 7
            white_idxs.append(idx)
    best_score = -1; best_cls = None
    for rot in range(6):
        rolled = corners[rot:] + corners[:rot]
        try: H = wh._homography(canon_corners, rolled)
        except Exception: continue
        tris_img = [wh._warp_many(H, v)[:3] for v in tri_verts]
        cents_img = wh._warp_many(H, cents_canon)
        samples = wh._sample_all(arr, [t.tolist() for t in tris_img], H_img, W_img)
        shade = wh._fit_shading(samples, white_idxs, cents_img)
        sf = samples - shade(cents_img)
        cf = wh._palette_centroids(sf, cal_map)
        cls, cnf = wh._classify(sf, cf)
        score = sum(1 for i,c in L['fixed'].items() if cls[i]==c)
        if score > best_score: best_score = score; best_cls = cls; bestrot=rot

    print(f"best_rot={bestrot}  fixed_hits={best_score}/{len(L['fixed'])}")
    try:
        out = orig(p)
        print(f"DECODED: {out!r}")
        print(f"MATCH: {out == URL}")
    except Exception as e:
        print(f"ERR: {e}")

traced(out)
