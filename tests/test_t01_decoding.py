"""T1 raw decoding vs independent references (R1 from-spec reader, R2 xradar). Hard-fail on any raw mismatch."""
import numpy as np
import pytest

from conftest import ROOT, SOURCE_FILES, record
import crosscheck_decoders as cc


def test_engine_raw_samples_match_fixture(case, fx, engine_vol):
    vol = engine_vol(case)
    rows = fx(case, "raw_samples.csv")
    bad = 0
    for r in rows:
        i, k = int(r["radial_index"]), int(r["gate_idx"])
        got = int(vol.ref_raw[i][k])
        if got != int(r["raw_N"]) or int(vol.elevation_number[i]) != int(r["elevation_number"]) or \
                float(vol.scale[i]) != float(r["scale"]) or float(vol.offset[i]) != float(r["offset"]):
            bad += 1
    record("T1", case, "raw_N / scale / offset mismatches vs fixture", bad, "gates", "raw_N_mismatch_count",
           note="%d fixture gates" % len(rows))
    assert bad == 0


def test_engine_full_volume_raw_equals_spec_reader(case, spec_vol, engine_vol):
    vol, R = engine_vol(case), spec_vol(case)["radials"]
    assert len(R) == len(vol.azimuth_deg)
    mism = n = 0
    for i, r in enumerate(R):
        if "REF" not in r["moments"]:
            assert not vol.has_ref[i]
            continue
        a = np.asarray(r["moments"]["REF"]["raw"], dtype=np.int64)
        b = vol.ref_raw[i].astype(np.int64)
        assert a.shape == b.shape, (case, i)
        mism += int((a != b).sum())
        n += a.size
    record("T1", case, "full-volume REF raw_N mismatches engine vs spec reader", mism, "gates",
           "raw_N_mismatch_count", note="%d gates compared" % n)
    assert mism == 0


def test_engine_geometry_metadata_equals_spec_reader(case, spec_vol, engine_vol):
    vol, R = engine_vol(case), spec_vol(case)["radials"]
    az = np.array([r["azimuth"] for r in R], dtype=np.float64)
    el = np.array([r["elevation"] for r in R], dtype=np.float64)
    assert np.array_equal(az, vol.azimuth_deg) and np.array_equal(el, vol.elevation_deg)
    assert np.array_equal(np.array([r["radial_status"] for r in R]), vol.radial_status)
    assert np.array_equal(np.array([r["elevation_number"] for r in R]), vol.elevation_number)
    v = R[0]["vol"]
    assert (vol.radar_lat, vol.radar_lon) == (v["lat"], v["lon"])
    assert (vol.site_height_m_msl, vol.tower_height_m_agl) == (v["site_height_m"], v["tower_height_m"])
    record("T1", case, "azimuth/elevation max abs diff engine vs spec reader",
           float(max(np.abs(az - vol.azimuth_deg).max(), np.abs(el - vol.elevation_deg).max())), "deg",
           "angle_vs_file")


def test_dbz_conversion_matches_fixture(case, fx, engine_vol):
    from engine.samples import dbz_from_raw
    rows = [r for r in fx(case, "raw_samples.csv") if r["expected_dbz"] != ""]
    n = np.array([int(r["raw_N"]) for r in rows])
    got = dbz_from_raw(n, np.array([float(r["scale"]) for r in rows]), np.array([float(r["offset"]) for r in rows]))
    exp = np.array([float(r["expected_dbz"]) for r in rows])
    err = float(np.abs(got - exp).max())
    record("T1", case, "max |dBZ engine - fixture|", err, "dB", "dbz_from_N")
    assert err <= 1e-9


@pytest.mark.slow
def test_independent_decoders_agree_over_full_volume(case, tmp_path):
    """R1 vs Py-ART vs xradar over every gate. xradar's N<2 encoding is recorded, not asserted."""
    import os
    import spec_reader
    path = os.path.join(ROOT, SOURCE_FILES[case])
    R1 = spec_reader.read_volume(path)["radials"]
    scratch = str(tmp_path)
    a = cc.check_pyart(cc._gunzip(path, scratch), R1)
    b = cc.check_xradar(path, R1, scratch)
    record("T1", case, "Py-ART vs spec raw_N mismatches", a["raw_mismatch_gates"], "gates", "raw_N_mismatch_count",
           note="%d gates" % a["gates_compared"])
    record("T1", case, "xradar vs spec dBZ mismatches (N>=2)", b["dbz_mismatch_gates"], "gates",
           "raw_N_mismatch_count", note="%d gates compared; xradar N<2 treatment: %s"
                                         % (b["gates_compared"], b.get("xradar_low_gate_values")))
    assert a["raw_mismatch_gates"] == 0 and a["time_mismatch_radials"] == 0
    assert a["radials_with_ngates_mismatch"] == 0 and a["gate_geom_mismatch_radials"] == 0
    assert b["dbz_mismatch_gates"] == 0 and b["rays_unmatched"] == 0
