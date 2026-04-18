"use client";

// Shared Pyodide loader. Loads once, installs reedsolo via micropip,
// and executes the bundled python code to define encode/decode.

declare global {
  interface Window {
    loadPyodide?: (opts?: any) => Promise<any>;
    __webcodePyodide?: Promise<any>;
  }
}

const PYODIDE_URL = "https://cdn.jsdelivr.net/pyodide/v0.26.4/full/pyodide.js";
const INDEX_URL = "https://cdn.jsdelivr.net/pyodide/v0.26.4/full/";

import { webcodePySrc } from "./webcode-src";

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
    py.runPython(webcodePySrc);
    return py;
  })();
  return window.__webcodePyodide;
}
