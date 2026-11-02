"""Mutation check (VALIDATION_PLAN section 3): inject plausible bugs into the engine and confirm the suite
fails. Restores every file afterwards. Writes report/mutation.json. Not a pytest test (it runs pytest)."""
import json
import os
import shutil
import subprocess
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
MUTATIONS = [
    ("engine/geometry.py", "KE = 4.0 / 3.0", "KE = 1.3", "effective-radius factor changed"),
    ("engine/geometry.py", "\"height_msl_m\": z + antenna_msl_m", "\"height_msl_m\": z", "antenna altitude dropped"),
    ("engine/geometry.py", "az_b, s_b)", "az_b + 0.01, s_b)", "azimuth offset 0.01 deg"),
    ("engine/geometry.py", "np.radians(np.asarray(elev_deg, dtype=np.float64))",
     "np.asarray(elev_deg, dtype=np.float64)", "elevation left in degrees"),
    ("engine/samples.py", "(n - np.asarray(offset, dtype=np.float64))", "(n + np.asarray(offset, dtype=np.float64))",
     "dBZ offset sign flipped"),
    ("engine/samples.py", "cls[raw == 1] = \"RANGE_FOLDED\"", "cls[raw == 2] = \"RANGE_FOLDED\"",
     "range-folded code wrong"),
    ("engine/decode.py", "tower_height_m_agl=float(v[\"feedhorn_height\"])", "tower_height_m_agl=0.0",
     "tower height dropped"),
    ("engine/samples.py", "rng = vol.first_gate_m[ri] + df[\"gate_idx\"].to_numpy() * vol.gate_spacing_m[ri]",
     "rng = vol.first_gate_m[ri] + (df[\"gate_idx\"].to_numpy() + 0.5) * vol.gate_spacing_m[ri]",
     "gate range shifted by half a gate"),
]
TESTS = ["tests/test_t01_decoding.py", "tests/test_t02_t04_geometry.py", "tests/test_t05_t12_data_semantics.py"]


def run_tests():
    r = subprocess.run([sys.executable, "-m", "pytest", "-q", "-x", "-m", "not slow", "-p", "no:cacheprovider"] + TESTS,
                       cwd=ROOT, capture_output=True, text=True)
    return r.returncode


def main():
    results = []
    for path, old, new, desc in MUTATIONS:
        full = os.path.join(ROOT, path)
        shutil.copy(full, full + ".orig")
        try:
            src = open(full, encoding="utf8").read()
            if old not in src:
                results.append({"mutation": desc, "file": path, "result": "NOT APPLIED (pattern missing)"})
                continue
            open(full, "w", encoding="utf8").write(src.replace(old, new, 1))
            rc = run_tests()
            results.append({"mutation": desc, "file": path, "result": "KILLED" if rc != 0 else "SURVIVED"})
        finally:
            shutil.move(full + ".orig", full)
    os.makedirs(os.path.join(ROOT, "report"), exist_ok=True)
    json.dump(results, open(os.path.join(ROOT, "report", "mutation.json"), "w"), indent=1)
    for r in results:
        print(r)
    return 1 if any(r["result"] != "KILLED" for r in results) else 0


if __name__ == "__main__":
    sys.exit(main())
