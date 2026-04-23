"""
Webcode v2-hex — hexagonal variant, faithful to paper's Figure 6 anatomy.

Role-based layout on an S=8 triangular tessellation (384 tris total):

  ANCHOR    (§3.1.1, 18 tris) — 3 PDPs at 3 alternating outer corners. Each
            PDP is the 6-triangle flower around the sector-boundary vertex
            one step inside the corner, so its 2 outermost tris have bases
            flush with the outer hex border. Each PDP uses a different fixed
            permutation of the 6 chromatic palette entries, giving the
            decoder an unambiguous orientation signature.
  ALIGNMENT (§3.1.2, 78 tris) — chamfered gray strip tracing the 3 NON-anchor
            outer edges (row 7 minus the 12 row-7 tris consumed by anchors).
            Acts as the "outer bounds" marker in the TS grid-topology spec.
  METADATA  (§3.1.3, 6 tris) — 6 triangles near the top corner encoding the
            URL symbol count as a triple-redundant 6-bit value (18 bits).
            Per-bit majority vote across 3 copies survives 1 corrupted copy.
  PAYLOAD   (§3.1.4, 128 tris) — RS-coded data, visited in row-major order
            (top→bottom, left→right). 128 trits × 3 bits = 384 bits = 48
            bytes = RS(48,24) → 24 data + 24 ECC, corrects 12 byte errors.
  SHIM      (154 tris) — white padding. Includes a localised radial buffer
            (12 tris, 4 per anchor) directly inside each PDP hexagon, so
            anchors never touch payload. NOT a continuous inner ring.

Paper's MP 6-bit character system (Table 1, with the 010011 ↔ 4 typo corrected)
and the "^" key mechanism for common URL phrases are preserved.

Modernized pipeline:
  * 8-color palette (3 bits/module), RGB-corner palette.
  * Reed-Solomon over GF(256) for ECC (replaces paper's Hamming(128,120)).
  * Homography-based decoding (no ML).

Capacity: 24 data bytes → up to 32 MP symbols → typically ~30–45 URL chars
after ^-compression (e.g. "^&github^*anthropics/claude-code" expands to
"https://www.github.com/anthropics/claude-code" on decode).
"""
from __future__ import annotations
import math, sys, random
from PIL import Image, ImageDraw
import numpy as np

try:
    import reedsolo as _rs
except ImportError as e:
    raise RuntimeError("requires `pip install reedsolo`") from e

_RS_CACHE: dict = {}
def _codec(nsym):
    if nsym not in _RS_CACHE:
        _RS_CACHE[nsym] = _rs.RSCodec(nsym)
    return _RS_CACHE[nsym]
def rs_encode(data, nsym): return bytes(_codec(nsym).encode(data))
def rs_decode(data, nsym):
    try:
        out, _, _ = _codec(nsym).decode(data)
        return bytes(out)
    except _rs.ReedSolomonError as e:
        raise ValueError(str(e))

# =========================================================================
# MP character system — paper Table 1 verbatim (010011↔4 typo corrected).
# =========================================================================
MP_TABLE = [
    ":", "*", "0", "r", "b", "=", "j", "#",   # 000000-000111
    "!", "_", "v", "l", "$", "6", "d", "^",   # 001000-001111
    "1", "w", "O", "4", "z", "(", "2", "x",   # 010000-010111
    "s", "m", "5", "E", "p", "[", "t", "n",   # 011000-011111
    "c", "@", ".", "q", "~", ",", "h", "&",   # 100000-100111
    "?", "7", ")", "]", "I", "U", "-", "8",   # 101000-101111
    "k", "e", "3", "u", "i", "+", "A", "f",   # 110000-110111
    "a", "%", "y", "o", "/", "9", "g", ";",   # 111000-111111
]
assert len(MP_TABLE) == 64 and len(set(MP_TABLE)) == 64
CHAR_TO_IDX = {c: i for i, c in enumerate(MP_TABLE)}
IDX_TO_CHAR = {i: c for i, c in enumerate(MP_TABLE)}
KEY = CHAR_TO_IDX["^"]  # 15 = 0b001111

KEY_PHRASES = {
    "$": "https://",
    "@": "www.",
    "&": "https://www.",
    "*": ".com/",
    "!": ".html",
    "#": ".php",
    "+": "login",
    "=": ".edu",
    "?": ".org",
    "~": "https://www.youtube.com/watch?v=",
}
_PHRASE_ORDER = sorted(KEY_PHRASES.items(), key=lambda kv: -len(kv[1]))

def compress(url: str) -> bytes:
    out: list[int] = []
    i, n = 0, len(url)
    while i < n:
        matched = None
        for ch, phrase in _PHRASE_ORDER:
            if url.startswith(phrase, i):
                matched = (ch, phrase)
                break
        if matched:
            out.append(KEY)
            out.append(CHAR_TO_IDX[matched[0]])
            i += len(matched[1])
            continue
        c = url[i]
        if c in CHAR_TO_IDX:
            out.append(CHAR_TO_IDX[c])
            i += 1
            continue
        if "A" <= c <= "Z" and c.lower() in CHAR_TO_IDX:
            out.append(KEY)
            out.append(CHAR_TO_IDX[c.lower()])
            i += 1
            continue
        b = ord(c) & 0xFF
        for pc in f"%{b:02X}":
            if pc in CHAR_TO_IDX:
                out.append(CHAR_TO_IDX[pc])
            elif "A" <= pc <= "Z":
                out.append(KEY); out.append(CHAR_TO_IDX[pc.lower()])
        i += 1
    return bytes(out)

