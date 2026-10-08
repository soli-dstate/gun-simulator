// Surfaces of revolution. Cartridges, cases and projectiles are all turned
// shapes, so each one is described by a 2D profile and revolved about the x axis.
//
// A profile is a list of parts. Each part is a polyline of [r, x] points that is
// shaded smoothly; where one part ends and the next begins there is a hard edge.
// Parts run continuously (each starts where the previous one ended) and the
// whole profile goes round the solid with the material on the left when walking
// along it with x up and r to the right, i.e. "out along the base, up the outside,
// back down the inside". That makes the outward normal of a segment (dx, -dr).

/**
 * Revolve a profile into a mesh: {positions, normals, indices} (Float32/Uint32 arrays).
 * a0..a1 revolves only part of the way round (radians from +y towards +z), leaving the ends open.
 */
export function lathe(parts, segments = 96, a0 = 0, a1 = 2 * Math.PI) {
  const positions = [], normals = [], indices = [];
  const cos = [], sin = [];
  for (let j = 0; j <= segments; j++) {
    const a = a0 + (j / segments) * (a1 - a0);
    cos.push(Math.cos(a));
    sin.push(Math.sin(a));
  }

  for (const part of parts) {
    if (part.length < 2) continue;
    // Outward normal of each segment, then averaged at shared points.
    const segNormals = [];
    for (let i = 0; i + 1 < part.length; i++) {
      const dr = part[i + 1][0] - part[i][0], dx = part[i + 1][1] - part[i][1];
      const len = Math.hypot(dr, dx) || 1;
      segNormals.push([dx / len, -dr / len]);  // [n_r, n_x]
    }
    const base = positions.length / 3;
    part.forEach(([r, x], i) => {
      const a = segNormals[Math.max(0, i - 1)], b = segNormals[Math.min(segNormals.length - 1, i)];
      let nr = a[0] + b[0], nx = a[1] + b[1];
      const len = Math.hypot(nr, nx) || 1;
      nr /= len; nx /= len;
      for (let j = 0; j <= segments; j++) {
        positions.push(x, r * cos[j], r * sin[j]);
        normals.push(nx, nr * cos[j], nr * sin[j]);
      }
    });
    // Counter-clockwise from outside: (a, d, b) and (b, d, c) for the quad
    // a=(i,j) b=(i+1,j) c=(i+1,j+1) d=(i,j+1).
    const ring = segments + 1;
    for (let i = 0; i + 1 < part.length; i++) {
      for (let j = 0; j < segments; j++) {
        const a = base + i * ring + j, b = a + ring, c = b + 1, d = a + 1;
        indices.push(a, d, b, b, d, c);
      }
    }
  }
  return { positions: new Float32Array(positions), normals: new Float32Array(normals), indices: new Uint32Array(indices) };
}

/** Volume of the solid enclosed by a closed profile (all parts joined), via frustum sums. */
export function profileVolume(parts) {
  const pts = parts.flat();
  let v = 0;
  for (let i = 0; i < pts.length; i++) {
    const [r0, x0] = pts[i], [r1, x1] = pts[(i + 1) % pts.length];
    v += (r0 * r0 + r0 * r1 + r1 * r1) * (x1 - x0);
  }
  return Math.abs((Math.PI / 3) * v);
}

/** Volume of revolution of r(x) between x0 and x1, where r is a polyline of [r, x] points sorted by x. */
export function radiusVolume(points, x0, x1, steps = 400) {
  if (x1 <= x0) return 0;
  const h = (x1 - x0) / steps;
  let v = 0;
  for (let i = 0; i < steps; i++) {
    const r = radiusAt(points, x0 + (i + 0.5) * h);
    v += r * r;
  }
  return Math.PI * v * h;
}

export function radiusAt(points, x) {
  if (x <= points[0][1]) return points[0][0];
  for (let i = 1; i < points.length; i++) {
    const [r1, x1] = points[i];
    if (x <= x1) {
      const [r0, x0] = points[i - 1];
      return x1 > x0 ? r0 + ((r1 - r0) * (x - x0)) / (x1 - x0) : r1;
    }
  }
  return points[points.length - 1][0];
}
