// Thin viewer: loads engine-produced artifacts and draws them. It performs NO scientific computation:
// positions, heights, ranges and dBZ are read from the artifact exactly as the engine wrote them. The only
// arithmetic here is display-only (colour binning, opacity, optional vertical exaggeration, plot axis scaling,
// selecting radials by azimuth for a cross-section, and max/count summaries for the KPI cards), each labelled.
(window as unknown as { CESIUM_BASE_URL: string }).CESIUM_BASE_URL = "./cesium/";

import * as Cesium from "cesium";
import { loadArtifact, loadCoverage, loadIndex, loadRadials, type Artifact, type Coverage, type Radials, type VolumeIndex } from "./artifact";

const $ = <T extends HTMLElement>(id: string) => document.getElementById(id) as T;
const KEY = "radar.server";
const BINS: [number, number, string][] = [
  [20, 30, "#4aa3df"], [30, 35, "#2e9e4f"], [35, 40, "#9acd32"], [40, 45, "#f2d21b"],
  [45, 50, "#f28c1b"], [50, 55, "#d62828"], [55, Infinity, "#c026d3"],
];

function safeGet(k: string): string | null { try { return localStorage.getItem(k); } catch { return null; } }
function safeSet(k: string, v: string) { try { localStorage.setItem(k, v); } catch { /* storage unavailable */ } }

const viewer = new Cesium.Viewer("cesium", {
  baseLayer: false, baseLayerPicker: false, geocoder: false, homeButton: false, sceneModePicker: false,
  navigationHelpButton: false, animation: false, timeline: false, fullscreenButton: false, infoBox: false,
  selectionIndicator: false, requestRenderMode: false,
});
viewer.scene.globe.baseColor = Cesium.Color.fromCssColorString("#1b2a38");
// Offline basemap shipped with Cesium (Natural Earth II, coarse). No tile server or token is contacted.
Cesium.TileMapServiceImageryProvider.fromUrl(Cesium.buildModuleUrl("Assets/Textures/NaturalEarthII"))
  .then((p) => { const l = viewer.imageryLayers.addImageryProvider(p); l.brightness = 0.45; l.saturation = 0.6; })
  .catch(() => { /* basemap is cosmetic */ });

let points: Cesium.PointPrimitiveCollection | null = null;
let covLines: Cesium.PolylineCollection | null = null;
let art: Artifact | null = null;
let radials: Radials | null = null;
let coverage: Coverage | null = null;
let index: VolumeIndex | null = null;
let section: Set<number> | null = null;
let volDir = "";
let timer: number | undefined;

$("legend").innerHTML = "<b>dBZ</b>" +
  BINS.map(([a, b, c]) => `<div><span class="sw" style="background:${c}"></span>${a}${b === Infinity ? "+" : "–" + b}</div>`).join("");

const binHex = (dbz: number): string => { for (const [a, b, c] of BINS) if (dbz >= a && dbz < b) return c; return "#ffffff"; };
const vex = () => Number($<HTMLSelectElement>("vex").value);
const alpha = () => Number($<HTMLInputElement>("alpha").value);
const base = () => $<HTMLInputElement>("server").value.trim().replace(/\/+$/, "");
const thr = () => $<HTMLSelectElement>("thr").value;
const sweepSel = () => $<HTMLSelectElement>("sweep").value;

function banner() {
  const k = vex();
  $("banner").innerHTML = (k !== 1 ? `<b>VERTICAL EXAGGERATION ${k}×: displayed heights are ${k}× ellipsoid height, NOT to scale.</b><br>` : "") +
    "Measured gates only, drawn as points at beam-centre height (4/3 Earth model); sample volumes are not drawn (beam width not decoded). Not interpolated. Gates below the threshold, range-folded gates and unscanned regions are not drawn; their absence is not evidence of no echo. Not an operational or safety product.";
}

// ---- KPI cards: summaries (max / count) of the gates in the loaded artifact, not new measurements
function kpis(a: Artifact) {
  let maxDbz = -Infinity, maxH = -Infinity, maxArc = 0;
  const cuts = new Set<number>();
  for (let i = 0; i < a.n; i++) {
    if (a.dbz[i] > maxDbz) maxDbz = a.dbz[i];
    if (a.hMsl[i] > maxH) maxH = a.hMsl[i];
    if (a.arc[i] > maxArc) maxArc = a.arc[i];
    cuts.add(a.elevNo[i]);
  }
  const card = (v: string, l: string) => `<div class="kpi"><b>${v}</b><span>${l}</span></div>`;
  const none = a.n === 0;
  $("kpis").innerHTML =
    card(none ? "–" : `${maxDbz.toFixed(1)}`, "max dBZ (loaded gates)") +
    card(a.n.toLocaleString(), `gates ≥ ${a.meta.reduction.threshold_dbz} dBZ`) +
    card(none ? "–" : `${(maxH / 1000).toFixed(1)} km`, "highest gate, MSL") +
    card(none ? "–" : `${(maxArc / 1000).toFixed(0)} km`, "farthest gate (arc)") +
    card(String(cuts.size), "cuts with gates") +
    card(a.meta.vcp ? `VCP ${a.meta.vcp}` : "–", "scan pattern");
  const last = Date.parse(a.meta.volume_time_utc.last_radial);
  const mins = Math.round((Date.now() - last) / 60000);
  $("age").textContent = Number.isFinite(mins) ? `data age ${mins >= 90 ? (mins / 60).toFixed(1) + " h" : mins + " min"}` : "";
}