def decompress(symbols: bytes) -> str:
    out: list[str] = []
    i = 0
    while i < len(symbols):
        s = symbols[i]
        if s == KEY:
            i += 1
            if i >= len(symbols): break
            nxt = IDX_TO_CHAR[symbols[i]]
            if nxt in KEY_PHRASES:
                out.append(KEY_PHRASES[nxt])
            elif nxt.isalpha():
                out.append(nxt.upper())
            else:
                out.append(nxt)
            i += 1
        else:
            out.append(IDX_TO_CHAR[s])
            i += 1
    return "".join(out)

# =========================================================================
# Bit packing — 6-bit symbols ↔ bytes, bytes ↔ 3-bit trits (color indices)
# =========================================================================
def pack6(symbols: bytes) -> bytes:
    bits = []
    for s in symbols:
        for k in range(5, -1, -1): bits.append((s >> k) & 1)
    while len(bits) % 8: bits.append(0)
    out = bytearray()
    for i in range(0, len(bits), 8):
        b = 0
        for k in range(8): b = (b << 1) | bits[i+k]
        out.append(b)
    return bytes(out)

def unpack6(packed: bytes, n: int) -> bytes:
    bits = []
    for b in packed:
        for k in range(7, -1, -1): bits.append((b >> k) & 1)
    out = bytearray()
    for i in range(n):
        s = 0
        for k in range(6): s = (s << 1) | bits[i*6+k]
        out.append(s)
    return bytes(out)

def bytes_to_trits(data: bytes) -> list[int]:
    bits = []
    for b in data:
        for k in range(7, -1, -1): bits.append((b >> k) & 1)
    while len(bits) % 3: bits.append(0)
    return [(bits[i]<<2)|(bits[i+1]<<1)|bits[i+2] for i in range(0, len(bits), 3)]

def trits_to_bytes(trits: list[int], n: int) -> bytes:
    bits = []
    for t in trits:
        bits.append((t>>2)&1); bits.append((t>>1)&1); bits.append(t&1)
    out = bytearray()
    for i in range(n):
        b = 0
        for k in range(8): b = (b << 1) | bits[i*8+k]
        out.append(b)
    return bytes(out)

# =========================================================================
# Hexagonal geometry — S=8 outer (384 triangles), role-based layout.
#
# Roles (paper Fig 6 taxonomy):
#   ANCHOR    : 3 PDP hexagons at alternate outer corners, flush with border
#               (18 tris total, fixed chromatic colours for orientation).
#   ALIGNMENT : chamfered gray strip along the 3 NON-anchor outer edges
#               (row 7 minus the 12 row-7 tris consumed by anchors = 78 tris).
#   METADATA  : 6 tris near the top corner encoding URL symbol count in
#               triple-redundant form (18 bits = 3× 6-bit length).
#   PAYLOAD   : 128 data tris carrying the RS-coded payload, visited in
#               row-major (top→bottom, left→right) order — matches the
#               reading trajectory in the TS grid-topology spec.
#   SHIM      : white padding. Two flavours:
#               - BUFFER : 12 tris forming radial collars JUST INSIDE each
#                          anchor (3 anchors × 4 tris), so anchors don't
#                          touch payload.
#               - PAD    : remaining tris, same palette-white index 7.
#
# No continuous inner ring of white — buffers are localised to anchors.
# =========================================================================
S = 8
BORDER_ROW = S - 1     # 7
PDP_ROW = S - 2        # 6
N_MODULES = 6 * S * S  # 384

# Palette index order matches the layout editor (editor.html).
PALETTE = [
    (0,   0,   0),   # 0 black
    (255, 0,   0),   # 1 red
    (0,   255, 0),   # 2 green
    (0,   0,   255), # 3 blue
    (255, 255, 0),   # 4 yellow
    (0,   255, 255), # 5 cyan
    (255, 0,   255), # 6 magenta
    (255, 255, 255), # 7 white
]

# ── Schema-defined layout (drawn in editor.html, submitted 2026-04-23) ──────
#
# Outer ring = row 7 of every sector (indices 49-63, 113-127, …, 369-383).
# The user drew these as black but wants them as white shim → excluded from
# the active fixed map and folded into the shim set.
#
# Payload: 132 free triangles from the schema; first 128 in row-major order
# carry RS-coded data; the remaining 4 → shim.  128 trits × 3 bits = 48 bytes.
#
# Length header: first byte of the 24-byte RS data block is the MP-symbol
# count (0-63).  Remaining 23 bytes = packed URL + zero padding.

_OUTER_RING: frozenset = frozenset(
    i for s in range(6) for i in range(s * 64 + 49, s * 64 + 64)
)

_SCHEMA_FIXED: dict[int, int] = {
    4: 5,  5: 0,  6: 3,  7: 7,  8: 2,
    16: 3, 17: 7, 18: 7,
    25: 1, 26: 6, 27: 7, 28: 7,
    39: 7,
    68: 0, 72: 7, 74: 4, 75: 7, 76: 1, 77: 0, 78: 6,
    88: 6, 98: 3, 99: 5,
    132: 5, 133: 0, 134: 3, 135: 7, 136: 2,
    144: 1, 153: 2, 154: 4,
    196: 0, 200: 7, 202: 4, 203: 7, 204: 1, 205: 0, 206: 6,
    216: 4, 226: 1, 227: 6,
    260: 5, 261: 0, 262: 3, 263: 7, 264: 2,
    272: 2, 281: 3, 282: 5,
    324: 0, 328: 7, 330: 4, 331: 7, 332: 1, 333: 0, 334: 6,
    344: 5, 354: 2, 355: 4,
}

_SCHEMA_BUFFER: frozenset = frozenset([
    9, 36, 37, 38, 40, 41, 42, 43, 44, 45, 46, 47, 48,
    79, 86, 87, 96, 97, 100, 101, 102, 103, 104, 105, 106, 107, 108, 109, 110, 111, 112,
    137, 145, 146, 155, 156, 164, 165, 166, 167, 168, 169, 170, 171, 172, 173, 174, 175, 176,
    207, 214, 215, 224, 225, 228, 229, 230, 231, 232, 233, 234, 235, 236, 237, 238, 239, 240,
    265, 273, 274, 283, 284, 292, 293, 294, 295, 296, 297, 298, 299, 300, 301, 302, 303, 304,
    335, 342, 343, 352, 353, 356, 357, 358, 359, 360, 361, 362, 363, 364, 365, 366, 367, 368,
])

