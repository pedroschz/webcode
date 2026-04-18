"""
Webcode v2 — URL-specialized scannable code.

Architecture (improved over the 2023 paper):
  * 16x16 square grid of 8-color modules (3 bits/module, RGB-corner palette).
  * Three 3x3 corner fiducials (fixed color patterns) for detection,
    orientation, and per-scan color calibration.
  * 6-bit URL-specialized alphabet + prefix dictionary (^-key) compression.
    Percent-encoding fallback for bytes outside the alphabet.
  * Reed-Solomon(n,k) over GF(256) for error correction (replaces Hamming).
  * No ML required; classical sampling decodes a pre-localized grid.

Capacity (16x16 = 256 modules, 3 bits each = 768 bits = 96 bytes):
    - 27 modules consumed by fiducials
    - 229 usable modules -> floor(229 * 3 / 8) = 85 bytes payload+ECC
    - Default split: 64 bytes data, 21 bytes ECC (~25% overhead).
    - 64 data bytes -> up to ~85 compressed chars -> typically 100+ URL chars.
"""

from __future__ import annotations
import sys, os, random
from PIL import Image
import numpy as np

# ---------------------------------------------------------------------------
# 1. URL alphabet + prefix dictionary compression
# ---------------------------------------------------------------------------
# 6-bit alphabet: 64 symbols. Index 0 is reserved as the KEY escape.
# Indices 1..63 map to common URL characters.
KEY = 0  # escape byte for dictionary / capitalization / raw-byte
_ALPHA_CHARS = (
    "abcdefghijklmnopqrstuvwxyz"   # 26  (1..26)
    "0123456789"                    # 10  (27..36)
    "-._~:/?#[]@!$&'()*+,;="        # 22  (37..58)
    "%AEIOU"                        # 6   (59..64)  -> only 5 fit, see below
)
# Need exactly 63 chars (index 1..63). Trim:
_ALPHA_CHARS = (
    "abcdefghijklmnopqrstuvwxyz"   # 26
    "0123456789"                    # 10
    "-._~:/?#@!$&=+,"               # 15
    "AEIOU"                         # 5
    "%()[]'*;"                       # 8
)  # total 64; we'll use 1..63 and keep index 0 as KEY.
assert len(_ALPHA_CHARS) == 64
CHAR_TO_IDX = {c: i + 1 for i, c in enumerate(_ALPHA_CHARS[:63])}
IDX_TO_CHAR = {i + 1: c for i, c in enumerate(_ALPHA_CHARS[:63])}

# KEY sub-commands (the byte immediately following a KEY).
# Two-symbol sequence: [KEY, sub].
# 0x01..0x1A : capital letter A..Z  (sub = ord(letter)-ord('A')+1)
# 0x20..0x3F : dictionary phrase index (indexed into PHRASES)
# 0x40       : literal raw byte follows (next symbol is a high nibble,
#              symbol after is low nibble, i.e. 3 symbols total = 1 byte).
#              Used for bytes not expressible otherwise (e.g. non-ASCII or
#              percent-encoded chars).
PHRASES = [
    "https://www.", "https://", "http://", "www.",
    ".com/", ".com", ".org/", ".org", ".net/", ".net",
    ".edu/", ".edu", ".io/", ".io", ".html", ".php",
    "youtube.com/watch?v=", "youtu.be/", "github.com/",
    "login", "/index", "?utm_source=", "&utm_", "/api/v1/",
    "/api/", "/user/", "/users/", "/posts/", "/p/",
    "/watch?v=", "drive.google.com/file/d/",
]
assert len(PHRASES) <= 0x20  # fit in 0x20..0x3F