function describe(a: Artifact) {
  const m = a.meta, r = m.reduction;
  $("title").textContent = `${m.station}  ·  reflectivity`;
  $("sub").textContent = `${m.volume_time_utc.first_radial.replace("+00:00", "Z")} → ${m.volume_time_utc.last_radial.replace("+00:00", "Z")}`;
  $("meta").innerHTML = `<table>
    <tr><td>Volume (UTC)</td><td>${m.volume_time_utc.first_radial}<br>to ${m.volume_time_utc.last_radial}<br><i>sweeps are not simultaneous</i></td></tr>
    <tr><td>Source file</td><td>${m.source_sha256.slice(0, 16)}… (SHA-256)</td></tr>
    <tr><td>Gates in data</td><td>${a.n.toLocaleString()} of ${r.n_samples_in.toLocaleString()} (MEASURED, ≥ ${r.threshold_dbz} dBZ)</td></tr>
    <tr><td>Height</td><td>beam centre, ellipsoid (${m.geoid.model}, ${m.geoid.status})</td></tr>
    <tr><td>Integrity</td><td>${a.hashStatus}</td></tr>
    <tr><td>Interpolation</td><td>${m.interpolation}</td></tr></table>`;
  kpis(a);
  const sel = $<HTMLSelectElement>("sweep"), keep = sel.value;
  const cuts = Array.from(new Set(Array.from(a.elevNo))).sort((x, y) => x - y);
  sel.innerHTML = `<option value="">All sweeps</option>` + cuts.map((c) => `<option value="${c}">Elevation no. ${c}</option>`).join("");
  if (cuts.map(String).includes(keep)) sel.value = keep;
}

function draw() {
  if (!art) return;
  const a = art, k = vex(), al = alpha(), sw = sweepSel();
  if (points) viewer.scene.primitives.remove(points);
  points = viewer.scene.primitives.add(new Cesium.PointPrimitiveCollection());
  let shown = 0;
  for (let i = 0; i < a.n; i++) {
    if (section && !section.has(a.radialIdx[i])) continue;
    if (sw !== "" && a.elevNo[i] !== Number(sw)) continue;
    points!.add({
      position: Cesium.Cartesian3.fromDegrees(a.lon[i], a.lat[i], a.hEll[i] * k),
      color: Cesium.Color.fromCssColorString(binHex(a.dbz[i])).withAlpha(al), pixelSize: 3, id: i,
    });
    shown++;
  }
  $("xsinfo").textContent = section ? `${shown.toLocaleString()} gates in ${section.size} radials` : "";
  banner();
  drawCoverage();
}

function drawCoverage() {
  if (covLines) { viewer.scene.primitives.remove(covLines); covLines = null; }
  if (!$<HTMLInputElement>("cov").checked || !coverage || !art) return;
  const k = vex();
  covLines = viewer.scene.primitives.add(new Cesium.PolylineCollection());
  for (const rows of Object.values(coverage.cuts)) {
    const flat: number[] = [];
    for (const r of rows) flat.push(r[1], r[2], r[3] * k); // lon, lat, ellipsoid height as written by the engine
    covLines!.add({ positions: Cesium.Cartesian3.fromDegreesArrayHeights(flat), width: 1,
      material: Cesium.Material.fromType("Color", { color: Cesium.Color.WHITE.withAlpha(0.5) }) });
  }
}

function coverageInfo() {
  if (!coverage || !radials) { $("covinfo").textContent = ""; return; }
  const noRef = radials.rows["has_ref"].filter((v) => !v).length;
  $("covinfo").textContent = `${Object.keys(coverage.cuts).length} cuts with reflectivity; ${noRef} of ${radials.rows["has_ref"].length} radials carry no REF moment (e.g. Doppler-only cuts). ${coverage.note}.`;
}