# Schema gives 132 payload triangles. Split:
#   4 trits  = length header (6-bit count stored twice = 12 bits)
#  128 trits = RS(48, 24) coded data  →  48 bytes = 384 bits
# Total: 132 trits used, none wasted.
N_LENGTH_MODULES  = 4
N_DATA_MODULES    = 128
N_PAYLOAD_MODULES = N_LENGTH_MODULES + N_DATA_MODULES   # 132
DATA_BYTES        = 24
ECC_BYTES         = 24
TOTAL_BYTES       = DATA_BYTES + ECC_BYTES              # 48 = exactly 128 trits

def _linear_idx(s, k, t):
    base = 0
    for ss in range(s):
        base += S * S
    for kk in range(k):
        base += 2 * kk + 1
    return base + t

def _sector_triangles(apex, v1, v2):
    apex = np.array(apex, dtype=float)
    v1   = np.array(v1,   dtype=float)
    v2   = np.array(v2,   dtype=float)
    for k in range(S):
        if k == 0:
            U = [apex.copy()]
        else:
            Ua = apex + (k/S)*(v1-apex)
            Ub = apex + (k/S)*(v2-apex)
            U = [Ua*(1-i/k) + Ub*(i/k) for i in range(k+1)]
        La = apex + ((k+1)/S)*(v1-apex)
        Lb = apex + ((k+1)/S)*(v2-apex)
        L = [La*(1-i/(k+1)) + Lb*(i/(k+1)) for i in range(k+2)]
        for t in range(2*k + 1):
            i = t // 2
            if t % 2 == 0:
                yield (k, t, (tuple(L[i]), tuple(L[i+1]), tuple(U[i])))
            else:
                yield (k, t, (tuple(U[i]), tuple(L[i+1]), tuple(U[i+1])))

def all_triangles(cx=0.0, cy=0.0, R=1.0):
    """N_MODULES triangles in canonical (sector-major, row-major) order."""
    out = []
    for s in range(6):
        a1 = math.radians(30 + s * 60)
        a2 = math.radians(30 + (s + 1) * 60)
        v1 = (cx + R*math.cos(a1), cy - R*math.sin(a1))
        v2 = (cx + R*math.cos(a2), cy - R*math.sin(a2))
        apex = (cx, cy)
        for k, t, tri in _sector_triangles(apex, v1, v2):
            out.append((s, k, t, tri))
    assert len(out) == N_MODULES
    return out


# =========================================================================
# Row-major traversal order — globally top→bottom, left→right over the
# whole hex. Built once from triangle centroids so payload indexing matches
# the rendered image's natural reading order.
# =========================================================================
_ROW_MAJOR_CACHE: list[int] | None = None
def _row_major_order() -> list[int]:
    """Return the 384 triangle indices sorted by (y_centroid, x_centroid).

    Triangles with similar y (within y_tol) are considered the same global
    row and sorted by x inside that row.
    """
    global _ROW_MAJOR_CACHE
    if _ROW_MAJOR_CACHE is not None:
        return _ROW_MAJOR_CACHE
    triangles = all_triangles(0.0, 0.0, 1.0)
    cents = []
    for idx, (_s, _k, _t, tri) in enumerate(triangles):
        cx_ = sum(p[0] for p in tri) / 3.0
        cy_ = sum(p[1] for p in tri) / 3.0
        cents.append((cy_, cx_, idx))
    cents.sort()
    # Bin by y into global rows using a tolerance just under a small-triangle
    # height (≈ R / (2S) = 0.0625 for S=8).
    y_tol = 0.03
    rows: list[list[tuple[float, int]]] = []
    cur_y = None
    for cy_, cx_, idx in cents:
        if cur_y is None or cy_ - cur_y > y_tol:
            rows.append([])
            cur_y = cy_
        rows[-1].append((cx_, idx))
    out: list[int] = []
    for row in rows:
        row.sort()
        out.extend(idx for _cx, idx in row)
    assert len(out) == N_MODULES
    _ROW_MAJOR_CACHE = out
    return out

# =========================================================================
# Module layout — schema-defined partition.
# =========================================================================
_LAYOUT_CACHE = None
def layout():
    """Return {'fixed': {idx: color}, 'payload': [idx, ...], 'shim': set}.

    fixed   — triangles with schema-defined colors (anchors / markers).
    payload — first N_PAYLOAD_MODULES free triangles in row-major order.
    shim    — everything else (outer ring + schema buffer + leftover free).
    """
    global _LAYOUT_CACHE
    if _LAYOUT_CACHE is not None:
        return _LAYOUT_CACHE

    fixed = _SCHEMA_FIXED
    shim  = _SCHEMA_BUFFER | _OUTER_RING

    reserved = set(fixed) | shim
    free_rm  = [i for i in _row_major_order() if i not in reserved]

    payload = free_rm[:N_PAYLOAD_MODULES]
    shim    = shim | set(free_rm[N_PAYLOAD_MODULES:])

    _LAYOUT_CACHE = {'fixed': fixed, 'payload': payload, 'shim': shim}
    return _LAYOUT_CACHE

