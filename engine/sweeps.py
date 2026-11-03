"""Per-sweep artifacts for filled ("cone") rendering (PLAN_V2 R1).

For every elevation cut and product, write
  sweeps/<PRODUCT>/cut<N>/sweep.json   manifest (geometry, accounting, SHA-256 of both binaries)
  sweeps/<PRODUCT>/cut<N>/tex.bin      uint8 [n_radials][n_gates], row = one radial (azimuth ascending), the RAW integer N
  sweeps/<PRODUCT>/cut<N>/mesh.bin     float32 columns dlon_deg | dlat_deg | height_ellipsoid_m, each [n_radials][2][n_knots];
                                       dlon/dlat are offsets from the radar position (sweep.json origin_lon_deg/origin_lat_deg)
and sweeps/<PRODUCT>/index.json listing the cuts (and any cut that was skipped, with the reason).

Nothing here is a new measurement or an interpolation of data:
  * The texture holds the decoded raw N unchanged. The viewer converts with value = (N - offset)/scale for N >= 2 and
    treats N = 0 (below threshold) and N = 1 (range folded) as such. Unscanned cells do not exist in the texture
    (every radial of a cut must have the same gate geometry, else the cut is skipped and listed).
  * The mesh gives each radial a strip: its two edges are azimuth -/+ half the local azimuth spacing (a DISPLAY EXTENT,
    not the antenna beamwidth, which is not decoded: L24). Knots are placed every `stride` gates along the strip at the
    gate boundaries r = first_gate - spacing/2 + j*stride*spacing, using the engine's own beam geometry
    (engine/geometry.place_gates, 4/3 Earth) and EGM2008 for the ellipsoid height. The viewer draws straight
    triangles between knots; the straight-line departure from the true beam curve over one knot interval is
    reported in the manifest (`mesh_chord_error_m`, computed, not assumed).
"""
import hashlib
import json
import os

import numpy as np

from . import geoid, geometry
from .products import PRODUCTS

KNOT_STRIDE_GATES = 32
FLOOR_ELEV_NUMBER_KEY = "elevation_number"


def _sha(b):
    return hashlib.sha256(b).hexdigest()


def _cut_rows(vol, product, cut):
    """Radial indices of `cut` that carry `product`, azimuth ascending, plus their (uniform) gate geometry."""
    if product == "REF":
        has, ng, fg, gs, sc, of = vol.has_ref, vol.ngates, vol.first_gate_m, vol.gate_spacing_m, vol.scale, vol.offset
        raw = vol.ref_raw
    else:
        m = vol.moments[product]
        has, ng, fg, gs, sc, of, raw = m["has"], m["ngates"], m["first_gate_m"], m["gate_spacing_m"], m["scale"], m["offset"], m["raw"]
    idx = np.nonzero((vol.elevation_number == cut) & has)[0]
    if idx.size == 0:
        return None, "no radials carry this product in this cut"
    geo = {(int(ng[i]), float(fg[i]), float(gs[i]), float(sc[i]), float(of[i])) for i in idx}
    if len(geo) != 1:
        return None, "gate geometry, scale or offset differs between radials of the cut (%d variants)" % len(geo)
    mx = max(int(raw[i].max()) for i in idx)
    if mx > 255:
        return None, "raw values up to %d do not fit a one-byte texture" % mx
    order = idx[np.argsort(vol.azimuth_deg[idx], kind="stable")]
    n_gates, first, spacing, scale, offset = next(iter(geo))
    return dict(rows=order, raw=raw, n_gates=n_gates, first_gate_m=first, gate_spacing_m=spacing, scale=scale,
                offset=offset), None


def _half_widths_deg(az):
    """Half azimuth extent per row: half the mean of the gaps to the two neighbours, capped at 0.75x the median gap
    so a missing radial leaves a hole instead of being painted over."""
    n = len(az)
    gap_next = (np.roll(az, -1) - az) % 360.0
    gap_prev = (az - np.roll(az, 1)) % 360.0
    med = float(np.median(gap_next))
    half = 0.5 * np.minimum(0.5 * (gap_next + gap_prev), 1.5 * med)
    return np.minimum(half, 0.75 * med), med


