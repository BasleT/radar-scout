# VALIDATION_PLAN.md

Status: **Phase 1 plan. Nothing here has been executed. Every item is "not yet validated".**
Verification tags follow `ARCHITECTURE.md` ([V-primary], [V-secondary], [UNVERIFIED]).

## 0. Validation philosophy

1. **Independence.** Expected values must come from (a) a different decoder or tool, (b) a from-spec byte reading written separately from the engine, (c) closed-form mathematics, or (d) published worked examples. They are never produced by running the code under test.
2. **Fixtures are frozen.** Reference fixtures are read-only, hashed, and listed in a manifest. A change to a fixture or tolerance requires a separate commit whose message states the scientific justification. CI fails if a fixture hash changes without a manifest update. Any test failure is reported as a failure and investigated, never "fixed" by editing expectations (rule 10).
3. **Tolerances are derived, not tuned.** Each tolerance in §4 has a stated physical or numerical basis (quantization step, float precision, documented model difference). Tolerances are fixed *before* the first comparison is run, and the justification is recorded in `tolerances.yaml`. If a tolerance is later found wrong, the change is documented as such.
4. **Three outcomes, not two.** Each check is `PASS`, `FAIL`, or `INCOMPLETE` (reference unavailable). Green tests never mean "scientifically validated". The report ends with an explicit readiness statement (§7).
5. **Implemented ≠ validated.** A status table (`docs/VALIDATION_STATUS.md`, to be created in Phase 3) lists each capability as `not implemented / implemented / validated against <reference IDs>`.

## 1. Reference tools and their own reliability

| ID | Reference | What it provides | Known weaknesses |
|---|---|---|---|
| R0 | ICD 2620002 Rev AA, Table XVII (archived in `docs/sources/`) | Normative field layout and the conversion F=(N−offset)/scale; N=0 below threshold, N=1 range folded **[V-primary]** | A spec describes the format. It does not provide expected values for a specific file. |
| R1 | Spec-derived byte extractor (test-only code, independent of the engine) | Raw N for selected gates, angles, times | Written by us, so it must itself be cross-checked against R2 and R3. A bug shared with the engine is still possible if both come from my reading of the spec. Mitigated by R2/R3. |
| R2 | A second open-source Level II reader (xradar/wradlib) | Independent decode of N, angles, ranges | Third-party. Version-pinned. Its own bugs are possible. |
| R3 | NOAA Weather and Climate Toolkit (NCEI) | Independent decode, gridded/GeoTIFF export **[V-secondary]** | GUI/batch workflow unverified. Algorithm documentation for gridding must be obtained before it is used for 3D comparisons. |
| R4 | Closed-form/high-precision calculations (mpmath, hand-derived) | Beam height, arc distance, geodesic placement | Valid only for the stated model (4/3 Earth). It cannot validate the model against reality. |
| R5 | Numerical ray-trace through a stated refractive-index profile | Sensitivity of beam height to refractivity | The profile is an assumption. This quantifies uncertainty. It is not ground truth. |
| R6 | Published worked examples (Doviak & Zrnić tables/figures, NWS training beam-height charts) | Sanity check on heights vs elevation and range | Must be read from the source. Secondary data not cited here. **[UNVERIFIED availability]** |
| R7 | GridRad or NOAA MRMS echo-top/composite products, if a matching time exists | Echo-top comparison (Phase 7) | Different algorithms and grids and not identical scans, so discrepancies are expected and must be classified. |

## 2. Ground-truth cases (Phase 2 preparation)

Cases are **not yet selected**. Selection criteria:

