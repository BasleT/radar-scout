"""Write engine artifacts: manifest.json, samples.parquet, radials.parquet (schema in engine/schema/)."""
import datetime
import json
import os
import platform

import pandas as pd
import pyart
import pyproj

from . import __version__, geoid, geometry
from .decode import load_volume
from .samples import CHAIN_ID, TRANSFORM_CHAIN, build_samples, radials_table


def _iso(ms):
    return (datetime.datetime(1970, 1, 1, tzinfo=datetime.timezone.utc)
            + datetime.timedelta(milliseconds=ms)).isoformat()


def _write_coverage(vol, rad, outdir):
    """coverage.json: per elevation number, the outer edge (last RECORDED gate centre) of every radial that has REF.

    This shows how far each cut recorded data. It is NOT terrain blockage, beam-overshoot or sensitivity coverage,
    and says nothing about whether echoes exist beyond it. Positions use the same placement and geoid as samples.
    """
    import numpy as np
    sel = np.flatnonzero(vol.has_ref & (vol.ngates > 0))
    rng = vol.first_gate_m[sel] + (vol.ngates[sel] - 1) * vol.gate_spacing_m[sel]
    g = geometry.place_gates(vol.radar_lat, vol.radar_lon, vol.antenna_msl_m, rng, vol.elevation_deg[sel],
                             vol.azimuth_deg[sel])
    N, status = geoid.undulation(np.asarray(g["lat_deg"]), np.asarray(g["lon_deg"]))
    if status != "ok":
        raise ValueError("geoid unavailable for coverage edge: %r" % status)
    h = np.asarray(g["height_msl_m"]) + N
    cuts = {}
    for k, i in enumerate(sel):
        cuts.setdefault(int(vol.elevation_number[i]), []).append(
            [int(i), float(g["lon_deg"][k]), float(g["lat_deg"][k]), float(h[k]), float(rng[k])])
    out = {"kind": "recorded-extent", "geoid_status": status,
           "note": "outer edge = last recorded gate centre per radial; not terrain blockage or sensitivity limit",
           "columns": ["radial_index", "lon_deg", "lat_deg", "height_ellipsoid_m", "slant_range_m"],
           "cuts": {str(k): v for k, v in sorted(cuts.items())}}
    with open(os.path.join(outdir, "coverage.json"), "w") as f:
        json.dump(out, f)
    cols = ["radial_index", "elevation_number", "azimuth_deg", "elevation_deg", "radial_time_ms_utc", "has_ref",
            "ngates_recorded", "first_gate_m", "gate_spacing_m"]
    with open(os.path.join(outdir, "radials.json"), "w") as f:
        json.dump({"columns": cols, "rows": {c: rad[c].tolist() for c in cols}}, f)


def export_volume(path, outdir, include=("MEASURED", "RANGE_FOLDED"), etag=None, source_url=None):
    vol = load_volume(path)
    df, geoid_status = build_samples(vol, include=include)
    rad = radials_table(vol)
    os.makedirs(outdir, exist_ok=True)
    df.to_parquet(os.path.join(outdir, "samples.parquet"), index=False)
    rad.to_parquet(os.path.join(outdir, "radials.parquet"), index=False)
    _write_coverage(vol, rad, outdir)
    manifest = {
        "schema_version": "1.0",
        "engine_version": __version__,
        "source": {"file": vol.source_name, "sha256": vol.source_sha256, "size_bytes": vol.source_size_bytes,
                   "s3_etag": etag, "url": source_url},
        "station": vol.station, "vcp": vol.vcp,
        "radar": {"lat": vol.radar_lat, "lon": vol.radar_lon, "site_height_m_msl": vol.site_height_m_msl,
                  "tower_height_m_agl": vol.tower_height_m_agl, "antenna_height_m_msl": vol.antenna_msl_m,
                  "antenna_height_assumption": "site height + tower height (unverified; see limitations)"},
        "volume_time_utc": {
            "first_radial": _iso(int(rad["radial_time_ms_utc"].iloc[0])),
            "last_radial": _iso(int(rad["radial_time_ms_utc"].iloc[-1])),
            "note": "per-radial times are in radials.parquet; sweeps are NOT simultaneous"},
        "n_radials": int(len(rad)), "n_samples": int(len(df)), "included_classes": list(include),
        "implicit_classes": {"BELOW_THRESHOLD": "recorded gate with N=0, absent from samples when excluded",
                             "NOT_SCANNED": "gate index >= ngates_recorded of its radial (see radials.parquet)"},
        "model": {"ke": geometry.KE, "re_m": geometry.RE_M, "horizontal": "WGS84 forward geodesic"},
        "geoid": {"model": geoid.MODEL, "status": geoid_status},
        "interpolation": "none",
        "transform_chains": {CHAIN_ID: TRANSFORM_CHAIN},
        "software": {"python": platform.python_version(), "pyart": pyart.__version__, "pyproj": pyproj.__version__,
                     "pandas": pd.__version__, "decoder": vol.decoder},
    }
    with open(os.path.join(outdir, "manifest.json"), "w") as f:
        json.dump(manifest, f, indent=2)
    return manifest