async function loadVolume(dir: string) {
  $("err").textContent = "";
  volDir = dir;
  try {
    art = await loadArtifact(`${dir}/thr${thr()}`);
    radials = await loadRadials(`${dir}/thr${thr()}`).catch(() => null);
    coverage = await loadCoverage(`${dir}/thr${thr()}`).catch(() => null);
    describe(art);
    coverageInfo();
    draw();
    return true;
  } catch (e) {
    $("err").textContent = `Load failed: ${(e as Error).message}`; // no fallback data is ever substituted
    showTab("info");
    return false;
  }
}

function home() {
  if (!art) return;
  const rd = art.meta.radar;
  if (viewer.scene.mode === Cesium.SceneMode.SCENE2D) {
    viewer.camera.setView({ destination: Cesium.Rectangle.fromDegrees(rd.lon - 4, rd.lat - 3, rd.lon + 4, rd.lat + 3) });
  } else {
    viewer.camera.setView({ destination: Cesium.Cartesian3.fromDegrees(rd.lon, rd.lat - 2.5, 450000), orientation: { pitch: Cesium.Math.toRadians(-50) } });
  }
}

async function loadLatest() {
  safeSet(KEY, base());
  index = await loadIndex(base()).catch(() => null);
  const slider = $<HTMLInputElement>("tsl");
  let ok: boolean;
  if (index && index.volumes.length > 0) {
    slider.max = String(index.volumes.length - 1); slider.disabled = false; $<HTMLButtonElement>("play").disabled = false;
    slider.value = slider.max;
    ok = await loadVolume(`${base()}/${index.volumes[index.volumes.length - 1].path}`);
    tlabel();
  } else {
    slider.disabled = true; $<HTMLButtonElement>("play").disabled = true;
    ok = await loadVolume(`${base()}/latest`);
  }
  if (ok) home();
}

function tlabel() {
  if (!index) return;
  const i = Number($<HTMLInputElement>("tsl").value);
  $("tlabel").textContent = `${index.volumes[i].first_radial.replace("+00:00", "Z")} (${i + 1}/${index.volumes.length})`;
}

async function goto(i: number) {
  if (!index) return;
  $<HTMLInputElement>("tsl").value = String(i);
  tlabel();
  await loadVolume(`${base()}/${index.volumes[i].path}`);
}

function setPlaying(on: boolean) {
  if (timer !== undefined) { window.clearInterval(timer); timer = undefined; }
  $("play").textContent = on ? "Pause" : "Play";
  if (!on || !index) return;
  let busy = false;
  timer = window.setInterval(async () => {
    if (busy || !index) return;
    busy = true;
    await goto((Number($<HTMLInputElement>("tsl").value) + 1) % index.volumes.length);
    busy = false;
  }, 2500);
}

// ---- cross-section: SELECTION of engine radials by azimuth + plot of engine values (no geometry computed here)
function angDiff(a: number, b: number) { const d = Math.abs(a - b) % 360; return d > 180 ? 360 - d : d; }

function applySection() {
  if (!art || !radials) { $("err").textContent = "No radials.json for this volume."; showTab("info"); return; }
  const raw = $<HTMLInputElement>("xaz").value;
  const az = Number(raw), hw = Number($<HTMLInputElement>("xhw").value);
  if (raw === "" || !Number.isFinite(az)) { $("err").textContent = "Enter an azimuth."; showTab("info"); return; }
  const azs = radials.rows["azimuth_deg"], idx = radials.rows["radial_index"];
  const sel = new Set<number>();
  for (let j = 0; j < idx.length; j++) if (angDiff(azs[j], az) <= hw) sel.add(idx[j]);
  section = sel;
  draw();
  plotSection();
}

function plotSection() {
  const box = $("xs"), c = $<HTMLCanvasElement>("xsc"), g = c.getContext("2d")!;
  if (!art || !section) { box.style.display = "none"; return; }
  box.style.display = "block";
  const dark = matchMedia("(prefers-color-scheme: dark)").matches;
  g.clearRect(0, 0, c.width, c.height);
  let xmax = 1, ymax = 1, ymin = 0;
  const sel: number[] = [];
  for (let i = 0; i < art.n; i++) if (section.has(art.radialIdx[i])) { sel.push(i); xmax = Math.max(xmax, art.arc[i]); ymax = Math.max(ymax, art.hMsl[i]); ymin = Math.min(ymin, art.hMsl[i]); }
  const L = 36, B = 20, W = c.width - L - 6, H = c.height - B - 6;
  g.strokeStyle = dark ? "#59636b" : "#9aa3aa"; g.fillStyle = dark ? "#e8ecef" : "#14181c"; g.font = "10px system-ui";
  g.strokeRect(L, 6, W, H);
  for (let t = 0; t <= 4; t++) { // axis labels: same units as the data (km), linear scale
    g.fillText(`${((xmax * t) / 4 / 1000).toFixed(0)}`, L + (W * t) / 4 - 6, c.height - 8);
    g.fillText(`${((ymin + ((ymax - ymin) * t) / 4) / 1000).toFixed(1)}`, 2, 6 + H - (H * t) / 4 + 3);
  }
  g.fillText("ground arc, km  (y: km MSL)", L + 4, c.height - 0);
  for (const i of sel) {
    g.fillStyle = binHex(art.dbz[i]);
    g.fillRect(L + (art.arc[i] / xmax) * W - 1, 6 + H - ((art.hMsl[i] - ymin) / (ymax - ymin || 1)) * H - 1, 2, 2);
  }
  $("xsinfo").textContent = `${sel.length.toLocaleString()} gates; gaps between points are unsampled, not empty.`;
}