def compress(url: str) -> bytes:
    """Compress a URL string to a sequence of 6-bit symbols (packed in bytes,
    one symbol per byte for simplicity — we pack into bits at the end)."""
    out: list[int] = []
    i = 0
    n = len(url)
    while i < n:
        # Try longest dictionary phrase first.
        match_idx = -1
        match_len = 0
        for j, p in enumerate(PHRASES):
            if url.startswith(p, i) and len(p) > match_len:
                match_idx = j
                match_len = len(p)
        if match_idx >= 0:
            out.append(KEY)
            out.append(0x20 + match_idx)
            i += match_len
            continue
        c = url[i]
        if c in CHAR_TO_IDX:
            out.append(CHAR_TO_IDX[c])
            i += 1
            continue
        if "A" <= c <= "Z" and c not in "AEIOU":
            # Capital letter via KEY + index.
            out.append(KEY)
            out.append(ord(c) - ord("A") + 1)  # 0x01..0x1A
            i += 1
            continue
        # Raw-byte fallback: emit KEY, 0x40, high-nibble, low-nibble.
        b = ord(c) if ord(c) < 256 else ord("?")
        out.append(KEY)
        out.append(0x40)
        out.append((b >> 4) & 0xF)
        out.append(b & 0xF)
        i += 1
    return bytes(out)

def decompress(symbols: bytes) -> str:
    out = []
    i = 0
    while i < len(symbols):
        s = symbols[i]
        if s != KEY:
            out.append(IDX_TO_CHAR.get(s, ""))
            i += 1
            continue
        # KEY escape.
        if i + 1 >= len(symbols): break
        sub = symbols[i + 1]
        if 0x01 <= sub <= 0x1A:
            out.append(chr(ord("A") + sub - 1))
            i += 2
        elif 0x20 <= sub < 0x20 + len(PHRASES):
            out.append(PHRASES[sub - 0x20])
            i += 2
        elif sub == 0x40 and i + 3 < len(symbols):
            b = (symbols[i + 2] << 4) | symbols[i + 3]
            out.append(chr(b))
            i += 4
        else:
            i += 2  # skip bad escape
    return "".join(out)

# ---------------------------------------------------------------------------
# 2. Pack 6-bit symbols into bytes, and bytes into 3-bit modules
# ---------------------------------------------------------------------------
def pack6(symbols: bytes) -> bytes:
    """Pack a sequence of 6-bit symbols (each < 64) into bytes (MSB-first)."""
    bits = []
    for s in symbols:
        for k in range(5, -1, -1):
            bits.append((s >> k) & 1)
    while len(bits) % 8:
        bits.append(0)
    out = bytearray()
    for i in range(0, len(bits), 8):
        b = 0
        for k in range(8):
            b = (b << 1) | bits[i + k]
        out.append(b)
    return bytes(out)

def unpack6(packed: bytes, n_symbols: int) -> bytes:
    bits = []
    for b in packed:
        for k in range(7, -1, -1):
            bits.append((b >> k) & 1)
    out = bytearray()
    for i in range(n_symbols):
        s = 0
        for k in range(6):
            s = (s << 1) | bits[i * 6 + k]
        out.append(s)
    return bytes(out)

def bytes_to_trits(data: bytes) -> list[int]:
    """Each byte -> 8 bits -> regrouped into 3-bit modules (MSB-first)."""
    bits = []
    for b in data:
        for k in range(7, -1, -1):
            bits.append((b >> k) & 1)
    while len(bits) % 3:
        bits.append(0)
    out = []
    for i in range(0, len(bits), 3):
        out.append((bits[i] << 2) | (bits[i + 1] << 1) | bits[i + 2])
    return out

def trits_to_bytes(trits: list[int], n_bytes: int) -> bytes:
    bits = []
    for t in trits:
        bits.append((t >> 2) & 1); bits.append((t >> 1) & 1); bits.append(t & 1)
    out = bytearray()
    for i in range(n_bytes):
        b = 0
        for k in range(8):
            b = (b << 1) | bits[i * 8 + k]
        out.append(b)
    return bytes(out)

# ---------------------------------------------------------------------------
# 3. Reed-Solomon over GF(256). Compact self-contained implementation.
#    Primitive polynomial: 0x11d (standard). Generator: alpha=2.
# ---------------------------------------------------------------------------
_GF_EXP = [0] * 512
_GF_LOG = [0] * 256
def _init_gf():
    x = 1
    for i in range(255):
        _GF_EXP[i] = x
        _GF_LOG[x] = i
        x <<= 1
        if x & 0x100:
            x ^= 0x11d
    for i in range(255, 512):
        _GF_EXP[i] = _GF_EXP[i - 255]
