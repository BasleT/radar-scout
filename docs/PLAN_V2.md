# PLAN_V2.md: scope, requirements and roadmap (2026-11-03)

Supersedes the "desktop-only, points-only" scope of the original brief. The scientific rules of the original brief and
`ARCHITECTURE.md` §1 are unchanged and still win any conflict with this file.

## 1. Product goal
A personal, dark-themed Android weather-radar app (RadarScope/RadarOmega/F5-Radar class) that shows NEXRAD data in true
3D, where **every displayed value stays traceable to the source file** and every derived or resampled picture is
labelled as such. Not an operational or safety product. Personal use; not published.

## 2. Architecture (unchanged split, clarified)
- **pve1 (Docker): engine + static server.** All decoding, unit conversion, beam geometry, geoid, resampling and
  derived products happen here, in Python, with provenance and a checksum on every artifact.
- **Phone / desktop viewer: draws only.** Cesium (WebGL) renders prepared artifacts and does display-level work only
  (colour palette, opacity, camera, picking). No beam physics, no resampling, no binning of data. The voxel binning that
  the first volume mode did in the viewer (`drawVolume`) is a **known violation** of this rule and is to be moved to the
  engine (R5).
- Artifacts are GPU-ready where possible (bytes + palette), so transfer and parse cost stay small.

## 3. Reference research (what typical 3D radar rendering does)
Studied (concepts only, nothing copied): F5 Radar (inspected locally by the owner; closed source, not distributed), the
MIT-licensed `andyfangdz/approach-viz`, and the public Level III archive. Findings that shape the requirements:
1. **Cone sweeps.** Each tilt is one polar texture (azimuth x range, 1 byte per gate); a polar mesh is turned into a
   cone by the standard beam geometry; colour comes from a 1-D palette texture. Cheap and uses real gates only.
2. **Voxel blocks.** One box per bin, with the 4/3-Earth drop applied.
3. **Smooth volume.** The polar data are resampled onto a **local Cartesian 3D grid around the storm** (order of
   256 x 256 x 96 cells, 16-bit float), built by **inverse mapping** (for each voxel compute range, azimuth, elevation and
   look up the gate), with a coarse max-pooled occupancy grid for empty-space skipping. A raymarcher then draws either
   translucent accumulation or a **shaded iso-surface** (threshold crossing, bisection refinement, gradient normal,
   soft lighting, per-pixel start jitter to hide banding). Height needs strong exaggeration or storms look flat.
4. **Quality processing:** velocity dealiasing, storm-relative velocity, and **SAILS** (several low cuts per volume).
5. **NWS-computed products are published.** NOAA's Level III archive (public bucket `unidata-nexrad-level3`, keys like
   `TLX_EET_YYYY_MM_DD_hh_mm_ss`) carries echo tops (EET), VIL density (DVL), KDP (N0K), hydrometeor class (HHC), storm
   tracks (NST), hail/mesocyclone/TVS products and more. Verified by listing the bucket; date coverage and file format
   details are **not yet checked** for the cases we want.

## 4. Requirements
Priority P0 = needed for the goal; P1 = should have; P2 = later. "Verify" names the check that must exist before the
item is called implemented (never "validated": see VALIDATION_PLAN.md).

