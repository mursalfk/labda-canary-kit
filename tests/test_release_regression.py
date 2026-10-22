# lambda-canary-kit/tests/test_release_regression.py
"""Proves the demo is honest: the bad release really breaks the slim image,
and it really would have slipped past a test that only uses scikit-learn."""
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SAMPLES = json.loads((ROOT / "app" / "model" / "samples.json").read_text())


def load_module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def bad():
    return load_module(ROOT / "releases" / "preprocess_bad.py", "preprocess_bad")


def test_bad_release_errors_on_the_onnx_backend(bad):
    from backends import OnnxBackend
    backend = OnnxBackend()
    with pytest.raises(Exception) as err:
        backend.predict(bad.to_batch(SAMPLES[0]["pixels"]))
    assert "float" in str(err.value).lower() or "double" in str(err.value).lower()


def test_bad_release_would_pass_a_scikit_learn_only_test(bad):
    pytest.importorskip("sklearn")
    from backends import SklearnBackend
    digit, _ = SklearnBackend().predict(bad.to_batch(SAMPLES[0]["pixels"]))
    assert digit == SAMPLES[0]["label"]


def test_good_release_file_is_an_exact_copy_of_the_live_one():
    live = (ROOT / "app" / "preprocess.py").read_text().split("\n", 1)[1]
    good = (ROOT / "releases" / "preprocess_good.py").read_text().split("\n", 1)[1]
    assert live == good, "app/preprocess.py is not the good release. Run: python tools/release.py good"
