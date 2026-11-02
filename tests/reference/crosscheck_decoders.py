"""R1 (from-spec reader) vs decoder A (Py-ART) vs decoder B (xradar) over the ENTIRE volume.

Any raw-integer mismatch is a hard failure (VALIDATION_PLAN T1). Writes a JSON report; does not
modify any fixture. Test-only module: must not import the engine.
"""
import gzip
import json
import os
import shutil
import sys
import warnings
from datetime import datetime, timezone

import numpy as np

sys.path.insert(0, os.path.dirname(__file__))
import spec_reader  # noqa: E402

warnings.filterwarnings("ignore")
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


def _gunzip(path, scratch):
    os.makedirs(scratch, exist_ok=True)
    dst = os.path.join(scratch, os.path.basename(path)[:-3])
    if not os.path.exists(dst):
        with gzip.open(path) as a, open(dst, "wb") as b:
            shutil.copyfileobj(a, b)
    return dst


def check_pyart(path, R1):
    from pyart.io.nexrad_level2 import NEXRADLevel2File
    f = NEXRADLevel2File(path)
    recs = f.radial_records
    res = {"n_radials_r1": len(R1), "n_radials_pyart": len(recs), "raw_mismatch_gates": 0, "gates_compared": 0,
           "radials_with_ngates_mismatch": 0, "azimuth_max_abs_diff_deg": 0.0, "elevation_max_abs_diff_deg": 0.0,
           "time_mismatch_radials": 0, "scale_offset_mismatch_radials": 0, "gate_geom_mismatch_radials": 0}
    if len(recs) != len(R1):
        res["fatal"] = "radial count differs"
        return res
    for a, b in zip(R1, recs):
        h = b["msg_header"]
        res["azimuth_max_abs_diff_deg"] = max(res["azimuth_max_abs_diff_deg"], abs(a["azimuth"] - h["azimuth_angle"]))
        res["elevation_max_abs_diff_deg"] = max(res["elevation_max_abs_diff_deg"],
                                                abs(a["elevation"] - h["elevation_angle"]))
        if (a["collect_ms"], a["collect_julian"]) != (h["collect_ms"], h["collect_date"]):
            res["time_mismatch_radials"] += 1
        if "REF" in a["moments"] or "REF" in b:
            ma, mb = a["moments"].get("REF"), b.get("REF")
            if ma is None or mb is None:
                res["radials_with_ngates_mismatch"] += 1
                continue
            if ma["ngates"] != mb["ngates"]:
                res["radials_with_ngates_mismatch"] += 1
            da = np.asarray(ma["raw"], dtype=np.int64)
            db = np.asarray(mb["data"], dtype=np.int64)
            n = min(len(da), len(db))
            res["gates_compared"] += n
            res["raw_mismatch_gates"] += int((da[:n] != db[:n]).sum())
            if (ma["scale"], ma["offset"]) != (mb["scale"], mb["offset"]):
                res["scale_offset_mismatch_radials"] += 1
            if (ma["first_gate_m"], ma["gate_spacing_m"]) != (mb["first_gate"], mb["gate_spacing"]):
                res["gate_geom_mismatch_radials"] += 1
    loc = f.location()
    v = R1[0]["vol"]
    res["pyart_location"] = list(map(float, loc))
    res["r1_location"] = [v["lat"], v["lon"], v["site_height_m"] + v["tower_height_m"]]
    return res


