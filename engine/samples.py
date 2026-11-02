"""Build the per-gate sample table with provenance and an explicit data_class.

data_class (ICD Table XVII-I note 21): raw N=0 below threshold, N=1 range folded, N>=2 measured.
Gates beyond a radial's ngates were never recorded and are simply absent: NOT_SCANNED (derivable from the
radials table). INTERPOLATED / EXTRAPOLATED are reserved values: this engine produces neither.
"""
import numpy as np
import pandas as pd

from . import geometry, geoid

DATA_CLASSES = ("MEASURED", "BELOW_THRESHOLD", "RANGE_FOLDED", "NOT_SCANNED", "INTERPOLATED", "EXTRAPOLATED")
CHAIN_ID = "chain-1"
TRANSFORM_CHAIN = [
    {"name": "decode", "impl": "pyart.io.nexrad_level2.NEXRADLevel2File", "output": "raw_N"},
    {"name": "dbz", "formula": "(N - offset) / scale, N>=2 only; offset/scale taken from the radial's REF block",
     "ref": "ICD 2620002 Table XVII-I notes 15, 20, 21"},
    {"name": "gate_range", "formula": "first_gate_m + gate_idx * gate_spacing_m (range to gate centre)",
     "ref": "ICD 2620002 Table XVII-B"},
    {"name": "beam_geometry", "model": "4/3 effective earth radius, re=6371000 m",
     "ref": "Doviak & Zrnic 1993 Eq. 2.28 (via Py-ART/wradlib documentation)"},
    {"name": "geodetic_placement", "method": "WGS84 forward geodesic (pyproj.Geod), true-north azimuth"},
    {"name": "antenna_height", "formula": "site_height_msl + tower_height_agl", "status": "assumption, see limitations"},
    {"name": "msl_to_ellipsoid", "formula": "h_ellipsoid = H_msl + N", "model": geoid.MODEL},
]


def dbz_from_raw(raw, scale, offset):
    """dBZ = (N - offset) / scale for N >= 2; NaN for N < 2 (below threshold / range folded).
    ICD 2620002 Table XVII-I notes 15, 20, 21. Scale/offset come from the radial's own block."""
    n = np.asarray(raw, dtype=np.float64)
    return np.where(n >= 2, (n - np.asarray(offset, dtype=np.float64)) / np.asarray(scale, dtype=np.float64), np.nan)


def classify(raw):
    raw = np.asarray(raw)
    cls = np.empty(raw.shape, dtype=object)
    cls[raw == 0] = "BELOW_THRESHOLD"
    cls[raw == 1] = "RANGE_FOLDED"
    cls[raw >= 2] = "MEASURED"
    return cls


def build_samples(vol, include=("MEASURED", "RANGE_FOLDED"), compute_geoid=True):
    """One row per retained recorded gate. Returns (DataFrame, geoid_status)."""
    parts = []
    for i in np.nonzero(vol.has_ref)[0]:
        raw = vol.ref_raw[i]
        cls = classify(raw)
        k = np.nonzero(np.isin(cls, include))[0]
        if k.size == 0:
            continue
        parts.append(pd.DataFrame({"radial_index": np.int32(i), "gate_idx": k.astype(np.int32),
                                   "raw_N": raw[k].astype(np.uint16), "data_class": cls[k]}))
    if not parts:
        return pd.DataFrame(), "no samples"
    df = pd.concat(parts, ignore_index=True)
    ri = df["radial_index"].to_numpy()
    df["source_sha256"] = vol.source_sha256
    df["elevation_number"] = vol.elevation_number[ri]
    df["radial_number"] = vol.radial_number[ri]
    df["scale"] = vol.scale[ri]
    df["offset"] = vol.offset[ri]
    df["dbz"] = dbz_from_raw(df["raw_N"].to_numpy(), df["scale"].to_numpy(), df["offset"].to_numpy())
    df["azimuth_deg"] = vol.azimuth_deg[ri]
    df["elevation_deg"] = vol.elevation_deg[ri]
    df["radial_time_ms_utc"] = vol.radial_time_ms_since_epoch()[ri]
    rng = vol.first_gate_m[ri] + df["gate_idx"].to_numpy() * vol.gate_spacing_m[ri]
    df["slant_range_m"] = rng
    g = geometry.place_gates(vol.radar_lat, vol.radar_lon, vol.antenna_msl_m, rng,
                             df["elevation_deg"].to_numpy(), df["azimuth_deg"].to_numpy())
    for k_, v_ in g.items():
        df[k_] = v_
    df["beamwidth_deg"] = np.nan   # not decoded from the file; explicitly unavailable (L2/L14)
    if compute_geoid:
        N, status = geoid.undulation(df["lat_deg"].to_numpy(), df["lon_deg"].to_numpy())
        df["geoid_undulation_m"] = N
        df["height_ellipsoid_m"] = df["height_msl_m"].to_numpy() + N
    else:
        status = "not computed"
        df["geoid_undulation_m"] = np.nan
        df["height_ellipsoid_m"] = np.nan
    df["chain_id"] = CHAIN_ID
    return df, status


def radials_table(vol):
    return pd.DataFrame({
        "radial_index": np.arange(len(vol.azimuth_deg), dtype=np.int32),
        "elevation_number": vol.elevation_number, "radial_number": vol.radial_number,
        "radial_status": vol.radial_status, "azimuth_deg": vol.azimuth_deg, "elevation_deg": vol.elevation_deg,
        "radial_time_ms_utc": vol.radial_time_ms_since_epoch(), "has_ref": vol.has_ref,
        "ngates_recorded": vol.ngates, "first_gate_m": vol.first_gate_m, "gate_spacing_m": vol.gate_spacing_m,
        "scale": vol.scale, "offset": vol.offset})
