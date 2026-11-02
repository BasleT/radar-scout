"""Phase 2 reference-fixture generator.

Expected values come ONLY from independent sources:
  - raw bytes:   tests/reference/spec_reader.py (from-spec reader, R1)
  - beam math:   mpmath (40 digits), closed-form Doviak & Zrnic 4/3 model (R4)
  - geodesic:    geographiclib Geodesic.WGS84.Direct (independent of PROJ and of the engine)
This script MUST NOT import the engine (enforced by tests/test_fixture_independence.py).

Run: python tests/reference/make_fixtures.py
Sample selection uses a fixed seed over INDICES only; values always come from R1.
"""
import csv
import hashlib
import json
import os
import sys
from collections import defaultdict

import numpy as np
from geographiclib.geodesic import Geodesic
from mpmath import mp, mpf, sqrt as msqrt, sin as msin, cos as mcos, asin as masin, radians as mrad

sys.path.insert(0, os.path.dirname(__file__))
import spec_reader  # noqa: E402

mp.dps = 40
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
R_EARTH_M = mpf(6371000)       # mean earth radius used by the 4/3 model (matches Py-ART documentation)
KE = mpf(4) / 3
THRESHOLDS = (20, 30, 40, 50)
WINDOW_M = 2000

CASES = {
    "KTLX_20130520_195111": {
        "file": "data/raw/KTLX20130520_195111_V06.gz",
        "key": "2013/05/20/KTLX/KTLX20130520_195111_V06.gz",
        "bucket": "unidata-nexrad-level2",
        "role": "vertically developed convection (case B)",
    },
    "KDIX_20140430_120023": {
        "file": "data/raw/KDIX20140430_120023_V06.gz",
        "key": "2014/04/30/KDIX/KDIX20140430_120023_V06.gz",
        "bucket": "unidata-nexrad-level2",
        "role": "widespread precipitation, low fraction of high dBZ (case A)",
    },
}


def beam(r_m, el_deg):
    """Doviak & Zrnic (1993) Eq. 2.28 (4/3 model), r in m. Returns (z_m, s_m) as mpf."""
    r = mpf(r_m)
    th = mrad(mpf(el_deg))
    R = KE * R_EARTH_M
    z = msqrt(r * r + R * R + 2 * r * R * msin(th)) - R
    s = R * masin(r * mcos(th) / (R + z))
    return z, s


def place(lat, lon, az_deg, s_m):
    g = Geodesic.WGS84.Direct(lat, lon, az_deg, float(s_m))
    return g["lat2"], g["lon2"]


def fmt(x, nd=25):
    return mp.nstr(x, nd)


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def gate_range(m, k):
    return m["first_gate_m"] + k * m["gate_spacing_m"]  # ICD: range to CENTER of gate


