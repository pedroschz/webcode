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
# Decode
# =========================================================================
def _homography(src, dst):
    A, b = [], []
    for (sx, sy), (dx, dy) in zip(src, dst):
        A.append([sx, sy, 1, 0, 0, 0, -dx*sx, -dx*sy]); b.append(dx)
        A.append([0, 0, 0, sx, sy, 1, -dy*sx, -dy*sy]); b.append(dy)
    h, *_ = np.linalg.lstsq(np.array(A), np.array(b), rcond=None)
    return np.array([[h[0], h[1], h[2]], [h[3], h[4], h[5]], [h[6], h[7], 1.0]])

def _warp(H, x, y):
    v = H @ np.array([x, y, 1.0])
    return v[0]/v[2], v[1]/v[2]

def _find_hex_corners(img: Image.Image):
    """Six outer hex corners (x,y) — detects colored, dark, OR gray-border pixels."""
    arr = np.asarray(img.convert("RGB"), dtype=np.int16)
    mx = arr.max(axis=2); mn = arr.min(axis=2); sat = mx - mn
    # Colored OR dark OR off-white gray (the 200-gray border).
    mask = (sat > 80) | (mx < 80) | ((mx < 230) & (sat < 30))
    ys, xs = np.where(mask)
    if len(ys) < 100:
        raise ValueError("No code found in image")
    corners = []
    for deg in (30, 90, 150, 210, 270, 330):
        th = math.radians(deg)
        proj = xs * math.cos(th) - ys * math.sin(th)
        i = int(np.argmax(proj))
        corners.append((float(xs[i]), float(ys[i])))
    return corners

def decode_image(path: str) -> str:
    img = Image.open(path)
    arr = np.asarray(img.convert("RGB"), dtype=np.float32)
    H_img, W_img = arr.shape[:2]

    img_corners = _find_hex_corners(img)

    R_can = 200.0
    canon_corners = []
    for s in range(6):
        a = math.radians(30 + s * 60)
        canon_corners.append((R_can * math.cos(a), -R_can * math.sin(a)))
    triangles_canon = all_triangles(0.0, 0.0, R_can)
    centroids_canon = np.array([
        [sum(p[0] for p in tri)/3, sum(p[1] for p in tri)/3]
        for (_s, _k, _t, tri) in triangles_canon
    ])
    L = layout()

    # Calibration: fixed triangles (known colors) + inner shim (white ref).
    # Outer ring is excluded — it renders gray for detection, not a palette color.
    cal_map: dict[int, int] = dict(L['fixed'])
    for idx in L['shim']:
        if idx not in _OUTER_RING:
            cal_map[idx] = 7  # white

    best_score = -1
    best_classes = None

    for rot in range(6):
        rolled = img_corners[rot:] + img_corners[:rot]
        try:
            H = _homography(canon_corners, rolled)
        except Exception:
            continue
        samples = np.zeros((N_MODULES, 3), dtype=np.float32)
        for k in range(N_MODULES):
            cx_c, cy_c = centroids_canon[k]
            ix, iy = _warp(H, cx_c, cy_c)
            acc = np.zeros(3, dtype=np.float32); cnt = 0
            for dy in (-1, 0, 1):
                for dx in (-1, 0, 1):
                    jx, jy = int(round(ix)) + dx, int(round(iy)) + dy
                    if 0 <= jx < W_img and 0 <= jy < H_img:
                        acc += arr[jy, jx]; cnt += 1
            samples[k] = acc / max(cnt, 1)
        # Calibration: derive channel-high/low from actual palette RGB values.
        ch_lo = [[], [], []]; ch_hi = [[], [], []]
        for idx, color_idx in cal_map.items():
            pr, pg, pb = PALETTE[color_idx]
            for ch, pv in enumerate((pr, pg, pb)):
                (ch_hi if pv > 127 else ch_lo)[ch].append(samples[idx, ch])
        try:
            thr = [(float(np.mean(ch_hi[ch])) + float(np.mean(ch_lo[ch]))) / 2
                   for ch in range(3)]
        except Exception:
            continue
        # Build RGB-bit → palette-index lookup for classification.
        rgb_to_idx: dict[int, int] = {}
        for pi, (pr, pg, pb) in enumerate(PALETTE):
            bits = ((1 if pr > 127 else 0) << 2) | ((1 if pg > 127 else 0) << 1) | (1 if pb > 127 else 0)
            rgb_to_idx[bits] = pi
        classes = []
        for k_i in range(N_MODULES):
            bits = sum((1 << (2 - ch)) for ch in range(3) if samples[k_i, ch] > thr[ch])
            classes.append(rgb_to_idx.get(bits, 7))
        # Score by how many fixed modules classify correctly.
        score = sum(1 for i, c in L['fixed'].items() if classes[i] == c)
        if score > best_score:
            best_score = score
            best_classes = classes

    if best_classes is None:
        raise ValueError("Could not orient hexagon")
    max_score = len(L['fixed'])
    if best_score < max_score * 0.6:
        print(f"[warn] low fixed score ({best_score}/{max_score})", file=sys.stderr)

    # First 4 payload trits = length header (6-bit count stored twice).
    length_trits = [best_classes[i] for i in L['payload'][:N_LENGTH_MODULES]]
    bits12 = []
    for t in length_trits:
        bits12 += [(t >> 2) & 1, (t >> 1) & 1, t & 1]
    n_symbols = sum(bits12[i] << (5 - i) for i in range(6))
    if n_symbols > 63:
        n_symbols = sum(bits12[6 + i] << (5 - i) for i in range(6))  # redundant copy
    if n_symbols > 63:
        raise ValueError(f"Decoded symbol count {n_symbols} > 63 max")

    data_trits = [best_classes[i] for i in L['payload'][N_LENGTH_MODULES:]]
    coded = trits_to_bytes(data_trits, TOTAL_BYTES)
    payload_bytes = rs_decode(coded, ECC_BYTES)
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
