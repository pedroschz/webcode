import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Webcode",
  description: "Generate and decode Webcodes — URL-specialized scannable codes with an 8-color palette.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body style={{
        fontFamily: "-apple-system, BlinkMacSystemFont, 'SF Pro Text', system-ui, sans-serif",
        margin: 0, background: "#fafafa", color: "#111",
      }}>
        {children}
      </body>
    </html>
  );
}