- **Case A (simple):** stratiform or widespread light-to-moderate precipitation, low vertical development, a single VCP throughout the volume, a station with a clear low-level view of the echo (minimal terrain blockage), and with radar-site metadata present.
- **Case B (vertically developed convection):** deep convection with echo tops well above the 40 dBZ level, a volume with ≥ 9 elevation cuts, preferably containing 50 dBZ cores, and a different station than Case A. Contains range-folded gates and below-threshold gates (so those code paths run on real data).
- For both: file retrieved from the archive; SHA-256 computed; S3 ETag, size and `Last-Modified` recorded; VCP number from the data; acquisition start time; scan metadata (number of sweeps, elevation list, gate spacing, number of gates, Scale/Offset per REF block); the same file cross-checked against a second archive (NCEI) where available, with a hash comparison.
- Selected after listing the archive. I will not name an event until I have retrieved and inspected the listing.

Fixtures to produce (all expected values from R1–R6, never from the engine):

| Fixture | Content | Source of expected values |
|---|---|---|
| `raw_samples.csv` | ~200 selected gates per case: sweep, radial, gate, raw N, with edge cases (N=0, N=1, N=2, N=255, first/last gate, first/last radial, sweep boundaries, split-cut and mixed-resolution rays) | R1, cross-checked with R2 |
| `radial_geometry.csv` | Azimuth, elevation, per-radial time, first-gate range, gate spacing, for the selected radials | R1 with R2 |
| `expected_geo.csv` | lat, lon, height MSL, height ellipsoid, ground arc for the selected gates | R4 (mpmath, pyproj geodesic as an independent implementation), with R2 georeferencing as a cross-check |
| `cross_section_ref.*` | Vertical cross-section along a fixed radial/azimuth, tabulated gates only (no interpolation) | R2 or R3 independent pipeline |
| `thresholds_ref.csv` | For 20/30/40/50 dBZ: highest gate with dBZ ≥ threshold along selected radials/columns, and its height MSL | Computed from R1/R2 raw values and R4 heights |
| `echo_top_ref.csv` | Echo-top heights at the thresholds for selected ground locations, using a declared echo-top definition | R2 plus R4. R7 only as a comparison |
| `fixtures.lock.json` | File hashes, tool versions, date of reference generation, who/what produced each | n/a |

Anything for which no independent reference can be produced is recorded as `INCOMPLETE` in the report.

## 3. Test catalogue (Phase 4)

IDs reference the ten required areas.

| # | Area | Method | Reference | Notes |
|---|---|---|---|---|
| T1 | Raw decoding | Engine raw N, scale, offset and angles vs `raw_samples.csv`, for every fixture gate; engine vs decoder B over the **entire** volume (bitwise-equal N) | R0, R1, R2 | Any mismatch is a failure. Also: unknown data blocks must be skipped (footnote 9), and per-block scale/offset must be used (footnote 20). |
| T2 | Range → coordinates | Engine vs R4 on the fixture gates; synthetic grid of (r, θ, az); radar at the equator, a mid-latitude, near ±180° longitude, and a high latitude | R4, pyproj | Includes the north-pole-adjacent and antimeridian cases as sanity checks for the geodesic code. |
| T3 | Beam height | Engine vs closed-form (4/3) at many (r, θ); vs wradlib `bin_altitude` and Py-ART `antenna_to_cartesian` | R4, R2, R6 | Particular scrutiny: that site altitude is added once; that R=4/3·6371 km vs the WGS84 local radius difference is quantified and documented, not hidden. |
| T4 | Geographic alignment | Engine lat/lon vs R2/R3 georeferenced output for identical gates; round-trip: place → invert (az, range) → compare | R2, R3, R4 | Round-trip with synthetic geometry only. Checks self-consistency, not truth. |
| T5 | Vertical consistency | Along fixed azimuth, successive elevation cuts: height monotonic in range for a given cut, monotonic in elevation at fixed range, cut heights consistent with the closed form. Observed dBZ not asserted to be continuous (that would be a weather assumption). | R4 | Real-data check reports statistics only, since reflectivity differences between cuts are physical. |
| T6 | Threshold extraction and units | Compare dBZ≥T masks against R1/R2 raw N: N ≥ 2·T+66 exactly for T=20,30,40,50 given offset 66 / scale 2; per-block constants used. Comparison done in integer N space to avoid float tie issues, plus a float check at exact threshold boundaries. | R0, R1 | Check ">=" vs ">" convention explicitly and document it. |
| T7 | Missing data | N=0 and N=1 never appear as measured dBZ; they stay in separate classes; below-threshold ≠ clear air; NOT_SCANNED separate from both; masked/NaN propagate through every transformation and export. | R0 | Property-based: for random N arrays, the class partition is exhaustive and exclusive. |
| T8 | Interpolation | Only if implemented. Linear-Z domain vs dBZ-domain test with mathematically known outputs (e.g., averaging two known Z values); boundary: no extrapolation beyond supported data unless labelled; INTERPOLATED never overwrites MEASURED; support/distance fields present. | Closed form | Interpolation is off by default and absent from Phase 3 MVP. |
| T9 | Reproducibility | Same input and config → byte-identical artifacts (hash compare) across two runs and across an environment rebuild; library versions recorded. | n/a | Float summation order controlled. |
| T10 | Metadata and timestamps | Output carries source file name/hash, VCP, per-radial times (UTC, ms resolution preserved), station ID, position; no time rewriting; sweep times are not averaged; start/end times match R1/R2. | R1, R2 | |
| T11 | Schema conformance | Every artifact validates against the JSON schema; `data_class` required; viewer loader rejects invalid data. | Schema | Prevents silent defaults. |
| T12 | Geoid and vertical datum | MSL→ellipsoid conversion vs an independent geoid calculator or published benchmark points (NGS/ GeographicLib `GeoidEval` values); sign and magnitude. | independent geoid tool | Directly protects against the Cesium ellipsoid/MSL trap. |

