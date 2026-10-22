# lambda-canary-kit/app/handler.py
"""Digit classifier Lambda.

Event: {"pixels": [64 numbers, 0..16]}  (a Function URL body works too)
Reply: {"digit": 3, "confidence": 0.99, "backend": "onnx", "release": "...", "cold": true}

Bad input returns statusCode 400 and does NOT raise, because a caller's typo is
not a failed release. Anything that goes wrong inside the model path DOES raise,
so Lambda counts it in the Errors metric and the canary alarm can see it.
"""
import json
import os
import time

_t0 = time.perf_counter()

from backends import load  # noqa: E402
from preprocess import to_batch  # noqa: E402

BACKEND = os.environ.get("BACKEND", "onnx")
RELEASE = os.environ.get("RELEASE", "dev")

_backend = load(BACKEND)
_init_ms = round((time.perf_counter() - _t0) * 1000, 1)
_cold = True


def _pixels_from(event):
    if isinstance(event, dict) and "pixels" in event:
        return event["pixels"]
    body = event.get("body") if isinstance(event, dict) else None
    if isinstance(body, str):
        body = json.loads(body)
    if isinstance(body, dict) and "pixels" in body:
        return body["pixels"]
    return None


def handler(event, context=None):
    global _cold
    pixels = _pixels_from(event)
    if pixels is None:
        return {"statusCode": 400, "error": "send {\"pixels\": [64 numbers]}"}
    try:
        batch = to_batch(pixels)
    except ValueError as exc:
        return {"statusCode": 400, "error": str(exc)}

    digit, confidence = _backend.predict(batch)   # may raise: that is the point
    out = {
        "statusCode": 200,
        "digit": digit,
        "confidence": round(confidence, 4),
        "backend": _backend.name,
        "release": RELEASE,
        "cold": _cold,
        "init_ms": _init_ms,
    }
    _cold = False
    return out