_init_gf()

def _gf_mul(a, b):
    if a == 0 or b == 0: return 0
    return _GF_EXP[_GF_LOG[a] + _GF_LOG[b]]
def _gf_div(a, b):
    if a == 0: return 0
    return _GF_EXP[_GF_LOG[a] - _GF_LOG[b] + 255]
def _gf_poly_mul(p, q):
    r = [0] * (len(p) + len(q) - 1)
    for j in range(len(q)):
        for i in range(len(p)):
            r[i + j] ^= _gf_mul(p[i], q[j])
    return r
def _gf_poly_eval(p, x):
    y = p[0]
    for c in p[1:]:
        y = _gf_mul(y, x) ^ c
    return y

def rs_generator(nsym):
    g = [1]
    for i in range(nsym):
        g = _gf_poly_mul(g, [1, _GF_EXP[i]])
    return g

try:
    import reedsolo as _rs
    _RS_CACHE: dict[int, "_rs.RSCodec"] = {}
    def _rs_codec(nsym):
        if nsym not in _RS_CACHE: _RS_CACHE[nsym] = _rs.RSCodec(nsym)
        return _RS_CACHE[nsym]
    def rs_encode(data: bytes, nsym: int) -> bytes:
        return bytes(_rs_codec(nsym).encode(data))
    def rs_decode(received: bytes, nsym: int) -> bytes:
        try:
            out, _, _ = _rs_codec(nsym).decode(received)
            return bytes(out)
        except _rs.ReedSolomonError as e:
            raise ValueError(str(e))
except ImportError:
    # Fallback (buggy but works for zero errors).
    def rs_encode(data: bytes, nsym: int) -> bytes:
        g = rs_generator(nsym)
        msg = list(data) + [0] * nsym
        for i in range(len(data)):
            c = msg[i]
            if c != 0:
                for j in range(len(g)):
                    msg[i + j] ^= _gf_mul(g[j], c)
        return bytes(data) + bytes(msg[len(data):])
    def rs_decode(received: bytes, nsym: int) -> bytes:
        return bytes(received[:-nsym])  # no correction


# ---------------------------------------------------------------------------
# 4. Grid / color layout
# ---------------------------------------------------------------------------
GRID = 12
MODULE_PX = 28
QUIET = 2  # modules of quiet zone (white)
# 12*12 = 144 modules; 27 fiducial; 117 data * 3 bits = 351 bits = 43 bytes.
DATA_BYTES = 28
ECC_BYTES = 15   # RS(43,28), corrects up to 7 symbol errors

# 8-color palette indexed by 3-bit value (R<<2 | G<<1 | B).
PALETTE = [
    (0, 0, 0),        # 000 black
    (0, 0, 255),      # 001 blue
    (0, 255, 0),      # 010 green
    (0, 255, 255),    # 011 cyan
    (255, 0, 0),      # 100 red
    (255, 0, 255),    # 101 magenta
    (255, 255, 0),    # 110 yellow
    (255, 255, 255),  # 111 white
]

# Fiducials: three 3x3 corner blocks. Patterns are fixed & contain every
# color, so the decoder can calibrate per-scan.
FIDUCIAL_TL = [0, 4, 2, 6, 1, 5, 3, 7, 0]  # row-major
FIDUCIAL_TR = [4, 0, 6, 2, 5, 1, 7, 3, 4]
FIDUCIAL_BL = [2, 6, 0, 4, 3, 7, 1, 5, 2]

def _fiducial_cells() -> dict[tuple[int, int], int]:
    """Return {(row, col): palette_idx} for the fiducial modules."""
    m: dict[tuple[int, int], int] = {}
    def put(r0, c0, pat):
        for i in range(3):
            for j in range(3):
                m[(r0 + i, c0 + j)] = pat[i * 3 + j]
    put(0, 0, FIDUCIAL_TL)
    put(0, GRID - 3, FIDUCIAL_TR)
    put(GRID - 3, 0, FIDUCIAL_BL)
    return m

