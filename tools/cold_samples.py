# lambda-canary-kit/tools/cold_samples.py
"""Collect real cold starts from a deployed function and print the Init Duration of each.

  python tools/cold_samples.py --function <FunctionName> --samples 10

How it forces a cold start: it changes an environment variable on the function (which makes
Lambda discard its warm environments), then invokes once and reads the REPORT line from the
invocation's log tail. Only replies that say "cold": true are counted.

Run it on the scratch comparison stack, not on a stack you care about: it edits the function's
configuration outside CloudFormation, and the next `sam deploy` puts things back.
"""
import argparse
import base64
import json
import re
import statistics
import sys
from pathlib import Path

import boto3

SAMPLES = Path(__file__).resolve().parent.parent / "app" / "model" / "samples.json"
INIT_RE = re.compile(r"Init Duration: ([\d.]+) ms")


def parse_init_ms(log_text):
    """Pull 'Init Duration' out of a Lambda REPORT line. None when the invocation was warm."""
    m = INIT_RE.search(log_text)
    return float(m.group(1)) if m else None


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--function", required=True)
    ap.add_argument("--region", default=None)
    ap.add_argument("--samples", type=int, default=10)
    args = ap.parse_args(argv)

    lam = boto3.client("lambda", region_name=args.region)
    pixels = json.loads(SAMPLES.read_text())[0]["pixels"]
    payload = json.dumps({"pixels": pixels}).encode()
    waiter = lam.get_waiter("function_updated_v2")

    inits, tried = [], 0
    while len(inits) < args.samples and tried < args.samples * 2:
        tried += 1
        cfg = lam.get_function_configuration(FunctionName=args.function)
        env = dict(cfg.get("Environment", {}).get("Variables", {}))
        env["COLD_NONCE"] = str(tried)
        lam.update_function_configuration(FunctionName=args.function, Environment={"Variables": env})
        waiter.wait(FunctionName=args.function)

        resp = lam.invoke(FunctionName=args.function, Payload=payload, LogType="Tail")
        body = json.loads(resp["Payload"].read() or b"{}")
        log = base64.b64decode(resp.get("LogResult", "")).decode("utf-8", "replace")
        init = parse_init_ms(log)
        if resp.get("FunctionError") or not body.get("cold") or init is None:
            print(f"sample {tried}: skipped (warm or error)")
            continue
        inits.append(init)
        print(f"sample {len(inits):>2}: Init Duration {init:7.1f} ms   (handler init_ms {body.get('init_ms')})")

    if not inits:
        print("no cold starts captured")
        return 1
    inits.sort()
    print(f"\n{len(inits)} cold starts: min {inits[0]:.0f} ms, median {statistics.median(inits):.0f} ms, max {inits[-1]:.0f} ms")
    return 0


if __name__ == "__main__":
    sys.exit(main())
