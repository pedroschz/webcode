"use client";

import { useEffect, useRef, useState } from "react";
import { loadWebcodeRuntime, type Variant } from "./pyodide-runtime";
import { HexRenderer, type RGB } from "./HexRenderer";

type Status = "loading" | "ready" | "error";

const serif = "var(--font-serif), Georgia, 'Times New Roman', serif";
const mono = "var(--font-mono), ui-monospace, monospace";

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
    <main style={{ maxWidth: 620, margin: "0 auto", padding: "96px 28px 120px" }}>
      <header>
        <h1
          style={{
            fontFamily: serif,
            fontSize: 56,
            lineHeight: 1,
            letterSpacing: "-0.02em",
            margin: 0,
            fontWeight: 400,
          }}
        >
          Webcode
        </h1>
        <p
          style={{
            fontFamily: serif,
            fontStyle: "italic",
            fontSize: 19,
            color: "var(--ink-3)",
            margin: "14px 0 0",
            lineHeight: 1.4,
            maxWidth: 480,
          }}
        >
          URL-specialized scannable codes.
        </p>
        <p
          style={{
            fontSize: 13,
            color: "var(--ink-3)",
            margin: "18px 0 0",
            maxWidth: 520,
            lineHeight: 1.6,
          }}
        >
          Eight-color palette, six-bit URL alphabet, Reed&ndash;Solomon error
          correction. Generate a code from a link, or decode one from a photo.
        </p>
      </header>

      <div style={{ height: 80 }} />

      <VariantSelector value={variant} onChange={setVariant} />
      <div style={{ height: 28 }} />

      <GeneratePanel pyRef={pyRef} ready={status === "ready"} variant={variant} />

      <div style={{ height: 96 }} />

      <DecodePanel pyRef={pyRef} ready={status === "ready"} />

      <div style={{ height: 96 }} />

      <footer
        style={{
          borderTop: "1px solid var(--line)",
          paddingTop: 20,
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          color: "var(--ink-4)",
          fontSize: 12,
          letterSpacing: "0.02em",
        }}
      >
        <StatusDot status={status} err={err} />
        <a
          href="https://github.com/pedroschz/webcode"
          className="wc-link"
          style={{ color: "var(--ink-4)", borderBottomColor: "transparent" }}
        >
          source
        </a>
      </footer>
    </main>
  );
}

function StatusDot({ status, err }: { status: Status; err: string }) {
  const color =
    status === "ready" ? "var(--ok)" : status === "error" ? "var(--err)" : "var(--ink-4)";
  const label =
    status === "ready"
      ? "ready"
      : status === "error"
      ? `error — ${err.slice(0, 60)}`
      : "loading runtime";
  return (
    <span style={{ display: "inline-flex", alignItems: "center", gap: 8 }}>
      <span
        aria-hidden
        style={{
          width: 6,
          height: 6,
          borderRadius: "50%",
          background: color,
          display: "inline-block",
          transition: "background .3s ease",
        }}
      />
      <span>{label}</span>
    </span>
  );
}

function VariantSelector({
  value,
  onChange,
}: {
  value: Variant;
  onChange: (v: Variant) => void;
}) {
  return (
    <div>
      <SectionLabel>Shape</SectionLabel>
      <div style={{ display: "flex", marginTop: 4 }}>
        <button
          className="wc-segment"
          data-active={value === "square"}
          onClick={() => onChange("square")}
        >
          Square
        </button>
        <button
          className="wc-segment"
          data-active={value === "hex"}
          onClick={() => onChange("hex")}
        >
          Hexagonal
        </button>
      </div>
      <p
        style={{
          fontSize: 12,
          color: "var(--ink-4)",
          margin: "10px 0 0",
          lineHeight: 1.5,
          fontStyle: "italic",
          fontFamily: serif,
        }}
      >
        {value === "square"
          ? "12 × 12 grid. 144 modules, 28 data bytes."
          : "216-triangle hexagon. Paper's original shape, 40 data bytes."}
      </p>
    </div>
  );
}

