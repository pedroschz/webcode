"use client";

// Shared Pyodide loader. Loads once, installs reedsolo via micropip,
// fetches /webcode.py from /public, and executes it to define encode/decode.

declare global {
  interface Window {
    loadPyodide?: (opts?: any) => Promise<any>;
    __webcodePyodide?: Promise<any>;
  }
}

const PYODIDE_URL = "https://cdn.jsdelivr.net/pyodide/v0.26.4/full/pyodide.js";
const INDEX_URL = "https://cdn.jsdelivr.net/pyodide/v0.26.4/full/";

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
    const src = await fetch("/webcode.py").then((r) => {
      if (!r.ok) throw new Error("Failed to fetch webcode.py");
      return r.text();
    });
    py.runPython(src);
    return py;
  })();
  return window.__webcodePyodide;
}
