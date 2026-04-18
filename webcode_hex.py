"""
Webcode v2-hex — hexagonal 216-triangle variant.

Matches the *shape* of the original 2023 paper (Webcode V1):
  * Hexagonal outline made of 216 triangular modules
    (6 sectors × 6² = 216, each sector subdivided into rows of 1, 3, 5 … 11 triangles).
  * Paper's MP 6-bit character system (Table 1, with the 010011 ↔ 4 typo corrected).
  * Paper's "^" key mechanism for capitalization and common URL phrases
    (^$ = https://, ^@ = www., ^& = https://www., ^* = .com/, ^! = .html,
     ^# = .php, ^+ = login, ^= = .edu, ^? = .org, ^~ = https://www.youtube.com/watch?v=).

Keeps the modernized pipeline from webcode.py:
  * 8-color palette (3 bits/module), RGB-corner palette.
  * Reed-Solomon over GF(256) for ECC (replaces the paper's Hamming(128,120)).
  * Homography-based decoding (no ML needed).

Capacity (216 modules, 33 reserved for 3 fiducial "petals"):
  * 183 data modules × 3 bits = 549 bits → 68 bytes
  * Split: 40 data + 28 ECC (RS(68,40), corrects up to 14 byte errors)
  * 40 bytes → 53 MP symbols → typical URL up to ~50 chars (after ^-compression,
    which e.g. expands "^&github^*anthropics/claude-code" back to the original
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
# MP character system — paper Table 1 verbatim (the obvious 010011↔4 typo
# corrected so that 001011 → 'l' and 010011 → '4').
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

# Paper's ^-key phrase table.
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
# Order longest-first for greedy matching
_PHRASE_ORDER = sorted(KEY_PHRASES.items(), key=lambda kv: -len(kv[1]))

def compress(url: str) -> bytes:
    """Compress a URL into a sequence of 6-bit MP symbols (one symbol per byte)."""
    out: list[int] = []
    i, n = 0, len(url)
    while i < n:
        # 1. Longest dictionary phrase
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
        # 2. Direct MP character
        if c in CHAR_TO_IDX:
            out.append(CHAR_TO_IDX[c])
            i += 1
            continue
        # 3. Uppercase non-vowel → ^ + lowercase (vowels have dedicated uppercase)
        if "A" <= c <= "Z" and c.lower() in CHAR_TO_IDX:
            out.append(KEY)
            out.append(CHAR_TO_IDX[c.lower()])
            i += 1
            continue
        # 4. Fallback: percent-encode the byte
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
                out.append(nxt)  # unknown ^-sequence, pass through
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
# Hexagonal geometry — 216 triangular modules in 6 sectors of 36 each
# =========================================================================
S = 6  # hexagon side in triangle units; 6*S² = 216 modules total
N_MODULES = 6 * S * S  # 216

PALETTE = [
    (0, 0, 0),       # 000 black
    (0, 0, 255),     # 001 blue
    (0, 255, 0),     # 010 green
    (0, 255, 255),   # 011 cyan
    (255, 0, 0),     # 100 red
    (255, 0, 255),   # 101 magenta
    (255, 255, 0),   # 110 yellow
    (255, 255, 255), # 111 white
]

def _sector_triangles(apex, v1, v2):
    """Yield (row_k, triangle_t, (p1,p2,p3)) for S² triangles in a sector."""
    apex = np.array(apex, dtype=float)
    v1   = np.array(v1,   dtype=float)
    v2   = np.array(v2,   dtype=float)
    for k in range(S):
        # Upper boundary of row k: k+1 points (collapsed to the apex when k=0).
        if k == 0:
            U = [apex.copy()]
        else:
            Ua = apex + (k/S)*(v1-apex)
            Ub = apex + (k/S)*(v2-apex)
            U = [Ua*(1-i/k) + Ub*(i/k) for i in range(k+1)]
        # Lower boundary of row k: k+2 points.
        La = apex + ((k+1)/S)*(v1-apex)
        Lb = apex + ((k+1)/S)*(v2-apex)
        L = [La*(1-i/(k+1)) + Lb*(i/(k+1)) for i in range(k+2)]
        # Row k has 2k+1 triangles, alternating (toward-apex / away-from-apex).
        for t in range(2*k + 1):
            i = t // 2
            if t % 2 == 0:
                yield (k, t, (tuple(L[i]), tuple(L[i+1]), tuple(U[i])))
            else:
                yield (k, t, (tuple(U[i]), tuple(L[i+1]), tuple(U[i+1])))

def all_triangles(cx=0.0, cy=0.0, R=1.0):
    """216 triangles in canonical (sector-major, row-major) order."""
    out = []
    for s in range(6):
        # Pointy-top hexagon, corners at 30° + s·60° (CCW from +x, image y is flipped).
        a1 = math.radians(30 + s * 60)
        a2 = math.radians(30 + (s + 1) * 60)
        v1 = (cx + R*math.cos(a1), cy - R*math.sin(a1))
        v2 = (cx + R*math.cos(a2), cy - R*math.sin(a2))
        apex = (cx, cy)
        for k, t, tri in _sector_triangles(apex, v1, v2):
            out.append((s, k, t, tri))
    assert len(out) == N_MODULES
    return out

# Fiducials: the outermost row (k = S-1 = 5, 11 triangles) of 3 alternating sectors.
# Each fiducial has a distinct color pattern so orientation is unambiguous.
FIDUCIAL_SECTORS = [0, 2, 4]
_FID_BASE = [0, 1, 2, 3, 4, 5, 6, 7, 0, 3, 6]  # 11 colors; hits all 8 of the palette
_FID_SHIFT = {0: 0, 2: 2, 4: 5}                # shifts distinguish the 3 sectors

def _fiducial_color(sector: int, t: int) -> int:
    shift = _FID_SHIFT[sector]
    return _FID_BASE[(t + shift) % len(_FID_BASE)]

def fiducial_map() -> dict[int, int]:
    """Return {module_index: palette_idx} for all fiducial modules (33 entries)."""
    fids = {}
    idx = 0
    for s in range(6):
        for k in range(S):
            for t in range(2*k + 1):
                if s in FIDUCIAL_SECTORS and k == S - 1:
                    fids[idx] = _fiducial_color(s, t)
                idx += 1
    return fids

N_FIDUCIAL = 11 * 3  # 33
N_DATA_MODULES = N_MODULES - N_FIDUCIAL  # 183
DATA_BYTES = 40
ECC_BYTES = 28
TOTAL_BYTES = DATA_BYTES + ECC_BYTES  # 68
TRITS_NEEDED = (TOTAL_BYTES * 8 + 2) // 3  # 182

# =========================================================================
# Encode
# =========================================================================
def encode_url(url: str, out_path: str, canvas: int = 720) -> None:
    symbols = compress(url)
    if len(symbols) > 0xFFFF:
        raise ValueError("URL too long")
    packed = pack6(symbols)
    header = bytes([(len(symbols) >> 8) & 0xFF, len(symbols) & 0xFF])
    payload = header + packed
    if len(payload) > DATA_BYTES:
        raise ValueError(f"URL compresses to {len(payload)} > {DATA_BYTES} bytes")
    payload = payload + b"\x00" * (DATA_BYTES - len(payload))
    coded = rs_encode(payload, ECC_BYTES)  # 68 bytes
    trits = bytes_to_trits(coded)          # 182 trits

    cx, cy = canvas / 2, canvas / 2
    R = canvas * 0.45
    img = Image.new("RGB", (canvas, canvas), (255, 255, 255))
    draw = ImageDraw.Draw(img)

    fids = fiducial_map()
    triangles = all_triangles(cx, cy, R)
    data_iter = iter(trits)

    for idx, (s, k, t, tri) in enumerate(triangles):
        if idx in fids:
            color_idx = fids[idx]
        else:
            try:
                color_idx = next(data_iter)
            except StopIteration:
                color_idx = 7  # pad white
        color = PALETTE[color_idx]
        poly = [(int(round(p[0])), int(round(p[1]))) for p in tri]
        draw.polygon(poly, fill=color)
    img.save(out_path)

# =========================================================================
# Decode
# =========================================================================
def _homography(src, dst):
    """3x3 homography mapping src (N,2) -> dst (N,2), N ≥ 4."""
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
    """Return 6 hexagon corners (x,y) in image space, ordered by angle from center."""
    arr = np.asarray(img.convert("RGB"), dtype=np.int16)
    mx = arr.max(axis=2); mn = arr.min(axis=2); sat = mx - mn
    mask = (sat > 80) | (mx < 80)
    ys, xs = np.where(mask)
    if len(ys) < 100:
        raise ValueError("No code found in image")
    # Use 6 direction extremes (angles for pointy-top hexagon corners).
    corners = []
    for deg in (30, 90, 150, 210, 270, 330):
        th = math.radians(deg)
        # Image y is flipped vs. mathematical y, so use -sin.
        proj = xs * math.cos(th) - ys * math.sin(th)
        i = int(np.argmax(proj))
        corners.append((float(xs[i]), float(ys[i])))
    return corners

def decode_image(path: str) -> str:
    img = Image.open(path)
    arr = np.asarray(img.convert("RGB"), dtype=np.float32)
    H_img, W_img = arr.shape[:2]

    img_corners = _find_hex_corners(img)

    # Canonical space: unit hexagon centered at origin.
    R_can = 200.0
    canon_corners = []
    for s in range(6):
        a = math.radians(30 + s * 60)
        canon_corners.append((R_can * math.cos(a), -R_can * math.sin(a)))
    triangles_canon = all_triangles(0.0, 0.0, R_can)
    fids = fiducial_map()

    # Precompute canonical centroids for fast sampling.
    centroids_canon = np.array([
        [sum(p[0] for p in tri)/3, sum(p[1] for p in tri)/3]
        for (_s, _k, _t, tri) in triangles_canon
    ])

    best_score = -1
    best_classes = None

    # Try all 6 rotational alignments (which image corner is canonical corner 0).
    for rot in range(6):
        rolled = img_corners[rot:] + img_corners[:rot]
        try:
            H_canon_to_img = _homography(canon_corners, rolled)
        except Exception:
            continue
        # Sample each triangle's centroid — average a small 3x3 window.
        samples = np.zeros((N_MODULES, 3), dtype=np.float32)
        for k in range(N_MODULES):
            cx_c, cy_c = centroids_canon[k]
            ix, iy = _warp(H_canon_to_img, cx_c, cy_c)
            acc = np.zeros(3, dtype=np.float32); cnt = 0
            for dy in (-1, 0, 1):
                for dx in (-1, 0, 1):
                    jx, jy = int(round(ix)) + dx, int(round(iy)) + dy
                    if 0 <= jx < W_img and 0 <= jy < H_img:
                        acc += arr[jy, jx]; cnt += 1
            samples[k] = acc / max(cnt, 1)
        # Per-channel threshold from fiducial samples.
        ch_lo = [[], [], []]; ch_hi = [[], [], []]
        for idx, color_idx in fids.items():
            for ch in range(3):
                bit = (color_idx >> (2 - ch)) & 1
                (ch_hi if bit else ch_lo)[ch].append(samples[idx, ch])
        try:
            thr = [(float(np.mean(ch_hi[ch])) + float(np.mean(ch_lo[ch]))) / 2
                   for ch in range(3)]
        except Exception:
            continue
        # Classify.
        classes = []
        for k in range(N_MODULES):
            idx = 0
            for ch in range(3):
                if samples[k, ch] > thr[ch]:
                    idx |= (1 << (2 - ch))
            classes.append(idx)
        score = sum(1 for i, c in fids.items() if classes[i] == c)
        if score > best_score:
            best_score = score
            best_classes = classes

    if best_classes is None:
        raise ValueError("Could not orient hexagon")
    if best_score < 20:
        print(f"[warn] low fiducial score ({best_score}/{N_FIDUCIAL})", file=sys.stderr)

    # Extract data trits in canonical order, skipping fiducials.
    data_trits = [c for i, c in enumerate(best_classes) if i not in fids]
    data_trits = data_trits[:TRITS_NEEDED]
    coded = trits_to_bytes(data_trits, TOTAL_BYTES)
    payload = rs_decode(coded, ECC_BYTES)
    n_symbols = (payload[0] << 8) | payload[1]
    packed = payload[2:2 + ((n_symbols * 6 + 7) // 8)]
    symbols = unpack6(packed, n_symbols)
    return decompress(symbols)

# =========================================================================
# Demo / CLI
# =========================================================================
def _demo():
    urls = [
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        "https://www.apple.com/mx/iphone-15/",
        "https://github.com/anthropics/claude-code",
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
        # Noisy round-trip: flip 20 random triangles.
        rng = random.Random(abs(hash(url)) % 10000)
        img = Image.open(path).convert("RGB")
        arr = np.array(img)
        H_img, W_img = arr.shape[:2]
        R = W_img * 0.45
        cx, cy = W_img / 2, H_img / 2
        triangles = all_triangles(cx, cy, R)
        fids = fiducial_map()
        flippable = [i for i in range(N_MODULES) if i not in fids]
        for idx in rng.sample(flippable, 20):
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
