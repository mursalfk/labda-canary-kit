# lambda-canary-kit/tests/test_handler.py
import importlib
import json
from pathlib import Path

import pytest

SAMPLES = json.loads((Path(__file__).resolve().parent.parent / "app" / "model" / "samples.json").read_text())


def fresh_handler(monkeypatch, backend="onnx"):
    monkeypatch.setenv("BACKEND", backend)
    monkeypatch.setenv("RELEASE", "test-release")
    import handler
    return importlib.reload(handler)


@pytest.mark.parametrize("sample", SAMPLES, ids=[f"digit-{s['label']}" for s in SAMPLES])
def test_every_sample_is_classified_correctly(monkeypatch, sample):
    h = fresh_handler(monkeypatch)
    out = h.handler({"pixels": sample["pixels"]})
    assert out["statusCode"] == 200
    assert out["digit"] == sample["label"]
    assert 0.0 <= out["confidence"] <= 1.0
    assert out["release"] == "test-release"
    assert out["backend"] == "onnx"


def test_function_url_style_body_is_accepted(monkeypatch):
    h = fresh_handler(monkeypatch)
    out = h.handler({"body": json.dumps({"pixels": SAMPLES[2]["pixels"]})})
    assert out["digit"] == 2


def test_cold_flag_is_true_once_then_false(monkeypatch):
    h = fresh_handler(monkeypatch)
    first = h.handler({"pixels": SAMPLES[0]["pixels"]})
    second = h.handler({"pixels": SAMPLES[0]["pixels"]})
    assert first["cold"] is True
    assert second["cold"] is False


@pytest.mark.parametrize("event", [{}, {"pixels": [1, 2, 3]}, {"body": "{\"nope\": 1}"}])
def test_bad_input_is_a_400_not_an_exception(monkeypatch, event):
    h = fresh_handler(monkeypatch)
    out = h.handler(event)
    assert out["statusCode"] == 400


def test_unknown_backend_fails_loudly(monkeypatch):
    monkeypatch.setenv("BACKEND", "nope")
    import handler
    with pytest.raises(ValueError):
        importlib.reload(handler)
    monkeypatch.setenv("BACKEND", "onnx")
    importlib.reload(handler)


def test_both_backends_give_the_same_answers():
    pytest.importorskip("sklearn")
    import numpy as np
    from sklearn.datasets import load_digits
    from backends import OnnxBackend, SklearnBackend
    from preprocess import to_batch

    onnx, sk = OnnxBackend(), SklearnBackend()
    X, _ = load_digits(return_X_y=True)
    worst = 0.0
    for row in X:
        batch = to_batch(row.tolist())
        d1, p1 = onnx.predict(batch)
        d2, p2 = sk.predict(batch)
        assert d1 == d2
        worst = max(worst, abs(p1 - p2))
    assert worst < 1e-3
