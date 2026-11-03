"""Per-sweep texture and mesh artifacts (engine/sweeps.py).

Texture: every raw N byte equals the independent from-spec reader's value for the same radial and gate (the reader
shares no code with Py-ART). Mesh: the engine gate-centre positions (a separate code path: engine/samples.py) must lie
where the mesh says that cell is. Honest limits: the mesh uses the same beam-geometry function as the gate table, so
the position check proves alignment between texture/mesh and the gate table, not that the geometry model is right
(that is the job of the geometry tests against wradlib).
"""
import json

import numpy as np
import pytest

from conftest import record
from engine.sweeps import write_sweep

PRODUCTS = ("REF", "VEL", "SW", "ZDR", "RHO")


def _spec_key(r, name):
    return next((k for k in r["moments"] if k.strip() == name), None)


def _load(d):
    meta = json.load(open(d / "sweep.json"))
    tex = np.fromfile(d / "tex.bin", dtype=np.uint8).reshape(meta["n_radials"], meta["n_gates"])
    nk, nr = meta["mesh"]["n_knots"], meta["n_radials"]
    cols = np.fromfile(d / "mesh.bin", dtype="<f4").astype(np.float64).reshape(3, nr, 2, nk)
    cols[0] += meta["mesh"]["origin_lon_deg"]; cols[1] += meta["mesh"]["origin_lat_deg"]  # back to absolute degrees
    return meta, tex, cols


@pytest.mark.parametrize("product", PRODUCTS)
def test_texture_equals_spec_reader_raw(case, product, engine_vol, spec_vol, tmp_path):
    vol, R = engine_vol(case), spec_vol(case)["radials"]
    cuts = sorted({int(c) for c in vol.elevation_number[(vol.has_ref if product == "REF" else vol.moments[product]["has"])]})
    n_cmp = bad = 0
    for cut in cuts:
        d = tmp_path / ("%s_%d" % (product, cut))
        meta = write_sweep(vol, product, cut, str(d), with_geoid=False)
        _, tex, _ = _load(d)
        for row, ri in enumerate(meta["rows"]["radial_index"]):
            r = R[ri]
            name = "REF" if product == "REF" else product
            m = r["moments"][_spec_key(r, name)]
            exp = np.asarray(m["raw"], dtype=np.uint8)
            assert exp.size == meta["n_gates"]
            n_cmp += exp.size
            bad += int((tex[row] != exp).sum())
            assert m["scale"] == meta["scale"] and m["offset"] == meta["offset"]
            assert m["first_gate_m"] == meta["first_gate_m"] and m["gate_spacing_m"] == meta["gate_spacing_m"]
    record("sweep_texture_raw", case, "%s gates compared / mismatches" % product, [n_cmp, bad], "count")
    assert bad == 0


def test_mesh_matches_gate_table_positions(case, engine_vol, engine_samples, tmp_path):
    """Gate centre from the gate table vs the mesh interpolated at the same (row, range) position."""
    vol = engine_vol(case)
    cut = int(sorted({int(c) for c in vol.elevation_number[vol.has_ref]})[2])
    d = tmp_path / "m"
    meta = write_sweep(vol, "REF", cut, str(d), with_geoid=False)
    _, _, cols = _load(d)
    df = engine_samples(case)
    df = df[(df["elevation_number"] == cut) & (df["data_class"] == "MEASURED")]
    rng = np.random.default_rng(1)
    df = df.iloc[rng.choice(len(df), size=min(400, len(df)), replace=False)]
    rows_of = {ri: k for k, ri in enumerate(meta["rows"]["radial_index"])}
    kb = np.asarray(meta["mesh"]["knot_gate_boundary"], dtype=float)
    worst = 0.0
    for _, g in df.iterrows():
        row = rows_of[int(g["radial_index"])]
        t = float(g["gate_idx"]) + 0.5                      # centre of the cell, in gate-boundary units
        k = int(np.searchsorted(kb, t, side="right") - 1)
        k = min(k, len(kb) - 2)
        f = (t - kb[k]) / (kb[k + 1] - kb[k])
        lon = np.mean([(1 - f) * cols[0, row, s, k] + f * cols[0, row, s, k + 1] for s in (0, 1)])
        lat = np.mean([(1 - f) * cols[1, row, s, k] + f * cols[1, row, s, k + 1] for s in (0, 1)])
        dlat_m = (lat - g["lat_deg"]) * 111132.0
        dlon_m = (lon - g["lon_deg"]) * 111320.0 * np.cos(np.radians(g["lat_deg"]))
        worst = max(worst, float(np.hypot(dlat_m, dlon_m)))
    record("sweep_mesh_vs_gate_table", case, "max horizontal offset of cell centre", worst, "m")
    # one knot interval is 32 gates (~8 km): straight-segment error is metres. 25 m is a deliberately loose bound
    # that still catches a half-cell (125 m) or a wrong-radial misalignment.
    assert worst < 25.0


def test_rows_ascend_in_azimuth_and_cover_cut(case, engine_vol, tmp_path):
    vol = engine_vol(case)
    cut = int(sorted({int(c) for c in vol.elevation_number[vol.has_ref]})[0])
    meta = write_sweep(vol, "REF", cut, str(tmp_path / "a"), with_geoid=False)
    az = np.asarray(meta["rows"]["azimuth_deg"])
    assert np.all(np.diff(az) > 0)
    assert meta["n_radials"] == int(((vol.elevation_number == cut) & vol.has_ref).sum())
    assert meta["texture"]["sha256"] and meta["interpolation"] == "none"


def test_value_table_matches_engine_conversion(case, engine_vol, tmp_path):
    from engine.samples import dbz_from_raw
    vol = engine_vol(case)
    cut = int(sorted({int(c) for c in vol.elevation_number[vol.has_ref]})[0])
    meta = write_sweep(vol, "REF", cut, str(tmp_path / "v"), with_geoid=False)
    tab = meta["value_of_n"]
    assert len(tab) == 256 and tab[0] is None and tab[1] is None
    n = np.arange(2, 256)
    exp = dbz_from_raw(n, meta["scale"], meta["offset"])
    assert np.array_equal(np.asarray(tab[2:], dtype=float), exp)
