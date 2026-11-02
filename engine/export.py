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


def export_volume(path, outdir, include=("MEASURED", "RANGE_FOLDED"), etag=None, source_url=None):
    vol = load_volume(path)
    df, geoid_status = build_samples(vol, include=include)
    rad = radials_table(vol)
    os.makedirs(outdir, exist_ok=True)
    df.to_parquet(os.path.join(outdir, "samples.parquet"), index=False)
    rad.to_parquet(os.path.join(outdir, "radials.parquet"), index=False)
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