def check_xradar(path, R1, scratch):
    import xradar as xd
    p = _gunzip(path, scratch)
    dt = xd.io.open_nexradlevel2_datatree(p)
    # index R1 radials by (julian, ms) -> radial
    idx = {(r["collect_julian"], r["collect_ms"]): r for r in R1 if "REF" in r["moments"]}
    epoch = np.datetime64("1970-01-01T00:00:00", "ms")
    res = {"sweeps": 0, "rays": 0, "rays_unmatched": 0, "gates_compared": 0, "dbz_mismatch_gates": 0,
           "max_abs_dbz_diff": 0.0, "azimuth_max_abs_diff_deg": 0.0, "elevation_max_abs_diff_deg": 0.0,
           "range_mismatch_rays": 0}
    for name in sorted(k for k in dt.children if k.startswith("sweep_")):
        ds = dt[name].ds
        if "DBZH" not in ds:
            continue
        res["sweeps"] += 1
        t = np.rint((ds["time"].values.astype("datetime64[ns]") - np.datetime64("1970-01-01T00:00:00", "ns"))
                    .astype(np.int64) / 1e6).astype(np.int64)
        for i in range(ds.sizes["azimuth"]):
            days, ms = divmod(int(t[i]), 86400000)
            r = idx.get((days + 1, ms))
            res["rays"] += 1
            if r is None:
                res["rays_unmatched"] += 1
                continue
            m = r["moments"]["REF"]
            raw = np.asarray(m["raw"], dtype=np.int64)
            exp = np.where(raw >= 2, (raw - m["offset"]) / m["scale"], np.nan)
            lowmask = raw < 2
            got = ds["DBZH"].values[i]
            n = min(len(exp), len(got))
            # xradar may drop leading/trailing gates: align on range
            rng = ds["range"].values.astype(np.float64)
            first = m["first_gate_m"]
            k0 = int(round((rng[0] - first) / m["gate_spacing_m"]))
            if abs(rng[0] - (first + k0 * m["gate_spacing_m"])) > 1e-3:
                res["range_mismatch_rays"] += 1
                continue
            sl = exp[k0:k0 + len(got)]
            g2 = got[:len(sl)]
            lm = lowmask[k0:k0 + len(got)][:len(g2)]
            # xradar's treatment of N<2 gates (reference-tool behaviour, recorded not asserted)
            res.setdefault("xradar_low_gate_values", {})
            for nv in (0, 1):
                sel = (raw[k0:k0 + len(got)][:len(g2)] == nv)
                if sel.any():
                    vals = g2[sel]
                    key = "N=%d" % nv
                    d_ = res["xradar_low_gate_values"].setdefault(key, {"n": 0, "nan": 0, "equals_(N-off)/scale": 0})
                    d_["n"] += int(sel.sum())
                    d_["nan"] += int(np.isnan(vals).sum())
                    d_["equals_(N-off)/scale"] += int((vals == (nv - m["offset"]) / m["scale"]).sum())
            sl = np.where(lm, np.nan, sl)
            g2 = np.where(lm, np.nan, g2)   # compare only gates with N>=2 (measured)
            both = ~(np.isnan(sl) & np.isnan(g2))
            res["gates_compared"] += int(len(sl))
            diff = np.where(np.isnan(sl) != np.isnan(g2), np.inf, np.abs(np.nan_to_num(sl) - np.nan_to_num(g2)))
            res["dbz_mismatch_gates"] += int((diff[both] > 0).sum())
            if both.any():
                fin = diff[both][np.isfinite(diff[both])]
                if fin.size:
                    res["max_abs_dbz_diff"] = max(res["max_abs_dbz_diff"], float(fin.max()))
            res["azimuth_max_abs_diff_deg"] = max(
                res["azimuth_max_abs_diff_deg"],
                abs((float(ds["azimuth"].values[i]) - float(r["azimuth"]) + 180) % 360 - 180))
            res["elevation_max_abs_diff_deg"] = max(res["elevation_max_abs_diff_deg"],
                                                    abs(float(ds["elevation"].values[i]) - float(r["elevation"])))
    return res


def run_case(rel_file, scratch):
    path = os.path.join(ROOT, rel_file)
    vol = spec_reader.read_volume(path)
    R1 = vol["radials"]
    return {"file": rel_file, "pyart_vs_spec": check_pyart(_gunzip(path, scratch), R1),
            "xradar_vs_spec": check_xradar(path, R1, scratch)}


if __name__ == "__main__":
    scratch = os.path.join(ROOT, "scratch")
    out = {}
    for rel in ("data/raw/KTLX20130520_195111_V06.gz", "data/raw/KDIX20140430_120023_V06.gz"):
        out[os.path.basename(rel)] = run_case(rel, scratch)
    print(json.dumps(out, indent=1, default=str))