function GeneratePanel({
  pyRef,
  ready,
  variant,
}: {
  pyRef: any;
  ready: boolean;
  variant: Variant;
}) {
  const [url, setUrl] = useState("https://github.com/pedroschz/webcode");
  const [imgSrc, setImgSrc] = useState("");
  const [hexColors, setHexColors] = useState<RGB[] | null>(null);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);

  async function generate() {
    if (!pyRef.current || busy) return;
    setBusy(true);
    setErr("");
    setImgSrc("");
    setHexColors(null);
    try {
      const py = pyRef.current;
      py.globals.set("_user_url", url);
      if (variant === "hex") {
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

  const hasResult = imgSrc || hexColors;

  return (
    <section>
      <SectionLabel>Link</SectionLabel>
      <input
        className="wc-url-input"
        value={url}
        onChange={(e) => setUrl(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter") generate();
        }}
        placeholder="https://…"
        spellCheck={false}
        autoCapitalize="off"
        autoCorrect="off"
      />

      <div
        style={{
          display: "flex",
          justifyContent: "flex-end",
          marginTop: 20,
        }}
      >
        <button
          className="wc-btn"
          onClick={generate}
          disabled={!ready || busy || !url}
        >
          {busy ? "Generating…" : "Generate"}
        </button>
      </div>

      {err && (
        <p
          className="wc-fade-in"
          style={{ color: "var(--err)", fontSize: 13, marginTop: 16 }}
        >
          {err}
        </p>
      )}

      {hasResult && (
        <div
          className="wc-fade-in"
          style={{ marginTop: 48, display: "flex", flexDirection: "column", alignItems: "center" }}
        >
          {hexColors && <HexRenderer colors={hexColors} />}
          {imgSrc && (
            <img
              src={imgSrc}
              alt="webcode"
              style={{
                imageRendering: "pixelated",
                width: "100%",
                maxWidth: 380,
                display: "block",
              }}
            />
          )}
          <a
            href={imgSrc || undefined}
            download={imgSrc ? `webcode-${variant}.png` : undefined}
            onClick={(e) => {
              if (!imgSrc) e.preventDefault();
            }}
            className="wc-link"
            style={{
              marginTop: 28,
              fontSize: 12,
              letterSpacing: "0.06em",
              textTransform: "uppercase",
              color: imgSrc ? "var(--ink-3)" : "var(--ink-4)",
              pointerEvents: imgSrc ? "auto" : "none",
              borderBottomColor: "transparent",
            }}
          >
            {imgSrc ? "Download PNG" : "Rendered as SVG"}
          </a>
        </div>
      )}
    </section>
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
    setBusy(true);
    setErr("");
    setResult("");
    setDetected("");
    try {
      const ab = await f.arrayBuffer();
      setPreview(URL.createObjectURL(f));
      const py = pyRef.current;
      const ext = f.name.split(".").pop()?.toLowerCase() || "png";
      const path = `/tmp/_in.${ext}`;
      py.FS.writeFile(path, new Uint8Array(ab));
      py.globals.set("_user_path", path);
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
    <section>
      <SectionLabel>Or decode</SectionLabel>
      <p
        style={{
          fontFamily: serif,
          fontStyle: "italic",
          fontSize: 16,
          color: "var(--ink-3)",
          margin: "4px 0 20px",
          lineHeight: 1.4,
        }}
      >
        Upload a photo of a webcode — shape detected automatically.
      </p>

      <label className="wc-file" style={{ position: "relative" }}>
        {busy ? "Decoding…" : preview ? "Upload another" : "Choose image"}
        <input
          type="file"
          accept="image/*"
          disabled={!ready || busy}
          onChange={(e) => {
            const f = e.target.files?.[0];
            if (f) handleFile(f);
            e.currentTarget.value = "";
          }}
        />
      </label>

      {err && (
        <p
          className="wc-fade-in"
          style={{ color: "var(--err)", fontSize: 13, marginTop: 16 }}
        >
          {err}
        </p>
      )}

      {(preview || result) && (
        <div
          className="wc-fade-in"
          style={{
            marginTop: 28,
            display: "grid",
            gridTemplateColumns: "96px 1fr",
            gap: 20,
            alignItems: "start",
          }}
        >
          {preview && (
            <img
              src={preview}
              alt="input"
              style={{
                width: 96,
                height: 96,
                objectFit: "cover",
                borderRadius: 4,
                display: "block",
              }}
            />
          )}
          {result && (
            <div>
              <div
                style={{
                  fontSize: 11,
                  letterSpacing: "0.08em",
                  textTransform: "uppercase",
                  color: "var(--ink-4)",
                  marginBottom: 6,
                }}
              >
                Decoded {detected && <span>· {detected}</span>}
              </div>
              <a
                href={result}
                target="_blank"
                rel="noreferrer"
                className="wc-link"
                style={{
                  fontFamily: mono,
                  fontSize: 14,
                  wordBreak: "break-all",
                  color: "var(--ink)",
                  borderBottomColor: "var(--line-2)",
                }}
              >
                {result}
              </a>
            </div>
          )}
        </div>
      )}
    </section>
  );
}

function SectionLabel({ children }: { children: React.ReactNode }) {
  return (
    <div
      style={{
        fontSize: 11,
        letterSpacing: "0.12em",
        textTransform: "uppercase",
        color: "var(--ink-4)",
        fontWeight: 500,
      }}
    >
      {children}
    </div>
  );
}