def write_sweep(vol, product, cut, out_dir, stride=KNOT_STRIDE_GATES, with_geoid=True):
    """Write one cut. Returns the sweep.json dict, or raises ValueError(reason) when the cut cannot be represented."""
    g, why = _cut_rows(vol, product, cut)
    if g is None:
        raise ValueError(why)
    rows, n_gates = g["rows"], g["n_gates"]
    nrad = len(rows)
    tex = np.zeros((nrad, n_gates), dtype=np.uint8)
    for k, i in enumerate(rows):
        tex[k, :] = g["raw"][i][:n_gates].astype(np.uint8)
    az = vol.azimuth_deg[rows]
    el = vol.elevation_deg[rows]
    half, med_gap = _half_widths_deg(az)
    spacing, first = g["gate_spacing_m"], g["first_gate_m"]
    knots_gate = np.unique(np.minimum(np.arange(0, n_gates + stride, stride), n_gates))  # gate-boundary indices
    r_knot = first - 0.5 * spacing + knots_gate * spacing
    r_knot = np.maximum(r_knot, 0.0)
    nk = len(knots_gate)
    # vertex (row, side, knot); side 0 = azimuth - half, side 1 = azimuth + half
    az_v = np.empty((nrad, 2, nk)); el_v = np.empty((nrad, 2, nk)); r_v = np.empty((nrad, 2, nk))
    az_v[:, 0, :] = (az - half)[:, None]; az_v[:, 1, :] = (az + half)[:, None]
    el_v[:] = el[:, None, None]
    r_v[:] = r_knot[None, None, :]
    p = geometry.place_gates(vol.radar_lat, vol.radar_lon, vol.antenna_msl_m, r_v.ravel(), el_v.ravel(), az_v.ravel())
    lon, lat, hmsl = p["lon_deg"], p["lat_deg"], p["height_msl_m"]
    if with_geoid:
        N, status = geoid.undulation(lat, lon)
        if status != "ok" or not np.all(np.isfinite(N)):
            raise ValueError("geoid unavailable (%s); refusing to substitute" % status)
        hell = hmsl + N
    else:
        status, hell = "not computed", np.full(hmsl.shape, np.nan)
    # straight-line (chord) departure of the true beam curve over one knot interval, at the interval midpoint
    mid = 0.5 * (r_knot[:-1] + r_knot[1:])
    pm = geometry.place_gates(vol.radar_lat, vol.radar_lon, vol.antenna_msl_m, mid, np.full(mid.shape, float(el.mean())),
                              np.full(mid.shape, float(az.mean())))
    pa = geometry.place_gates(vol.radar_lat, vol.radar_lon, vol.antenna_msl_m, r_knot, np.full(r_knot.shape, float(el.mean())),
                              np.full(r_knot.shape, float(az.mean())))
    dh = np.abs(0.5 * (pa["height_msl_m"][:-1] + pa["height_msl_m"][1:]) - pm["height_msl_m"]) if nk > 1 else np.zeros(1)
    dg = np.abs(0.5 * (pa["ground_arc_m"][:-1] + pa["ground_arc_m"][1:]) - pm["ground_arc_m"]) if nk > 1 else np.zeros(1)
    tex_b = np.ascontiguousarray(tex).tobytes()
    # float32 offsets from the radar: resolution about 3 cm at 4 degrees, far below the 1 m chord error reported below
    mesh_b = b"".join(np.ascontiguousarray(c.astype("<f4")).tobytes()
                      for c in (lon - vol.radar_lon, lat - vol.radar_lat, hell))
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "tex.bin"), "wb") as f:
        f.write(tex_b)
    with open(os.path.join(out_dir, "mesh.bin"), "wb") as f:
        f.write(mesh_b)
    n_class = {"below_threshold_N0": int((tex == 0).sum()), "range_folded_N1": int((tex == 1).sum()),
               "measured_N_ge_2": int((tex >= 2).sum())}
    meta = {
        "schema_version": "1.0", "kind": "sweep-texture", "product": product, "unit": PRODUCTS[product]["unit"],
        "elevation_number": int(cut), "elevation_deg_mean": float(el.mean()),
        "elevation_deg_min": float(el.min()), "elevation_deg_max": float(el.max()),
        "n_radials": nrad, "n_gates": n_gates, "first_gate_m": first, "gate_spacing_m": spacing,
        "scale": g["scale"], "offset": g["offset"],
        "value_of_n": [None if n < 2 else float((n - g["offset"]) / g["scale"]) for n in range(256)],
        "conversion": "value = (N - offset) / scale for N >= 2; N = 0 below threshold; N = 1 range folded (ICD 2620002 Table XVII-I note 21)",
        "texture": {"file": "tex.bin", "dtype": "u8", "layout": "row-major [n_radials][n_gates]", "width": n_gates,
                    "height": nrad, "sha256": _sha(tex_b), "size_bytes": len(tex_b), "classes": n_class},
        "rows": {"radial_index": [int(i) for i in rows], "azimuth_deg": [float(a) for a in az],
                 "azimuth_half_width_deg": [float(h) for h in half], "median_azimuth_gap_deg": med_gap,
                 "radial_time_ms_utc": [int(t) for t in vol.radial_time_ms_since_epoch()[rows]],
                 "note": "half-width is a display extent (half the local azimuth spacing), not the antenna beamwidth (L24)"},
        "mesh": {"file": "mesh.bin", "dtype": "<f4", "layout": "columns dlon_deg | dlat_deg | height_ellipsoid_m, each [n_radials][2][n_knots]",
                 "origin_lon_deg": float(vol.radar_lon), "origin_lat_deg": float(vol.radar_lat),
                 "n_knots": nk, "knot_stride_gates": stride, "knot_gate_boundary": [int(k) for k in knots_gate],
                 "knot_range_m": [float(r) for r in r_knot], "sha256": _sha(mesh_b), "size_bytes": len(mesh_b),
                 "model": "4/3 effective Earth radius (engine/geometry.py), WGS84 geodesic, EGM2008 via PROJ",
                 "geoid_status": status,
                 "mesh_chord_error_m": {"height_max": float(dh.max()), "ground_arc_max": float(dg.max()),
                                        "note": "departure of a straight segment from the beam curve over one knot interval, at the mean cut elevation"}},
        "source_sha256": vol.source_sha256, "station": vol.station, "interpolation": "none",
    }
    with open(os.path.join(out_dir, "sweep.json"), "w") as f:
        json.dump(meta, f)
    return meta