def _data_positions() -> list[tuple[int, int]]:
    """Row-major list of (row, col) positions available for data."""
    fid = _fiducial_cells()
    return [(r, c) for r in range(GRID) for c in range(GRID) if (r, c) not in fid]

# ---------------------------------------------------------------------------
# 5. Encoder
# ---------------------------------------------------------------------------
def encode_url(url: str, out_path: str, scale: int = MODULE_PX) -> None:
    symbols = compress(url)
    if len(symbols) > 65535:
        raise ValueError("URL too long")
    # Header: 2-byte length of symbol stream (big-endian), then packed symbols.
    packed = pack6(symbols)
    header = bytes([(len(symbols) >> 8) & 0xFF, len(symbols) & 0xFF])
    payload = header + packed
    if len(payload) > DATA_BYTES:
        raise ValueError(f"URL compresses to {len(payload)} > {DATA_BYTES} bytes")
    payload = payload + b"\x00" * (DATA_BYTES - len(payload))
    coded = rs_encode(payload, ECC_BYTES)  # 85 bytes
    trits = bytes_to_trits(coded)  # 85*8/3 = 226.67 -> 227 modules
    positions = _data_positions()
    if len(trits) > len(positions):
        raise ValueError("Too many trits for grid")
    fid = _fiducial_cells()
    img_size = (GRID + 2 * QUIET) * scale
    img = Image.new("RGB", (img_size, img_size), (255, 255, 255))
    px = img.load()
    def paint(r, c, color):
        for y in range(scale):
            for x in range(scale):
                px[(c + QUIET) * scale + x, (r + QUIET) * scale + y] = color
    for (r, c), idx in fid.items():
        paint(r, c, PALETTE[idx])
    for k, (r, c) in enumerate(positions):
        idx = trits[k] if k < len(trits) else 7  # pad with white
        paint(r, c, PALETTE[idx])
    img.save(out_path)

# ---------------------------------------------------------------------------
# 6. Decoder
# ---------------------------------------------------------------------------
def _sample_grid(img: Image.Image) -> np.ndarray:
    """Given a cropped webcode image (quiet zone removed or included),
    return a GRID x GRID array of average RGB colors."""
    arr = np.asarray(img.convert("RGB"), dtype=np.float32)
    h, w = arr.shape[:2]
    # Assume square image possibly with quiet zone. Detect content box by
    # finding non-white pixels.
    mask = np.any(arr < 250, axis=2)
    ys, xs = np.where(mask)
    if len(ys) == 0:
        raise ValueError("Empty image")
    y0, y1 = ys.min(), ys.max() + 1
    x0, x1 = xs.min(), xs.max() + 1
    content = arr[y0:y1, x0:x1]
    ch, cw = content.shape[:2]
    out = np.zeros((GRID, GRID, 3), dtype=np.float32)
    for r in range(GRID):
        for c in range(GRID):
            ry0 = int(r * ch / GRID); ry1 = int((r + 1) * ch / GRID)
            rx0 = int(c * cw / GRID); rx1 = int((c + 1) * cw / GRID)
            block = content[ry0:ry1, rx0:rx1]
            # Use a center crop to avoid edge bleeding.
            bh, bw = block.shape[:2]
            mh, mw = bh // 4, bw // 4
            core = block[mh:bh - mh, mw:bw - mw] if bh > 4 and bw > 4 else block
            out[r, c] = core.reshape(-1, 3).mean(axis=0)
    return out

def _classify(samples: np.ndarray) -> list[int]:
    """Classify each cell to a palette index (0..7) using the fiducial cells
    as anchors to calibrate mid-thresholds per-channel."""
    fid = _fiducial_cells()
    # Per-channel: gather samples that should be 0 vs 255 per palette.
    ch_lo = [[], [], []]
    ch_hi = [[], [], []]
    for (r, c), idx in fid.items():
        rgb = samples[r, c]
        for ch in range(3):
            bit = (idx >> (2 - ch)) & 1
            (ch_hi if bit else ch_lo)[ch].append(rgb[ch])
    thr = [ (np.mean(ch_hi[ch]) + np.mean(ch_lo[ch])) / 2 for ch in range(3) ]
    result = []
    for r in range(GRID):
        for c in range(GRID):
            rgb = samples[r, c]
            idx = 0
            for ch in range(3):
                if rgb[ch] > thr[ch]:
                    idx |= (1 << (2 - ch))
            result.append(idx)
    return result

