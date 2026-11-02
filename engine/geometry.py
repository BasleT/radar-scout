"""Beam geometry and geodetic placement.

Model (documented assumption, see ARCHITECTURE.md 4.1): standard-atmosphere 4/3 effective earth radius,
Doviak & Zrnic (1993) Eq. 2.28, as implemented in the Py-ART and wradlib documentation:

    R = ke * re
    z = sqrt(r^2 + R^2 + 2 r R sin(theta)) - R      (height above the antenna's local reference sphere)
    s = R * asin(r cos(theta) / (R + z))            (arc length along the reference sphere)

z is evaluated in the algebraically identical, cancellation-free form
    z = (r^2 + 2 r R sin(theta)) / (sqrt(r^2 + R^2 + 2 r R sin(theta)) + R).

Horizontal placement: forward geodesic on the WGS84 ellipsoid from the radar position, distance s,
true-north azimuth. Refractivity is NOT measured; real beams can deviate (SCIENTIFIC_LIMITATIONS L3).
"""
import numpy as np
from pyproj import Geod

KE = 4.0 / 3.0
RE_M = 6371000.0
_GEOD = Geod(ellps="WGS84")


def beam_height_and_arc(range_m, elev_deg, ke=KE, re=RE_M):
    r = np.asarray(range_m, dtype=np.float64)
    th = np.radians(np.asarray(elev_deg, dtype=np.float64))
    R = ke * re
    root = np.sqrt(r * r + R * R + 2.0 * r * R * np.sin(th))
    z = (r * r + 2.0 * r * R * np.sin(th)) / (root + R)
    s = R * np.arcsin(r * np.cos(th) / (R + z))
    return z, s


def place_gates(radar_lat, radar_lon, antenna_msl_m, range_m, elev_deg, az_deg, ke=KE, re=RE_M):
    """Return dict of float64 arrays: ground_arc_m, z_above_antenna_m, height_msl_m, lat_deg, lon_deg."""
    z, s = beam_height_and_arc(range_m, elev_deg, ke, re)
    az = np.asarray(az_deg, dtype=np.float64)
    s_b, az_b = np.broadcast_arrays(s, az)
    lon, lat, _ = _GEOD.fwd(np.full(s_b.shape, radar_lon), np.full(s_b.shape, radar_lat), az_b, s_b)
    return {"ground_arc_m": s, "z_above_antenna_m": z, "height_msl_m": z + antenna_msl_m,
            "lat_deg": lat, "lon_deg": lon}
