"""MSL -> WGS84 ellipsoidal height conversion via the EGM2008 geoid grid distributed with PROJ.

h_ellipsoid = H_msl + N, where N is the geoid undulation (EPSG:3855 vertical CRS, "EGM2008 height").
If the grid cannot be obtained, N is NaN and ellipsoid heights are NaN: never silently replaced by 0.
"""
import numpy as np
from pyproj import Transformer
from pyproj.network import set_network_enabled

MODEL = "EGM2008 (EPSG:3855) via PROJ grid us_nga_egm08_25"


def undulation(lat_deg, lon_deg):
    """Return (N_metres array, status string). status is 'ok' or a failure description."""
    lat = np.asarray(lat_deg, dtype=np.float64)
    lon = np.asarray(lon_deg, dtype=np.float64)
    try:
        set_network_enabled(True)
        t = Transformer.from_crs("EPSG:4326+3855", "EPSG:4979", always_xy=True)
        _, _, h = t.transform(lon, lat, np.zeros_like(lat))
        h = np.asarray(h, dtype=np.float64)
        if not np.all(np.isfinite(h)):
            return np.full(lat.shape, np.nan), "grid returned non-finite values"
        return h, "ok"
    except Exception as e:  # noqa: BLE001 - report, never mask
        return np.full(lat.shape, np.nan), "geoid unavailable: %s" % e
