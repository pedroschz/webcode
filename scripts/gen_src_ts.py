#!/usr/bin/env python3
"""Regenerate app/webcode-src.ts from the two .py codec files.

Run this whenever webcode.py or webcode_hex.py changes:

    python3 scripts/gen_src_ts.py
"""
import json, pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC_SQ = (ROOT / "webcode.py").read_text()
SRC_HEX = (ROOT / "webcode_hex.py").read_text()

out = (
    "// AUTO-GENERATED from webcode.py / webcode_hex.py — do not edit by hand.\n"
    "// Regenerate with: python3 scripts/gen_src_ts.py\n\n"
    f"export const webcodePySrc: string = {json.dumps(SRC_SQ)};\n\n"
    f"export const webcodeHexPySrc: string = {json.dumps(SRC_HEX)};\n"
)
(ROOT / "app" / "webcode-src.ts").write_text(out)
print(f"Wrote app/webcode-src.ts ({len(SRC_SQ)} + {len(SRC_HEX)} bytes)")
