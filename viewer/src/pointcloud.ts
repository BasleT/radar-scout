// One GPU buffer for a whole set of gates (instead of one JS object per gate). Display only.
//  - "points": each gate is a round dot of fixed pixel size.
//  - "volume": each entry is a soft round sprite whose size is in METRES (scaled with distance), so overlapping
//    sprites read as a continuous cloud. The softness is a rendering effect, not data.
import * as Cesium from "cesium";

const VS = `in vec3 position3DHigh;
in vec3 position3DLow;
in vec4 color;
in float batchId; // required by Cesium's primitive wrapper (show/distance conditions)
out vec4 v_color;
void main() {
  vec4 p = czm_computePosition();
  v_color = color;
  gl_Position = czm_modelViewProjectionRelativeToEye * p;
  SIZE_EXPR
}`;

const FS_POINTS = `in vec4 v_color;
void main() {
  vec2 d = gl_PointCoord - vec2(0.5);
  if (dot(d, d) > 0.25) discard;
  out_FragColor = v_color;
}`;

const FS_VOLUME = `in vec4 v_color;
void main() {
  float d = length(gl_PointCoord - vec2(0.5)) * 2.0;
  float a = smoothstep(1.0, 0.0, d);
  out_FragColor = vec4(v_color.rgb, v_color.a * a);
}`;

export interface CloudOpts { mode: "points" | "volume"; sizePx?: number; sizeM?: number; center: Cesium.Cartesian3; }

// positions: ECEF metres (x, y, z per entry); rgba: 4 bytes per entry
export function buildCloud(positions: Float64Array, rgba: Uint8Array, o: CloudOpts): Cesium.Primitive {
  const n = positions.length / 3;
  const indices = new Uint32Array(n);
  for (let i = 0; i < n; i++) indices[i] = i;
  const geometry = new Cesium.Geometry({
    attributes: {
      position: new Cesium.GeometryAttribute({ componentDatatype: Cesium.ComponentDatatype.DOUBLE, componentsPerAttribute: 3, values: positions }),
      color: new Cesium.GeometryAttribute({ componentDatatype: Cesium.ComponentDatatype.UNSIGNED_BYTE, componentsPerAttribute: 4, normalize: true, values: rgba }),
    } as never,
    indices, primitiveType: Cesium.PrimitiveType.POINTS, boundingSphere: new Cesium.BoundingSphere(o.center, 600000),
  });
  const size = o.mode === "volume"
    ? `gl_PointSize = clamp(${(o.sizeM ?? 2000).toFixed(1)} * czm_projection[1][1] * 0.5 * czm_viewport.w / max(gl_Position.w, 1.0), 2.0, 120.0);`
    : `gl_PointSize = ${(o.sizePx ?? 4).toFixed(1)};`;
  const appearance = new Cesium.Appearance({
    translucent: true, closed: false,
    vertexShaderSource: VS.replace("SIZE_EXPR", size),
    fragmentShaderSource: o.mode === "volume" ? FS_VOLUME : FS_POINTS,
    renderState: { depthTest: { enabled: true }, depthMask: o.mode === "points", blending: Cesium.BlendingState.ALPHA_BLEND },
  });
  return new Cesium.Primitive({
    geometryInstances: new Cesium.GeometryInstance({ geometry }), appearance, asynchronous: false, allowPicking: false,
    releaseGeometryInstances: true,
  });
}
