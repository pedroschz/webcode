// Triangular tessellation geometry — direct port of webcode_hex.py's
// all_triangles() / _sector_triangles() so the browser SVG renderer uses
// exactly the same vertex math as the Python encoder.

export type Pt = [number, number];
export type Triangle = [Pt, Pt, Pt];

const S = 8;

function lerp(a: Pt, b: Pt, t: number): Pt {
  return [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t];
}

function* sectorTriangles(apex: Pt, v1: Pt, v2: Pt): Generator<Triangle> {
  for (let k = 0; k < S; k++) {
    let U: Pt[];
    if (k === 0) {
      U = [apex];
    } else {
      const Ua = lerp(apex, v1, k / S);
      const Ub = lerp(apex, v2, k / S);
      U = Array.from({ length: k + 1 }, (_, i) => lerp(Ua, Ub, i / k));
    }
    const La = lerp(apex, v1, (k + 1) / S);
    const Lb = lerp(apex, v2, (k + 1) / S);
    const L: Pt[] = Array.from({ length: k + 2 }, (_, i) =>
      lerp(La, Lb, i / (k + 1))
    );
    for (let t = 0; t < 2 * k + 1; t++) {
      const i = Math.floor(t / 2);
      if (t % 2 === 0) {
        yield [L[i], L[i + 1], U[i]];
      } else {
        yield [U[i], L[i + 1], U[i + 1]];
      }
    }
  }
}

// Returns all 384 triangles in the same canonical sector-major order as
// all_triangles() in webcode_hex.py, so index i matches color[i].
export function allTriangles(cx = 0, cy = 0, R = 1): Triangle[] {
  const tris: Triangle[] = [];
  for (let s = 0; s < 6; s++) {
    const a1 = (Math.PI / 180) * (30 + s * 60);
    const a2 = (Math.PI / 180) * (30 + (s + 1) * 60);
    const v1: Pt = [cx + R * Math.cos(a1), cy - R * Math.sin(a1)];
    const v2: Pt = [cx + R * Math.cos(a2), cy - R * Math.sin(a2)];
    const apex: Pt = [cx, cy];
    for (const tri of sectorTriangles(apex, v1, v2)) {
      tris.push(tri);
    }
  }
  return tris;
}
