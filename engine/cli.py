import argparse
import json

from .export import export_volume


def main():
    ap = argparse.ArgumentParser(prog="engine")
    ap.add_argument("file")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    m = export_volume(a.file, a.out)
    print(json.dumps({k: m[k] for k in ("station", "n_radials", "n_samples")}))


if __name__ == "__main__":
    main()
