"""Shared fixtures and the numeric-metric recorder used by report generation.

Tests call record(...) so the validation report lists every numerical discrepancy with units and the
governing tolerance (VALIDATION_PLAN section 5). Tolerances are read from tolerances.yaml and are never
edited by tests.
"""
import csv
import json
import os
import sys
import warnings

import pytest
import yaml

warnings.filterwarnings("ignore")
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests", "reference"))

CASES = ["KTLX_20130520_195111", "KDIX_20140430_120023"]
SOURCE_FILES = {
    "KTLX_20130520_195111": "data/raw/KTLX20130520_195111_V06.gz",
    "KDIX_20140430_120023": "data/raw/KDIX20140430_120023_V06.gz",
}
TOL = yaml.safe_load(open(os.path.join(ROOT, "tolerances.yaml")))
_METRICS = []


def record(test_id, case, quantity, value, unit, tolerance_key=None, note=""):
    tol = TOL[tolerance_key]["value"] if tolerance_key else None
    _METRICS.append({"test": test_id, "case": case, "quantity": quantity, "value": value, "unit": unit,
                     "tolerance": tol, "tolerance_key": tolerance_key,
                     "tolerance_basis": TOL[tolerance_key]["basis"] if tolerance_key else None, "note": note})
    return value


def pytest_sessionfinish(session, exitstatus):
    os.makedirs(os.path.join(ROOT, "report"), exist_ok=True)
    with open(os.path.join(ROOT, "report", "metrics.json"), "w") as f:
        json.dump(_METRICS, f, indent=1, default=float)


def _csv(case, name):
    with open(os.path.join(ROOT, "fixtures", case, name), newline="") as f:
        return list(csv.DictReader(f))


@pytest.fixture(scope="session", params=CASES)
def case(request):
    return request.param


@pytest.fixture(scope="session")
def fx():
    return _csv


@pytest.fixture(scope="session")
def case_meta():
    return {c: json.load(open(os.path.join(ROOT, "fixtures", c, "case.json"))) for c in CASES}


_VOL = {}


@pytest.fixture(scope="session")
def engine_vol():
    from engine.decode import load_volume

    def get(case):
        if case not in _VOL:
            _VOL[case] = load_volume(os.path.join(ROOT, SOURCE_FILES[case]))
        return _VOL[case]
    return get


_SPEC = {}


@pytest.fixture(scope="session")
def spec_vol():
    import spec_reader

    def get(case):
        if case not in _SPEC:
            _SPEC[case] = spec_reader.read_volume(os.path.join(ROOT, SOURCE_FILES[case]))
        return _SPEC[case]
    return get


_SAMPLES = {}


@pytest.fixture(scope="session")
def engine_samples(engine_vol):
    from engine.samples import build_samples

    def get(case):
        if case not in _SAMPLES:
            _SAMPLES[case] = build_samples(engine_vol(case), include=("MEASURED", "RANGE_FOLDED", "BELOW_THRESHOLD"),
                                           compute_geoid=False)[0]
        return _SAMPLES[case]
    return get
