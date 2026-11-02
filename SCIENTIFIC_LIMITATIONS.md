# SCIENTIFIC_LIMITATIONS.md (permanent; update with every phase)

Last updated: 2026-11-02 (Phase 1). Status key: **OPEN** = unresolved; **KNOWN** = inherent in the data or model, only documentable; **MITIGATED** = handled in design, to be verified.

| ID | Limitation | Status | Treatment |
|---|---|---|---|
| L1 | Reflectivity (dBZ) measures backscattered power from hydrometeors within a pulse volume. It is not a cloud boundary, liquid water content, rain rate, or hazard level. Absence of echo does not mean absence of cloud. | KNOWN | UI wording avoids "cloud". Thresholds are labelled "reflectivity ≥ X dBZ". |
| L2 | Radar beam is about 1° wide. Sample volumes grow with range (about 1.7 km wide at 100 km, using 0.96°, own arithmetic to be verified). Vertical position of a gate is the beam-center height, not an exact location. | KNOWN | Per-sample beamwidth and half-width stored. Gates drawn as volumes, not points. |
| L3 | Beam height assumes the standard 4/3 effective Earth radius. Real refraction varies, and ducting or super-refraction can displace beams by amounts not recoverable without sounding data. | KNOWN | Stated on every height. Sensitivity bound via ray-trace (VALIDATION_PLAN R5). |
| L4 | Coverage gaps: cone of silence above the top elevation cut, gaps between cuts, and beam overshoot at long range. Terrain blockage and clutter are not corrected. | KNOWN | `NOT_SCANNED` regions shown. No filling. |
| L5 | Volume scans take several minutes (VCP 12 about 4.3 min, VCP 212 about 4.6 min, from secondary sources). Sweeps are not simultaneous, and fast-evolving storms change during a volume. | KNOWN | Per-radial times preserved. Viewer shows the time spread. |
| L6 | N=0 (below threshold) and N=1 (range folded) are not reflectivity values. Range-folded gates may hide real echoes. | MITIGATED | Distinct data classes. Never rendered as a dBZ number. |
| L7 | MSL vs ellipsoid: the ICD gives site height above MSL, but the geoid model is not identified in the sections read. Cesium needs ellipsoid heights. Geoid undulation in CONUS is tens of metres. | OPEN | Both heights stored. Geoid model and version recorded. Test T12. |
| L8 | Horizontal datum of the radar position (WGS84 vs NAD83) is unstated in the sections read. Difference is about a metre in CONUS, small against 250 m gates. | OPEN | Treated as WGS84. Recorded as an assumption. |
| L9 | Terrain-relative (AGL) altitude needs a DEM with its own datum and error. | OPEN | AGL is a derived, DEM-attributed quantity only, off by default. |
| L10 | The sphere-based propagation model (effective radius) versus the WGS84 ellipsoid causes a small horizontal and vertical placement difference. | OPEN | Quantify analytically and numerically in Phase 4. Report, don't hide. |
| L11 | Interpolation or smoothing between gates creates values that were not measured. Averaging in dBZ rather than linear Z is wrong in principle. Iso-surfaces imply boundaries that do not exist. | MITIGATED | Off by default. Separate artifact with `INTERPOLATED` class, domain/method recorded, and a persistent UI label. |
| L12 | Dual-polarization data quality (attenuation, calibration, non-meteorological echoes such as birds and insects) is not assessed. Only reflectivity is in scope. | KNOWN | No QC beyond the source's own flags. |
| L13 | Doviak & Zrnić Eq. 2.28 has been verified only through secondary sources (Py-ART, wradlib docs), not the book. | OPEN | See VALIDATION_PLAN §8 item 2. |
| L14 | Beamwidth values (0.88° to 0.96°) come from non-authoritative search summaries. | OPEN | Confirm in NEXRAD Technical Information. |
| L15 | Py-ART's reader interpolates mixed-resolution rays by default (`linear_interp=True`). This would create non-measured values. | MITIGATED | Disable; verify that the output equals decoder B. |
| L16 | Third-party reference tools (WCT, GridRad, MRMS) use their own gridding and Earth models, so disagreement is not automatically an error in either. | KNOWN | Classified in §6 of the validation plan. |
| L17 | Real-data validation currently has no cases. No fixtures exist yet. | OPEN | Phase 2. |

Implementation vs validation status: **nothing implemented, nothing validated.**
