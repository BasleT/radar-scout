"""Reference fixtures must not be produced by the code under test (project rule 10 / Phase 2)."""
import ast
import os

from conftest import ROOT

REF_FILES = ["tests/reference/make_fixtures.py", "tests/reference/spec_reader.py",
             "tests/reference/crosscheck_decoders.py"]


def _imports(path):
    tree = ast.parse(open(os.path.join(ROOT, path), encoding="utf8").read())
    names = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            names.update(a.name.split(".")[0] for a in n.names)
        elif isinstance(n, ast.ImportFrom) and n.module:
            names.add(n.module.split(".")[0])
    return names


def test_reference_generators_do_not_import_engine():
    for f in REF_FILES:
        assert "engine" not in _imports(f), f


def test_spec_reader_is_independent_of_radar_libraries():
    assert not (_imports("tests/reference/spec_reader.py") & {"pyart", "xradar", "wradlib", "engine"})


def test_make_fixtures_uses_only_independent_math():
    imps = _imports("tests/reference/make_fixtures.py")
    assert {"mpmath", "geographiclib", "spec_reader"} <= imps
    assert not (imps & {"pyproj", "pyart", "engine"})