// ---- inspection
const handler = new Cesium.ScreenSpaceEventHandler(viewer.scene.canvas);
handler.setInputAction((ev: { position: Cesium.Cartesian2 }) => {
  const p = viewer.scene.pick(ev.position);
  const box = $("inspect");
  if (!art || !p || typeof p.id !== "number") { box.style.display = "none"; return; }
  const i = p.id;
  const ri = art.radialIdx[i];
  const raz = radials ? radials.rows["azimuth_deg"][ri] : null;
  const rel = radials ? radials.rows["elevation_deg"][ri] : null;
  const rt = radials ? radials.rows["radial_time_ms_utc"][ri] : null;
  box.style.display = "block";
  box.innerHTML = `<table>
    <tr><td>Class</td><td>MEASURED (not interpolated)</td></tr>
    <tr><td>Reflectivity</td><td>${art.dbz[i].toFixed(1)} dBZ (raw N = ${art.rawN[i]})</td></tr>
    <tr><td>Position</td><td>${art.lat[i].toFixed(5)}°, ${art.lon[i].toFixed(5)}°</td></tr>
    <tr><td>Beam-centre height</td><td>${art.hMsl[i].toFixed(0)} m MSL · ${art.hEll[i].toFixed(0)} m ellipsoid</td></tr>
    <tr><td>Range</td><td>slant ${(art.slant[i] / 1000).toFixed(2)} km · ground arc ${(art.arc[i] / 1000).toFixed(2)} km</td></tr>
    ${raz === null ? "" : `<tr><td>Radial</td><td>az ${raz!.toFixed(2)}° · el ${rel!.toFixed(2)}°<br>${new Date(rt!).toISOString()}</td></tr>`}
    <tr><td>Source</td><td>${art.meta.station} · file ${art.meta.source_sha256.slice(0, 12)}…<br>elevation no. ${art.elevNo[i]}, radial index ${ri}, gate ${art.gateIdx[i]}</td></tr>
    <tr><td>Uncertainty</td><td>≈1° beam (width not decoded), 4/3 refraction model; not quantified per gate</td></tr></table>`;
}, Cesium.ScreenSpaceEventType.LEFT_CLICK);

// ---- UI wiring
function showTab(name: string) {
  document.querySelectorAll<HTMLElement>("#tabs [data-tab]").forEach((b) => b.classList.toggle("on", b.dataset.tab === name));
  document.querySelectorAll<HTMLElement>(".tab").forEach((t) => t.classList.toggle("on", t.id === `t-${name}`));
  $("sheet").classList.remove("min");
}
document.querySelectorAll<HTMLElement>("#tabs [data-tab]").forEach((b) => b.addEventListener("click", () => showTab(b.dataset.tab!)));
$("grip").addEventListener("click", () => $("sheet").classList.toggle("min"));

function setView(two: boolean) {
  $("v2d").classList.toggle("pri", two);
  $("v3d").classList.toggle("pri", !two);
  if (two) viewer.scene.morphTo2D(0); else viewer.scene.morphTo3D(0);
  viewer.scene.morphComplete.addEventListener(function once() { viewer.scene.morphComplete.removeEventListener(once); home(); });
}
$("v3d").addEventListener("click", () => setView(false));
$("v2d").addEventListener("click", () => setView(true));
$("home").addEventListener("click", home);

$<HTMLInputElement>("server").value = safeGet(KEY) ?? (import.meta.env.VITE_DEFAULT_SERVER as string | undefined) ?? "/data";
$("load").addEventListener("click", () => { setPlaying(false); void loadLatest(); });
$("thr").addEventListener("change", () => { if (volDir) void loadVolume(volDir); });
$("alpha").addEventListener("input", draw);
$("vex").addEventListener("change", draw);
$("sweep").addEventListener("change", draw);
$("cov").addEventListener("change", drawCoverage);
$("xgo").addEventListener("click", applySection);
$("xclear").addEventListener("click", () => { section = null; $("xs").style.display = "none"; draw(); });
$("tsl").addEventListener("input", () => { setPlaying(false); void goto(Number($<HTMLInputElement>("tsl").value)); });
$("play").addEventListener("click", () => setPlaying(timer === undefined));
banner();
