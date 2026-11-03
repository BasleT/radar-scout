# Validation status (implemented != validated)

As of Phase 4. "Validated" means: compared against the named independent reference(s) on the two cases below, within
the tolerance in `tolerances.yaml`, with the result in `report/validation_report.md`. It does NOT mean scientifically
correct in general.

Cases: KTLX20130520_195111_V06 (sha256 d41dcfa4...), KDIX20140430_120023_V06 (sha256 f384c447...).

| Capability | Implemented | Validated against | Status |
|---|---|---|---|
| Level II decode, REF raw N (engine) | yes (`engine/decode.py`, Py-ART NEXRADLevel2File) | from-spec reader R1 (gate-for-gate, 15.6 M gates), xradar (N>=2) | validated on 2 cases |
| Radial angles, times, gate geometry, scale/offset | yes | R1 exact equality | validated on 2 cases |
| dBZ conversion, class partition (N=0/1/>=2) | yes | R1, closed form, property tests | validated on 2 cases |
| Beam height / ground arc (4/3 model) | yes (`engine/geometry.py`) | 40-digit mpmath, Py-ART formula | validated for the model (not for real refraction) |
| Horizontal placement (WGS84 geodesic) | yes | GeographicLib | validated for the method; differs from Py-ART spherical by up to 0.25% (L10) |
| Echo-top (highest measured gate >= T) | yes (test helper only) | independent fixture, same definition | validated for definition; no external product compared |
| MSL -> ellipsoid height | yes (`engine/geoid.py`) | sanity vs EGM96 only | NOT independently validated |
| Antenna height assumption | yes | tool conventions only | unvalidated assumption (L20) |
| Beam width / sample volume | no | - | not implemented (L24) |
| Interpolation | no (by design) | - | absent; tests assert none occurs |
| Coverage (NOT_SCANNED) regions | partially (derivable from radials table) | - | not validated |
| Other moments VEL, SW, ZDR, PHI, RHO (`engine/decode.py`, `build_moment_samples`) | yes | spec reader R1: raw N, scale, offset, gate geometry equal for every radial on both volumes (`tests/test_moments.py`); conversion equals closed form; values inside ICD Table XVII-I ranges (4-digit-truncation slack stated in the test) | raw decode and unit conversion validated on 2 cases; no QC, no sign-convention check (L25, L26) |
| Viewer-ready reduction (`engine/viewer_export.py`) | yes | `tests/test_viewer_export.py`: output is an exact subset of engine samples; accounting adds up; refuses missing ellipsoid height. Uses a labelled synthetic geoid offset, not real geoid values | subset logic verified on KDIX; reduction itself is not a measurement |
| Fetch + publish (`engine/publish.py`, Docker on pve1) | yes | none: not run against the live archive; not run on Linux; Message Type 31 LDM-bzip2 files from the current archive untested (L17, L21) | NOT validated |
| Viewer (Cesium, point primitives, click inspect, loader checks) | yes, first version | `npm run build` type-checks and bundles. Not opened in a WebView2/Android WebView; no rendering or position check against any reference | NOT validated; Phase 5 incomplete |
| Android debug APK / Windows exe | build scripts + CI workflow | APK build result recorded in the commit message; not installed or run on a device | NOT validated |
| Inspection mode (Phase 6) | minimal click panel (class, dBZ, raw N, position, heights, source indices) | none; no link back to the original source bytes yet | NOT validated |
| External product comparison (WCT, MRMS, GridRad) | no | - | Phase 7, INCOMPLETE |