| ID | Req | Pri | Verify |
|---|---|---|---|
| R1 | **[IMPLEMENTED 2026-11-03 for 8-bit products; PHI needs a 16-bit texture] Filled-sweep rendering (2D map and 3D cones).** Engine publishes, per elevation cut and product, a polar byte texture (raw N), scale/offset, per-radial azimuth/elevation/time, gate geometry, and a coarse positional mesh computed with the engine's own geometry. Viewer draws the mesh, samples the texture per pixel, colours via a palette texture. Gates not scanned / below threshold / folded are distinguishable (not painted as zero). | P0 | texture bytes equal decoded raw N gate-for-gate (independent spec reader); mesh positions equal `place_gates` at knots; round-trip pick returns the same gate as `gates.bin` |
| R2 | **Storm library / archive.** Publish named historic cases (El Reno 2013-05-31, Moore 2013-05-20, KDIX 2014 case, others) from the public archive via the same engine; list them in the app with site and time pinned. | P0 | each volume keeps source SHA-256; app lists only what the server published |
| R3 | **Time playback done right.** Per-sweep time shown; loop over volumes; "go live" jump; no claim that sweeps are simultaneous. | P0 | UI shows per-radial time (exists); playback uses index.json only |
| R4 | **Shareable moment link** (site, volume, product, camera in the URL). | P1 | URL round-trip test |
| R5 | **Derived local 3D grid (engine).** Storm-centred Cartesian grid built by inverse mapping from the polar data, written as 3D texture + occupancy + manifest (method, grid spec, nearest vs interpolated, source SHA-256, "DERIVED / INTERPOLATED"). Replaces the viewer-side voxel binning. | P0 | resampled value at sample voxels equals the nearest-gate value (nearest mode) or the stated interpolation (checked against a direct implementation); occupancy never under-reports max; grid round-trips through the independent reader |
| R6 | **Volume render modes in the viewer:** Points (exact, default), Cones (R1), Voxel blocks, Smooth volume (translucent) and Iso-surface, the last three reading R5 and always showing a persistent DERIVED label. | P0 | visual check on a real tornado case, plus the label test |
| R7 | **Velocity dealiasing and storm-relative velocity** in the engine (Py-ART dealiasing, with the storm-motion input shown on screen and recorded in the manifest, never silently chosen). Resolve the velocity sign convention from an authoritative source first (L25). | P1 | compare to Py-ART reference output; synthetic aliased case with known answer |
| R8 | **SAILS / split-cut handling.** Cut selection and "lowest sweep" logic must work with repeated low elevations. | P1 | VCP 212/215 fixture with extra low cuts |
| R9 | **NWS warnings, SPC outlook and storm-report overlays** (public, timestamped, labelled "not an official warning source"). | P1 | each overlay shows source, fetch time and validity time |
| R10 | **Level III products:** EET, DVL, N0K (KDP), HHC, NST, hail/TVS/MD fetched and decoded from the NOAA bucket, shown with their NWS product name, not recomputed by us. Check Py-ART/MetPy support first. | P1 | decoded values equal an independent reader on at least one file |
| R11 | **Vector basemap** option (needs a map key) or keep Esri raster tiles. Decision pending: raster is fine for now. | P2 | n/a |
| R12 | **Ground layer:** low-tilt reflectivity painted under the 3D view so the storm has a footprint (comes from R1's lowest sweep, not a separate product). | P1 | label states beam height of that sweep |
| R13 | Dual-pol quality control and hydrometeor classification (our own). | P2 | **skipped on purpose:** use NWS HHC (R10) |
| R14 | AR camera view, push alerts, Android Auto, accounts, subscriptions. | P2 / out | not planned (location/Firebase collection) |
| R15 | Move validation to Linux/pve1 and the live archive, including current LDM-bzip2 files (L17, L21, L29). | P0 | engine container runs end to end against a live volume |

## 5. Scientific-honesty rules for the new modes
- **Resampling is interpolation.** R5 output is labelled DERIVED/INTERPOLATED in the file, the app and on every
  screenshot-able view; nearest-gate mode is the default and the method is stated.
- **Max-per-voxel** summaries (first volume mode) are labelled as a display reduction and are removed once R5 exists.
- **Iso-surface and smooth volume imply a boundary and a certainty the data do not carry** (ARCHITECTURE §6): off by
  default, persistent label, per-gate Points mode always one tap away.
- **Level III products are NWS outputs**: show the NWS product code and file time; do not blend them with our values.
- **Vertical exaggeration** is always displayed when not 1x.
- Beam width stays NaN until it is decoded from an authoritative source (L24); sprite or voxel size is a display choice.

## 6. Roadmap
1. **Foundation (now):** R15 container run on pve1 against the live archive; R2 El Reno and Moore published; R3.
2. **Sweeps:** R1 + R12 (cones and filled 2D map).
3. **Derived volume:** R5 + R6 (voxel blocks, smooth volume, iso-surface) with the DERIVED label and tests.
4. **Science depth:** R8, then R7, then R10 (Level III products).
5. **Overlays and sharing:** R9, R4.
Each step updates `docs/VALIDATION_STATUS.md` and `SCIENTIFIC_LIMITATIONS.md` in the same commit.

## 7. Explicit non-goals
Operational or safety use; copying any third-party app's code, assets, colour tables or wording; publishing the app;
our own hail/mesocyclone/TVS detection algorithms; accounts, analytics or location collection.
