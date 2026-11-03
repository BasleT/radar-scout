// Schema-checked loader for engine/viewer_export.py output. Mirrors COLUMNS there. No scientific computation.
export interface ViewerMeta {
  schema_version: string; kind: string; product: string; product_label: string; unit: string; source_sha256: string; station: string; vcp: number; interpolation: string; n_gates: number;
  radar: { lat: number; lon: number };
  volume_time_utc: { first_radial: string; last_radial: string };
  geoid: { model: string; status: string };
  reduction: { threshold: number; unit: string; n_samples_in: number };
  gates_bin: { file: string; sha256: string; size_bytes: number; byte_order: string; layout: string; columns: { name: string; dtype: string }[] };
}

export interface Artifact {
  meta: ViewerMeta; n: number; hashStatus: string;
  lon: Float64Array; lat: Float64Array; hEll: Float64Array; hMsl: Float64Array; arc: Float64Array; slant: Float64Array;
  value: Float32Array; rawN: Uint16Array; radialIdx: Int32Array; gateIdx: Int32Array; elevNo: Int16Array;
}

export interface Radials { columns: string[]; rows: Record<string, number[]>; }
export interface Coverage { kind: string; note: string; columns: string[]; cuts: Record<string, number[][]>; }
export interface ProductInfo { id: string; label: string; unit: string; thresholds: number[]; }
export interface VolumeIndex { volumes: { path: string; station: string; vcp: number; first_radial: string; last_radial: string; products: ProductInfo[] }[]; }

const EXPECT = [["lon_deg", "<f8"], ["lat_deg", "<f8"], ["height_ellipsoid_m", "<f8"], ["height_msl_m", "<f8"],
  ["ground_arc_m", "<f8"], ["slant_range_m", "<f8"], ["value", "<f4"], ["raw_N", "<u2"], ["radial_index", "<i4"],
  ["gate_idx", "<i4"], ["elevation_number", "<i2"]];
const SIZE: Record<string, number> = { "<f8": 8, "<f4": 4, "<u2": 2, "<i4": 4, "<i2": 2 };

async function sha256Hex(buf: ArrayBuffer): Promise<string | null> {
  if (!globalThis.crypto?.subtle) return null; // insecure context (plain http): cannot verify
  const d = new Uint8Array(await crypto.subtle.digest("SHA-256", buf));
  return Array.from(d, (b) => b.toString(16).padStart(2, "0")).join("");
}

async function getJson<T>(url: string): Promise<T> {
  const r = await fetch(url, { cache: "no-store" });
  if (!r.ok) throw new Error(`${url}: HTTP ${r.status}`);
  return (await r.json()) as T;
}

export const loadRadials = (dir: string) => getJson<Radials>(`${dir}/radials.json`);
export const loadCoverage = (dir: string) => getJson<Coverage>(`${dir}/coverage.json`);
export const loadIndex = (base: string) => getJson<VolumeIndex>(`${base}/index.json`);

export async function loadArtifact(dirUrl: string): Promise<Artifact> {
  const meta = await getJson<ViewerMeta>(`${dirUrl}/viewer.json`);
  if (meta.kind !== "viewer-reduction" || meta.schema_version !== "1.1") throw new Error("unsupported artifact schema");
  if (meta.interpolation !== "none") throw new Error("artifact claims interpolation; this viewer only draws measured gates");
  const g = meta.gates_bin;
  if (g.byte_order !== "little" || g.layout !== "column-major") throw new Error("unsupported gates.bin layout");
  if (g.columns.length !== EXPECT.length || g.columns.some((c, i) => c.name !== EXPECT[i][0] || c.dtype !== EXPECT[i][1]))
    throw new Error("gates.bin columns differ from the expected layout");
  const n = meta.n_gates;
  const want = EXPECT.reduce((s, [, t]) => s + SIZE[t] * n, 0);
  if (want !== g.size_bytes) throw new Error("size_bytes inconsistent with n_gates");
  const br = await fetch(`${dirUrl}/${g.file}`, { cache: "no-store" });
  if (!br.ok) throw new Error(`${g.file}: HTTP ${br.status}`);
  const buf = await br.arrayBuffer();
  if (buf.byteLength !== g.size_bytes) throw new Error(`gates.bin is ${buf.byteLength} bytes, expected ${g.size_bytes}`);
  const h = await sha256Hex(buf);
  if (h !== null && h !== g.sha256) throw new Error("gates.bin SHA-256 does not match viewer.json");
  const hashStatus = h === null ? "NOT verified (insecure context: SHA-256 unavailable)" : "gates.bin SHA-256 verified";
  let off = 0;
  // Columns are packed back to back, so with an odd row count a column can start at an offset that is not a
  // multiple of its element size (typed arrays then throw). Such a column is copied byte for byte to an aligned buffer.
  const take = <T>(Ctor: (new (b: ArrayBuffer, o: number, l: number) => T) & { BYTES_PER_ELEMENT: number }, size: number): T => {
    const start = off; off += size * n;
    if (start % Ctor.BYTES_PER_ELEMENT === 0) return new Ctor(buf, start, n);
    return new Ctor(buf.slice(start, off), 0, n);
  };
  // Little-endian typed arrays assume a little-endian host (true for x86-64 and arm64 Android/Windows).
  return {
    meta, n, hashStatus,
    lon: take(Float64Array, 8), lat: take(Float64Array, 8), hEll: take(Float64Array, 8), hMsl: take(Float64Array, 8),
    arc: take(Float64Array, 8), slant: take(Float64Array, 8), value: take(Float32Array, 4), rawN: take(Uint16Array, 2),
    radialIdx: take(Int32Array, 4), gateIdx: take(Int32Array, 4), elevNo: take(Int16Array, 2),
  };
}

