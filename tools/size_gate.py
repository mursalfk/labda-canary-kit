# lambda-canary-kit/tools/size_gate.py
"""Fail the build when an image is bigger than its budget.

  python tools/size_gate.py canary-kit:slim --budget-mb 350

The number is the uncompressed size Docker reports for the image. ECR bills on the
compressed size and Lambda enforces its own limit, so treat this as a regression
tripwire: set the budget a little above today's number and let CI shout when a
change makes the image grow.
"""
import argparse
import json
import os
import subprocess
import sys

MB = 1024 * 1024


def image_bytes(image):
    out = subprocess.run(
        ["docker", "image", "inspect", image, "--format", "{{json .Size}}"],
        check=True, capture_output=True, text=True,
    ).stdout
    return int(json.loads(out.strip()))


def verdict(size_bytes, budget_mb):
    """Return (ok, one-line message). Pure function so it is easy to test."""
    size_mb = size_bytes / MB
    if size_mb <= budget_mb:
        return True, f"OK: {size_mb:.1f} MB is within the {budget_mb:.0f} MB budget ({budget_mb - size_mb:.1f} MB to spare)"
    return False, f"FAIL: {size_mb:.1f} MB is over the {budget_mb:.0f} MB budget by {size_mb - budget_mb:.1f} MB"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("image")
    ap.add_argument("--budget-mb", type=float, required=True)
    ap.add_argument("--bytes", type=int, help="skip docker and use this size (for tests)")
    args = ap.parse_args(argv)
    size = args.bytes if args.bytes is not None else image_bytes(args.image)
    ok, msg = verdict(size, args.budget_mb)
    print(f"{args.image}: {msg}")
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a") as fh:
            fh.write(f"### Image size gate\n`{args.image}`: {msg}\n")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
