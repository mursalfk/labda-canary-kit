# lambda-canary-kit/docs/measured-in-sandbox.md

# What was actually measured while building this kit

These numbers are real, from clean virtual environments in the build sandbox (Linux x86_64,
Python 3.13, fresh `pip install --no-cache-dir`, 2026-10-16). They are **package footprints**,
not Docker image sizes. Docker was not available in the sandbox, so no image was built there.
Your `make report` output replaces anything marked "yours to measure".

## Dependency footprint (site-packages)

| Dependency set | Size on disk | Heaviest parts |
|---|---|---|
| Bloated (`app/requirements-bloated.txt`) | 349 MB (336 MB without the 13 MB of pip a venv carries) | scipy 109 MB (+30 MB libs), pandas 72, scikit-learn 48, numpy 43 (+27 MB libs) |
| Slim (`app/requirements-slim.txt`) | 153 MB (140 MB without pip) | onnxruntime 68, numpy 43 (+27 MB libs) |
| Slim after the Dockerfile's strip step (`__pycache__` and `tests` folders removed) | 114 MB | same packages, less clutter |

Two honest findings from that table:

1. The model itself is tiny: `digits.onnx` is 3.6 KB and `digits.joblib` is 3.0 KB. Everything
   in the image weight is the runtime needed to execute it, not the model.
2. Installing onnxruntime with `--no-deps` (to skip its dependencies) only saves about 4 MB
   (153 to 149 MB). It is not worth the fragility, so the Dockerfile does not do it.

## Import + model load time (the part of a cold start your code controls)

Median of 7 fresh Python processes, `handler._init_ms`, sandbox disk cache warm:

| Backend | Median | Range |
|---|---|---|
| onnxruntime | 117 ms | 95 to 192 ms |
| scikit-learn + joblib | 1181 ms | 1122 to 1289 ms |

This is import-and-load time on a sandbox CPU, **not** a Lambda cold start. It shows the
direction and rough ratio, nothing more. Your Lambda numbers come from CloudWatch (see below).

## Model quality

Holdout accuracy on scikit-learn's digits set: 97.78 percent (`app/model/metrics.json`).
Both backends return the same label for all 1,797 digits and probabilities within 0.001
(`tests/test_handler.py::test_both_backends_give_the_same_answers`).

## Verified here

- 24 tests pass with the exact pinned versions (`pytest -q`).
- The bad release really fails on the slim backend with an ONNX Runtime "Unexpected input data
  type" error, and really passes on the scikit-learn backend (`tests/test_release_regression.py`).
- The slim file layout (stripped dependencies plus the four runtime files and the model, with
  scikit-learn not importable) classifies all ten smoke samples correctly.
- `template.yaml` passes `cfn-lint` (which expands the SAM transform).

## Yours to measure (could not be done in the sandbox)

- Docker image sizes for `canary-kit:bloated` and `canary-kit:slim`: `make report`
- Local cold-start proxy under the Lambda emulator: `make smoke`
- Real Lambda cold start: CloudWatch Logs Insights, query in `instructions.md`
- Canary timing and rollback behaviour: `tools/watch_deploy.py` during the bad release
- The GitHub Actions workflows (ci.yml parses as YAML but has not run)