# =========================================================================
# Encode
# =========================================================================
def _encode_data(url: str) -> tuple[list[int], list[int]]:
    """Returns (length_trits[4], data_trits[128]).

    length_trits: 4 trits = 12 bits = 6-bit symbol count stored twice
                  (primary copy + redundant copy; decoder uses primary).
    data_trits  : 128 trits from RS(48, 24) over the packed URL.
    """
    symbols = compress(url)
    n = len(symbols)
    if n > 63:
        raise ValueError(f"URL compresses to {n} MP symbols > 63 max")
    packed = pack6(symbols)
    if len(packed) > DATA_BYTES:
        raise ValueError(f"Packed URL {len(packed)} bytes > {DATA_BYTES} max")
    data = packed + b'\x00' * (DATA_BYTES - len(packed))
    coded = rs_encode(data, ECC_BYTES)
    data_trits = bytes_to_trits(coded)  # 128 trits

    # 6-bit count, stored twice in 12 bits = 4 trits.
    bits6 = [(n >> k) & 1 for k in range(5, -1, -1)]
    bits12 = bits6 + bits6
    length_trits = [(bits12[3*i] << 2) | (bits12[3*i+1] << 1) | bits12[3*i+2]
                    for i in range(4)]
    return length_trits, data_trits


def _payload_map(url: str, L: dict) -> dict[int, int]:
    length_trits, data_trits = _encode_data(url)
    all_trits = length_trits + data_trits  # 132 trits
    return {idx: all_trits[i] for i, idx in enumerate(L['payload'])}


def encode_url_to_colors(url: str) -> str:
    """Return JSON array of N_MODULES [r,g,b] triples in all_triangles() order."""
    import json as _json
    L = layout()
    pm = _payload_map(url, L)
    colors = []
    for idx in range(N_MODULES):
        if idx in _OUTER_RING:
            c = (180, 180, 180)
        elif idx in L['fixed']:
            c = PALETTE[L['fixed'][idx]]
        elif idx in pm:
            c = PALETTE[pm[idx]]
        else:
            c = PALETTE[7]
        colors.append(list(c))
    return _json.dumps(colors)


def encode_url(url: str, out_path: str, canvas: int = 720) -> None:
    L = layout()
    pm = _payload_map(url, L)

    cx, cy = canvas / 2, canvas / 2
    R = canvas * 0.47
    img = Image.new("RGB", (canvas, canvas), (255, 255, 255))
    draw = ImageDraw.Draw(img)

    OUTER_RING_COLOR = (180, 180, 180)  # gray detector ring — visible, non-data
    for idx, (_s, _k, _t, tri) in enumerate(all_triangles(cx, cy, R)):
        if idx in _OUTER_RING:
            color = OUTER_RING_COLOR
        elif idx in L['fixed']:
            color = PALETTE[L['fixed'][idx]]
        elif idx in pm:
            color = PALETTE[pm[idx]]
        else:
            color = PALETTE[7]
        poly = [(int(round(p[0])), int(round(p[1]))) for p in tri]
        draw.polygon(poly, fill=color)
    img.save(out_path)

# =========================================================================
# Decode v2 — robust to perspective warp, color cast, shading gradients,
# motion/focus blur, JPEG noise, and per-cell corruption.
#
# Pipeline (each stage is replaceable in isolation; see _pipeline_trace):
#   1. Localization
#      a. Multi-criterion pixel mask (saturated | dark | gray-ring).
#      b. Explicit gray-ring extraction (outer ring renders at (180,180,180),
#         a signature no other cell uses), with fallback to the full code
#         mask when the ring is partially occluded.
#      c. Convex hull of the selected pixel set, then angular-extrema on
#         HULL points (not raw pixels) → 6 hex corners. Hull restriction
#         rejects background clutter and noise outliers.
#   2. Geometry fit
#      a. Seed homography from 6 hull corners (DLT).
#      b. Iteratively refit over all ~200 known-color calibration cells
#         (42 schema-fixed + 154 white-shim): warp canonical centroid →
#         observe RGB → use cells whose RGB matches expected palette color
#         as keypoints for a weighted least-squares re-fit. Reweighted over
#         2 iterations converges and corrects corner-detection quantization.
#   3. Sampling
#      Per-triangle polygon-interior sampling: for each warped triangle,
#      take the median of N barycentric-distributed interior points. Robust
#      to (a) small triangles near outer ring where centroid-only can land
#      on an edge, and (b) JPEG / demosaicing artifacts that concentrate on
#      pixel boundaries.
#   4. Color calibration — learned palette centroids
#      For each of the 8 palette colors, take the mean of observed RGB over
#      cells known to be that color (from calibration map). This 8-centroid
#      model absorbs global color cast, white balance, exposure, and a
#      near-linear gamma. Vastly more robust than per-channel binary
#      thresholding at a fixed midpoint.
#   5. Shading correction
#      Fit a 2nd-order bivariate polynomial per channel to the residuals
#      of white-shim cells: s(x,y) = a0 + a1 x + a2 y + a3 x² + a4 y² + a5 xy.
#      Subtract predicted shading from each sample so the downstream
#      centroid classifier sees a flat illumination field.
#   6. Classification with soft confidence
#      For each cell: Euclidean distance to each of 8 shading-corrected
#      palette centroids. class = argmin. confidence = (2nd_best − best) /
#      (best + ε). Low confidence → cell is ambiguous.
#   7. Orientation
#      Score each of 6 rotations by Σ confidence over cells where the
#      classification matches the schema-fixed color. Pick highest score.
#   8. EM refinement (2 iterations)
#      Re-fit centroids using all classified cells whose confidence exceeds
#      the mean confidence of calibration cells, then reclassify. Converges
#      fast because the calibration set is already dense.
#   9. Erasure-aware Reed-Solomon
#      Trits below a confidence threshold are mapped to the bytes they
#      contribute to and marked as erasures via reedsolo's erase_pos.
#      RS(48,24) corrects up to 24 erasures (vs 12 pure errors), roughly
#      doubling tolerable corruption.
# =========================================================================

