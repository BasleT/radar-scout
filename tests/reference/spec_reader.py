"""R1: independent from-spec reader for NEXRAD Archive II / Message Type 31.

Written directly from ROC ICD 2620010 section 7.3-7.6 (archive wrapper) and
ICD 2620002 Rev AA Tables II and XVII-A/B/E/H (docs/sources/2620002AA.txt).
Deliberately shares NO code with Py-ART, xradar, wradlib or the engine.
Test-only: it is not part of the application.

Layout used (byte offsets are from the ICD tables):
  file:        [gzip] -> 24-byte volume header -> LDM records
  LDM record:  4-byte big-endian signed size (abs value = compressed bytes), bzip2 block
  message:     12-byte legacy CTM pad, then Table II header (16 bytes), then body
               header: size(halfwords, incl. header) u16 @0, channel u8 @2, type u8 @3,
                       seq u16 @4, julian u16 @6, ms u32 @8, nseg u16 @12, segno u16 @14
  type 31 body (Table XVII-A, offsets relative to start of body):
    0-3 ICAO, 4-7 collect ms (u32), 8-9 collect julian date (u16, 1 = 1970-01-01),
    10-11 radial number (u16), 12-15 azimuth (f32), 16 compression, 18-19 radial length,
    20 az resolution code, 21 radial status, 22 elevation number, 23 cut sector,
    24-27 elevation angle (f32), 30-31 data block count, 32+ u32 block pointers
    (VOL, ELV, RAD, REF, VEL, SW, ZDR, PHI, RHO, CFP), relative to body start.
  VOL block (XVII-E): 8-11 lat f32, 12-15 lon f32, 16-17 site height i16 (m MSL),
    18-19 tower height u16 (m AGL).
  Moment block (XVII-B): 1-3 name, 8-9 ngates u16, 10-11 first gate range u16 (m),
    12-13 gate interval u16 (m), 19 data word size u8, 20-23 scale f32, 24-27 offset f32,
    28.. data (DWS bits per gate).
All multi-byte values big-endian.
"""
import bz2
import gzip
import struct
from datetime import datetime, timedelta, timezone

MOMENT_ORDER = ["REF", "VEL", "SW ", "ZDR", "PHI", "RHO", "CFP"]


def _open_bytes(path):
    raw = open(path, "rb").read()
    if raw[:2] == b"\x1f\x8b":
        raw = gzip.decompress(raw)
    return raw


def read_volume(path):
    raw = _open_bytes(path)
    hdr = raw[:24]
    out = {"volume_header": {"tape": hdr[:9].decode("ascii"), "ext": hdr[9:12].decode("ascii"),
                             "julian": struct.unpack(">I", hdr[12:16])[0],
                             "ms": struct.unpack(">I", hdr[16:20])[0],
                             "icao": hdr[20:24].decode("ascii")},
           "radials": [], "msg_counts": {}}
    pos = 24
    if raw[pos + 4:pos + 7] != b"BZh":
        # Uncompressed message stream (older archive files: the .gz wraps raw
        # CTM-padded messages directly; no LDM bzip2 records).
        out["container"] = "raw-messages"
        _parse_block(raw[pos:], out)
        return out
    out["container"] = "ldm-bzip2"
    while pos + 4 <= len(raw):
        (size,) = struct.unpack(">i", raw[pos:pos + 4])
        pos += 4
        n = abs(size)
        if n == 0:
            break
        block = bz2.decompress(raw[pos:pos + n])
        pos += n
        _parse_block(block, out)
    return out


def _parse_block(buf, out):
    p = 0
    while p + 28 <= len(buf):
        hdr = buf[p + 12:p + 28]
        size_hw, _ch, mtype, _seq, _jd, _ms, _nseg, _segno = struct.unpack(">HBBHHIHH", hdr)
        if size_hw == 0 and mtype == 0:
            p += 2432
            continue
        out["msg_counts"][mtype] = out["msg_counts"].get(mtype, 0) + 1
        if mtype == 31:
            body = buf[p + 28:p + 12 + size_hw * 2]
            out["radials"].append(_parse_radial(body))
            p += 12 + size_hw * 2
        else:
            p += 2432


def _parse_radial(b):
    r = {}
    r["icao"] = b[0:4].decode("ascii")
    r["collect_ms"], r["collect_julian"], r["radial_number"] = struct.unpack(">IHH", b[4:12])
    r["azimuth"], = struct.unpack(">f", b[12:16])
    r["compression"] = b[16]
    r["radial_length"], = struct.unpack(">H", b[18:20])
    r["az_res_code"] = b[20]
    r["radial_status"] = b[21]
    r["elevation_number"] = b[22]
    r["elevation"], = struct.unpack(">f", b[24:28])
    nblocks, = struct.unpack(">H", b[30:32])
    ptrs = struct.unpack(">%dI" % nblocks, b[32:32 + 4 * nblocks])
    r["moments"] = {}
    for off in ptrs:
        tag = b[off:off + 4]
        if tag == b"RVOL":
            lat, lon, sh, th = struct.unpack(">ffhH", b[off + 8:off + 20])
            r["vol"] = {"lat": lat, "lon": lon, "site_height_m": sh, "tower_height_m": th}
        elif tag[:1] == b"D":
            name = tag[1:4].decode("ascii")
            ng, fg, gs = struct.unpack(">HHH", b[off + 8:off + 14])
            dws = b[off + 19]
            scale, offset = struct.unpack(">ff", b[off + 20:off + 28])
            assert dws in (8, 16), dws
            fmt = ">%d%s" % (ng, "B" if dws == 8 else "H")
            data = struct.unpack(fmt, b[off + 28:off + 28 + ng * (dws // 8)])
            r["moments"][name] = {"ngates": ng, "first_gate_m": fg, "gate_spacing_m": gs,
                                  "scale": scale, "offset": offset, "raw": data}
    return r


def radial_time_utc(r):
    return (datetime(1970, 1, 1, tzinfo=timezone.utc)
            + timedelta(days=r["collect_julian"] - 1, milliseconds=r["collect_ms"]))
