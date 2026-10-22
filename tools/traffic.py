# lambda-canary-kit/tools/traffic.py
"""Send steady traffic to the `live` alias and show which release answered.

  python tools/traffic.py --function <FunctionName> --seconds 600 --rps 4

Run it in one terminal while a deploy is in progress and you can watch the canary:
a few answers from the new release, then either all of them (good release) or the
errors that trip the alarm and the traffic flowing back to the old one (bad release).
"""
import argparse
import collections
import json
import sys
import time
from pathlib import Path

import boto3

SAMPLES = Path(__file__).resolve().parent.parent / "app" / "model" / "samples.json"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--function", required=True, help="the FunctionName stack output")
    ap.add_argument("--alias", default="live")
    ap.add_argument("--region", default=None)
    ap.add_argument("--seconds", type=int, default=600)
    ap.add_argument("--rps", type=float, default=4)
    ap.add_argument("--report-every", type=int, default=10)
    args = ap.parse_args(argv)

    client = boto3.client("lambda", region_name=args.region)
    pixels = json.loads(SAMPLES.read_text())[0]["pixels"]
    payload = json.dumps({"pixels": pixels}).encode()

    start = last = time.time()
    ok = err = 0
    releases = collections.Counter()
    gap = 1.0 / args.rps
    while time.time() - start < args.seconds:
        t0 = time.time()
        resp = client.invoke(FunctionName=f"{args.function}:{args.alias}", Payload=payload)
        body = json.loads(resp["Payload"].read() or b"{}")
        if resp.get("FunctionError"):
            err += 1
            releases["ERROR"] += 1
        else:
            ok += 1
            releases[body.get("release", "?")] += 1
        if time.time() - last >= args.report_every:
            print(f"t={int(time.time() - start):>4}s  ok={ok:<5} err={err:<5} answered_by={dict(releases)}", flush=True)
            ok = err = 0
            releases.clear()
            last = time.time()
        time.sleep(max(0.0, gap - (time.time() - t0)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