def _homography(src, dst):
    """8-point DLT, minimum case (4 src/dst pairs or more)."""
    A, b = [], []
    for (sx, sy), (dx, dy) in zip(src, dst):
        A.append([sx, sy, 1, 0, 0, 0, -dx*sx, -dx*sy]); b.append(dx)
        A.append([0, 0, 0, sx, sy, 1, -dy*sx, -dy*sy]); b.append(dy)
    h, *_ = np.linalg.lstsq(np.array(A), np.array(b), rcond=None)
    return np.array([[h[0], h[1], h[2]], [h[3], h[4], h[5]], [h[6], h[7], 1.0]])

def _homography_weighted(src, dst, w):
    """Overdetermined weighted DLT (same setup as _homography, per-point w)."""
    A, b = [], []
    for (sx, sy), (dx, dy), wi in zip(src, dst, w):
        s = math.sqrt(max(wi, 1e-6))
        A.append([s*sx, s*sy, s, 0, 0, 0, -s*dx*sx, -s*dx*sy]); b.append(s*dx)
        A.append([0, 0, 0, s*sx, s*sy, s, -s*dy*sx, -s*dy*sy]); b.append(s*dy)
    h, *_ = np.linalg.lstsq(np.array(A), np.array(b), rcond=None)
    return np.array([[h[0], h[1], h[2]], [h[3], h[4], h[5]], [h[6], h[7], 1.0]])

def _warp(H, x, y):
    v = H @ np.array([x, y, 1.0])
    return v[0]/v[2], v[1]/v[2]

def _warp_many(H, pts):
    """Batch warp — pts: (N,2), returns (N,2)."""
    ones = np.ones((pts.shape[0], 1), dtype=pts.dtype)
    hom = np.concatenate([pts, ones], axis=1) @ H.T
    return hom[:, :2] / hom[:, 2:3]

def _convex_hull(xs, ys):
    """Andrew's monotone chain. Returns (hx, hy) CCW without duplicate endpoint."""
    pts = sorted(set(zip(xs.tolist(), ys.tolist())))
    if len(pts) <= 1:
        return np.array([p[0] for p in pts]), np.array([p[1] for p in pts])
    def cross(o, a, b):
        return (a[0]-o[0])*(b[1]-o[1]) - (a[1]-o[1])*(b[0]-o[0])
    lower = []
    for p in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    upper = []
    for p in reversed(pts):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    hull = lower[:-1] + upper[:-1]
    return np.array([p[0] for p in hull], dtype=np.float64), np.array([p[1] for p in hull], dtype=np.float64)