Techniques:
- **Property-based testing** (Hypothesis): height monotonicity in range at fixed elevation > 0; height ≥ site altitude for non-negative elevation (note: the effective-earth model can place a negative-elevation beam below the site, which is physical, so the property is stated only for θ ≥ 0); geodesic distance equals the model ground arc within the sphere/ellipsoid error budget; class partition exclusivity; invariance to the radial order within a sweep for per-gate computations.
- **Synthetic geometries**, always tagged `synthetic`: a single point target at known (r, az, el); a ring at constant range; a vertical column at constant ground distance; a degenerate zero-range case. The outputs have closed forms. These **never** appear in a viewer layer without a conspicuous SYNTHETIC banner, and are excluded from validation reports of observational data.
- **Mutation testing** of the geometry module (e.g., `mutmut`), to show that the tests would catch a plausible sign, unit, or offset bug.

## 4. Tolerances (to be fixed before the first run; bases stated)

| Quantity | Proposed tolerance | Basis |
|---|---|---|
| Raw integer N | **0 (exact)** | Integers. Any difference is a decoding error. |
| dBZ from N | ≤ 1e-9 dB | Float64 arithmetic of (N−66)/2. Exact in binary for these inputs. |
| Azimuth/elevation from file | exact to float32 representation | Real*4 in the file; compare as float32. |
| Beam height, engine vs closed form (same model) | ≤ 1e-6 m | Float64 evaluation of an identical formula. This is a bug detector. A larger difference means a different formula or a unit error. |
| Beam height, engine vs another library (different Earth radius choice) | Not a pass/fail on equality. Report the difference in metres with the cause (e.g., 6371 km vs WGS84 local radius). | Documented model difference. A tolerance chosen after seeing the result would violate §0.3, so the difference is computed analytically in advance and the observed value must agree with that prediction to ≤ 1 m. |
| Geographic position vs geodesic reference | ≤ 0.01 m horizontal where both use the same sphere/ellipsoid assumption | PROJ is accurate far below this. |
| Horizontal position, sphere-model engine vs ellipsoidal geodesic | Report only (error budget); predicted analytically in advance | Documented model difference. |
| Geoid undulation vs independent calculator | ≤ 0.01 m for the same model | Grid interpolation differences; to be confirmed against the tool. |
| Echo-top height, engine vs independent reference using the same definition | ≤ 1 m (identical gates) | Same data, same formula. |
| Echo top vs a different product (MRMS, GridRad, WCT gridded) | **No pass/fail tolerance.** Report distributions of differences, and classify (§6). | Different grids, interpolation and definitions. Pre-declaring a "good enough" number would be arbitrary. |