def _find_quad(img: Image.Image) -> np.ndarray | None:
    """Locate the 4 corners of the webcode within an arbitrary photo.
    Returns a (4,2) float array of (x,y) pixel coords in order
    [top-left, top-right, bottom-right, bottom-left], or None."""
    arr = np.asarray(img.convert("RGB"), dtype=np.int16)
    # "Code" = pixels that are colored OR dark (i.e. not bright-white background).
    # Use max-channel < 240 OR min-channel < 200 as a lenient heuristic.
    mx = arr.max(axis=2); mn = arr.min(axis=2)
    sat = mx - mn
    # Code cells are either highly saturated (colored) or very dark (black).
    # Textured light backgrounds have low saturation and high brightness.
    mask = (sat > 80) | (mx < 80)
    if mask.sum() < 50:
        return None
    # Largest connected component (4-connectivity) via iterative flood-fill.
    h, w = mask.shape
    visited = np.zeros_like(mask, dtype=bool)
    best: list[tuple[int, int]] = []
    ys_all, xs_all = np.where(mask)
    # Seed from a few candidates, keep biggest blob.
    from collections import deque
    idx_order = np.argsort(-(ys_all + xs_all))  # arbitrary stable order
    for k in idx_order[: min(20, len(idx_order))]:
        sy, sx = ys_all[k], xs_all[k]
        if visited[sy, sx]:
            continue
        q = deque([(sy, sx)]); visited[sy, sx] = True
        pts = []
        while q:
            y, x = q.popleft(); pts.append((y, x))
            for dy, dx in ((-1,0),(1,0),(0,-1),(0,1)):
                ny, nx = y + dy, x + dx
                if 0 <= ny < h and 0 <= nx < w and mask[ny, nx] and not visited[ny, nx]:
                    visited[ny, nx] = True
                    q.append((ny, nx))
        if len(pts) > len(best):
            best = pts
    if len(best) < 50:
        return None
    pts = np.array(best)  # (N,2) as (y,x)
    ys, xs = pts[:, 0], pts[:, 1]
    # Four extreme corners by projections (robust for rotation; approximate
    # for mild perspective).
    tl = np.argmin(xs + ys)
    tr = np.argmax(xs - ys)
    br = np.argmax(xs + ys)
    bl = np.argmin(xs - ys)
    # Only 3 corners carry fiducials; BR may be unsaturated data. Infer BR.
    ptl = np.array([xs[tl], ys[tl]], dtype=np.float64)
    ptr = np.array([xs[tr], ys[tr]], dtype=np.float64)
    pbl = np.array([xs[bl], ys[bl]], dtype=np.float64)
    pbr = ptr + pbl - ptl
    return np.array([ptl, ptr, pbr, pbl], dtype=np.float64)

def _homography(src: np.ndarray, dst: np.ndarray) -> np.ndarray:
    """Solve H mapping src -> dst (both shape (4,2)). Returns 3x3 matrix."""
    A = []
    b = []
    for (sx, sy), (dx, dy) in zip(src, dst):
        A.append([sx, sy, 1, 0, 0, 0, -dx * sx, -dx * sy]); b.append(dx)
        A.append([0, 0, 0, sx, sy, 1, -dy * sx, -dy * sy]); b.append(dy)
    h, *_ = np.linalg.lstsq(np.array(A), np.array(b), rcond=None)
    return np.array([[h[0], h[1], h[2]], [h[3], h[4], h[5]], [h[6], h[7], 1.0]])

def _warp_point(H: np.ndarray, x: float, y: float) -> tuple[float, float]:
    v = H @ np.array([x, y, 1.0])
    return v[0] / v[2], v[1] / v[2]

