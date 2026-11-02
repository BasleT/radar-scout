"""T5 vertical consistency, T6 thresholds/units, T7 missing data, T8 interpolation (absence), T9 reproducibility,
T10 metadata/timestamps, T11 schema, T12 vertical datum."""
import hashlib
import json
import os

import numpy as np
import pandas as pd
import pytest
from hypothesis import given, settings, strategies as st
from hypothesis.extra import numpy as hnp

from conftest import ROOT, SOURCE_FILES, TOL, record
from engine import geometry
from engine.samples import classify, dbz_from_raw


# ------------------------------------------------------------------ helpers
def _section_radials(vol, az, tol_deg=1.0):
    """Nearest REF radial (<=1 deg) per elevation number; ties -> first in file order (same rule as fixtures)."""
    out = []
    for en in sorted(set(vol.elevation_number[vol.has_ref].tolist())):
        idx = np.nonzero((vol.elevation_number == en) & vol.has_ref)[0]
        d = np.abs((vol.azimuth_deg[idx] - az + 180) % 360 - 180)
        if d.min() <= tol_deg:
            out.append((en, int(idx[int(np.argmin(d))])))
    return out


# ------------------------------------------------------------------ T5
def test_t5_heights_ordered_by_elevation_at_equal_slant_range(case, engine_vol, case_meta):
    vol = engine_vol(case)
    viol = n = 0
    for az in case_meta[case]["cross_section_azimuths_deg"]:
        sec = _section_radials(vol, az)
        for (e1, r1), (e2, r2) in zip(sec, sec[1:]):
            if vol.elevation_deg[r2] <= vol.elevation_deg[r1]:
                continue            # split-cut pairs at equal angle: no ordering expected
            k = min(vol.ngates[r1], vol.ngates[r2])
            if vol.first_gate_m[r1] != vol.first_gate_m[r2] or vol.gate_spacing_m[r1] != vol.gate_spacing_m[r2]:
                continue
            rng = vol.first_gate_m[r1] + np.arange(k) * vol.gate_spacing_m[r1]
            h1 = geometry.beam_height_and_arc(rng, vol.elevation_deg[r1])[0]
            h2 = geometry.beam_height_and_arc(rng, vol.elevation_deg[r2])[0]
            viol += int((h2 <= h1).sum())
            n += k
    record("T5", case, "gates where a higher-elevation beam is not higher", viol, "gates", None,
           note="%d gate pairs; geometric consistency only (no assumption about reflectivity continuity)" % n)
    assert viol == 0 and n > 0


def test_t5_sweep_time_spread_is_preserved(case, engine_vol):
    vol = engine_vol(case)
    t = vol.radial_time_ms_since_epoch()
    per = {int(en): (t[vol.elevation_number == en].min(), t[vol.elevation_number == en].max())
           for en in np.unique(vol.elevation_number)}
    spread = (t.max() - t.min()) / 1000.0
    record("T5", case, "volume time spread (first to last radial)", float(spread), "s", None,
           note="sweeps are not simultaneous; %d sweeps" % len(per))
    assert spread > 60.0 and all(v[1] >= v[0] for v in per.values())
    # sweeps are sequential, never interleaved
    starts = sorted(v[0] for v in per.values())
    assert starts == [per[k][0] for k in sorted(per)]