All tolerances live in `tolerances.yaml` with their derivations, and changes are reviewed separately from code changes.

## 5. Reproducible validation command (Phase 8)

`python validate.py` (planned) will:
1. Create/verify the pinned environment, and record library versions.
2. Fetch the fixed datasets by exact object key from the archive; verify SHA-256 against `fixtures.lock.json`. Fail loudly if a file is unavailable. It never substitutes other data.
3. Run unit, property and reference tests (T1–T12) and collect results in machine-readable form.
4. Run the comparison suite (§6) and write numerical tables (CSV/JSON).
5. Generate `report/validation_report.md` (+ JSON) containing: tests executed; pass/fail/incomplete counts; reference dataset IDs and hashes; every numerical discrepancy with units and the governing tolerance; unvalidated assumptions (auto-collected from `SCIENTIFIC_LIMITATIONS.md` status fields); known limitations; an explicit **readiness verdict** that defaults to *"not ready for scientifically credible use"* unless all gates in §7 are met.

## 6. Independent comparison (Phase 7)

Quantities: reflectivity discrepancy (per-gate, in integer-N and dB), horizontal and vertical position error (m), echo-top difference at 20/30/40/50 dBZ (m), vertical cross-section agreement (matched gates; residual statistics), and 3D threshold-region disagreement (volume overlap/Jaccard index, with different grids and reported at several resolutions, counted on gate-support and not on interpolated voxels).

Every discrepancy is classified in the report as exactly one of:
- **implementation error** (our bug, so a fix and a regression test are required),
- **reference limitation** (the reference tool is known to do something coarser, documented with a source),
- **data-processing difference** (different declared definition, grid, interpolation, or Earth model, which must be quantified),
- **unresolved** (not yet explained; blocks the readiness verdict).

## 7. Readiness gates

The verdict is "ready for scientifically credible use" only if **all** hold:
1. T1 passes with zero raw-value mismatches on both cases, against R1 and R2.
2. T2, T3, T4, T12 pass against independent references at the stated tolerances.
3. T7/T11 pass, and no code path presents a non-measured value as measured.
4. No `unresolved` discrepancy remains in §6.
5. Every `INCOMPLETE` check is listed in the report, and each is judged not material to the claimed uses (else the verdict is "partially validated").
6. `SCIENTIFIC_LIMITATIONS.md` is current and surfaced in the viewer UI.

A passing report still does **not** certify that displayed reflectivity represents physical cloud or hazard boundaries. It certifies only the documented transformations.

## 8. Open verification tasks (Phase 1 → 2)

1. Extract Table XVII-A (radial header: azimuth, elevation, time fields, radial status) from the archived ICD and fix the byte layout used by R1.
2. Obtain and read Doviak & Zrnić §2.2 (Eq. 2.28) or a worked example, and verify the figure −39 N-units/km / ke = 4/3.
3. Confirm pyproj geoid support (EGM96/EGM2008 grids) and pick the independent geoid tool for T12.
4. Test environment installability (Py-ART, xradar/wradlib, pyproj) on Windows 11 / Python 3.10.
5. Determine whether NCEI and the Unidata bucket serve byte-identical files for the selected cases.
6. Establish the WCT batch workflow and document its gridding algorithm, or drop R3 from the plan.
7. Check the antenna-height question: does feedhorn height = site height + tower height in the engine and in each reference? (ICD Table XVII-E/F.)