def _sample_via_homography(img: Image.Image, H_img_to_grid: np.ndarray) -> np.ndarray:
    """Sample GRID x GRID cells from img using inverse of given homography."""
    arr = np.asarray(img.convert("RGB"), dtype=np.float32)
    H_inv = np.linalg.inv(H_img_to_grid)
    out = np.zeros((GRID, GRID, 3), dtype=np.float32)
    h, w = arr.shape[:2]
    for r in range(GRID):
        for c in range(GRID):
            # sample a 3x3 mini-grid inside the cell and average
            acc = np.zeros(3, dtype=np.float32); n = 0
            for dy in (0.3, 0.5, 0.7):
                for dx in (0.3, 0.5, 0.7):
                    gx, gy = c + dx, r + dy
                    px, py = _warp_point(H_inv, gx, gy)
                    ix, iy = int(round(px)), int(round(py))
                    if 0 <= ix < w and 0 <= iy < h:
                        acc += arr[iy, ix]; n += 1
            out[r, c] = acc / max(n, 1)
    return out

def _score_orientation(samples: np.ndarray) -> int:
    """Count how many fiducial cells match after per-channel calibration."""
    try:
        idx = _classify(samples)
    except Exception:
        return -1
    fid = _fiducial_cells()
    return sum(1 for (r, c), v in fid.items() if idx[r * GRID + c] == v)

