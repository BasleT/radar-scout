# ARCHITECTURE.md — Scientifically Verifiable 3D NEXRAD Visualization

Status: **Phase 1 (research and design). No application code exists yet.**
Scope: single desktop application (Tauri 2 + TypeScript + CesiumJS) on the Windows development host, with the Python/Py-ART engine as the reference processor. No mobile or cross-platform targets.
Date: 2026-11-02

Every factual claim is tagged with its verification status:

- **[V-primary]** read by me in the primary source (file and section given).
- **[V-secondary]** confirmed only through library documentation or secondary summaries. Re-check against the primary source before relying on it.
- **[UNVERIFIED]** from background knowledge or an open question. This must not be treated as established.

---

## 1. Guiding principles (map to the project rules)

| Rule | Architectural consequence |
|---|---|
| Never invent data (1, 2) | The engine has no code path that generates weather. Synthetic geometry lives only under `tests/synthetic/`, is tagged `synthetic=true`, and is never importable from the app. |
| Measured / interpolated / extrapolated / unavailable (4) | Every output sample carries a mandatory `data_class` enum: `MEASURED`, `BELOW_THRESHOLD`, `RANGE_FOLDED`, `NOT_SCANNED`, `INTERPOLATED`, `EXTRAPOLATED`. The enum is required by the schema (§5). |
| Metadata and timestamps (5) | Per-radial timestamps are preserved. Volume time is never substituted for sweep or radial time. |
| Engine independent of renderer (6) | Python engine → versioned, schema-validated artifacts on disk → TypeScript viewer. The viewer does no scientific computation beyond display (§6). |
| Prefer validated libraries (7) | Py-ART and/or xradar/wradlib for decoding and the geometry baseline; pyproj for geodesy. Custom math is allowed only where noted in §4 and is cross-checked against the libraries. |
| Traceability (9) | Each displayed value maps to `(source_sha256, volume, sweep, radial, gate, raw_N)` plus a list of named transformations. |

---

## 2. Data source and format

