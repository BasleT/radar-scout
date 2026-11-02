"""T2 range->coordinates, T3 beam height, T4 geographic alignment.

References: 40-digit mpmath evaluation (R4, fixtures), GeographicLib geodesic (fixtures + inverse checks),
Py-ART and wradlib (R2, cross-library). Synthetic cases are labelled synthetic and have closed-form answers.
"""
import numpy as np
import pytest
from geographiclib.geodesic import Geodesic
from hypothesis import given, settings, strategies as st

from conftest import record
from engine import geometry


def _expected(case, fx, vol):
    rows = fx(case, "expected_geo.csv")
    cols = {k: np.array([float(r[k]) for r in rows]) for k in
            ("slant_range_m", "azimuth_deg", "elevation_deg", "ground_arc_m", "z_above_antenna_m",
             "height_msl_m", "lat_deg", "lon_deg")}
    cols["radial_index"] = np.array([int(r["radial_index"]) for r in rows])
    cols["gate_idx"] = np.array([int(r["gate_idx"]) for r in rows])
    return cols


def _engine_for(vol, e):
    ri = e["radial_index"]
    rng = vol.first_gate_m[ri] + e["gate_idx"] * vol.gate_spacing_m[ri]
    g = geometry.place_gates(vol.radar_lat, vol.radar_lon, vol.antenna_msl_m, rng, vol.elevation_deg[ri],
                             vol.azimuth_deg[ri])
    return rng, g


def test_t2_t3_engine_vs_mpmath_reference(case, fx, engine_vol):
    vol = engine_vol(case)
    e = _expected(case, fx, vol)
    rng, g = _engine_for(vol, e)
    assert np.array_equal(rng, e["slant_range_m"])
    dz = float(np.abs(g["height_msl_m"] - e["height_msl_m"]).max())
    ds = float(np.abs(g["ground_arc_m"] - e["ground_arc_m"]).max())
    record("T3", case, "max |height_msl engine - mpmath|", dz, "m", "beam_height_same_model",
           note="%d gates, slant range %.0f-%.0f m" % (len(rng), rng.min(), rng.max()))
    record("T2", case, "max |ground arc engine - mpmath|", ds, "m", "ground_arc_same_model")
    # horizontal: geodesic distance between engine and reference position
    d = np.array([Geodesic.WGS84.Inverse(a, b, c, dd)["s12"] for a, b, c, dd in
                  zip(g["lat_deg"], g["lon_deg"], e["lat_deg"], e["lon_deg"])])
    record("T2", case, "max horizontal distance engine(PROJ) vs reference(GeographicLib)", float(d.max()), "m",
           "horizontal_position_same_ellipsoid")
    assert dz <= 1e-6 and ds <= 1e-6 and d.max() <= 0.01


def test_t3_cross_section_heights_match_reference(case, fx, engine_vol):
    vol = engine_vol(case)
    rows = fx(case, "cross_section_ref.csv")
    ri = np.array([int(r["radial_index"]) for r in rows])
    gi = np.array([int(r["gate_idx"]) for r in rows])
    rng = vol.first_gate_m[ri] + gi * vol.gate_spacing_m[ri]
    g = geometry.place_gates(vol.radar_lat, vol.radar_lon, vol.antenna_msl_m, rng, vol.elevation_deg[ri],
                             vol.azimuth_deg[ri])
    ref_h = np.array([float(r["height_msl_m"]) for r in rows])
    ref_s = np.array([float(r["ground_arc_m"]) for r in rows])
    dh, ds = float(np.abs(g["height_msl_m"] - ref_h).max()), float(np.abs(g["ground_arc_m"] - ref_s).max())
    record("T3", case, "cross-section max |height engine - reference|", dh, "m", "beam_height_same_model",
           note="%d gates" % len(rows))
    record("T2", case, "cross-section max |ground arc engine - reference|", ds, "m", "ground_arc_same_model")
    assert dh <= 1e-6 and ds <= 1e-6


