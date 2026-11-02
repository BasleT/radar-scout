"""Level II decoding via Py-ART's NEXRADLevel2File (decoder A).

Raw integer data (N) are kept; nothing is converted, masked or interpolated here.
Py-ART's higher-level reader is deliberately NOT used: it masks N=0 and N=1 together, fills missing
gates with 1 (ambiguous with range folding), and may interpolate mixed-resolution rays
(SCIENTIFIC_LIMITATIONS L15).
"""
import gzip
import hashlib
import os
import shutil
import tempfile
from dataclasses import dataclass, field

import numpy as np


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


@dataclass
class Volume:
    source_path: str
    source_name: str
    source_sha256: str
    source_size_bytes: int
    station: str
    radar_lat: float
    radar_lon: float
    site_height_m_msl: float
    tower_height_m_agl: float
    vcp: int
    # per-radial arrays (file order)
    elevation_number: np.ndarray
    radial_number: np.ndarray
    radial_status: np.ndarray
    azimuth_deg: np.ndarray       # float64 widened from float32 in file
    elevation_deg: np.ndarray
    collect_julian: np.ndarray
    collect_ms: np.ndarray
    has_ref: np.ndarray
    ngates: np.ndarray
    first_gate_m: np.ndarray
    gate_spacing_m: np.ndarray
    scale: np.ndarray
    offset: np.ndarray
    ref_raw: list = field(default_factory=list)   # list[np.ndarray uint8] (None where no REF)
    decoder: dict = field(default_factory=dict)

    @property
    def antenna_msl_m(self):
        return self.site_height_m_msl + self.tower_height_m_agl

    def radial_time_ms_since_epoch(self):
        return (self.collect_julian.astype(np.int64) - 1) * 86400000 + self.collect_ms.astype(np.int64)


def load_volume(path):
    import pyart
    from pyart.io.nexrad_level2 import NEXRADLevel2File

    path = os.path.abspath(path)
    sha = sha256_file(path)
    tmpdir = tempfile.mkdtemp(prefix="nexrad_")
    try:
        with open(path, "rb") as f:
            magic = f.read(2)
        if magic == b"\x1f\x8b":
            local = os.path.join(tmpdir, "volume.ar2v")
            with gzip.open(path) as a, open(local, "wb") as b:
                shutil.copyfileobj(a, b)
        else:
            local = path
        nf = NEXRADLevel2File(local)
        if nf._msg_type != "31":
            raise ValueError("only Message Type 31 volumes are supported (found %r)" % nf._msg_type)
        recs = nf.radial_records
        n = len(recs)
        v = recs[0]["VOL"]
        out = dict(
            elevation_number=np.zeros(n, np.int16), radial_number=np.zeros(n, np.int32),
            radial_status=np.zeros(n, np.int8), azimuth_deg=np.zeros(n), elevation_deg=np.zeros(n),
            collect_julian=np.zeros(n, np.int32), collect_ms=np.zeros(n, np.int64),
            has_ref=np.zeros(n, bool), ngates=np.zeros(n, np.int32), first_gate_m=np.zeros(n),
            gate_spacing_m=np.zeros(n), scale=np.zeros(n), offset=np.zeros(n))
        ref_raw = []
        for i, r in enumerate(recs):
            h = r["msg_header"]
            out["elevation_number"][i] = h["elevation_number"]
            # Py-ART labels ICD byte 21 (radial status, Table XVII-A) 'radial_spacing'; verified equal to the
            # independent spec reader in tests (test_decode_matches_spec_reader).
            out["radial_status"][i] = h["radial_spacing"]
            out["radial_number"][i] = h["azimuth_number"]
            out["azimuth_deg"][i] = h["azimuth_angle"]
            out["elevation_deg"][i] = h["elevation_angle"]
            out["collect_julian"][i] = h["collect_date"]
            out["collect_ms"][i] = h["collect_ms"]
            if "REF" in r:
                m = r["REF"]
                out["has_ref"][i] = True
                out["ngates"][i] = m["ngates"]
                out["first_gate_m"][i] = m["first_gate"]
                out["gate_spacing_m"][i] = m["gate_spacing"]
                out["scale"][i] = m["scale"]
                out["offset"][i] = m["offset"]
                ref_raw.append(np.asarray(m["data"]).astype(np.uint16))
            else:
                ref_raw.append(None)
        vcp = v.get("vcp")
        return Volume(
            source_path=path, source_name=os.path.basename(path), source_sha256=sha,
            source_size_bytes=os.path.getsize(path), station=recs[0]["msg_header"]["id"].decode(),
            radar_lat=float(v["lat"]), radar_lon=float(v["lon"]), site_height_m_msl=float(v["height"]),
            tower_height_m_agl=float(v["feedhorn_height"]), vcp=int(vcp) if vcp is not None else -1,
            ref_raw=ref_raw,
            decoder={"name": "pyart.io.nexrad_level2.NEXRADLevel2File", "pyart_version": pyart.__version__},
            **out)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
