# lambda-canary-kit

A small, copyable release kit for **Lambda container images**: a diet for the image, CI gates that
stop it growing back, and a canary deployment that rolls itself back when a release is bad.

The service is a deliberately boring digit classifier (a 3.6 KB model). That is the point: the
model is tiny, so every megabyte and every second you see comes from the packaging, not the model.

> Article: *Ship Lambda Containers Safely: Slim Images, Auto-Rollback* (link coming once it is published).

## What is in the box

| Piece | Where | What it does |
|---|---|---|
| Heavy image | `docker/Dockerfile.bloated` | The "works on my laptop" image: build tools kept, caches kept, whole repo copied, scikit-learn + scipy + pandas |
| Slim image | `docker/Dockerfile.slim` | Same API and model, multi-stage, onnxruntime + numpy only, nothing else |
| Size gate | `tools/size_gate.py` | Fails CI when the image passes its budget |
| Cold-start smoke | `tools/cold_start_smoke.py` | Runs the image under the Lambda emulator, checks the answer, times the first request |
| Canary + rollback | `template.yaml` | SAM alias with a CodeDeploy canary and a CloudWatch alarm on the new version |
| Bad release on demand | `tools/release.py`, `releases/` | One command swaps in a realistic regression |
| Live demo helpers | `tools/traffic.py`, `tools/watch_deploy.py` | Steady traffic, and a timestamped view of the deployment state |
| One-command deploy | `tools/deploy.py` | Build, push to ECR, `sam deploy` |
| CI | `.github/workflows/` | Tests, size gate, smoke test; a manual OIDC deploy button |

## The two images, side by side

Both serve the same request and return the same answers (a test proves it). They differ only in packaging.

| | `Dockerfile.bloated` | `Dockerfile.slim` |
|---|---|---|
| Libraries | scikit-learn, scipy, pandas, joblib, numpy | onnxruntime, numpy |
| Build tools in the final image | yes (gcc, g++, make, git) | no |
| pip cache kept | yes | no |
| What gets copied in | the whole repository | four runtime files and the model |
| Build style | one stage | two stages |
| Dependency footprint (measured) | 349 MB | 114 MB after stripping |
| Import + load time (measured, sandbox) | about 1.2 s | about 0.12 s |
| Image size (uncompressed) | run `make report` | run `make report` |

The dependency numbers come from clean virtual environments, not from built images, because the
build sandbox had no Docker daemon. See `docs/measured-in-sandbox.md` for exactly what was measured,
how, and what is left for you to measure.

## The release story

1. **Release v1** goes out. First deploy, no canary yet (there is nothing to roll back to).
2. **Release v2** (good): CodeDeploy sends 10 percent of traffic to the new version for 5 minutes,
   the alarm stays quiet, then shifts the rest.
3. **Release v3-bad**: `python tools/release.py bad` swaps in a "cleanup" that uses float64.
   Every scikit-learn test still passes, but the ONNX model wants float32, so every request errors.
   The canary sees errors, the alarm fires, CodeDeploy puts the alias back on v2. Most users never notice.

Why the bad release is realistic: nothing about it looks wrong in review, and it passes any test that
goes through scikit-learn (`tests/test_release_regression.py` proves both halves).

## Quick start (local, no AWS needed)

```bash
python -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
pytest -q                                              # 24 tests
python -c "import sys; sys.path.insert(0,'app'); import handler, json; s=json.load(open('app/model/samples.json')); print(handler.handler({'pixels': s[3]['pixels']}))"
```

Everything else (images, deploy, the rollback demo) is in `instructions.md`, step by step.

## No AWS account? Run the canary locally

`make simulate-bad`, `make simulate-good` and `make simulate-quiet` run `tools/local_canary.py`: the real handler and
model with a simulated router, clock and alarm that copy the rules in `template.yaml`. It is a simulation and says so
in its output. It shows the release logic, not CodeDeploy or CloudWatch behaviour.

## How the canary works

`AutoPublishAlias: live` makes SAM publish a new Lambda version on every deploy and move the `live`
alias with CodeDeploy. `DeploymentPreference: Canary10Percent5Minutes` sends 10 percent of the alias
traffic to the new version for 5 minutes. The `CanaryErrorsAlarm` watches `AWS/Lambda Errors` for the
function with `ExecutedVersion` set to the new version. If it goes into alarm during the window,
CodeDeploy stops and rolls the alias back.

Two things worth knowing:

- **The alarm needs traffic to see errors.** No requests, no errors, no rollback. That is why
  `tools/traffic.py` exists. In production you have real traffic; for the demo you generate it.
- **The alarm is two one-minute periods.** The rollback is not instant, it is "a couple of minutes".
  Use a pre-traffic hook if you want to catch a broken release before it sees any request.

## Repository layout

```
app/                handler, backends, preprocess, model files, requirements
docker/             Dockerfile.bloated, Dockerfile.slim
tools/              release, size gate, size report, cold-start smoke, deploy, traffic, watch
releases/           the good and bad preprocessing files
tests/              handler, backend equivalence, bad-release regression, tool tests
train/              retrains the model (only needed if you change it)
docs/               measured-in-sandbox.md
template.yaml       Lambda + alias + canary + alarm
.github/workflows/  ci.yml, deploy.yml
```

## Tests

| File | What it pins |
|---|---|
| `tests/test_handler.py` | Every smoke sample is classified correctly, 400 on bad input, cold flag, both backends agree on all 1,797 digits |
| `tests/test_release_regression.py` | The bad release errors on ONNX, passes on scikit-learn, and the good file is an exact copy of the live one |
| `tests/test_tools.py` | Size gate verdicts and exit codes, reply checking, the release switcher |

## Limits, stated plainly

- The cold-start smoke test runs in the Lambda emulator on your machine. It catches regressions; it
  does not tell you your real cold start. Read that from CloudWatch (query in `instructions.md`).
- The size gate uses the uncompressed size Docker reports. ECR bills on compressed size.
- Budgets are not guessed. You set them from your own first measurement.
- The canary alarm is a blunt "any error" rule. Real services usually want an error-rate threshold.
- Not verified here: Docker builds, the SAM deployment, the CodeDeploy rollback, the GitHub workflows.

## Cleanup

`make destroy` deletes the stack and the ECR repository. Do it when you finish the demo.

MIT licensed.