def _estimate_background(arr: np.ndarray) -> np.ndarray:
    """Background RGB via mode of 16³-binned pixels (≤8000 samples)."""
    H_img, W_img = arr.shape[:2]
    step_y = max(1, H_img // 90); step_x = max(1, W_img // 90)
    sp = arr[::step_y, ::step_x].reshape(-1, 3).astype(np.int16)
    binned = (sp // 16).astype(np.int32)
    packed = (binned[:, 0] << 16) | (binned[:, 1] << 8) | binned[:, 2]
    vals, counts = np.unique(packed, return_counts=True)
    mode = int(vals[int(np.argmax(counts))])
    br = ((mode >> 16) & 0xFF) * 16 + 8
    bg = ((mode >> 8) & 0xFF) * 16 + 8
    bb = (mode & 0xFF) * 16 + 8
    return np.array([br, bg, bb], dtype=np.float32)

def _mask_via_gradient(arr: np.ndarray, F: int = 8) -> np.ndarray:
    """Shading-invariant code-pixel mask via block-wise gradient density.

    The hex is densely cellular (many cell boundaries = high gradient), while
    any smooth background — including steep illumination gradients — has
    low gradient. Summing |∇| over F×F blocks and thresholding on that
    block-level edge energy gives a mask that tolerates arbitrary smooth
    shading, moderate color cast, and partial occlusion.
    """
    H_img, W_img = arr.shape[:2]
    gray = arr.mean(axis=2)
    gx = np.abs(np.diff(gray, axis=1, prepend=gray[:, :1]))
    gy = np.abs(np.diff(gray, axis=0, prepend=gray[:1, :]))
    grad = gx + gy
    Hb = (H_img // F) * F; Wb = (W_img // F) * F
    blk = grad[:Hb, :Wb].reshape(Hb // F, F, Wb // F, F).sum(axis=(1, 3))
    thr = max(float(np.percentile(blk, 70)), float(blk.max()) * 0.05)
    mask_blk = blk > thr
    # Upsample block mask to pixel mask (nearest).
    mask = np.zeros((H_img, W_img), dtype=bool)
    ys_b, xs_b = np.where(mask_blk)
    for yb, xb in zip(ys_b, xs_b):
        mask[yb*F:yb*F+F, xb*F:xb*F+F] = True
    return mask

def _subpixel_refine_corners(corners, hx, hy, radius: float = 6.0):
    """Weighted-centroid refinement of each corner using nearby hull points."""
    refined = []
    for (cx_c, cy_c) in corners:
        d2 = (hx - cx_c)**2 + (hy - cy_c)**2
        w = np.maximum(radius*radius - d2, 0.0)
        if w.sum() < 1e-6:
            refined.append((cx_c, cy_c)); continue
        rx = float((hx * w).sum() / w.sum())
        ry = float((hy * w).sum() / w.sum())
        refined.append((rx, ry))
    return refined

def _corners_from_mask(mask: np.ndarray):
    """6 corners from a binary mask via convex hull + canonical angular-extrema."""
    ys, xs = np.where(mask)
    if len(ys) < 100:
        return None, None, None
    hx, hy = _convex_hull(xs.astype(np.float64), ys.astype(np.float64))
    if len(hx) < 6:
        return None, None, None
    corners = []
    for deg in (30, 90, 150, 210, 270, 330):
        th = math.radians(deg)
        proj = hx * math.cos(th) - hy * math.sin(th)
        i = int(np.argmax(proj))
        corners.append((float(hx[i]), float(hy[i])))
    corners = _subpixel_refine_corners(corners, hx, hy, radius=8.0)
    return corners, hx, hy

def _find_hex_corner_candidates(img: Image.Image) -> list[list[tuple[float, float]]]:
    """Produce multiple 6-corner hypotheses using complementary strategies.

    Returns a list of candidate corner-sets; the decoder tries each and
    keeps the one that maximizes fixed-cell agreement.
    """
    arr = np.asarray(img.convert("RGB"), dtype=np.float32)
    cands: list[list[tuple[float, float]]] = []

    # Strategy A: gradient/texture — invariant to smooth shading.
    try:
        m = _mask_via_gradient(arr, F=8)
        c, _, _ = _corners_from_mask(m)
        if c is not None: cands.append(c)
    except Exception:
        pass
    # Also try a finer block size (catches small codes).
    try:
        m = _mask_via_gradient(arr, F=4)
        c, _, _ = _corners_from_mask(m)
        if c is not None: cands.append(c)
    except Exception:
        pass

    # Strategy B: mode-bg distance — handles color cast cleanly.
    try:
        bg = _estimate_background(arr)
        dist = np.linalg.norm(arr - bg[None, None, :], axis=2)
        d_max = float(dist.max())
        thr = min(120.0, max(40.0, d_max * 0.25))
        m = dist > thr
        c, _, _ = _corners_from_mask(m)
        if c is not None: cands.append(c)
    except Exception:
        pass

    # Strategy C: saturation + darkness — handles heavy cast where gray is
    # ambiguous but colored cells are still distinctive.
    try:
        mx = arr.max(axis=2); mn = arr.min(axis=2); sat = mx - mn
        m = (sat > 60) | (mx < 60)
        c, _, _ = _corners_from_mask(m)
        if c is not None: cands.append(c)
    except Exception:
        pass

    if not cands:
        raise ValueError("No code found in image")
    return cands

def _find_hex_corners(img: Image.Image):
    """Kept for backwards compatibility — returns the gradient-based corners."""
    return _find_hex_corner_candidates(img)[0]

def _sample_triangle(arr, tri_pts, H_img, W_img):
    """Median RGB over a dense barycentric grid inside the (image-space)
    triangle. Falls back gracefully when the triangle is tiny or clipped."""
    (x0, y0), (x1, y1), (x2, y2) = tri_pts
    # 10 barycentric points including interior-weighted centroid.
    bc = [
        (1/3, 1/3, 1/3),
        (1/2, 1/4, 1/4), (1/4, 1/2, 1/4), (1/4, 1/4, 1/2),
        (3/5, 1/5, 1/5), (1/5, 3/5, 1/5), (1/5, 1/5, 3/5),
        (0.45, 0.45, 0.10), (0.45, 0.10, 0.45), (0.10, 0.45, 0.45),
    ]
    pts = []
    for a, b, c in bc:
        ix = a*x0 + b*x1 + c*x2
        iy = a*y0 + b*y1 + c*y2
        jx = int(round(ix)); jy = int(round(iy))
        if 0 <= jx < W_img and 0 <= jy < H_img:
            pts.append(arr[jy, jx])
    if not pts:
        return np.array([127.0, 127.0, 127.0], dtype=np.float32)
    # Median is robust against spillover from neighboring cells and JPEG.
    return np.median(np.stack(pts, axis=0), axis=0).astype(np.float32)

def _sample_all(arr, tris_img, H_img, W_img):
    return np.stack([_sample_triangle(arr, t, H_img, W_img) for t in tris_img], axis=0)

def _fit_shading(samples, white_idxs, centroids_img):
    """Fit a MULTIPLICATIVE per-channel shading factor s(x,y) from the
    observed brightness of white-shim cells. The physical model of
    non-uniform illumination on a flat surface is multiplicative (each
    cell's reflectance is scaled by local irradiance), so we fit:

        shading(x,y) = Σ c_k · φ_k(x,y)   with basis {1, x, y, x², y², xy}

    normalized so the MEAN white sample divided by the mean shading factor
    equals identity. The returned callable shade(pts) gives a (N,3)
    multiplicative factor — callers divide samples by this factor to
    obtain an illumination-flat image that classifies cleanly.
    """
    if len(white_idxs) < 10:
        def one(_p): return np.ones((_p.shape[0], 3), dtype=np.float32)
        return one
    W = np.asarray(white_idxs, dtype=int)
    pts = centroids_img[W]
    # Normalize coordinates so polynomial conditioning is stable.
    cx_n = float(pts[:, 0].mean()); cy_n = float(pts[:, 1].mean())
    sx_n = float(pts[:, 0].std() + 1e-6); sy_n = float(pts[:, 1].std() + 1e-6)
    x = (pts[:, 0] - cx_n) / sx_n; y = (pts[:, 1] - cy_n) / sy_n
    Phi = np.stack([np.ones_like(x), x, y, x*x, y*y, x*y], axis=1)
    mean_white = samples[W].mean(axis=0, keepdims=True) + 1e-6
    # Relative factor per white cell: target ≈ 1 everywhere if illumination is flat.
    target = samples[W] / mean_white
    coefs, *_ = np.linalg.lstsq(Phi, target, rcond=None)
    def shade(p):
        xp = (p[:, 0] - cx_n) / sx_n; yp = (p[:, 1] - cy_n) / sy_n
        Phi_p = np.stack([np.ones_like(xp), xp, yp, xp*xp, yp*yp, xp*yp], axis=1)
        f = Phi_p @ coefs
        # Clamp to a sane range so cells landing outside the white-sample
        # spatial support don't produce wild factors.
        return np.clip(f, 0.25, 4.0).astype(np.float32)
    return shade

def _palette_centroids(samples, cal_map):
    """8 observed-RGB centroids, one per palette color, from calibration cells."""
    cents = np.zeros((8, 3), dtype=np.float32)
    counts = np.zeros(8, dtype=np.int32)
    for idx, color_idx in cal_map.items():
        cents[color_idx] += samples[idx]
        counts[color_idx] += 1
    # Fill any gap with the palette-true color (should not happen with the
    # current schema but keeps the classifier well-conditioned).
    for c in range(8):
        if counts[c] == 0:
            cents[c] = np.array(PALETTE[c], dtype=np.float32)
        else:
            cents[c] /= counts[c]
    return cents

def _classify(samples, cents):
    """Returns (classes[N], confidence[N]). Confidence = margin / best_dist."""
    # (N, 8) squared distances.
    d2 = ((samples[:, None, :] - cents[None, :, :]) ** 2).sum(axis=2)
    d = np.sqrt(d2 + 1e-9)
    classes = np.argmin(d, axis=1)
    d_sorted = np.sort(d, axis=1)
    best = d_sorted[:, 0]; second = d_sorted[:, 1]
    conf = (second - best) / (best + 10.0)   # +10 keeps confidence finite for near-zero distances
    return classes.astype(np.int32), conf.astype(np.float32)

def _refit_homography(canon_centroids, img_centroids, classes, cal_map, conf):
    """Weighted least-squares homography using calibration cells that
    classified correctly as high-weight keypoints. Caller must pass the
    CURRENT image-space centroids (from previous H) as img_centroids — we
    use those positions directly; if they are correct, re-solving
    reproduces H. The refit helps when the initial corners are noisy and
    one or two of them land off the true vertex: the dense interior
    fiducials then anchor H back."""
    src, dst, w = [], [], []
    for idx, color_idx in cal_map.items():
        if classes[idx] != color_idx:
            continue  # mismatches can't inform geometry
        src.append(tuple(canon_centroids[idx]))
        dst.append(tuple(img_centroids[idx]))
        w.append(float(conf[idx]) + 0.1)
    if len(src) < 8:
        return None
    try:
        return _homography_weighted(src, dst, w)
    except Exception:
        return None

def _trit_erasures(conf, order, payload_idx_list, total_bytes):
    """Map low-confidence trits to byte-indices for RS erasure decoding.

    payload_idx_list is the list of module indices in payload order
    (length N_PAYLOAD_MODULES). Only DATA trits (after the 4 length trits)
    map to the RS block.
    """
    data_conf = np.array([conf[i] for i in payload_idx_list[N_LENGTH_MODULES:]],
                         dtype=np.float32)
    # Mark up to ECC_BYTES trits with the worst confidence as erasures.
    # Each trit contributes to 1-2 bytes; we cap total byte erasures at
    # ECC_BYTES to stay within RS correction capacity.
    n_mark = min(len(data_conf), ECC_BYTES)
    if n_mark == 0:
        return []
    worst = np.argsort(data_conf)[:n_mark]
    bytes_erased = set()
    for trit_k in worst.tolist():
        b_start = (3 * trit_k) // 8
        b_end   = (3 * trit_k + 2) // 8
        for b in range(b_start, b_end + 1):
            if 0 <= b < total_bytes:
                bytes_erased.add(b)
        if len(bytes_erased) >= ECC_BYTES:
            break
    return sorted(bytes_erased)[:ECC_BYTES]

def _rs_decode_with_erasures(coded: bytes, erase_pos: list) -> bytes:
    """Try erasure-aware RS first, fall back to pure-error decode."""
    codec = _codec(ECC_BYTES)
    try:
        out, _, _ = codec.decode(coded, erase_pos=erase_pos)
        return bytes(out)
    except _rs.ReedSolomonError:
        out, _, _ = codec.decode(coded)  # fallback
        return bytes(out)

def decode_image(path: str) -> str:
    img = Image.open(path)
    arr = np.asarray(img.convert("RGB"), dtype=np.float32)
    H_img, W_img = arr.shape[:2]

    # Multiple localization strategies; pick whichever produces the best
    # fixed-cell agreement after running the full classification pipeline.
    corner_candidates = _find_hex_corner_candidates(img)

    R_can = 200.0
    canon_corners = [(R_can * math.cos(math.radians(30 + s * 60)),
                     -R_can * math.sin(math.radians(30 + s * 60)))
                     for s in range(6)]
    triangles_canon = all_triangles(0.0, 0.0, R_can)
    centroids_canon = np.array([
        [sum(p[0] for p in tri)/3, sum(p[1] for p in tri)/3]
        for (_s, _k, _t, tri) in triangles_canon
    ], dtype=np.float64)
    tri_vertices_canon = [np.array(tri, dtype=np.float64) for (_s, _k, _t, tri) in triangles_canon]

    L = layout()
    cal_map: dict[int, int] = dict(L['fixed'])
    white_shim_idxs: list[int] = []
    for idx in L['shim']:
        if idx not in _OUTER_RING:
            cal_map[idx] = 7  # white
            white_shim_idxs.append(idx)

    best_score = -1.0
    best_classes = None
    best_conf = None

    def _run(H):
        """Full classify pipeline for one homography. Returns (classes, conf, samples_flat, centroids_img)."""
        centroids_img = _warp_many(H, centroids_canon)
        tris_img = [_warp_many(H, v)[:3] for v in tri_vertices_canon]
        samples = _sample_all(arr, [t.tolist() for t in tris_img], H_img, W_img)
        shade_fn = _fit_shading(samples, white_shim_idxs, centroids_img)
        factor = shade_fn(centroids_img)
        samples_flat = samples / np.maximum(factor, 0.05)
        cents = _palette_centroids(samples_flat, cal_map)
        classes, conf = _classify(samples_flat, cents)
        return classes, conf, samples_flat, centroids_img

    for img_corners in corner_candidates:
        for rot in range(6):
            rolled = img_corners[rot:] + img_corners[:rot]
            try:
                H = _homography(canon_corners, rolled)
            except Exception:
                continue
            classes, conf, samples_flat, centroids_img = _run(H)
            hits = sum(1 for i, c in L['fixed'].items() if classes[i] == c)
            if hits >= len(L['fixed']) * 0.35:
                H2 = _refit_homography(centroids_canon, centroids_img, classes, cal_map, conf)
                if H2 is not None:
                    classes2, conf2, sf2, ci2 = _run(H2)
                    hits2 = sum(1 for i, c in L['fixed'].items() if classes2[i] == c)
                    if hits2 >= hits:
                        classes, conf, samples_flat, centroids_img = classes2, conf2, sf2, ci2
                        hits = hits2
            # EM refinement: expand calibration with high-confidence cells.
            for _em in range(2):
                cal_conf = np.array([conf[i] for i in cal_map.keys()])
                thr_c = float(np.median(cal_conf) * 0.5)
                ext_map = dict(cal_map)
                for i in range(N_MODULES):
                    if i in ext_map or i in _OUTER_RING: continue
                    if conf[i] >= thr_c:
                        ext_map[i] = int(classes[i])
                cents_em = _palette_centroids(samples_flat, ext_map)
                new_classes, new_conf = _classify(samples_flat, cents_em)
                new_hits = sum(1 for i, c in L['fixed'].items() if new_classes[i] == c)
                if new_hits < hits:
                    break
                classes, conf = new_classes, new_conf
                hits = new_hits
            hits_final = sum(1 for i, c in L['fixed'].items() if classes[i] == c)
            conf_mass = float(sum(conf[i] for i, c in L['fixed'].items() if classes[i] == c))
            score = hits_final * 1000.0 + conf_mass
            if score > best_score:
                best_score = score
                best_classes = classes.copy()
                best_conf = conf.copy()

    if best_classes is None:
        raise ValueError("Could not orient hexagon")

    # Soft-decision warning based on fixed-cell agreement.
    fixed_hits = sum(1 for i, c in L['fixed'].items() if best_classes[i] == c)
    if fixed_hits < len(L['fixed']) * 0.6:
        print(f"[warn] low fixed score ({fixed_hits}/{len(L['fixed'])})", file=sys.stderr)

    # Length header (first 4 trits, stored twice as 2×6 bits).
    length_trits = [int(best_classes[i]) for i in L['payload'][:N_LENGTH_MODULES]]
    bits12 = []
    for t in length_trits:
        bits12 += [(t >> 2) & 1, (t >> 1) & 1, t & 1]
    n_symbols = sum(bits12[i] << (5 - i) for i in range(6))
    if n_symbols > 63:
        n_symbols = sum(bits12[6 + i] << (5 - i) for i in range(6))
    if n_symbols > 63:
        raise ValueError(f"Decoded symbol count {n_symbols} > 63 max")

    data_trits = [int(best_classes[i]) for i in L['payload'][N_LENGTH_MODULES:]]
    coded = trits_to_bytes(data_trits, TOTAL_BYTES)
    erase_pos = _trit_erasures(best_conf, None, L['payload'], TOTAL_BYTES)
    try:
        payload_bytes = _rs_decode_with_erasures(coded, erase_pos)
    except _rs.ReedSolomonError as e:
        raise ValueError(str(e))
    packed = payload_bytes[:(n_symbols * 6 + 7) // 8]
    symbols = unpack6(packed, n_symbols)
    return decompress(symbols)

# =========================================================================
# Demo / CLI
# =========================================================================
def _demo():
    urls = [
        "https://github.com/anthropics/claude-code",
        "https://www.apple.com/iphone-15/",
        "https://en.wikipedia.org/wiki/QR_code",
    ]
    for url in urls:
        path = f"/tmp/webcode_hex_{abs(hash(url)) % 10000}.png"
        try:
            encode_url(url, path)
        except ValueError as e:
            print(f"SKIP: {url} -> {e}")
            continue
        try:
            back = decode_image(path)
            ok = back == url
            print(f"[{'OK' if ok else 'FAIL'}] {url}")
            if not ok:
                print(f"       got: {back!r}")
        except ValueError as e:
            print(f"[FAIL] {url}  ({e})")
        # Noise test: flip 15 random data triangles.
        rng = random.Random(abs(hash(url)) % 10000)
        img = Image.open(path).convert("RGB")
        arr = np.array(img)
        H_img, W_img = arr.shape[:2]
        R = W_img * 0.47
        cx, cy = W_img / 2, H_img / 2
        triangles = all_triangles(cx, cy, R)
        data_list = layout()['payload']
        for idx in rng.sample(data_list, min(15, len(data_list))):
            tri = triangles[idx][3]
            fake = PALETTE[rng.randrange(8)]
            poly_arr = np.array([[p[0], p[1]] for p in tri])
            x0 = int(poly_arr[:,0].min()); x1 = int(poly_arr[:,0].max())
            y0 = int(poly_arr[:,1].min()); y1 = int(poly_arr[:,1].max())
            cxp = (x0 + x1) // 2; cyp = (y0 + y1) // 2
            arr[cyp-2:cyp+3, cxp-2:cxp+3] = fake
        noisy = path.replace(".png", "_noisy.png")
        Image.fromarray(arr).save(noisy)
        try:
            ok = decode_image(noisy) == url
            print(f"   noisy: {'OK' if ok else 'FAIL'} ({noisy})")
        except ValueError as e:
            print(f"   noisy: FAIL ({e})")

if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "encode":
        encode_url(sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else "webcode_hex.png")
        print(f"Wrote {sys.argv[3] if len(sys.argv) > 3 else 'webcode_hex.png'}")
    elif len(sys.argv) >= 3 and sys.argv[1] == "decode":
        print(decode_image(sys.argv[2]))
    else:
        _demo()
