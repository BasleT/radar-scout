"""Named historic cases published from the public Level II archive (PLAN_V2 R2).

Each case is a station plus a UTC window; every volume in the window is fetched unmodified from the archive and run
through the same engine as live data, so every value keeps its source SHA-256. The windows and event times below are
approximate, taken from public NWS event summaries and NOT verified by this project; they only choose which archive
files to fetch. Output: <out>/cases/<id>/<STATION>/<stamp>/ with its own index.json (point the app's server URL at
<data>/cases/<id>), plus <out>/cases.json listing the cases that were actually published.
"""
import json
import os
import re
import sys

from .publish import BUCKET_DEFAULT, list_keys, publish_key, write_index

CASES = [
    dict(id="el-reno-2013-05-31", title="El Reno tornado, 31 May 2013", station="KTLX", date="2013-05-31",
         window=("2250", "2320"), note="Event time approximate (touchdown near 23:03 UTC per public NWS summaries)."),
    dict(id="moore-2013-05-20", title="Moore tornado, 20 May 2013", station="KTLX", date="2013-05-20",
         window=("1940", "2010"), note="Event time approximate (touchdown near 19:56 UTC per public NWS summaries)."),
]


def case_keys(c, bucket_url):
    y, m, d = c["date"].split("-")
    lo, hi = c["window"]
    out = []
    for key, etag in list_keys(bucket_url, "%s/%s/%s/%s/" % (y, m, d, c["station"])):
        mm = re.search(r"_(\d{4})\d{2}_V\d\d(\.gz)?$", key)
        if mm and lo <= mm.group(1) <= hi and not key.endswith("_MDM"):
            out.append((key, etag))
    return sorted(out)


def publish_cases(out_root, raw_cache, work, bucket_url=BUCKET_DEFAULT, only=None):
    listing = []
    for c in CASES:
        if only and c["id"] not in only:
            continue
        keys = case_keys(c, bucket_url)
        if not keys:
            print("no archive files found for", c["id"], "; case not published")
            continue
        root = os.path.join(out_root, "cases", c["id"])
        for key, etag in keys:
            publish_key(key, etag, bucket_url, raw_cache, work, root, skip_lowest_threshold=True)
        write_index(root, c["station"])
        listing.append({"id": c["id"], "title": c["title"], "station": c["station"], "date": c["date"],
                        "base": "cases/%s" % c["id"], "n_volumes": len(keys), "note": c["note"]})
    if listing:
        with open(os.path.join(out_root, "cases.json"), "w") as f:
            json.dump({"cases": listing}, f, indent=1)
    return listing


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("WEB_DATA", "/var/radar/web")
    publish_cases(out, os.environ.get("RAW_CACHE", "/var/radar/raw"), os.environ.get("WORK_DIR", "/var/radar/work"))
