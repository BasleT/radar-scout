"""Reduce samples.parquet to a viewer-ready artifact (viewer.json + gates.bin).

This is a REDUCTION of engine output, not a new measurement: only MEASURED gates with dBZ >= threshold are kept,
every value is copied unchanged from samples.parquet, and the manifest records what was dropped. Nothing is
interpolated, rounded or recomputed. Gates whose ellipsoid height is unavailable (geoid failure) are an error.

gates.bin layout (little-endian, column-major, n = viewer.json["n_gates"]):
  lon_deg f8[n] | lat_deg f8[n] | height_ellipsoid_m f8[n] | height_msl_m f8[n] | ground_arc_m f8[n]
  | slant_range_m f8[n] | dbz f4[n]
  raw_N u2[n] | radial_index i4[n] | gate_idx i4[n] | elevation_number i2[n]
"""
import hashlib
import json
import os

import numpy as np
import pandas as pd

COLUMNS = [("lon_deg", "<f8"), ("lat_deg", "<f8"), ("height_ellipsoid_m", "<f8"), ("height_msl_m", "<f8"),
           ("ground_arc_m", "<f8"), ("slant_range_m", "<f8"), ("dbz", "<f4"), ("raw_N", "<u2"), ("radial_index", "<i4"), ("gate_idx", "<i4"),
           ("elevation_number", "<i2")]


def export_viewer(artifact_dir, threshold_dbz=30.0, out_dir=None):
    out_dir = out_dir or artifact_dir
    os.makedirs(out_dir, exist_ok=True)
    man = json.load(open(os.path.join(artifact_dir, "manifest.json")))
    df = pd.read_parquet(os.path.join(artifact_dir, "samples.parquet"))
    total = len(df)
    n_by_class = df["data_class"].value_counts().to_dict()
    keep = df[(df["data_class"] == "MEASURED") & (df["dbz"] >= threshold_dbz)]
    if keep["height_ellipsoid_m"].isna().any():
        raise ValueError("ellipsoid height unavailable for kept gates (geoid status %r); refusing to substitute"
                         % man["geoid"]["status"])
    n = len(keep)
    buf = b"".join(np.ascontiguousarray(keep[c].to_numpy().astype(t)).tobytes() for c, t in COLUMNS)
    with open(os.path.join(out_dir, "gates.bin"), "wb") as f:
        f.write(buf)
    meta = {
        "schema_version": "1.0",
        "kind": "viewer-reduction",
        "source_manifest": "manifest.json",
        "source_sha256": man["source"]["sha256"],
        "station": man["station"], "vcp": man["vcp"],
        "radar": man["radar"], "volume_time_utc": man["volume_time_utc"],
        "geoid": man["geoid"], "model": man["model"], "interpolation": "none",
        "reduction": {"keep": "data_class == MEASURED and dbz >= threshold_dbz", "threshold_dbz": threshold_dbz,
                      "n_samples_in": total, "n_in_by_class": {k: int(v) for k, v in n_by_class.items()},
                      "n_gates": n, "n_dropped": total - n,
                      "note": "dropped gates are below the display threshold, BELOW_THRESHOLD, or RANGE_FOLDED; "
                              "their absence here is not evidence of absence of echo"},
        "n_gates": n,
        "gates_bin": {"file": "gates.bin", "sha256": hashlib.sha256(buf).hexdigest(), "size_bytes": len(buf),
                      "byte_order": "little", "layout": "column-major",
                      "columns": [{"name": c, "dtype": t} for c, t in COLUMNS]},
    }
    for side in ("coverage.json", "radials.json"):  # copied unchanged from the engine run, when present
        p = os.path.join(artifact_dir, side)
        if os.path.exists(p) and os.path.abspath(out_dir) != os.path.abspath(artifact_dir):
            import shutil
            shutil.copy(p, os.path.join(out_dir, side))
    with open(os.path.join(out_dir, "viewer.json"), "w") as f:
        json.dump(meta, f, indent=2)
    return meta


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("artifact_dir")
    ap.add_argument("--threshold", type=float, default=30.0)
    a = ap.parse_args()
    m = export_viewer(a.artifact_dir, a.threshold)
    print(m["n_gates"], "gates kept of", m["reduction"]["n_samples_in"])
