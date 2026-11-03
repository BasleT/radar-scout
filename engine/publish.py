"""Fetch the newest Level II volume for one station, run the engine, and publish viewer artifacts.

Output layout under WEB_DATA:  <STATION>/<volume-stamp>/{manifest.json,thr30/,thr40/,thr50/}  and a `latest` symlink.
The source file is the public NOAA archive object, stored unmodified in RAW_CACHE with its SHA-256 and S3 ETag
recorded in manifest.json. If anything fails the previous `latest` is left untouched; no stand-in data is created.
The S3 bucket and object naming are configurable because they have changed before (see ARCHITECTURE.md sources).
"""
import datetime
import json
import os
import re
import shutil
import sys
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

from .decode import load_volume
from .export import export_volume
from .products import PRODUCTS
from .samples import build_moment_samples
from .viewer_export import export_viewer


BUCKET_DEFAULT = "https://unidata-nexrad-level2.s3.amazonaws.com"


def thr_dir(t):
    return "thr%g" % t


def export_all_products(wdir, stage, vol, skip_lowest_threshold=False):
    """<stage>/<PRODUCT>/thr<T>/ for every product present in the volume. REF comes from samples.parquet; the other
    moments are built in memory from the same decode (their full tables are not persisted; gates stay traceable by
    source SHA-256 + radial_index + gate_idx)."""
    done = []
    for prod, spec in PRODUCTS.items():
        df = None
        if prod != "REF":
            if not vol.moments[prod]["has"].any():
                continue
            df, status = build_moment_samples(vol, prod, include=("MEASURED",))
            if status != "ok" or df.empty:
                raise RuntimeError("%s: no usable samples (geoid status %r)" % (prod, status))
        ths = spec["thresholds"][1:] if skip_lowest_threshold else spec["thresholds"]
        for t in ths:
            export_viewer(wdir, t, out_dir=os.path.join(stage, prod, thr_dir(t)), product=prod, df=df)
        done.append({"id": prod, "label": spec["label"], "unit": spec["unit"], "thresholds": list(ths)})
    return done


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
    vols = []
    for s in sorted(os.listdir(os.path.join(web_data, station))):
        mp = os.path.join(web_data, station, s, "manifest.json")
        if os.path.exists(mp):
            m = json.load(open(mp))
            pj = os.path.join(web_data, station, s, "products.json")
            prods = json.load(open(pj))["products"] if os.path.exists(pj) else []
            vols.append({"path": "%s/%s" % (station, s), "station": m["station"], "vcp": m["vcp"], "products": prods,
                         "first_radial": m["volume_time_utc"]["first_radial"],
                         "last_radial": m["volume_time_utc"]["last_radial"]})
    tmp = os.path.join(web_data, "index.json.tmp")
    with open(tmp, "w") as f:
        json.dump({"volumes": vols}, f)
    os.replace(tmp, os.path.join(web_data, "index.json"))


def publish_key(key, etag, bucket_url, raw_cache, work, out_root, skip_lowest_threshold=False):
    """Download one known archive object, run the engine, and write <out_root>/<STATION>/<stamp>/. Returns the dir.
    skip_lowest_threshold: omit each product's lowest display threshold (keeps case archives small)."""
    station = key.split("/")[-1][:4]
    stamp = os.path.basename(key)
    final = os.path.join(out_root, station, stamp)
    if os.path.isdir(final):
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
    prods = export_all_products(wdir, stage, load_volume(raw), skip_lowest_threshold=skip_lowest_threshold)
    with open(os.path.join(stage, "products.json"), "w") as f:
        json.dump({"products": prods}, f)
    os.replace(stage, final)
    shutil.rmtree(wdir, ignore_errors=True)
    print("published", stamp, man["n_samples"], "samples")
    return final


def publish(station, bucket_url, raw_cache, work, web_data, keep=6):
    key, etag = newest_key(bucket_url, station)
    stamp = os.path.basename(key)
    if os.path.isdir(os.path.join(web_data, station, stamp)):
        print("already published:", stamp)
        return os.path.join(web_data, station, stamp)
    final = publish_key(key, etag, bucket_url, raw_cache, work, web_data)
    link = os.path.join(web_data, "latest")
    tmp_link = link + ".new"
    if os.path.lexists(tmp_link):
        os.remove(tmp_link)
    os.symlink(os.path.relpath(final, web_data), tmp_link)
    os.replace(tmp_link, link)
    vols = sorted(os.listdir(os.path.join(web_data, station)))
    for old in vols[:-keep]:
        shutil.rmtree(os.path.join(web_data, station, old), ignore_errors=True)
    write_index(web_data, station)
    return final


def main():
    env = os.environ.get
    publish(env("STATION", "KTLX"), env("BUCKET_URL", BUCKET_DEFAULT),
            env("RAW_CACHE", "/var/radar/raw"), env("WORK_DIR", "/var/radar/work"), env("WEB_DATA", "/var/radar/web"),
            int(env("KEEP_VOLUMES", "6")))


if __name__ == "__main__":
    sys.exit(main())
