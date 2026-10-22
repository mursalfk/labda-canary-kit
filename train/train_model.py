# lambda-canary-kit/train/train_model.py
"""Train a tiny digit classifier on scikit-learn's built-in digits set and export it.

Outputs (written next to the app so the Docker build can copy them):
  app/model/digits.onnx    used by the slim image (onnxruntime)
  app/model/digits.joblib  used by the bloated image (scikit-learn)
  app/model/samples.json   ten smoke-test inputs, one correctly classified row per digit
  app/model/metrics.json   holdout accuracy, so the README never has to guess

No downloads, no network, no GPU. Runs in a few seconds.
"""
import json
from pathlib import Path

import joblib
import numpy as np
from sklearn.datasets import load_digits
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import train_test_split
from skl2onnx import convert_sklearn
from skl2onnx.common.data_types import FloatTensorType

OUT = Path(__file__).resolve().parent.parent / "app" / "model"
OUT.mkdir(parents=True, exist_ok=True)

X, y = load_digits(return_X_y=True)
X = (X / 16.0).astype(np.float32)          # pixels are 0..16, scale to 0..1
Xtr, Xte, ytr, yte = train_test_split(X, y, test_size=0.25, random_state=7, stratify=y)

clf = LogisticRegression(max_iter=3000)
clf.fit(Xtr, ytr)
acc = float(clf.score(Xte, yte))

onx = convert_sklearn(
    clf,
    initial_types=[("pixels", FloatTensorType([None, 64]))],
    options={id(clf): {"zipmap": False}},
    target_opset=13,
)
(OUT / "digits.onnx").write_bytes(onx.SerializeToString())
joblib.dump(clf, OUT / "digits.joblib", compress=3)

# Smoke-test inputs: for each digit, the first holdout row the model classifies correctly.
# They exist to catch a broken release (wrong dtype, wrong model file), not to flatter accuracy;
# the honest accuracy number is in metrics.json.
pred = clf.predict(Xte)
samples = []
for d in range(10):
    i = int(np.where((yte == d) & (pred == d))[0][0])
    samples.append({"label": d, "pixels": [round(float(v) * 16) for v in Xte[i]]})
(OUT / "samples.json").write_text(json.dumps(samples))
(OUT / "metrics.json").write_text(json.dumps({"holdout_accuracy": round(acc, 4), "train_rows": int(len(Xtr)), "test_rows": int(len(Xte))}))

print(f"holdout accuracy: {acc:.4f}")
for f in sorted(OUT.iterdir()):
    print(f"{f.name:16s} {f.stat().st_size/1024:8.1f} KB")
