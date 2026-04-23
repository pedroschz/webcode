"use client";

import { useEffect, useRef, useState } from "react";
import { loadWebcodeRuntime, type Variant } from "./pyodide-runtime";
import { HexRenderer, type RGB } from "./HexRenderer";

type Status = "loading" | "ready" | "error";

export default function Home() {
  const [status, setStatus] = useState<Status>("loading");
  const [err, setErr] = useState<string>("");
  const [variant, setVariant] = useState<Variant>("square");
  const pyRef = useRef<any>(null);

  useEffect(() => {
    loadWebcodeRuntime()
      .then((py) => {
        pyRef.current = py;
        setStatus("ready");
      })
      .catch((e) => {
        setErr(String(e));
        setStatus("error");
      });
  }, []);

  return (
    <main style={{ maxWidth: 880, margin: "0 auto", padding: "40px 24px 80px" }}>
      <header style={{ marginBottom: 32 }}>
        <h1 style={{ fontSize: 34, margin: 0, letterSpacing: -0.5 }}>Webcode</h1>
        <p style={{ color: "#555", marginTop: 6, marginBottom: 0 }}>
          URL-specialized scannable codes. 8-color palette, 6-bit URL alphabet,
          Reed&ndash;Solomon ECC. Generate one or decode an image.
        </p>
        <p style={{ color: "#888", fontSize: 13, marginTop: 8 }}>
          Runtime: {status === "loading" && "loading Python…"}
          {status === "ready" && <span style={{ color: "#0a7" }}>ready</span>}
          {status === "error" && <span style={{ color: "#c33" }}>error: {err}</span>}
        </p>
      </header>

      <VariantTabs value={variant} onChange={setVariant} />
      <div style={{ height: 16 }} />

      <GeneratePanel pyRef={pyRef} ready={status === "ready"} variant={variant} />
      <div style={{ height: 40 }} />
      <DecodePanel pyRef={pyRef} ready={status === "ready"} />

      <footer style={{ marginTop: 64, color: "#999", fontSize: 12, textAlign: "center" }}>
        Based on the 2023 paper &ldquo;Decoding Efficiency: The Next Generation
        of Scannable Systems&rdquo; &mdash; architecture updated 2026. &middot;{" "}
        <a href="https://github.com/pedroschz/webcode" style={{ color: "#999" }}>
          source
        </a>
      </footer>
    </main>
  );
}

function VariantTabs({ value, onChange }: { value: Variant; onChange: (v: Variant) => void }) {
  const tab = (v: Variant, label: string, sub: string) => (
    <button
      key={v}
      onClick={() => onChange(v)}
      style={{
        flex: 1, padding: "12px 16px", textAlign: "left",
        background: value === v ? "white" : "transparent",
        border: value === v ? "1px solid #111" : "1px solid #e5e5e5",
        borderRadius: 10, cursor: "pointer",
      }}
    >
      <div style={{ fontSize: 14, fontWeight: 600 }}>{label}</div>
      <div style={{ fontSize: 12, color: "#666", marginTop: 2 }}>{sub}</div>
    </button>
  );
  return (
    <div style={{ display: "flex", gap: 8 }}>
      {tab("square", "Square 12×12", "144 modules · 28 data bytes · simpler geometry")}
      {tab("hex", "Hexagonal 216-triangle", "paper's original shape · MP alphabet · 40 data bytes")}
    </div>
  );
}

function Panel({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section style={{
      background: "white", border: "1px solid #e5e5e5", borderRadius: 12,
      padding: 24,
    }}>
      <h2 style={{ margin: 0, fontSize: 20 }}>{title}</h2>
      <div style={{ marginTop: 16 }}>{children}</div>
    </section>
  );
}

