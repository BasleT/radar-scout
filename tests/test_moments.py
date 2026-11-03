"""VEL / SW / ZDR / PHI / RHO decoding against the independent from-spec reader, plus ICD range plausibility.

The spec reader (tests/reference/spec_reader.py) shares no code with Py-ART, so equality of every raw integer, scale,
offset and gate geometry is an independent check of the engine's moment extraction. The range checks use the "Data
Range after conversion" column of ICD Table XVII-I; they are plausibility bounds, not equality with a reference.
"""
import numpy as np
import pytest

from conftest import record
from engine.decode import MOMENTS
from engine.samples import build_moment_samples, dbz_from_raw

# ICD 2620002AA Table XVII-I "Data Range after conversion" (extracted text is garbled; values read from it).
ICD_RANGE = {"VEL": (-127.0, 126.0), "ZDR": (-13.0, 20.0), "PHI": (0.0, 360.0), "RHO": (0.2083, 1.0516)}


def _spec_key(R, name):
    return next(k for k in R["moments"] if k.strip() == name)


@pytest.mark.parametrize("product", MOMENTS)
def test_moment_raw_geometry_scale_equal_spec_reader(case, product, spec_vol, engine_vol):
    vol, R = engine_vol(case), spec_vol(case)["radials"]
    m = vol.moments[product]
    assert len(R) == len(m["has"])
    n_gates = bad = 0
    for i, r in enumerate(R):
        has = any(k.strip() == product for k in r["moments"])
        assert bool(m["has"][i]) == has, (product, i)
        if not has:
            continue
        s = r["moments"][_spec_key(r, product)]
        assert m["ngates"][i] == s["ngates"]
        assert m["first_gate_m"][i] == s["first_gate_m"] and m["gate_spacing_m"][i] == s["gate_spacing_m"]
        assert m["scale"][i] == s["scale"] and m["offset"][i] == s["offset"], (product, i)
        e = m["raw"][i]
        bad += int(np.count_nonzero(e != np.asarray(s["raw"], dtype=e.dtype)))
        n_gates += e.size
    record("moments", case, "%s raw_N mismatches (of %d gates)" % (product, n_gates), bad, "gates", "raw_N_mismatch_count")
    assert bad == 0


@pytest.mark.parametrize("product", MOMENTS)
def test_moment_values_inside_icd_range_and_codes(case, product, engine_vol):
    vol = engine_vol(case)
    df, _ = build_moment_samples(vol, product, include=("MEASURED", "BELOW_THRESHOLD", "RANGE_FOLDED"),
                                 compute_geoid=False)
    if df.empty:
        pytest.skip("no %s gates in %s" % (product, case))
    meas = df[df["data_class"] == "MEASURED"]
    assert (meas["raw_N"] >= 2).all()
    assert df.loc[df["data_class"] != "MEASURED", "value"].isna().all()   # N=0/1 never become numbers
    assert (df.loc[df["raw_N"] == 0, "data_class"] == "BELOW_THRESHOLD").all()
    assert (df.loc[df["raw_N"] == 1, "data_class"] == "RANGE_FOLDED").all()
    # closed-form conversion on every measured gate
    exp = (meas["raw_N"].to_numpy(float) - meas["offset"].to_numpy()) / meas["scale"].to_numpy()
    assert np.array_equal(meas["value"].to_numpy(), exp)
    lo, hi = float(meas["value"].min()), float(meas["value"].max())
    record("moments", case, "%s measured min/max (%s)" % (product, df["unit"].iloc[0]), [lo, hi], df["unit"].iloc[0])
    if product in ICD_RANGE:
        a, b = ICD_RANGE[product]
        # The ICD prints these bounds to 4 decimals and TRUNCATES (RHO max is printed 1.0516 while its own
        # formula (255+60.5)/300 = 1.05167), so allow one unit in the last printed digit.
        slack = 1e-4
        assert a - slack <= lo and hi <= b + slack, (product, lo, hi, a, b)


def test_moment_conversion_closed_form_examples():
    # hand-computed from ICD note 20/21: VEL scale 2 offset 129 -> N=129 is 0 m/s, N=2 is -63.5, N=255 is +63.0
    assert dbz_from_raw([129, 2, 255], 2.0, 129.0).tolist() == [0.0, -63.5, 63.0]
    # RHO scale 300 offset -60.5: N=2 -> 0.2083.., N=255 -> 1.0516.. (ICD range 0.2083 to 1.0516)
    r = dbz_from_raw([2, 255], 300.0, -60.5)
    assert abs(r[0] - 0.20833) < 1e-4 and abs(r[1] - 1.05167) < 1e-4
    assert np.isnan(dbz_from_raw([0, 1], 2.0, 129.0)).all()