// ---- Per-sweep artifacts (engine/sweeps.py): a one-byte polar texture of raw N plus a positional mesh. No computation.
export interface SweepIndex {
  product: string; unit: string;
  cuts: { elevation_number: number; path: string; elevation_deg_mean: number; n_radials: number; n_gates: number }[];
  skipped: { elevation_number: number; reason: string }[];
}
export interface SweepMeta {
  kind: string; schema_version: string; interpolation: string; product: string; unit: string; elevation_number: number;
  elevation_deg_mean: number; n_radials: number; n_gates: number; value_of_n: (number | null)[];
  texture: { file: string; dtype: string; sha256: string; size_bytes: number; width: number; height: number };
  mesh: { file: string; dtype: string; sha256: string; size_bytes: number; n_knots: number; knot_gate_boundary: number[];
          origin_lon_deg: number; origin_lat_deg: number; mesh_chord_error_m: { height_max: number; ground_arc_max: number } };
}
export interface Sweep { meta: SweepMeta; tex: Uint8Array; dlon: Float32Array; dlat: Float32Array; h: Float32Array; hashStatus: string; }

export const loadSweepIndex = (volDir: string, product: string) => getJson<SweepIndex>(`${volDir}/sweeps/${product}/index.json`);

export async function loadSweep(volDir: string, path: string): Promise<Sweep> {
  const dir = `${volDir}/${path}`;
  const meta = await getJson<SweepMeta>(`${dir}/sweep.json`);
  if (meta.kind !== "sweep-texture" || meta.schema_version !== "1.0") throw new Error("unsupported sweep schema");
  if (meta.interpolation !== "none") throw new Error("sweep claims interpolation; this viewer only draws decoded values");
  if (meta.texture.dtype !== "u8" || meta.mesh.dtype !== "<f4") throw new Error("unsupported sweep dtypes");
  const nv = meta.n_radials * 2 * meta.mesh.n_knots;
  if (meta.texture.size_bytes !== meta.n_radials * meta.n_gates || meta.mesh.size_bytes !== nv * 12) throw new Error("sweep sizes inconsistent");
  const [tb, mb] = await Promise.all([meta.texture.file, meta.mesh.file].map(async (f) => {
    const r = await fetch(`${dir}/${f}`, { cache: "no-store" });
    if (!r.ok) throw new Error(`${f}: HTTP ${r.status}`);
    return r.arrayBuffer();
  }));
  if (tb.byteLength !== meta.texture.size_bytes || mb.byteLength !== meta.mesh.size_bytes) throw new Error("sweep file size differs from manifest");
  const [ht, hm] = await Promise.all([sha256Hex(tb), sha256Hex(mb)]);
  if ((ht !== null && ht !== meta.texture.sha256) || (hm !== null && hm !== meta.mesh.sha256)) throw new Error("sweep SHA-256 does not match manifest");
  return {
    meta, hashStatus: ht === null ? "NOT verified (insecure context)" : "verified", tex: new Uint8Array(tb),
    dlon: new Float32Array(mb, 0, nv), dlat: new Float32Array(mb, nv * 4, nv), h: new Float32Array(mb, nv * 8, nv),
  };
}