def test_t3_pyart_same_formula(case, fx, engine_vol):
    import pyart
    vol = engine_vol(case)
    e = _expected(case, fx, vol)
    rng, g = _engine_for(vol, e)
    x, y, z = pyart.core.antenna_to_cartesian(rng / 1000.0, e["azimuth_deg"], e["elevation_deg"])
    dz = float(np.abs((z + vol.antenna_msl_m) - g["height_msl_m"]).max())
    ds = float(np.abs(np.hypot(x, y) - g["ground_arc_m"]).max())
    record("T3", case, "max |height engine - Py-ART antenna_to_cartesian|", dz, "m",
           "cross_library_height_same_parameters")
    record("T3", case, "max |ground arc engine - Py-ART|", ds, "m", "cross_library_height_same_parameters")
    assert dz <= 1e-6 and ds <= 1e-6


def test_t3_wradlib_is_a_different_model_and_matches_its_own_formula(case, fx, engine_vol):
    """wradlib puts the antenna altitude inside the sphere radius (R+a); recorded as a model difference."""
    import wradlib
    from mpmath import mp, mpf, sqrt, sin, radians
    mp.dps = 40
    vol = engine_vol(case)
    e = _expected(case, fx, vol)
    rng, g = _engine_for(vol, e)
    a = vol.antenna_msl_m
    w = wradlib.georef.bin_altitude(rng, e["elevation_deg"], a, re=6371000.0)
    R = mpf(4) / 3 * 6371000
    own = np.array([float(sqrt(mpf(float(r)) ** 2 + (R + a) ** 2 + 2 * mpf(float(r)) * (R + a) *
                               sin(radians(mpf(float(t))))) - R) for r, t in zip(rng, e["elevation_deg"])])
    d_own = float(np.abs(w - own).max())
    diff = np.abs(w - g["height_msl_m"])
    record("T3", case, "wradlib vs mpmath evaluation of wradlib formula", d_own, "m", "wradlib_vs_own_formula_evaluation")
    record("T3", case, "max |height wradlib - engine| (model difference, report only)", float(diff.max()), "m",
           "wradlib_height_model_difference_bound",
           note="classification: data-processing difference (antenna altitude placement in the sphere)")
    assert d_own <= 1e-6
    assert diff.max() <= 1.0


def test_t4_pyart_spherical_horizontal_difference_within_apriori_bound(case, fx, engine_vol):
    """Py-ART places gates on a sphere (R=6370997 m); the engine uses the WGS84 geodesic (L10)."""
    import pyart
    vol = engine_vol(case)
    e = _expected(case, fx, vol)
    rng, g = _engine_for(vol, e)
    x, y, _ = pyart.core.antenna_to_cartesian(rng / 1000.0, e["azimuth_deg"], e["elevation_deg"])
    lon, lat = pyart.core.cartesian_to_geographic_aeqd(x, y, vol.radar_lon, vol.radar_lat)
    d = np.array([Geodesic.WGS84.Inverse(la1, lo1, la2, lo2)["s12"] for la1, lo1, la2, lo2 in
                  zip(g["lat_deg"], g["lon_deg"], lat, lon)])
    rel = d / np.maximum(g["ground_arc_m"], 1.0)
    far = g["ground_arc_m"] > 1000
    record("T4", case, "max horizontal |engine - Py-ART spherical aeqd| / ground arc", float(rel[far].max()),
           "fraction of ground arc", "pyart_spherical_horizontal_relative_bound",
           note="max %.0f m absolute (at %.0f km ground arc); classification: data-processing difference "
                "(spherical vs WGS84 ellipsoidal placement, L10)" % (d[far].max(),
                                                                    g["ground_arc_m"][far][np.argmax(d[far])] / 1000))
    assert rel[g["ground_arc_m"] > 1000].max() <= 0.004


def test_t4_geodesic_round_trip_self_consistency(case, fx, engine_vol):
    """Self-consistency only: inverse geodesic from radar to placed gate returns azimuth and arc (not a truth test)."""
    vol = engine_vol(case)
    e = _expected(case, fx, vol)
    rng, g = _engine_for(vol, e)
    daz, ds = [], []
    for la, lo, az, s in zip(g["lat_deg"], g["lon_deg"], e["azimuth_deg"], g["ground_arc_m"]):
        inv = Geodesic.WGS84.Inverse(vol.radar_lat, vol.radar_lon, la, lo)
        if inv["s12"] > 1.0:
            daz.append(abs((inv["azi1"] - az + 180) % 360 - 180))
            ds.append(abs(inv["s12"] - s))
    record("T4", case, "round-trip azimuth max error", float(max(daz)), "deg", None)
    record("T4", case, "round-trip distance max error", float(max(ds)), "m", "horizontal_position_same_ellipsoid")
    assert max(ds) <= 0.01 and max(daz) <= 1e-6


