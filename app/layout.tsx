import type { Metadata } from "next";
import { Inter, Instrument_Serif, JetBrains_Mono } from "next/font/google";

const inter = Inter({
  subsets: ["latin"],
  variable: "--font-sans",
  weight: ["300", "400", "500"],
  display: "swap",
});

const serif = Instrument_Serif({
  subsets: ["latin"],
  variable: "--font-serif",
  weight: "400",
  style: ["normal", "italic"],
  display: "swap",
});

const mono = JetBrains_Mono({
  subsets: ["latin"],
  variable: "--font-mono",
  weight: ["400"],
  display: "swap",
});

export const metadata: Metadata = {
  title: "Webcode",
  description: "Generate and decode Webcodes — URL-specialized scannable codes with an 8-color palette.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${inter.variable} ${serif.variable} ${mono.variable}`}>
      <body>
        <style>{`
          :root {
            --ink: #0a0a0a;
            --ink-2: #3f3f3f;
            --ink-3: #737373;
            --ink-4: #a3a3a3;
            --line: #ebebeb;
            --line-2: #dcdcdc;
            --paper: #fbfaf7;
            --accent: #0a0a0a;
            --ok: #2f7d4f;
            --err: #a83232;
          }
          * { box-sizing: border-box; }
          html, body { margin: 0; padding: 0; }
          body {
            font-family: var(--font-sans), -apple-system, BlinkMacSystemFont, system-ui, sans-serif;
            background: var(--paper);
            color: var(--ink);
            font-weight: 400;
            font-size: 15px;
            line-height: 1.55;
            -webkit-font-smoothing: antialiased;
            -moz-osx-font-smoothing: grayscale;
            text-rendering: optimizeLegibility;
          }
          a { color: inherit; }
          input, button { font-family: inherit; color: inherit; }
          input:focus { outline: none; }
          button { -webkit-tap-highlight-color: transparent; }
          ::selection { background: #0a0a0a; color: #fbfaf7; }
          ::placeholder { color: var(--ink-4); }

          .wc-fade-in { animation: wc-fade .5s cubic-bezier(.2,.7,.2,1) both; }
          @keyframes wc-fade {
            from { opacity: 0; transform: translateY(4px); }
            to { opacity: 1; transform: none; }
          }
          @media (prefers-reduced-motion: reduce) {
            .wc-fade-in { animation: none; }
          }

          .wc-url-input {
            width: 100%;
            border: 0;
            background: transparent;
            padding: 14px 0 14px;
            font-size: 17px;
            letter-spacing: -0.005em;
            border-bottom: 1px solid var(--line-2);
            transition: border-color .2s ease;
            font-family: var(--font-mono), ui-monospace, monospace;
          }
          .wc-url-input:focus { border-bottom-color: var(--ink); }

          .wc-btn {
            appearance: none;
            border: 0;
            background: var(--ink);
            color: var(--paper);
            padding: 11px 22px;
            border-radius: 999px;
            font-size: 14px;
            font-weight: 500;
            letter-spacing: 0.01em;
            cursor: pointer;
            transition: transform .15s ease, opacity .2s ease, background .2s ease;
          }
          .wc-btn:hover:not(:disabled) { transform: translateY(-1px); }
          .wc-btn:active:not(:disabled) { transform: translateY(0); }
          .wc-btn:disabled { opacity: .35; cursor: default; }

          .wc-link {
            color: var(--ink-3);
            text-decoration: none;
            border-bottom: 1px solid var(--line-2);
            padding-bottom: 1px;
            transition: color .2s ease, border-color .2s ease;
          }
          .wc-link:hover { color: var(--ink); border-bottom-color: var(--ink); }

          .wc-segment {
            background: transparent;
            border: 0;
            padding: 6px 0;
            margin-right: 22px;
            font-size: 13px;
            letter-spacing: 0.02em;
            color: var(--ink-4);
            cursor: pointer;
            position: relative;
            transition: color .2s ease;
          }
          .wc-segment:hover { color: var(--ink-2); }
          .wc-segment[data-active="true"] { color: var(--ink); }
          .wc-segment[data-active="true"]::after {
            content: "";
            position: absolute;
            left: 0; right: 0; bottom: 0;
            height: 1px;
            background: var(--ink);
          }

          .wc-file {
            display: inline-block;
            padding: 9px 16px;
            border: 1px solid var(--line-2);
            border-radius: 999px;
            font-size: 13px;
            color: var(--ink-2);
            cursor: pointer;
            transition: border-color .2s ease, color .2s ease;
          }
          .wc-file:hover { border-color: var(--ink); color: var(--ink); }
          .wc-file input { position: absolute; width: 1px; height: 1px; opacity: 0; pointer-events: none; }
        `}</style>
        {children}
      </body>
    </html>
  );
}
