# lambda-canary-kit/tools/release.py
"""Swap the preprocessing file between the good release and the bad one.

  python tools/release.py bad      # copy releases/preprocess_bad.py over app/preprocess.py
  python tools/release.py good     # restore the good version
  python tools/release.py status   # say which one is active

Plain file copies, so it works the same on Windows, macOS and Linux.
"""
import argparse
import hashlib
import shutil
import sys
from pathlib import Path


def _body(path):
    """File content without the first (path comment) line, so copies compare equal."""
    return path.read_text().split("\n", 1)[1]


def active(root):
    live = _body(root / "app" / "preprocess.py")
    if live == _body(root / "releases" / "preprocess_good.py"):
        return "good"
    if live == _body(root / "releases" / "preprocess_bad.py"):
        return "bad"
    return "unknown"


def switch(root, which):
    src = root / "releases" / f"preprocess_{which}.py"
    dst = root / "app" / "preprocess.py"
    text = src.read_text().split("\n", 1)
    dst.write_text("# lambda-canary-kit/app/preprocess.py\n" + text[1])
    return active(root)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("action", choices=["good", "bad", "status"])
    ap.add_argument("--root", default=str(Path(__file__).resolve().parent.parent))
    args = ap.parse_args(argv)
    root = Path(args.root)
    if args.action == "status":
        print(active(root))
        return 0
    state = switch(root, args.action)
    print(f"app/preprocess.py is now the {state} release")
    return 0 if state == args.action else 1


if __name__ == "__main__":
    sys.exit(main())