# ------------------------------------------------------------------ T6
def test_t6_echo_tops_match_independent_reference(case, fx, engine_vol, engine_samples, case_meta):
    vol, df = engine_vol(case), engine_samples(case)
    meas = df[df["data_class"] == "MEASURED"]
    ref = fx(case, "echo_top_ref.csv")
    assert ref, "reference has no rows"
    got = {}
    for az in case_meta[case]["cross_section_azimuths_deg"]:
        rad = [r for _, r in _section_radials(vol, az)]
        sub = meas[meas["radial_index"].isin(rad)]
        win = (sub["ground_arc_m"].to_numpy() // 2000).astype(int)
        for T in (20, 30, 40, 50):
            crit = T * sub["scale"].to_numpy() + sub["offset"].to_numpy()
            m = sub["raw_N"].to_numpy() >= crit
            for w in np.unique(win[m]):
                sel = m & (win == w)
                got[(float(az), T, int(w))] = float(sub["height_msl_m"].to_numpy()[sel].max())
    expected = {(float(r["section_azimuth_deg"]), int(r["threshold_dbz"]), int(r["ground_window_start_m"]) // 2000):
                float(r["top_height_msl_m"]) for r in ref}
    assert set(got) == set(expected), (len(got), len(expected))
    err = max(abs(got[k] - expected[k]) for k in expected)
    record("T6", case, "max |echo-top height engine - reference| (same definition)", float(err), "m",
           "echo_top_same_definition", note="%d (azimuth,threshold,window) entries" % len(expected))
    assert err <= 1e-6


def test_t6_threshold_is_integer_exact(case, engine_samples):
    """dBZ >= T  <=>  N >= T*scale+offset, including exact boundary values."""
    df = engine_samples(case)
    m = df[df["data_class"] == "MEASURED"]
    for T in (20, 30, 40, 50):
        a = (m["dbz"].to_numpy() >= T)
        b = (m["raw_N"].to_numpy() >= T * m["scale"].to_numpy() + m["offset"].to_numpy())
        assert np.array_equal(a, b), T
    assert m["dbz"].min() >= (2 - 66) / 2


@settings(max_examples=200, deadline=None)
@given(n=hnp.arrays(np.uint16, st.integers(1, 500), elements=st.integers(0, 255)))
def test_t6_prop_dbz_domain_and_threshold_equivalence(n):
    d = dbz_from_raw(n, 2.0, 66.0)
    assert np.array_equal(np.isnan(d), n < 2)
    ok = n >= 2
    assert np.all(d[ok] == (n[ok].astype(float) - 66.0) / 2.0)
    for T in (20, 30, 40, 50):
        assert np.array_equal(d[ok] >= T, n[ok] >= 2 * T + 66)


# ------------------------------------------------------------------ T7
def test_t7_class_counts_match_spec_reader(case, spec_vol, engine_samples):
    R = spec_vol(case)["radials"]
    cnt = {0: 0, 1: 0, 2: 0}
    for r in R:
        if "REF" in r["moments"]:
            a = np.asarray(r["moments"]["REF"]["raw"])
            cnt[0] += int((a == 0).sum())
            cnt[1] += int((a == 1).sum())
            cnt[2] += int((a >= 2).sum())
    vc = engine_samples(case)["data_class"].value_counts().to_dict()
    assert vc.get("BELOW_THRESHOLD", 0) == cnt[0] and vc.get("RANGE_FOLDED", 0) == cnt[1]
    assert vc.get("MEASURED", 0) == cnt[2]
    record("T7", case, "engine-vs-spec-reader class count differences (N=0, N=1, N>=2)",
           [vc.get("BELOW_THRESHOLD", 0) - cnt[0], vc.get("RANGE_FOLDED", 0) - cnt[1], vc.get("MEASURED", 0) - cnt[2]],
           "gates", "raw_N_mismatch_count", note="populations: N=0: %d, N=1: %d, N>=2: %d" % (cnt[0], cnt[1], cnt[2]))


def test_t7_only_measured_have_dbz_and_no_unscanned_rows(case, engine_samples, engine_vol):
    df, vol = engine_samples(case), engine_vol(case)
    assert df.loc[df["data_class"] != "MEASURED", "dbz"].isna().all()
    assert df.loc[df["data_class"] == "MEASURED", "dbz"].notna().all()
    assert (df["gate_idx"].to_numpy() < vol.ngates[df["radial_index"].to_numpy()]).all()
    assert set(df["data_class"]) <= {"MEASURED", "BELOW_THRESHOLD", "RANGE_FOLDED"}
    # radials without REF contribute nothing
    no_ref = np.nonzero(~vol.has_ref)[0]
    assert not df["radial_index"].isin(no_ref).any()


@settings(max_examples=200, deadline=None)
@given(n=hnp.arrays(np.uint16, st.integers(1, 300), elements=st.integers(0, 65535)))
def test_t7_prop_class_partition_exhaustive_exclusive(n):
    c = classify(n)
    assert all(x in ("BELOW_THRESHOLD", "RANGE_FOLDED", "MEASURED") for x in c)
    assert (c == "BELOW_THRESHOLD").sum() + (c == "RANGE_FOLDED").sum() + (c == "MEASURED").sum() == n.size


# ------------------------------------------------------------------ T8
def test_t8_no_interpolation_or_resampling(case, spec_vol, engine_vol, engine_samples):
    R, vol, df = spec_vol(case)["radials"], engine_vol(case), engine_samples(case)
    for i, r in enumerate(R):
        if "REF" in r["moments"]:
            m = r["moments"]["REF"]
            assert (vol.ngates[i], vol.first_gate_m[i], vol.gate_spacing_m[i]) == \
                   (m["ngates"], m["first_gate_m"], m["gate_spacing_m"])
    assert len(df) == int(vol.ngates[vol.has_ref].sum())      # one row per recorded gate, none created
    assert not df["data_class"].isin(["INTERPOLATED", "EXTRAPOLATED"]).any()
    spacings = sorted(set(vol.gate_spacing_m[vol.has_ref].tolist()))
    record("T8", case, "distinct REF gate spacings preserved (not resampled)", spacings, "m", None,
           note="interpolation not implemented; boundary-condition tests N/A until it exists")


# ------------------------------------------------------------------ T9
def test_t9_reproducible_exports(tmp_path):
    from engine.export import export_volume
    src = os.path.join(ROOT, SOURCE_FILES["KDIX_20140430_120023"])
    a, b = str(tmp_path / "a"), str(tmp_path / "b")
    export_volume(src, a)
    export_volume(src, b)
    res = {}
    for f in ("samples.parquet", "radials.parquet", "manifest.json"):
        ha = hashlib.sha256(open(os.path.join(a, f), "rb").read()).hexdigest()
        hb = hashlib.sha256(open(os.path.join(b, f), "rb").read()).hexdigest()
        res[f] = ha == hb
    record("T9", "KDIX_20140430_120023", "byte-identical artifacts across two runs", res, "bool", None)
    assert all(res.values()), res
    pd.testing.assert_frame_equal(pd.read_parquet(os.path.join(a, "samples.parquet")),
                                  pd.read_parquet(os.path.join(b, "samples.parquet")))


# ------------------------------------------------------------------ T10
def test_t10_timestamps_and_metadata_preserved(case, spec_vol, engine_vol, case_meta):
    R, vol, meta = spec_vol(case)["radials"], engine_vol(case), case_meta[case]
    t_ref = np.array([(r["collect_julian"] - 1) * 86400000 + r["collect_ms"] for r in R], dtype=np.int64)
    assert np.array_equal(t_ref, vol.radial_time_ms_since_epoch())
    assert vol.station == meta["station"] == R[0]["icao"]
    assert vol.source_sha256 == meta["sha256"]
    lock = json.load(open(os.path.join(ROOT, "fixtures", "fixtures.lock.json")))
    assert lock[case]["_source_sha256"] == vol.source_sha256
    assert (vol.radar_lat, vol.radar_lon) == (meta["radar"]["lat"], meta["radar"]["lon"])
    assert vol.antenna_msl_m == meta["radar"]["assumed_antenna_msl_m"]
    # per-radial times are distinct values, i.e. not collapsed to a volume time
    assert len(np.unique(t_ref)) > 0.99 * len(t_ref)


def test_t10_fixture_integrity(case):
    lock = json.load(open(os.path.join(ROOT, "fixtures", "fixtures.lock.json")))[case]
    for f, h in lock.items():
        if f.startswith("_"):
            continue
        got = hashlib.sha256(open(os.path.join(ROOT, "fixtures", case, f), "rb").read()).hexdigest()
        assert got == h, "fixture %s changed since it was generated" % f


# ------------------------------------------------------------------ T11
def test_t11_manifest_and_samples_schema(tmp_path):
    import jsonschema
    from engine.export import export_volume
    out = str(tmp_path / "o")
    m = export_volume(os.path.join(ROOT, SOURCE_FILES["KDIX_20140430_120023"]), out)
    schema = json.load(open(os.path.join(ROOT, "engine", "schema", "manifest.schema.json")))
    jsonschema.validate(m, schema)
    cols = json.load(open(os.path.join(ROOT, "engine", "schema", "samples.columns.json")))
    df = pd.read_parquet(os.path.join(out, "samples.parquet"))
    assert list(df.columns) == list(cols["columns"]), "column set/order differs from schema"
    for c, dt in cols["columns"].items():
        assert str(df[c].dtype) == dt, (c, df[c].dtype, dt)
    for c in cols["non_null"]:
        assert df[c].notna().all(), c
    assert set(df["data_class"]) <= set(cols["engine_emits_only"])
    assert df["chain_id"].isin(m["transform_chains"]).all()
    bad = dict(m)
    bad["interpolation"] = "linear"
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(bad, schema)


# ------------------------------------------------------------------ T12 (sanity only; see INCOMPLETE below)
def test_t12_geoid_sign_and_plausibility(case, engine_vol):
    from engine import geoid
    vol = engine_vol(case)
    N, status = geoid.undulation(np.array([vol.radar_lat]), np.array([vol.radar_lon]))
    assert status == "ok"
    record("T12", case, "EGM2008 undulation N at the radar site", float(N[0]), "m", None,
           note="SANITY ONLY: CONUS geoid is below the ellipsoid (N<0, tens of metres); no independent value obtained")
    assert -60 < N[0] < -5
    from pyproj import Transformer
    t96 = Transformer.from_crs("EPSG:4326+5773", "EPSG:4979", always_xy=True)
    n96 = t96.transform(vol.radar_lon, vol.radar_lat, 0.0)[2]
    diff = abs(N[0] - n96)
    record("T12", case, "|N(EGM2008) - N(EGM96)| at the radar site", float(diff), "m", "geoid_vs_second_model_sanity",
           note="sanity bound between two published models, not a validation")
    assert diff <= TOL["geoid_vs_second_model_sanity"]["value"]


# ------------------------------------------------------------------ declared INCOMPLETE items
@pytest.mark.parametrize("what", [
    "T12 independent geoid reference (GeographicLib GeoidEval / NGS benchmark) not obtained",
    "R3 NOAA Weather and Climate Toolkit reference products not generated",
    "R7 echo-top / composite comparison against MRMS or GridRad not performed",
    "R5 refractivity ray-trace sensitivity bound not computed",
    "Doviak & Zrnic Eq. 2.28 not checked against the book itself (only Py-ART / wradlib documentation)",
    "NCEI vs Unidata-bucket byte-identity of source files not checked",
    "antenna height = site height + tower height confirmed only by Py-ART and xradar conventions, not an ICD statement",
])
def test_incomplete_validation_item(what):
    pytest.skip("INCOMPLETE: " + what)
