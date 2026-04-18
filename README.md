# Webcode

URL-specialized scannable codes. An 8-color palette (3 bits per module) plus a 6-bit URL alphabet and prefix-dictionary compression packs more data per unit area than a QR code, for the single use case people actually scan in 2026: opening a URL.

Based on the 2023 paper [*Decoding Efficiency: The Next Generation of Scannable Systems*](https://drive.google.com/file/d/1-3EZ7VpKjN5rB6MF5F2J8wKxTcO6JOPw/view) by Pedro Sánchez-Gil Galindo. The architecture here updates the paper's proposal with modern decisions.

## What's kept from the paper

- **8-color palette (3 bits/module).** RGB corners of the color cube — maximally separable, per-scan calibration handles lighting.
- **6-bit URL alphabet + prefix dictionary.** Common phrases like `https://www.`, `.com/`, `youtu.be/`, `github.com/` collapse to two symbols via a `^`-key escape.
- **Corner fiducials** for detection, orientation, and color calibration.

## What's replaced

| Paper (2023) | Here (2026) | Why |
| --- | --- | --- |
| Hamming(128,120) + bit-padding | Reed–Solomon over GF(256) | Standard since 1960; corrects many more errors |
| Hexagonal grid of 216 triangles | 12×12 square grid | Dramatically simpler to sample/decode, same capacity |
| YOLO/CNN-based detection | Classical blob + homography | No ML needed; deterministic and instant |
| Aesthetic char↔color pairing | Dropped | Not load-bearing |
| Database-of-URL-IDs | Dropped | That's a URL shortener, not a codec feature |

## Layout

- 12×12 grid of 3-bit color modules (144 total).
- Three 3×3 corner fiducials (27 modules). Each fiducial uses all 8 palette colors so decoders can calibrate per-scan thresholds.
- 117 data modules → 43 bytes after 3-bit packing, split as **28 data + 15 ECC** via RS(43,28), correcting up to 7 byte errors.
- Data bytes: 2-byte length header + packed 6-bit symbols (compressed URL).

## Pipeline

```
URL → dictionary compress → 6-bit symbols → bytes → RS encode
    → 3-bit modules → 8-color cells → PNG
```

Decode reverses, plus: locate code in image (saturation mask + largest connected blob), infer 4th corner from the other three (BR has no fiducial), solve homography, sample each cell, calibrate per-channel color thresholds from fiducial pixels, classify.

## Usage — Python

```bash
# macOS system Python has Pillow + numpy preinstalled
/usr/bin/pip3 install --user reedsolo
/usr/bin/python3 webcode.py                                    # round-trip demo
/usr/bin/python3 webcode.py encode "https://example.com" out.png
/usr/bin/python3 webcode.py decode out.png
```

## Usage — Web app

A Next.js site under [`web/`](web/) runs the Python codec in the browser via Pyodide. Generate codes or decode uploaded images.

```bash
cd web
npm install
npm run dev
```

Open http://localhost:3000. First load fetches Pyodide + numpy + Pillow + reedsolo (~15 MB), cached afterward.

## Limits

- Max compressed URL length ≈ 43 characters. Long URLs (e.g. encoded Wikipedia slugs) will overflow — shorten first.
- Decoder is robust to rotation and mild perspective (camera from a reasonable angle). Extreme tilt or partial occlusion is out of scope.
- No live webcam capture yet — upload a photo.

## Contributing

**Webcode is open-source and contributions are genuinely welcome.** This is a first usable implementation, not a finished system — there's a lot of useful work left, and small PRs are as welcome as big ones.

Some directions that would move the project forward:

- **Live webcam decoding** in the web app (`getUserMedia` + frame loop).
- **Extreme-perspective robustness** — current decoder handles mild tilt; fixing steep angles needs either 4 real anchor points or iterative refinement against the fiducial pattern.
- **Bigger versions** (V2/V3 with 16×16 or 20×20 grids) for longer URLs, with version encoded in the format modules.
- **Masking** to avoid pathological color distributions (e.g. a mostly-white code that triggers calibration issues), analogous to QR data masks.
- **Native TypeScript port** of the codec so the web app doesn't need Pyodide (~15 MB first load).
- **Mobile apps** (iOS / Android) that decode from the camera. Native CoreImage / MLKit detectors can do the localization step far faster than the Python reference.
- **Benchmarks** vs QR across URL lengths, print sizes, lighting conditions, and scan angles.
- **Security review.** Scannable codes are a phishing vector; thinking about URL display / domain highlighting at decode time is worthwhile.

If you want to work on something, open an issue first so we can sanity-check the direction. PRs without a corresponding issue are still welcome for small fixes (typos, bugs, doc clarifications).

No CLA. By contributing you agree your changes are released under the MIT license below.

## License

MIT — see [LICENSE](LICENSE). Use it for anything, including commercially. If you build on this, a citation back to the original 2023 paper by Pedro Sánchez-Gil Galindo is appreciated but not required.