def write_all_sweeps(vol, out_root, products=None, stride=KNOT_STRIDE_GATES):
    """sweeps/<PRODUCT>/cut<N>/ for every product and cut that can be represented. Returns {product: index dict}."""
    result = {}
    for prod in PRODUCTS:
        if products is not None and prod not in products:
            continue
        if prod == "REF":
            has = vol.has_ref
        else:
            if not vol.moments[prod]["has"].any():
                continue
            has = vol.moments[prod]["has"]
        cuts = sorted({int(c) for c in vol.elevation_number[has]})
        entries, skipped = [], []
        for c in cuts:
            d = os.path.join(out_root, "sweeps", prod, "cut%d" % c)
            try:
                m = write_sweep(vol, prod, c, d, stride=stride)
                entries.append({"elevation_number": c, "path": "sweeps/%s/cut%d" % (prod, c),
                                "elevation_deg_mean": m["elevation_deg_mean"], "n_radials": m["n_radials"], "n_gates": m["n_gates"]})
            except ValueError as e:
                skipped.append({"elevation_number": c, "reason": str(e)})
        os.makedirs(os.path.join(out_root, "sweeps", prod), exist_ok=True)
        idx = {"product": prod, "unit": PRODUCTS[prod]["unit"], "cuts": entries, "skipped": skipped}
        with open(os.path.join(out_root, "sweeps", prod, "index.json"), "w") as f:
            json.dump(idx, f)
        result[prod] = idx
    return result