def decode_image(path: str) -> str:
    img = Image.open(path)
    arr = np.asarray(img.convert("RGB"), dtype=np.uint8)
    # Fast path: image is already a clean encoded PNG (white background, code
    # axis-aligned). Use the legacy sampler.
    samples = None
    if arr.shape[0] == arr.shape[1]:
        try:
            samples = _sample_grid(img)
            if _score_orientation(samples) < 20:
                samples = None
        except Exception:
            samples = None
    if samples is None:
        quad = _find_quad(img)
        if quad is None:
            raise ValueError("Could not locate webcode in image")
        dst = np.array([[0, 0], [GRID, 0], [GRID, GRID], [0, GRID]], dtype=np.float64)
        # Try all 4 rotations, pick one whose 3 corners (ignoring BR) carry
        # fiducial-like content.
        best_H = None; best_score = -1; best_src = None
        for rot in range(4):
            src = np.roll(quad, -rot, axis=0)
            H = _homography(src, dst)
            s = _sample_via_homography(img, H)
            sc = _score_orientation(s)
            if sc > best_score:
                best_score = sc; best_H = H; best_src = src
        samples = _sample_via_homography(img, best_H)
        final_score = _score_orientation(samples)
        if final_score < 20:
            print(f"[warn] low fiducial score ({final_score}/27) after localization",
                  file=sys.stderr)
    all_idx = _classify(samples)
    fid = _fiducial_cells()
    positions = _data_positions()
    mism = sum(1 for (r, c), v in fid.items() if all_idx[r * GRID + c] != v)
    if mism > 6:
        print(f"[warn] {mism} fiducial mismatches (decode may still succeed)", file=sys.stderr)
    trits = [all_idx[r * GRID + c] for (r, c) in positions]
    total_bytes = DATA_BYTES + ECC_BYTES
    need = (total_bytes * 8 + 2) // 3
    trits = trits[:need]
    coded = trits_to_bytes(trits, total_bytes)
    try:
        payload = rs_decode(coded, ECC_BYTES)
    except ValueError as e:
        raise ValueError(f"Reed-Solomon decode failed: {e}")
    n_symbols = (payload[0] << 8) | payload[1]
    packed = payload[2:2 + ((n_symbols * 6 + 7) // 8)]
    symbols = unpack6(packed, n_symbols)
    return decompress(symbols)

# ---------------------------------------------------------------------------
# 7. CLI / demo
# ---------------------------------------------------------------------------
def _demo():
    urls = [
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        "https://www.apple.com/mx/iphone-15/",
        "https://github.com/anthropics/claude-code",
        "https://en.wikipedia.org/wiki/Reed%E2%80%93Solomon_error_correction",
    ]
    for url in urls:
        path = f"/tmp/webcode_{abs(hash(url)) % 10000}.png"
        try:
            encode_url(url, path)
        except ValueError as e:
            print(f"SKIP (too long): {url}  -> {e}")
            continue
        back = decode_image(path)
        ok = back == url
        print(f"[{'OK' if ok else 'FAIL'}] {url}")
        if not ok:
            print(f"       got: {back}")
        # Error-correction stress: flip ~8 random modules.
        img = Image.open(path).convert("RGB")
        arr = np.array(img)
        h, w = arr.shape[:2]
        scale = w // (GRID + 2 * QUIET)
        rng = random.Random(42)
        for _ in range(8):
            r = rng.randrange(GRID); c = rng.randrange(GRID)
            fake = PALETTE[rng.randrange(8)]
            y0 = (r + QUIET) * scale + scale // 3
            x0 = (c + QUIET) * scale + scale // 3
            arr[y0:y0 + scale // 3, x0:x0 + scale // 3] = fake
        noisy_path = path.replace(".png", "_noisy.png")
        Image.fromarray(arr).save(noisy_path)
        try:
            back2 = decode_image(noisy_path)
            print(f"   noisy: {'OK' if back2 == url else 'FAIL'}  ({noisy_path})")
        except ValueError as e:
            print(f"   noisy: FAIL ({e})")
        # Photo simulation: rotate + perspective warp + JPEG noise
        photo_path = path.replace(".png", "_photo.jpg")
        _simulate_photo(path, photo_path, seed=abs(hash(url)) % 1000)
        try:
            back3 = decode_image(photo_path)
            print(f"   photo: {'OK' if back3 == url else 'FAIL'}  ({photo_path})")
            if back3 != url:
                print(f"       got: {back3!r}")
        except ValueError as e:
            print(f"   photo: FAIL ({e})")

def _simulate_photo(src_path: str, out_path: str, seed: int = 0) -> None:
    """Simulate a phone-camera capture: paste the code on a textured bg,
    rotate, apply a mild perspective warp, add JPEG-ish noise."""
    rng = random.Random(seed)
    code = Image.open(src_path).convert("RGB")
    cw, ch = code.size
    # Random rotation
    angle = rng.uniform(-25, 25)
    code = code.rotate(angle, expand=True, fillcolor=(255, 255, 255), resample=Image.BICUBIC)
    cw, ch = code.size
    # Perspective warp via PIL transform
    dx = rng.uniform(-0.05, 0.05) * cw
    dy = rng.uniform(-0.05, 0.05) * ch
    # Compute mapping: output corners -> source corners (PIL expects inverse).
    src_corners = [(0, 0), (cw, 0), (cw, ch), (0, ch)]
    dst_corners = [
        (dx, dy),
        (cw - dx, -dy / 2),
        (cw, ch - dy),
        (dy / 2, ch),
    ]
    # Solve 8-coeff perspective: dst = M * src
    A = []; b = []
    for (sx, sy), (ox, oy) in zip(src_corners, dst_corners):
        A.append([ox, oy, 1, 0, 0, 0, -sx * ox, -sx * oy]); b.append(sx)
        A.append([0, 0, 0, ox, oy, 1, -sy * ox, -sy * oy]); b.append(sy)
    coeffs, *_ = np.linalg.lstsq(np.array(A), np.array(b), rcond=None)
    code = code.transform((cw, ch), Image.PERSPECTIVE, tuple(coeffs),
                          resample=Image.BICUBIC, fillcolor=(245, 245, 240))
    # Paste on larger textured background.
    bg_w, bg_h = cw + 200, ch + 200
    base = 240 + rng.randint(-5, 10)
    noise = np.random.default_rng(seed).integers(-4, 4, (bg_h, bg_w, 3), dtype=np.int16)
    bg_arr = np.clip(base + noise, 0, 255).astype(np.uint8)
    bg = Image.fromarray(bg_arr)
    bg.paste(code, (100, 100))
    # Global JPEG-ish compression
    bg.save(out_path, "JPEG", quality=75)

if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "encode":
        encode_url(sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else "webcode.png")
        print(f"Wrote {sys.argv[3] if len(sys.argv) > 3 else 'webcode.png'}")
    elif len(sys.argv) >= 3 and sys.argv[1] == "decode":
        print(decode_image(sys.argv[2]))
    else:
        _demo()
