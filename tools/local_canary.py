# lambda-canary-kit/tools/local_canary.py
"""Run a canary release on your own machine. No AWS account, no cost.

THIS IS A SIMULATION. What is real: the handler code, the ONNX model and the
good/bad preprocessing files, all executed for every simulated request.
What is simulated: the traffic router (CodeDeploy), the clock (one simulated
minute runs instantly) and the alarm (CloudWatch). It copies the rules in
template.yaml: Canary10Percent5Minutes, alarm on any error in 2 consecutive
1-minute periods. It proves the release logic, not AWS behaviour.

  python tools/local_canary.py --candidate good
  python tools/local_canary.py --candidate bad
  python tools/local_canary.py --candidate bad --requests-per-minute 0   # no traffic, no alarm
"""
import argparse
import importlib.util
import json
import os
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load_release(root, which, label):
    """Import app/handler.py with releases/preprocess_<which>.py as its preprocessing."""
    app = str(root / "app")
    if app not in sys.path:
        sys.path.insert(0, app)
    os.environ["BACKEND"] = "onnx"
    os.environ["RELEASE"] = label
    pre = _module(root / "releases" / f"preprocess_{which}.py", f"preprocess_{label}")
    saved = sys.modules.get("preprocess")
    sys.modules["preprocess"] = pre
    try:
        return _module(root / "app" / "handler.py", f"handler_{label}")
    finally:
        if saved is None:
            sys.modules.pop("preprocess", None)
        else:
            sys.modules["preprocess"] = saved


def _module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def invoke(handler_module, event):
    """True if the call counts as a Lambda error (the handler raised)."""
    try:
        handler_module.handler(event, None)
        return False
    except Exception:
        return True


def simulate(root, candidate, requests_per_minute=60, seed=7, canary_pct=10,
             canary_minutes=5, eval_periods=2):
    samples = json.loads((root / "app" / "model" / "samples.json").read_text())
    old = load_release(root, "good", "stable")
    new = load_release(root, candidate, f"candidate-{candidate}")
    rng = random.Random(seed)
    rows, bad_streak, outcome = [], 0, None

    for minute in range(1, canary_minutes + 1):
        counts = {"old": 0, "new": 0}
        errors = {"old": 0, "new": 0}
        for i in range(requests_per_minute):
            side = "new" if rng.random() < canary_pct / 100 else "old"
            event = {"pixels": samples[i % len(samples)]["pixels"]}
            counts[side] += 1
            errors[side] += invoke(new if side == "new" else old, event)
        bad_streak = bad_streak + 1 if errors["new"] > 0 else 0
        state = "ALARM" if bad_streak >= eval_periods else "OK"
        rows.append({"minute": minute, "weight": canary_pct, "old": counts["old"],
                     "new": counts["new"], "old_errors": errors["old"],
                     "new_errors": errors["new"], "alarm": state})
        if state == "ALARM":
            outcome = "rolled_back"
            break
    if outcome is None:
        outcome = "promoted"
    return {"candidate": candidate, "outcome": outcome, "rows": rows}


def render(result):
    out = ["SIMULATION, not AWS: real handler and model, simulated router, clock and alarm.", ""]
    out.append("minute  weight  to-old  to-new  old-errors  new-errors  alarm")
    for r in result["rows"]:
        out.append(f"{r['minute']:>6}  {r['weight']:>5}%  {r['old']:>6}  {r['new']:>6}  "
                   f"{r['old_errors']:>10}  {r['new_errors']:>10}  {r['alarm']}")
    out.append("")
    if result["outcome"] == "rolled_back":
        out.append("RESULT: alarm fired, traffic shifted back to 100% stable. Candidate rolled back.")
    else:
        silent = sum(r["new"] for r in result["rows"]) == 0
        extra = " The canary never received a request, so nothing could have raised the alarm." if silent else ""
        out.append("RESULT: no alarm, candidate promoted to 100%." + extra)
    return "\n".join(out)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--candidate", choices=["good", "bad"], required=True)
    ap.add_argument("--requests-per-minute", type=int, default=60)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--root", default=str(ROOT))
    args = ap.parse_args(argv)
    try:
        result = simulate(Path(args.root), args.candidate, args.requests_per_minute, args.seed)
    except ModuleNotFoundError as exc:
        print(f"Missing {exc.name}. Run: pip install -r requirements-dev.txt")
        return 2
    print(render(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
