# lambda-canary-kit/app/backends.py
"""Two interchangeable ways to run the same model.

The slim image only ever imports OnnxBackend, so scikit-learn, scipy and joblib
never need to be installed there. The bloated image uses SklearnBackend.
Imports are deliberately lazy for exactly that reason.
"""
from pathlib import Path

MODEL_DIR = Path(__file__).resolve().parent / "model"


class OnnxBackend:
    name = "onnx"

    def __init__(self):
        import onnxruntime as ort

        so = ort.SessionOptions()
        so.intra_op_num_threads = 1
        self.session = ort.InferenceSession(
            str(MODEL_DIR / "digits.onnx"), sess_options=so, providers=["CPUExecutionProvider"]
        )
        self.input_name = self.session.get_inputs()[0].name

    def predict(self, batch):
        label, proba = self.session.run(None, {self.input_name: batch})
        return int(label[0]), float(proba[0].max())


class SklearnBackend:
    name = "sklearn"

    def __init__(self):
        import joblib

        self.model = joblib.load(MODEL_DIR / "digits.joblib")

    def predict(self, batch):
        proba = self.model.predict_proba(batch)[0]
        return int(self.model.classes_[proba.argmax()]), float(proba.max())


def load(name):
    if name == "onnx":
        return OnnxBackend()
    if name == "sklearn":
        return SklearnBackend()
    raise ValueError(f"unknown BACKEND {name!r}, expected 'onnx' or 'sklearn'")