# ---------------------------- synthetic geometry (mathematically known; NOT observed weather) -------------
def test_synthetic_vertical_beam_exact():
    """theta = 90 deg: z = r exactly and s = 0 (closed form). SYNTHETIC."""
    r = np.array([1000.0, 50000.0, 250000.0])
    z, s = geometry.beam_height_and_arc(r, 90.0)
    assert np.allclose(z, r, rtol=0, atol=1e-6)
    assert np.allclose(s, 0.0, atol=1e-6)


def test_synthetic_zero_range_exact():
    z, s = geometry.beam_height_and_arc(np.array([0.0]), np.array([0.5]))
    assert z[0] == 0.0 and s[0] == 0.0


def test_synthetic_horizontal_beam_series():
    """theta=0: z = sqrt(r^2+R^2)-R = r^2/(2R) - r^4/(8R^3) + r^6/(16R^5) - ... (binomial series of
    R*sqrt(1+x), x=r^2/R^2); the r^8 term is ~5e-14 m here. Independent closed-form check. SYNTHETIC."""
    R = 4.0 / 3.0 * 6371000.0
    r = 100000.0
    series = r * r / (2 * R) - r ** 4 / (8 * R ** 3) + r ** 6 / (16 * R ** 5)
    z, _ = geometry.beam_height_and_arc(np.array([r]), 0.0)
    assert abs(z[0] - series) < 1e-6


def test_synthetic_due_north_east_placement():
    """Azimuth 0 increases latitude only; azimuth 90 keeps latitude approximately and increases longitude."""
    g = geometry.place_gates(35.0, -97.0, 0.0, np.array([50000.0]), np.array([0.5]), np.array([0.0]))
    assert g["lat_deg"][0] > 35.0 and abs(g["lon_deg"][0] + 97.0) < 1e-9
    g = geometry.place_gates(35.0, -97.0, 0.0, np.array([50000.0]), np.array([0.5]), np.array([90.0]))
    assert g["lon_deg"][0] > -97.0 and abs(g["lat_deg"][0] - 35.0) < 0.01


# ---------------------------- property-based -----------------------------------------------------------------
@settings(max_examples=300, deadline=None)
@given(r1=st.floats(100, 460000), r2=st.floats(100, 460000), th=st.floats(0, 20))
def test_prop_height_monotonic_in_range_nonneg_elevation(r1, r2, th):
    lo, hi = sorted((r1, r2))
    z, _ = geometry.beam_height_and_arc(np.array([lo, hi]), th)
    assert z[1] >= z[0] - 1e-9


@settings(max_examples=300, deadline=None)
@given(r=st.floats(100, 460000), t1=st.floats(0, 20), t2=st.floats(0, 20))
def test_prop_height_monotonic_in_elevation(r, t1, t2):
    lo, hi = sorted((t1, t2))
    z1, _ = geometry.beam_height_and_arc(np.array([r]), lo)
    z2, _ = geometry.beam_height_and_arc(np.array([r]), hi)
    assert z2[0] >= z1[0] - 1e-9


@settings(max_examples=300, deadline=None)
@given(r=st.floats(100, 460000), th=st.floats(0, 20))
def test_prop_arc_not_longer_than_slant_range_and_height_nonneg(r, th):
    z, s = geometry.beam_height_and_arc(np.array([r]), th)
    assert 0 <= s[0] <= r + 1e-6 and z[0] >= 0


@settings(max_examples=200, deadline=None)
@given(lat=st.floats(-60, 60), lon=st.floats(-179, 179), az=st.floats(0, 360), r=st.floats(1000, 460000),
       th=st.floats(0.1, 20))
def test_prop_geodesic_distance_equals_model_arc(lat, lon, az, r, th):
    g = geometry.place_gates(lat, lon, 0.0, np.array([r]), np.array([th]), np.array([az]))
    inv = Geodesic.WGS84.Inverse(lat, lon, float(g["lat_deg"][0]), float(g["lon_deg"][0]))
    assert abs(inv["s12"] - g["ground_arc_m"][0]) < 0.01