def build_case(name, spec):
    path = os.path.join(ROOT, spec["file"])
    vol = spec_reader.read_volume(path)
    R = vol["radials"]
    v = R[0]["vol"]
    lat, lon = v["lat"], v["lon"]
    ant_msl = v["site_height_m"] + v["tower_height_m"]
    out = os.path.join(ROOT, "fixtures", name)
    os.makedirs(out, exist_ok=True)

    sweeps = {}
    for i, r in enumerate(R):
        sw = sweeps.setdefault(r["elevation_number"], {"first_radial_index": i, "n_radials": 0, "els": [],
                                                      "moments": sorted(r["moments"])})
        sw["n_radials"] += 1
        sw["els"].append(r["elevation"])
    ref_idx = [i for i, r in enumerate(R) if "REF" in r["moments"]]
    so = sorted({(r["moments"]["REF"]["scale"], r["moments"]["REF"]["offset"]) for r in R if "REF" in r["moments"]})
    assert len(so) == 1, so
    sc, of = so[0]
    meta = {
        "case": name, "role": spec["role"],
        "station": R[0]["icao"], "source_bucket": spec["bucket"], "source_key": spec["key"],
        "source_url": "https://%s.s3.amazonaws.com/%s" % (spec["bucket"], spec["key"]),
        "local_file": spec["file"], "sha256": sha256(path), "size_bytes": os.path.getsize(path),
        "container": vol["container"], "volume_header": vol["volume_header"],
        "n_radials": len(R), "message_counts": {str(k): n for k, n in vol["msg_counts"].items()},
        "first_radial_time_utc": spec_reader.radial_time_utc(R[0]).isoformat(),
        "last_radial_time_utc": spec_reader.radial_time_utc(R[-1]).isoformat(),
        "radar": {"lat": lat, "lon": lon, "site_height_m_msl": v["site_height_m"],
                  "tower_height_m_agl": v["tower_height_m"], "assumed_antenna_msl_m": ant_msl,
                  "assumption": "antenna MSL = site height + tower height (ICD Table XVII-E; Py-ART names the "
                                "tower field 'feedhorn_height'); not independently verified"},
        "ref_scale_offset": [sc, of],
        "sweeps": {str(k): {"first_radial_index": s["first_radial_index"], "n_radials": s["n_radials"],
                            "elev_min": min(s["els"]), "elev_max": max(s["els"]), "moments": s["moments"]}
                   for k, s in sorted(sweeps.items())},
        "model": {"effective_earth_radius_factor": "4/3", "earth_radius_m": 6371000,
                  "reference": "Doviak & Zrnic 1993 Eq. 2.28 via Py-ART/wradlib docs"},
    }

    # ---- raw_samples.csv ---------------------------------------------------
    rng = np.random.RandomState(sum(map(ord, name)))
    chosen = set()
    for i in rng.choice(ref_idx, size=min(120, len(ref_idx)), replace=False):
        m = R[i]["moments"]["REF"]
        chosen.add((int(i), int(rng.randint(0, m["ngates"]))))
    by_val = {}
    for i in ref_idx:
        raw = R[i]["moments"]["REF"]["raw"]
        mx = max(raw)
        for k, n in enumerate(raw):
            if n in (0, 1, 2):
                by_val.setdefault(str(n), []).append((i, k))
            elif n == mx and mx > 2:
                by_val.setdefault("rowmax", []).append((i, k))
    edge_log = {}
    for key, lst in sorted(by_val.items()):
        sel = rng.choice(len(lst), size=min(15, len(lst)), replace=False)
        chosen.update(lst[j] for j in sel)
        edge_log[key] = len(lst)
    for s in sweeps.values():
        a = s["first_radial_index"]
        for i in (a, a + s["n_radials"] - 1):
            if "REF" in R[i]["moments"]:
                n = R[i]["moments"]["REF"]["ngates"]
                chosen.update({(i, 0), (i, n - 1)})
    rows = sorted(chosen)
    with open(os.path.join(out, "raw_samples.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["elevation_number", "radial_index", "radial_number", "gate_idx", "raw_N", "scale", "offset",
                    "expected_dbz", "expected_class"])
        for i, k in rows:
            m = R[i]["moments"]["REF"]
            n = m["raw"][k]
            cls = "BELOW_THRESHOLD" if n == 0 else "RANGE_FOLDED" if n == 1 else "MEASURED"
            dbz = repr((n - m["offset"]) / m["scale"]) if n >= 2 else ""
            w.writerow([R[i]["elevation_number"], i, R[i]["radial_number"], k, n, m["scale"], m["offset"], dbz, cls])
    meta["raw_samples"] = {"n": len(rows), "value_populations_in_volume": edge_log}

    # ---- radial_geometry.csv (all REF radials) -----------------------------
    with open(os.path.join(out, "radial_geometry.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["radial_index", "elevation_number", "radial_number", "radial_status", "azimuth_deg",
                    "elevation_deg", "collect_julian", "collect_ms", "time_utc", "ngates", "first_gate_m",
                    "gate_spacing_m", "scale", "offset", "az_res_code"])
        for i in ref_idx:
            r = R[i]
            m = r["moments"]["REF"]
            w.writerow([i, r["elevation_number"], r["radial_number"], r["radial_status"], repr(float(r["azimuth"])),
                        repr(float(r["elevation"])), r["collect_julian"], r["collect_ms"],
                        spec_reader.radial_time_utc(r).isoformat(), m["ngates"], m["first_gate_m"],
                        m["gate_spacing_m"], m["scale"], m["offset"], r["az_res_code"]])

    def geo_row(i, k):
        r = R[i]
        m = r["moments"]["REF"]
        rng_m = gate_range(m, k)
        z, s = beam(rng_m, float(r["elevation"]))
        la, lo = place(lat, lon, float(r["azimuth"]), s)
        return [i, k, rng_m, repr(float(r["azimuth"])), repr(float(r["elevation"])), fmt(s), fmt(z),
                fmt(z + ant_msl), repr(la), repr(lo)]

    with open(os.path.join(out, "expected_geo.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["radial_index", "gate_idx", "slant_range_m", "azimuth_deg", "elevation_deg", "ground_arc_m",
                    "z_above_antenna_m", "height_msl_m", "lat_deg", "lon_deg"])
        for i, k in rows:
            w.writerow(geo_row(i, k))

    # ---- cross sections ----------------------------------------------------
    low = min(e for e in sweeps if any(R[i]["elevation_number"] == e for i in ref_idx))
    best = (-1, None, None)
    for i in ref_idx:
        if R[i]["elevation_number"] != low:
            continue
        raw = R[i]["moments"]["REF"]["raw"]
        k = int(np.argmax(raw))
        if raw[k] > best[0]:
            best = (raw[k], i, k)
    A1 = float(R[best[1]]["azimuth"])
    azs = [round(A1, 3) % 360, round(A1 + 90.0, 3) % 360]
    meta["cross_section_azimuths_deg"] = azs
    meta["cross_section_anchor"] = {"radial_index": best[1], "gate_idx": best[2], "raw_N": int(best[0])}

    xs_rows = []
    for az in azs:
        for en in sorted(sweeps):
            idx = [i for i in ref_idx if R[i]["elevation_number"] == en]
            if not idx:
                continue
            d = [abs((float(R[i]["azimuth"]) - az + 180) % 360 - 180) for i in idx]
            j = idx[int(np.argmin(d))]
            if min(d) > 1.0:
                continue
            m = R[j]["moments"]["REF"]
            for k, n in enumerate(m["raw"]):
                g = geo_row(j, k)
                xs_rows.append([az, en, j, k, n, g[2], g[5], g[6], g[7]])
    with open(os.path.join(out, "cross_section_ref.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["section_azimuth_deg", "elevation_number", "radial_index", "gate_idx", "raw_N", "slant_range_m",
                    "ground_arc_m", "z_above_antenna_m", "height_msl_m"])
        w.writerows(xs_rows)

    # ---- echo tops: highest MEASURED gate >= T per ground-arc window --------
    best_top = {}
    for az, en, j, k, n, rng_m, s, z, h in xs_rows:
        if n < 2:
            continue
        win = int(float(s) // WINDOW_M)
        for T in THRESHOLDS:
            if n >= T * sc + of:
                key = (az, T, win)
                hv = mpf(h)
                if key not in best_top or hv > best_top[key][0]:
                    best_top[key] = (hv, en, j, k)
    with open(os.path.join(out, "echo_top_ref.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["section_azimuth_deg", "threshold_dbz", "ground_window_start_m", "ground_window_end_m",
                    "top_height_msl_m", "elevation_number", "radial_index", "gate_idx"])
        for (az, T, win), (hv, en, j, k) in sorted(best_top.items()):
            w.writerow([az, T, win * WINDOW_M, (win + 1) * WINDOW_M, fmt(hv), en, j, k])
    meta["echo_top_definition"] = (
        "highest beam-centre height (MSL) among MEASURED gates with raw_N >= T*scale+offset in the nearest "
        "radial (<=1 deg) of each elevation on the section azimuth, per %d m ground-arc window. NOT an "
        "interpolated or physical echo top." % WINDOW_M)
    meta["threshold_integer_criterion"] = {str(T): int(T * sc + of) for T in THRESHOLDS}
    json.dump(meta, open(os.path.join(out, "case.json"), "w"), indent=2, default=str)
    return meta


if __name__ == "__main__":
    lock = {}
    for n, s in CASES.items():
        m = build_case(n, s)
        print(n, m["sha256"], m["n_radials"], "radials; raw samples:", m["raw_samples"]["n"])
        d = os.path.join(ROOT, "fixtures", n)
        lock[n] = {f: sha256(os.path.join(d, f)) for f in sorted(os.listdir(d))}
        lock[n]["_source_sha256"] = m["sha256"]
    json.dump(lock, open(os.path.join(ROOT, "fixtures", "fixtures.lock.json"), "w"), indent=2)
