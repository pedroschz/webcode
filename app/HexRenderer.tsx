"use client";

import { useMemo } from "react";
import { allTriangles } from "./hex-geometry";
import type { Triangle } from "./hex-geometry";

export type RGB = [number, number, number];

// Every one of the 384 triangles is rendered — white shims are opaque white,
// not omitted, so the surrounding triangles can't collapse inward. The same
// geometry function that drives the Python encoder drives the SVG, so anchor,
// alignment, metadata, payload, and shim triangles all land in exactly the
// right positions with no floating elements.

const SIZE = 480;
const CX = SIZE / 2;
const CY = SIZE / 2;
const R = SIZE * 0.47;

function triPath(pts: Triangle): string {
  return (
    pts
      .map(([x, y], j) => `${j === 0 ? "M" : "L"}${x.toFixed(2)},${y.toFixed(2)}`)
      .join(" ") + " Z"
  );
}

export function HexRenderer({ colors }: { colors: RGB[] }) {
  const tris = useMemo(() => allTriangles(CX, CY, R), []);

  return (
    <svg
      viewBox={`0 0 ${SIZE} ${SIZE}`}
      width={SIZE}
      height={SIZE}
      style={{ display: "block", maxWidth: "100%", height: "auto" }}
      aria-label="Hex webcode"
    >
      {tris.map((pts, i) => {
        const [r, g, b] = colors[i] ?? [255, 255, 255];
        const fill = `rgb(${r},${g},${b})`;
        return (
          <path
            key={i}
            d={triPath(pts)}
            fill={fill}
            // hairline stroke matching fill prevents sub-pixel gaps between
            // adjacent triangles without altering perceived color
            stroke={fill}
            strokeWidth={0.6}
          />
        );
      })}
    </svg>
  );
}
