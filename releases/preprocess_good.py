# lambda-canary-kit/releases/preprocess_good.py
"""Turn the request pixels into the batch the model expects.

This is the file `make ship-bad` swaps out. The good version lives in
releases/preprocess_good.py (an exact copy), the regression in
releases/preprocess_bad.py.
"""
import numpy as np


def to_batch(pixels):
    arr = np.asarray(pixels, dtype=np.float32)
    if arr.shape != (64,):
        raise ValueError("pixels must be a list of 64 numbers (an 8x8 image, values 0 to 16)")
    return (arr / 16.0).reshape(1, 64)