### 2.1 Source
- NEXRAD Level II ("Archive II") is archived in a public AWS bucket. The NSF Unidata-hosted bucket `unidata-nexrad-level2` is the current bucket. Updates to the legacy `noaa-nexrad-level2` bucket were discontinued on 2025-09-01 **[V-secondary: Unidata announcement https://www.unidata.ucar.edu/blogs/news/entry/important-changes-to-noaa-nexrad]**. Bucket layout is `/<Year>/<Month>/<Day>/<Station>/<file>`. Names look like `KXXXYYYYMMDD_HHMMSS[_V06]`. Files are gzip-compressed in older years **[V-secondary: AWS Open Data registry search results]**. The NCEI Weather and Climate Toolkit 4.9.0 also switched to the Unidata bucket **[V-secondary: https://www.ncei.noaa.gov/node/5596]**.
- Alternative authoritative archive: NCEI/NCDC (the official NOAA archive of record). For Phase 2 each fixture records the origin bucket and whether it was cross-checked against NCEI. **[UNVERIFIED: that the two copies are byte-identical for a given file. This must be tested in Phase 2 by comparing hashes.]**
- AWS provides no checksum I could confirm. We compute **SHA-256 locally** and also record the S3 ETag and `Last-Modified`. An ETag is not a content hash for multipart uploads, so it is only informational.

### 2.2 Format specification (primary sources)
Fetched and archived: `docs/sources/2620002AA.pdf` (ROC ICD 2620002, Rev AA, Build 24.0, 19 Aug 2025). SHA-256 `98b29802f0c598c51a768217e37f007ec231571e098e8c2fa0ac92c6059b1a81`. Extracted text is in `docs/sources/2620002AA.txt`.
Listing of ICDs: https://www.roc.noaa.gov/interface-control-documents.php

- ICD **2620010** ("Archive II/User") defines the archive file wrapper. Rev J / Build 23.0 was read in part. Files hold compressed records of 120 radials (type 31) plus RDA status messages, and Message Type 31 is variable-length **[V-primary: 2620010J.pdf, sections near lines 581 and 658 of the extracted text]**.
- ICD **2620002** (RDA/RPG) defines Message Type 31 in Table XVII **[V-primary]**:
  - Table XVII-E `VOL` block: latitude and longitude (Real*4, deg), `Site Height` = "height of site base above mean sea level" (m, SInteger*2), `Tower Height` = "height of tower above ground level" (m), VCP number.
  - Table XVII-H `RAD` block: unambiguous range, Nyquist velocity, noise levels.
  - Table XVII-B moment header: first-gate range to the *center* of the first gate (km), gate sample interval (km), number of gates. Moment names are `REF`, `VEL`, `SW`, `ZDR`, `PHI`, `RHO`, `CFP`.
  - Table XVII-I footnote 15: a nonzero Scale means the data are unsigned integers with **F = (N − OFFSET) / SCALE**. Scale = 0 means floating-point data.
  - Footnote 21: for REF, VEL, SW, ZDR, PHI and RHO, **N = 0 means below threshold and N = 1 means range folded**. Real data start at N = 2.
  - Footnote 20: the typical REF Offset = 66.0 and Scale = 2.0 (0.5 dB steps), but readers **must use the per-block Scale and Offset**.
  - Footnote 9: readers must ignore unknown block types. The moment set varies by VCP.
  - Footnote 5: the azimuth spacing field is the *commanded* spacing, not necessarily the actual spacing.
- Open items, **[UNVERIFIED]**: the exact elevation and azimuth angle field definitions in Table XVII-A (the radial header), the per-radial time fields, the radial status codes, and whether `Site Height + Tower Height` is the feedhorn altitude or the ICD intends something else. These must be extracted from Table XVII-A/F and Table III before the decoder is finalized.

### 2.3 Reflectivity semantics
Reflectivity Z is in dBZ = 10·log10(Z / 1 mm⁶ m⁻³). It is logarithmic. Averaging, interpolation and resampling must therefore **not** be done on dBZ values directly. The conventional approach is to average linear Z and convert back, but this is a processing choice that must be declared. **[UNVERIFIED as to which approach each reference tool uses. Phase 2 must document this per tool.]**

dBZ describes backscattered power from hydrometeors. It is **not** a cloud boundary, a liquid water content, or a rain rate. See `SCIENTIFIC_LIMITATIONS.md`.

---

## 3. Library survey and decision

| Candidate | Role | Evidence | Decision |
|---|---|---|---|
| **Py-ART** (Helmus & Collis 2016, DOI 10.5334/jors.119) | Level II reader (`pyart.io.read_nexrad_archive`; supports message types 1 and 31), `antenna_to_cartesian`, gridding | Reader docs read **[V-secondary]**. Gates not collected are masked; the docs do not discuss range folding. `linear_interp=True` by default for mixed-resolution rays, **which is an interpolation we must disable or record**. | **Primary decoder candidate (A).** Set `linear_interp=False` and report any resolution mismatch. |
| **xradar / wradlib** (open_radar_data ecosystem) | Independent Level II reader and georeferencing (`wradlib.georef.bin_altitude`, `spherical_to_proj`) | wradlib georef docs read; `bin_altitude` uses the Doviak formula with default ke = 4/3 **[V-secondary]**. The docs say 4/3 is wavelength-dependent in principle. Whether wradlib reads Level II itself or defers to xradar is **[UNVERIFIED]**. | **Independent decoder (B)** for cross-validation. |
| **pyproj** (PROJ) | WGS84 geodetic and geocentric transforms, AEQD projection, forward azimuth/distance | **[UNVERIFIED in this session; standard and widely validated]** | Used for all geodesy. No hand-rolled ellipsoid code. |
| **A from-spec minimal byte reader** | Independent ground-truth byte extraction for *selected* gates | Required by rule 8/Phase 2 to avoid a decoder shared with the code under test | Tests only (`tests/reference/`). It is not used by the app, and it is limited to a few hundred gates read via `struct` straight from the ICD table. |
| **NOAA Weather and Climate Toolkit (WCT)** | Independent reference product | NCEI describes export to GeoTIFF, NetCDF, shapefile and others, and batch/command-line operation **[V-secondary: ncei.noaa.gov/node/5596 and AMS abstracts]**. Whether it reads current Level II without GUI and what its georeferencing assumptions are is **[UNVERIFIED]**. | Reference product (R2). Its algorithms must be documented before comparison. Not authoritative by default. |
| **GridRad** (Texas A&M/Univ. Oklahoma gridded NEXRAD) | Reference for 3D gridded composites | Algorithm description found at dcotss.geos.tamu.edu **[not read]** | Candidate for the Phase 7 cross-check only. Its gridding differs from ours by design. |
| Cesium 3D / deck.gl / VTK | Rendering | See §6 | See §6. |

**Decision:** Python engine built on Py-ART as decoder A. A second decoder B (xradar or wradlib) plus a spec-derived byte extractor cross-check A. Disagreement between A and B on any raw integer N is a **hard failure**, not something to tolerate. Geodesy uses pyproj.

---

## 4. Coordinate and propagation mathematics

### 4.1 Beam geometry baseline (4/3 effective Earth radius)
Py-ART implements Doviak & Zrnić (1993) Eq. 2.28(b)/(c) for the standard atmosphere **[V-secondary: https://arm-doe.github.io/pyart/API/generated/pyart.core.antenna_to_cartesian.html]**:

- R = (4/3)·6371 km (Py-ART). wradlib's `bin_altitude` takes `re` and `ke` as parameters.
- z = sqrt(r² + R² + 2·r·R·sin θe) − R
- s = R·arcsin(r·cos θe / (R + z))
- x = s·sin θa, y = s·cos θa

wradlib gives the same height form, h = sqrt(r² + (ke·re)² + 2·r·ke·re·sin θ) − ke·re, plus `sitealt` **[V-secondary: https://docs.wradlib.org/en/1.19.1/generated/wradlib.georef.misc.bin_altitude.html]**.

Caveats:
- These are **height above the radar's local reference sphere**. The radar site altitude must be added, and it is defined relative to MSL (ICD) **[V-primary]**.
- 4/3 assumes a standard atmospheric refractivity gradient of about −39 N-units/km **[UNVERIFIED as to the exact figure; confirm against Doviak & Zrnić Ch. 2 or Bean & Dutton]**. Real beams in non-standard conditions (ducting, super-refraction) deviate. This is irreducible without sounding data, and we do not have it. It is a documented uncertainty, not an error we can correct.
- Equation page and number come only from secondary sources. I have **not** read Doviak & Zrnić itself. Validation therefore requires (a) an independently derived check of the formula from first principles, and (b) a numerical ray-trace with a stated refractive index profile as a sensitivity bound.

### 4.2 Geodetic placement
- Polar coordinates (azimuth, elevation, slant range) → ground arc distance and beam height (§4.1) → geodetic lat/lon via the **forward geodesic on WGS84** (pyproj `Geod.fwd`) from the radar geodetic position, using azimuth as true bearing. **Do not** use a flat-earth x,y offset for lat/lon. For a sphere-based s, the sphere/ellipsoid mismatch is an explicit error budget item (expected on the order of the 0.3% ellipsoid flattening scale, **[UNVERIFIED magnitude, to be quantified numerically in Phase 4]**).
- NEXRAD azimuth is relative to **true north** and measured clockwise **[UNVERIFIED: confirm in ICD Table XVII-A azimuth field definition]**.
- The radar position in the VOL block is Real*4 degrees, presumably WGS84. The datum is **not stated** in the sections I read **[UNVERIFIED]**. NAD83 vs WGS84 differences are around 1 m in CONUS, which is small relative to the 250 m gate size, and this is recorded as a limitation.

### 4.3 Vertical reference: MSL vs ellipsoid (critical)
- ICD site height is above **mean sea level** **[V-primary]**. The geoid model behind that MSL is not specified in the portion read **[UNVERIFIED]**.
- CesiumJS positions use **heights above the WGS84 ellipsoid**, and terrain heights in Cesium quantized-mesh data are ellipsoid-relative **[V-secondary: CesiumJS `sampleTerrain` docs, Cesium community threads]**. Cesium staff say that a terrain source returning geoid heights must be converted to ellipsoid heights.
- Therefore: `h_ellipsoid = h_msl + N`, where N is the geoid undulation (EGM96 or EGM2008, **to be chosen and recorded; we use EGM2008, to be implemented via pyproj's geoid grids or GeographicLib**). In CONUS, |N| is tens of metres (≈ −20 to −35 m **[UNVERIFIED rough range, to be tabulated for the actual stations]**), which is not negligible against 250 m–1 km vertical features. Sign convention gets a dedicated test against a published reference point.
- The engine outputs **both** `height_msl_m` (primary, as the physics/ICD defines it) and `height_ellipsoid_m` (derived, geoid model and version recorded). The viewer uses only the latter, for placement.
- **Terrain-relative altitude** (above ground level) requires a DEM. Candidates are USGS 3DEP or SRTM. Their vertical datum is NAVD88 or EGM96, and the DEM's own vertical error is tens of centimetres to metres. AGL is a *derived* quantity with a declared DEM source. It is **not** a measurement.

### 4.4 Beam broadening and sampling volume
- WSR-88D beamwidth is about 0.9–1.0° (values found: 0.96° at 2.7 GHz, 0.88° at 3.0 GHz, 0.925° listed elsewhere) **[V-secondary: search results, not primary; confirm against the NEXRAD Technical Information document at roc.noaa.gov/public-documents/wsr88d/NEXRAD-Technical-Information.pdf]**.
- Beam width at range r ≈ r·Δθ (Δθ in radians), about 1.7 km at 100 km and 4.2 km at 250 km for 0.96° (own arithmetic, to be test-verified). A gate is a polar sample volume, **not a point**. The 250 m "gate size" is only the range extent.
- Consequences encoded in the data model: each sample carries `beamwidth_deg`, `range_m`, derived `beam_half_width_m`, and `beam_center_height_m`. It does **not** carry an implied thickness for the cloud.

### 4.5 Coverage geometry
- Cone of silence above the highest elevation cut, and gaps between elevation cuts, are **not scanned** space. These must be exposed as `NOT_SCANNED` regions rather than empty/no-echo.
- Lowest-beam blockage and ground clutter handling is out of scope (§8 limitations). We do **not** apply clutter filtering beyond what is in the source data.
- VCP elevation angles differ per VCP. Example found: VCP 12 and 212 use 14 angles, 0.5° to 19.5° **[V-secondary: search result summary; confirm in ICD Appendix C]**. The engine reads actual angles from the radials, not from a VCP table.

### 4.6 Time
- Each radial has its own timestamp (Table XVII-A fields **[UNVERIFIED: field names and epoch to be extracted]**). A full volume takes minutes (VCP 12 about 4.3 min, VCP 212 about 4.6 min **[V-secondary]**). Sweep times are never merged. The 3D display of a "single volume" must show the time spread, and cross-sections through multiple sweeps must show the max time difference.

---

## 5. Data model and provenance

Engine output = per-volume artifact set:

```
out/<station>_<volume-id>/
  manifest.json        # schema-versioned; source file name, sha256, S3 etag, VCP, library versions, git commit,
                       # geoid model, ke, re, config used, run timestamp
  samples.parquet      # one row per retained gate
  sweeps.json          # per-sweep: elevation (nominal & per-radial actual), start/end time, nyquist, gate spacing, first-gate range
  coverage.*           # NOT_SCANNED regions (derived, labeled)
```

Per-sample columns (required, no silent defaults):

`source_sha256, volume_id, sweep_idx, radial_idx, gate_idx, raw_N, scale, offset, dbz (float64; NaN where N<2), data_class, azimuth_deg, elevation_deg, slant_range_m, range_to_gate_center_m, radial_time_utc, lat_deg, lon_deg, height_msl_m, height_ellipsoid_m, ground_arc_m, beamwidth_deg, transform_chain (ordered list of {name, version, params})`

Rules:
- `raw_N` is always kept. `dbz` is derived by `F = (N − offset) / scale` using the *per-block* constants.
- N = 0 → `BELOW_THRESHOLD`, N = 1 → `RANGE_FOLDED`. These are **not** converted to a dBZ number, and **not** treated as "no precipitation".
- Interpolated grids (if produced) are a **separate artifact** with their own `data_class=INTERPOLATED`, the method, kernel, the linear-Z vs dBZ domain, and per-cell support/distance-to-nearest-measurement fields. The viewer can never load these under the measured layer's name.
- Original-measurement retrieval (Phase 6): `(source_file, volume, sweep, radial, gate)` is sufficient to re-read the original byte. A CLI `engine fetch-raw` re-decodes from the source via decoder B.

---

## 6. Visualization technology

### CesiumJS (primary)
- WGS84 globe with ellipsoid-height positioning, matching §4.3 **[V-secondary]**; custom geometry/primitive APIs; time-dynamic support.
- Terrain: Cesium World Terrain requires a Cesium ion token, and its geoid/datum handling is not documented in anything I found **[UNVERIFIED]**. The default provider (ellipsoid, no terrain) is the safe fallback. Alternative terrain from open DEM (3DEP/SRTM) converted to quantized-mesh is possible but not designed here.
- Volume rendering: Cesium has no native volumetric renderer. Options evaluated, in decreasing order of scientific defensibility:
  1. **Per-gate polar-cell primitives** (each gate's truncated wedge using azimuth width, range extent and beam width at that range) filtered by threshold, rendered with instanced geometry or a custom Primitive. Faithful to measurement support. Cost: many cells, so level-of-detail is needed. *Preferred for "measured" mode.*
  2. Thresholded point cloud with a point size matching the sample volume. Cheap, and visibly discrete, which avoids false continuity.
  3. Iso-surfaces/marching cubes on an interpolated grid. This yields a smooth, plausible-looking surface that **implies a physical boundary and certainty the data do not support**. Allowed only as a clearly styled "DERIVED/INTERPOLATED" mode, off by default, with a persistent label.
- Alternatives not chosen as the baseline: deck.gl, VTK/ParaView (strong for scientific volume work; good for the independent *reference* visualizations), and three.js. None change the engine design, because the engine/viewer boundary (§5) is renderer-neutral.

### Application shell (scope: desktop only)
- **Tauri 2 + TypeScript + CesiumJS**, as a single desktop application. Android, iOS, macOS and Linux are out of scope, and there are no cross-platform or mobile requirements. The development machine (Windows 11) is the only platform that is built and tested. Tauri on Windows renders in the system WebView2 **[UNVERIFIED in this session: Cesium WebGL2 behavior inside WebView2 must be checked in a Phase 5 spike before the shell choice is final. The fallback is a plain browser tab served locally, which needs no architectural change.]**
- The shell is thin. It opens engine artifacts from disk (§5), hosts the viewer, and gives access to the original source file for the Phase 6 "retrieve original measurement" feature.
- **No scientific code in Rust or JS.** All decoding, geometry and unit conversion stay in the Python engine, which is the single implementation. This avoids a second decoder that would need its own validation. The engine runs as a separate offline step (CLI), and the app does not embed Python. If on-the-fly processing is wanted later, it would call the engine as a subprocess, which is not planned.
- Nothing here adds servers, cloud services, or accounts. Data is fetched from the public archive by the engine CLI.

### Viewer constraints
- TypeScript, strict mode; schema-validated loaders (JSON schema or zod) generated from the same schema the Python engine writes; **no recomputation of dBZ, heights, or coordinates in JS**.
- Vertical exaggeration default 1×, and any non-1× value is shown persistently in the UI.
- Inspection panel (Phase 6) reads exclusively from fields in §5.

---

## 7. Project layout (proposed)

```
engine/            Python package (decode, geometry, provenance, export). No rendering imports.
engine/schema/     JSON schema (single source of truth for the artifacts)
tests/reference/   independent from-spec readers & third-party-derived expected values (read-only fixtures)
tests/synthetic/   mathematically known geometries (labelled synthetic)
fixtures/          real data manifests (+ hashes); raw files fetched, not committed if large
viewer/            TypeScript + CesiumJS, wrapped by Tauri 2 (src-tauri/ is shell glue only)
docs/sources/      archived primary spec excerpts + checksums
validate.py        single reproducible validation command (Phase 8)
```

Environment notes: single supported platform is the Windows 11 development host, Python 3.10.11 present. Py-ART requires a compatible scientific Python stack; I have **not** yet confirmed installability on this Windows setup (**[UNVERIFIED]**). A pinned lock file or conda env is a Phase 3 prerequisite.

---

## 8. Decisions needing confirmation before Phase 2

1. Which radar sites/cases? Proposed selection criteria are in `VALIDATION_PLAN.md` §2. No specific event has been selected, and I will not assume one exists in the archive until I have fetched its listing.
2. Commit workflow: this directory is not a git repository. I propose `git init` and one commit per deliverable.
3. A Cesium ion token for World Terrain is optional. Without it the viewer uses an ellipsoid-only globe.
4. Scope is a desktop application on the Windows development host only. I interpreted "desktop only" as Windows, since that is the host. Say so if you want another desktop OS.

## 9. Source list

- ROC ICD index: https://www.roc.noaa.gov/interface-control-documents.php
- ICD 2620002 Rev AA (Build 24.0): https://www.roc.noaa.gov/public-documents/icds/2620002AA.pdf (archived, hash above)
- ICD 2620010 Rev J: https://www.roc.noaa.gov/public-documents/icds/2620010J.pdf
- Unidata bucket-change notice: https://www.unidata.ucar.edu/blogs/news/entry/important-changes-to-noaa-nexrad
- Py-ART reader: https://arm-doe.github.io/pyart/API/generated/pyart.io.read_nexrad_archive.html
- Py-ART geometry: https://arm-doe.github.io/pyart/API/generated/pyart.core.antenna_to_cartesian.html
- Helmus & Collis (2016), J. Open Research Software 4(1):e25, DOI 10.5334/jors.119
- wradlib georef: https://docs.wradlib.org/en/stable/georef.html ; `bin_altitude`: https://docs.wradlib.org/en/1.19.1/generated/wradlib.georef.misc.bin_altitude.html
- Doviak & Zrnić, *Doppler Radar and Weather Observations*, 2nd ed., Dover/Academic Press, 1993 (not read directly)
- NCEI Weather and Climate Toolkit: https://www.ncei.noaa.gov/node/5596
- CesiumJS `sampleTerrain` docs and community threads on ellipsoid-relative terrain heights (secondary)
- NEXRAD Technical Information: https://roc.noaa.gov/public-documents/wsr88d/NEXRAD-Technical-Information.pdf (not read)
- GridRad algorithm description: https://dcotss.geos.tamu.edu/pdf/GridRad-v3.1-Algorithm-Description.pdf (not read)
