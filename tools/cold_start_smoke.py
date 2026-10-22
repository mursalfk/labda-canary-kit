# lambda-canary-kit/tools/cold_start_smoke.py
"""Run the image under the Lambda Runtime Interface Emulator and time it.

  python tools/cold_start_smoke.py canary-kit:slim --max-cold-ms 3000

What it proves: the image starts, answers correctly, and the first request (which
includes the function's init) finishes inside your budget. What it does NOT prove:
real Lambda cold-start numbers. The emulator runs on your machine, so use it as a
regression tripwire (did this change make start-up slower?) and read the real
numbers from CloudWatch after a deploy.
"""
import argparse
import json
import statistics
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

SAMPLES = Path(__file__).resolve().parent.parent / "app" / "model" / "samples.json"


def invoke(port, payload, timeout=60):
    url = f"http://localhost:{port}/2015-03-31/functions/function/invocations"
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), method="POST")
    t0 = time.perf_counter()
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = json.loads(resp.read())
    return (time.perf_counter() - t0) * 1000, body


def check_reply(reply, expected_digit):
    """Return a list of problems with one reply (empty list means fine)."""
    problems = []
    if not isinstance(reply, dict) or reply.get("statusCode") != 200:
        problems.append(f"unexpected reply: {reply!r}")
        return problems
    if reply.get("digit") != expected_digit:
        problems.append(f"expected digit {expected_digit}, got {reply.get('digit')}")
    return problems


def wait_until_up(port, tries=40):
    for _ in range(tries):
        try:
            urllib.request.urlopen(f"http://localhost:{port}/", timeout=1)
        except urllib.error.HTTPError:
            return True          # the emulator answered, even if with a 404
        except Exception:
            time.sleep(0.25)
    return False


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("image")
    ap.add_argument("--max-cold-ms", type=float, required=True)
    ap.add_argument("--port", type=int, default=9000)
    ap.add_argument("--warm-calls", type=int, default=5)
    args = ap.parse_args(argv)

    sample = json.loads(SAMPLES.read_text())[0]
    name = f"canary-smoke-{uuid.uuid4().hex[:8]}"
    subprocess.run(["docker", "run", "-d", "--rm", "--name", name, "-p", f"{args.port}:8080", args.image],
                   check=True, capture_output=True)
    try:
        if not wait_until_up(args.port):
            print("FAIL: container never started answering")
            return 1
        cold_ms, first = invoke(args.port, {"pixels": sample["pixels"]})
        warm = [invoke(args.port, {"pixels": sample["pixels"]})[0] for _ in range(args.warm_calls)]
    finally:
        subprocess.run(["docker", "stop", "-t", "1", name], capture_output=True)

    problems = check_reply(first, sample["label"])
    print(f"first request (includes init): {cold_ms:.0f} ms   reported init_ms: {first.get('init_ms')}")
    print(f"warm requests: median {statistics.median(warm):.1f} ms over {len(warm)} calls")
    if problems:
        print("FAIL: " + "; ".join(problems))
        return 1
    if cold_ms > args.max_cold_ms:
        print(f"FAIL: first request took {cold_ms:.0f} ms, budget is {args.max_cold_ms:.0f} ms")
        return 1
    print(f"OK: first request inside the {args.max_cold_ms:.0f} ms budget")
    return 0


if __name__ == "__main__":
    sys.exit(main())
