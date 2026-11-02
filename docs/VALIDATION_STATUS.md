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
| Viewer, inspection mode | no | - | Phases 5-6 |
| External product comparison (WCT, MRMS, GridRad) | no | - | Phase 7, INCOMPLETE |