function GeneratePanel({ pyRef, ready, variant }: { pyRef: any; ready: boolean; variant: Variant }) {
  const [url, setUrl] = useState("https://github.com/pedroschz/webcode");
  const [imgSrc, setImgSrc] = useState("");
  const [hexColors, setHexColors] = useState<RGB[] | null>(null);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);

  async function generate() {
    if (!pyRef.current || busy) return;
    setBusy(true); setErr(""); setImgSrc(""); setHexColors(null);
    try {
      const py = pyRef.current;
      py.globals.set("_user_url", url);
      if (variant === "hex") {
        // SVG path: get per-triangle colors directly — no PNG round-trip.
        const json: string = py.runPython(`wc_hex_colors(_user_url)`);
        setHexColors(JSON.parse(json) as RGB[]);
      } else {
        py.globals.set("_user_variant", variant);
        py.runPython(`wc_encode(_user_url, "/tmp/_out.png", _user_variant)`);
        const bytes: Uint8Array = py.FS.readFile("/tmp/_out.png");
        const buf = new Uint8Array(bytes.byteLength);
        buf.set(bytes);
        const blob = new Blob([buf], { type: "image/png" });
        setImgSrc(URL.createObjectURL(blob));
      }
    } catch (e: any) {
      setErr(e?.message || String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Panel title="Generate">
      <div style={{ display: "flex", gap: 8 }}>
        <input
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          placeholder="https://…"
          style={{
            flex: 1, padding: "10px 12px", borderRadius: 8,
            border: "1px solid #ddd", fontSize: 14, fontFamily: "inherit",
          }}
        />
        <button
          onClick={generate}
          disabled={!ready || busy || !url}
          style={{
            padding: "10px 18px", borderRadius: 8, border: "none",
            background: ready && !busy ? "#111" : "#888", color: "white",
            fontSize: 14, cursor: ready && !busy ? "pointer" : "default",
          }}
        >
          {busy ? "Generating…" : "Generate"}
        </button>
      </div>
      {err && <p style={{ color: "#c33", fontSize: 13, marginTop: 10 }}>{err}</p>}
      {hexColors && (
        <div style={{ marginTop: 20, display: "flex", justifyContent: "center" }}>
          <HexRenderer colors={hexColors} />
        </div>
      )}
      {imgSrc && (
        <div style={{ marginTop: 20, textAlign: "center" }}>
          <img src={imgSrc} alt="webcode" style={{
            imageRendering: "pixelated",
            maxWidth: 420, width: "100%",
            border: "1px solid #eee", borderRadius: 8,
          }} />
          <div style={{ marginTop: 8 }}>
            <a href={imgSrc} download={`webcode-${variant}.png`} style={{ fontSize: 13 }}>
              Download PNG
            </a>
          </div>
        </div>
      )}
    </Panel>
  );
}

function DecodePanel({ pyRef, ready }: { pyRef: any; ready: boolean }) {
  const [result, setResult] = useState("");
  const [detected, setDetected] = useState<string>("");
  const [preview, setPreview] = useState("");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);

  async function handleFile(f: File) {
    if (!pyRef.current || busy) return;
    setBusy(true); setErr(""); setResult(""); setDetected("");
    try {
      const ab = await f.arrayBuffer();
      setPreview(URL.createObjectURL(f));
      const py = pyRef.current;
      const ext = f.name.split(".").pop()?.toLowerCase() || "png";
      const path = `/tmp/_in.${ext}`;
      py.FS.writeFile(path, new Uint8Array(ab));
      py.globals.set("_user_path", path);
      // wc_decode_auto returns (url, variant_name) as a Python tuple → PyProxy
      const tuple: any = py.runPython(`wc_decode_auto(_user_path)`);
      const url = tuple.get(0);
      const variantName = tuple.get(1);
      tuple.destroy?.();
      setResult(url);
      setDetected(variantName);
    } catch (e: any) {
      setErr(e?.message || String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Panel title="Decode">
      <p style={{ color: "#666", fontSize: 13, marginTop: 0, marginBottom: 10 }}>
        Upload any webcode image (square or hex — variant auto-detected).
      </p>
      <input
        type="file"
        accept="image/*"
        disabled={!ready || busy}
        onChange={(e) => {
          const f = e.target.files?.[0];
          if (f) handleFile(f);
        }}
        style={{ fontSize: 14 }}
      />
      <p style={{ color: "#888", fontSize: 12, marginTop: 6, marginBottom: 0 }}>
        For photos: plain background, roughly centered, mild rotation OK.
      </p>
      {preview && (
        <div style={{ marginTop: 16 }}>
          <img src={preview} alt="input" style={{
            maxWidth: 200, borderRadius: 6, border: "1px solid #eee",
          }} />
        </div>
      )}
      {busy && <p style={{ fontSize: 13, marginTop: 10 }}>Decoding…</p>}
      {err && <p style={{ color: "#c33", fontSize: 13, marginTop: 10 }}>Error: {err}</p>}
      {result && (
        <div style={{ marginTop: 16 }}>
          <div style={{ fontSize: 12, color: "#888", marginBottom: 4 }}>
            Decoded URL {detected && <span>({detected} variant)</span>}:
          </div>
          <a href={result} target="_blank" rel="noreferrer" style={{
            fontSize: 15, wordBreak: "break-all",
          }}>
            {result}
          </a>
        </div>
      )}
    </Panel>
  );
}
