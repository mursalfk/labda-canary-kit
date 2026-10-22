# lambda-canary-kit/releases/preprocess_bad.py
"""The regression `make ship-bad` ships on purpose.

A plausible "cleanup": use float64 everywhere, it is the numpy default and it
passes every test that goes through scikit-learn. The ONNX model, however, was
exported with a float32 input and refuses float64, so every request errors.
"""
import numpy as np


def to_batch(pixels):
    arr = np.asarray(pixels, dtype=np.float64)
    if arr.shape != (64,):
        raise ValueError("pixels must be a list of 64 numbers (an 8x8 image, values 0 to 16)")
    return (arr / 16.0).reshape(1, 64)
