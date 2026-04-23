"use client";

// Shared Pyodide loader. Loads once, installs reedsolo via micropip,
// and executes BOTH codec variants (square + hex) into separate
// Python namespaces so they don't clobber each other's globals.

declare global {
  interface Window {
    loadPyodide?: (opts?: any) => Promise<any>;
    __webcodePyodide?: Promise<any>;
  }
}

const PYODIDE_URL = "https://cdn.jsdelivr.net/pyodide/v0.26.4/full/pyodide.js";
const INDEX_URL = "https://cdn.jsdelivr.net/pyodide/v0.26.4/full/";

import { webcodePySrc, webcodeHexPySrc } from "./webcode-src";

export type Variant = "square" | "hex";

export function loadWebcodeRuntime(): Promise<any> {
  if (typeof window === "undefined") return Promise.reject(new Error("SSR"));
  if (window.__webcodePyodide) return window.__webcodePyodide;

  window.__webcodePyodide = (async () => {
    if (!window.loadPyodide) {
      await new Promise<void>((res, rej) => {
        const s = document.createElement("script");
        s.src = PYODIDE_URL;
        s.onload = () => res();
        s.onerror = () => rej(new Error("Failed to load Pyodide"));
        document.head.appendChild(s);
      });
    }
    const py = await window.loadPyodide!({ indexURL: INDEX_URL });
    await py.loadPackage(["numpy", "Pillow", "micropip"]);
    await py.runPythonAsync(`
import micropip
await micropip.install("reedsolo")
`);
    py.globals.set("_wc_sq_src", webcodePySrc);
    py.globals.set("_wc_hex_src", webcodeHexPySrc);
    py.runPython(`
sq_ns = {"__name__": "webcode_sq"}
hex_ns = {"__name__": "webcode_hex"}
exec(_wc_sq_src, sq_ns)
exec(_wc_hex_src, hex_ns)

def wc_encode(url, path, variant):
    mod = sq_ns if variant == "square" else hex_ns
    return mod["encode_url"](url, path)

def wc_hex_colors(url):
    return hex_ns["encode_url_to_colors"](url)

def wc_decode(path, variant):
    mod = sq_ns if variant == "square" else hex_ns
    return mod["decode_image"](path)

def wc_decode_auto(path):
    errs = []
    for name, mod in (("hex", hex_ns), ("square", sq_ns)):
        try:
            return mod["decode_image"](path), name
        except Exception as e:
            errs.append(f"{name}: {e}")
    raise ValueError("; ".join(errs))
`);
    return py;
  })();
  return window.__webcodePyodide;
}
