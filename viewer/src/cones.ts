// Filled ("cone") sweep rendering: one textured mesh per elevation cut. The polar texture holds the decoded raw N; the
// colour comes from a 256-entry palette texture built from the engine's value_of_n table. Display only: no gate is
// created, moved or smoothed (texture filtering is NEAREST), and N = 0 / N = 1 are never drawn.
import * as Cesium from "cesium";
import type { Sweep } from "./artifact";

function canvasOf(w: number, h: number, rgba: Uint8ClampedArray<ArrayBuffer>): HTMLCanvasElement {
  const c = document.createElement("canvas");
  c.width = w; c.height = h;
  c.getContext("2d")!.putImageData(new ImageData(rgba, w, h), 0, 0);
  return c;
}

// colorOf(value) returns a CSS colour, or null when that value is hidden (below the chosen minimum).
// Two opaque 256x1 canvases (colour; visible flag) avoid the premultiplied-alpha precision loss of a translucent canvas.
export interface Lut { rgb: HTMLCanvasElement; vis: HTMLCanvasElement; }
export function buildLut(s: Sweep, colorOf: (v: number) => string | null): Lut {
  const rgb = new Uint8ClampedArray(new ArrayBuffer(256 * 4)), vis = new Uint8ClampedArray(new ArrayBuffer(256 * 4));
  for (let n = 0; n < 256; n++) { rgb[n * 4 + 3] = 255; vis[n * 4 + 3] = 255; }
  for (let n = 2; n < 256; n++) {
    const v = s.meta.value_of_n[n];
    if (v === null || v === undefined) continue;
    const c = colorOf(v);
    if (!c) continue;
    const col = Cesium.Color.fromCssColorString(c);
    rgb.set([Math.round(col.red * 255), Math.round(col.green * 255), Math.round(col.blue * 255)], n * 4);
    vis[n * 4] = 255;
  }
  return { rgb: canvasOf(256, 1, rgb), vis: canvasOf(256, 1, vis) };
}

const SOURCE = `czm_material czm_getMaterial(czm_materialInput materialInput) {
  czm_material m = czm_getDefaultMaterial(materialInput);
  float n = floor(texture(tex, materialInput.st).r * 255.0 + 0.5);
  vec2 q = vec2((n + 0.5) / 256.0, 0.5);
  m.diffuse = texture(lut, q).rgb;
  m.alpha = texture(vis, q).r * opacity;
  return m;
}`;

export interface ConeLayer { primitive: Cesium.Primitive; destroy(): void; }

export function buildCone(s: Sweep, vex: number, lut: Lut, opacity: number): ConeLayer {
  const { n_radials: nr, n_gates: ng, mesh } = s.meta, nk = mesh.n_knots, nv = nr * 2 * nk;
  const pos = new Float64Array(nv * 3), st = new Float32Array(nv * 2);
  const tmp = new Cesium.Cartesian3();
  for (let r = 0; r < nr; r++) {
    for (let side = 0; side < 2; side++) {
      for (let k = 0; k < nk; k++) {
        const v = (r * 2 + side) * nk + k;
        Cesium.Cartesian3.fromDegrees(mesh.origin_lon_deg + s.dlon[v], mesh.origin_lat_deg + s.dlat[v], s.h[v] * vex, undefined, tmp);
        pos[v * 3] = tmp.x; pos[v * 3 + 1] = tmp.y; pos[v * 3 + 2] = tmp.z;
        st[v * 2] = mesh.knot_gate_boundary[k] / ng; st[v * 2 + 1] = (r + 0.5) / nr;
      }
    }
  }
  const idx = new Uint32Array(nr * (nk - 1) * 6);
  let q = 0;
  for (let r = 0; r < nr; r++) {
    for (let k = 0; k < nk - 1; k++) {
      const a = (r * 2) * nk + k, b = a + 1, c = (r * 2 + 1) * nk + k, d = c + 1;
      idx[q++] = a; idx[q++] = b; idx[q++] = d; idx[q++] = a; idx[q++] = d; idx[q++] = c;
    }
  }
  const geometry = new Cesium.Geometry({
    attributes: {
      position: new Cesium.GeometryAttribute({ componentDatatype: Cesium.ComponentDatatype.DOUBLE, componentsPerAttribute: 3, values: pos }),
      st: new Cesium.GeometryAttribute({ componentDatatype: Cesium.ComponentDatatype.FLOAT, componentsPerAttribute: 2, values: st }),
    } as never,
    indices: idx, primitiveType: Cesium.PrimitiveType.TRIANGLES, boundingSphere: Cesium.BoundingSphere.fromVertices(Array.from(pos)),
  });
  const polar = new Uint8ClampedArray(new ArrayBuffer(ng * nr * 4));
  for (let i = 0; i < ng * nr; i++) { polar[i * 4] = s.tex[i]; polar[i * 4 + 3] = 255; }
  const material = new Cesium.Material({
    fabric: { type: "RadarSweep", uniforms: { tex: Cesium.Material.DefaultImageId, lut: Cesium.Material.DefaultImageId, vis: Cesium.Material.DefaultImageId, opacity }, source: SOURCE },
    translucent: true, minificationFilter: Cesium.TextureMinificationFilter.NEAREST, magnificationFilter: Cesium.TextureMagnificationFilter.NEAREST,
  });
  // Canvases are assigned after construction: Material clones its fabric and cannot clone an HTMLCanvasElement.
  const u = material.uniforms as Record<string, unknown>;
  u.tex = canvasOf(ng, nr, polar); u.lut = lut.rgb; u.vis = lut.vis;
  const appearance = new Cesium.MaterialAppearance({
    material, translucent: true, flat: true, faceForward: false, closed: false,
    materialSupport: Cesium.MaterialAppearance.MaterialSupport.TEXTURED,
    renderState: { cull: { enabled: false }, depthTest: { enabled: true }, depthMask: false, blending: Cesium.BlendingState.ALPHA_BLEND },
  });
  const primitive = new Cesium.Primitive({
    geometryInstances: new Cesium.GeometryInstance({ geometry }), appearance, asynchronous: false, allowPicking: false,
    releaseGeometryInstances: true,
  });
  return { primitive, destroy() { /* the Primitive owns and releases the textures with the material */ } };
}
