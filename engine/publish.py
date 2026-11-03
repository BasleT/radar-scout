"""Fetch the newest Level II volume for one station, run the engine, and publish viewer artifacts.

Output layout under WEB_DATA:  <STATION>/<volume-stamp>/{manifest.json,thr30/,thr40/,thr50/}  and a `latest` symlink.
The source file is the public NOAA archive object, stored unmodified in RAW_CACHE with its SHA-256 and S3 ETag
recorded in manifest.json. If anything fails the previous `latest` is left untouched; no stand-in data is created.
The S3 bucket and object naming are configurable because they have changed before (see ARCHITECTURE.md sources).
"""
import datetime
import os
import re
import shutil
import sys
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

from .export import export_volume
from .viewer_export import export_viewer

THRESHOLDS = (20, 30, 40, 50)


def list_keys(bucket_url, prefix):
    keys = []
    url = "%s/?list-type=2&prefix=%s" % (bucket_url, urllib.parse.quote(prefix))
    with urllib.request.urlopen(url, timeout=60) as r:
        root = ET.fromstring(r.read())
    ns = {"s": root.tag.split("}")[0].strip("{")}
    for c in root.findall("s:Contents", ns):
        keys.append((c.find("s:Key", ns).text, c.find("s:ETag", ns).text.strip('"')))
    return keys


def newest_key(bucket_url, station, now=None):
    now = now or datetime.datetime.now(datetime.timezone.utc)
    for back in (0, 1):  # today, then yesterday (UTC), in case it is just after 00Z
        d = now - datetime.timedelta(days=back)
        keys = [k for k in list_keys(bucket_url, "%04d/%02d/%02d/%s/" % (d.year, d.month, d.day, station))
                if not k[0].endswith("_MDM") and re.search(r"_V\d\d(\.gz)?$", k[0])]
        if keys:
            return sorted(keys)[-1]
    raise RuntimeError("no volumes found for %s in %s" % (station, bucket_url))


def download(bucket_url, key, dst):
    tmp = dst + ".part"
    with urllib.request.urlopen("%s/%s" % (bucket_url, urllib.parse.quote(key)), timeout=120) as r, open(tmp, "wb") as f:
        shutil.copyfileobj(r, f)
    os.replace(tmp, dst)


def write_index(web_data, station):
    """index.json: retained volumes, oldest first, for time playback. Times are copied from each manifest."""
    import json
    vols = []
    for s in sorted(os.listdir(os.path.join(web_data, station))):
        mp = os.path.join(web_data, station, s, "manifest.json")
        if os.path.exists(mp):
            m = json.load(open(mp))
            vols.append({"path": "%s/%s" % (station, s), "station": m["station"], "vcp": m["vcp"],
                         "first_radial": m["volume_time_utc"]["first_radial"],
                         "last_radial": m["volume_time_utc"]["last_radial"]})
    tmp = os.path.join(web_data, "index.json.tmp")
    with open(tmp, "w") as f:
        json.dump({"volumes": vols}, f)
    os.replace(tmp, os.path.join(web_data, "index.json"))


def publish(station, bucket_url, raw_cache, work, web_data, keep=6):
    key, etag = newest_key(bucket_url, station)
    stamp = os.path.basename(key)
    final = os.path.join(web_data, station, stamp)
    if os.path.isdir(final):
        print("already published:", stamp)
        return final
    os.makedirs(raw_cache, exist_ok=True)
    raw = os.path.join(raw_cache, stamp)
    if not os.path.exists(raw):
        download(bucket_url, key, raw)
    wdir = os.path.join(work, stamp)
    man = export_volume(raw, wdir, etag=etag, source_url="%s/%s" % (bucket_url, key))
    stage = final + ".tmp"
    shutil.rmtree(stage, ignore_errors=True)
    os.makedirs(stage)
    shutil.copy(os.path.join(wdir, "manifest.json"), stage)
    for t in THRESHOLDS:
        export_viewer(wdir, float(t), out_dir=os.path.join(stage, "thr%d" % t))
    os.replace(stage, final)
    link = os.path.join(web_data, "latest")
    tmp_link = link + ".new"
    if os.path.lexists(tmp_link):
        os.remove(tmp_link)
    os.symlink(os.path.relpath(final, web_data), tmp_link)
    os.replace(tmp_link, link)
    shutil.rmtree(wdir, ignore_errors=True)
    vols = sorted(os.listdir(os.path.join(web_data, station)))
    for old in vols[:-keep]:
        shutil.rmtree(os.path.join(web_data, station, old), ignore_errors=True)
    write_index(web_data, station)
    print("published", stamp, man["n_samples"], "samples")
    return final


def main():
    env = os.environ.get
    publish(env("STATION", "KTLX"), env("BUCKET_URL", "https://noaa-nexrad-level2.s3.amazonaws.com"),
            env("RAW_CACHE", "/var/radar/raw"), env("WORK_DIR", "/var/radar/work"), env("WEB_DATA", "/var/radar/web"),
            int(env("KEEP_VOLUMES", "6")))


if __name__ == "__main__":
    sys.exit(main())
