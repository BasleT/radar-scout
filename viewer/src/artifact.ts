// Schema-checked loader for engine/viewer_export.py output. Mirrors COLUMNS there. No scientific computation.
export interface ViewerMeta {
  schema_version: string; kind: string; source_sha256: string; station: string; vcp: number; interpolation: string; n_gates: number;
  radar: { lat: number; lon: number };
  volume_time_utc: { first_radial: string; last_radial: string };
  geoid: { model: string; status: string };
  reduction: { threshold_dbz: number; n_samples_in: number };
  gates_bin: { file: string; sha256: string; size_bytes: number; byte_order: string; layout: string; columns: { name: string; dtype: string }[] };
}

export interface Artifact {
  meta: ViewerMeta; n: number; hashStatus: string;
  lon: Float64Array; lat: Float64Array; hEll: Float64Array; hMsl: Float64Array; arc: Float64Array; slant: Float64Array;
  dbz: Float32Array; rawN: Uint16Array; radialIdx: Int32Array; gateIdx: Int32Array; elevNo: Int16Array;
}

export interface Radials { columns: string[]; rows: Record<string, number[]>; }
export interface Coverage { kind: string; note: string; columns: string[]; cuts: Record<string, number[][]>; }
export interface VolumeIndex { volumes: { path: string; station: string; vcp: number; first_radial: string; last_radial: string }[]; }

const EXPECT = [["lon_deg", "<f8"], ["lat_deg", "<f8"], ["height_ellipsoid_m", "<f8"], ["height_msl_m", "<f8"],
  ["ground_arc_m", "<f8"], ["slant_range_m", "<f8"], ["dbz", "<f4"], ["raw_N", "<u2"], ["radial_index", "<i4"],
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
  if (meta.kind !== "viewer-reduction" || meta.schema_version !== "1.0") throw new Error("unsupported artifact schema");
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
  const take = <T>(Ctor: new (b: ArrayBuffer, o: number, l: number) => T, size: number): T => {
    const a = new Ctor(buf, off, n); off += size * n; return a;
  };
  // Little-endian typed arrays assume a little-endian host (true for x86-64 and arm64 Android/Windows).
  return {
    meta, n, hashStatus,
    lon: take(Float64Array, 8), lat: take(Float64Array, 8), hEll: take(Float64Array, 8), hMsl: take(Float64Array, 8),
    arc: take(Float64Array, 8), slant: take(Float64Array, 8), dbz: take(Float32Array, 4), rawN: take(Uint16Array, 2),
    radialIdx: take(Int32Array, 4), gateIdx: take(Int32Array, 4), elevNo: take(Int16Array, 2),
  };
}
