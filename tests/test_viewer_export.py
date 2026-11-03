"""Viewer reduction must be an exact subset of engine output (no recomputation, no substitution)."""
import json

import numpy as np
import pandas as pd
import pytest

from engine.viewer_export import COLUMNS, export_viewer


@pytest.fixture(scope="module")
def reduced(tmp_path_factory, engine_samples):
    d = tmp_path_factory.mktemp("art")
    df = engine_samples("KDIX_20140430_120023").copy()
    # engine_samples is built without the geoid (network); the ellipsoid height here is a LABELLED SYNTHETIC
    # constant offset (msl - 30 m) so this test exercises only the subset/serialisation logic, not the geoid.
    df["height_ellipsoid_m"] = df["height_msl_m"] - 30.0
    df.to_parquet(d / "samples.parquet", index=False)
    (d / "manifest.json").write_text(json.dumps({
        "source": {"sha256": "x"}, "station": "TEST", "vcp": 0, "radar": {}, "volume_time_utc": {},
        "geoid": {"status": "synthetic-test-offset"}, "model": {}}))
    meta = export_viewer(str(d), 30.0)
    raw = (d / "gates.bin").read_bytes()
    return df, meta, raw


def test_gates_are_exact_subset(reduced):
    df, meta, raw = reduced
    n = meta["n_gates"]
    off, cols = 0, {}
    for c, t in COLUMNS:
        dt = np.dtype(t)
        cols[c] = np.frombuffer(raw, dtype=dt, count=n, offset=off)
        off += dt.itemsize * n
    assert off == len(raw)
    exp = df[(df["data_class"] == "MEASURED") & (df["dbz"] >= 30.0)]
    assert n == len(exp)
    for c in ("lon_deg", "lat_deg", "height_ellipsoid_m", "height_msl_m", "ground_arc_m", "slant_range_m", "raw_N",
              "radial_index", "gate_idx"):
        assert np.array_equal(cols[c], exp[c].to_numpy().astype(dict(COLUMNS)[c])), c
    assert np.array_equal(cols["dbz"], exp["dbz"].to_numpy().astype("<f4"))


def test_accounting_adds_up(reduced):
    df, meta, _ = reduced
    r = meta["reduction"]
    assert r["n_gates"] + r["n_dropped"] == r["n_samples_in"] == len(df)
    assert meta["interpolation"] == "none"


def test_refuses_missing_ellipsoid_height(tmp_path):
    df = pd.DataFrame({"data_class": ["MEASURED"], "dbz": [40.0], "height_ellipsoid_m": [np.nan],
                       "lon_deg": [0.0], "lat_deg": [0.0], "height_msl_m": [1.0], "raw_N": [100],
                       "radial_index": [0], "gate_idx": [0], "elevation_number": [1]})
    df.to_parquet(tmp_path / "samples.parquet")
    (tmp_path / "manifest.json").write_text(json.dumps({
        "source": {"sha256": "x"}, "station": "T", "vcp": 0, "radar": {}, "volume_time_utc": {},
        "geoid": {"status": "failed"}, "model": {}}))
    with pytest.raises(ValueError):
        export_viewer(str(tmp_path))
