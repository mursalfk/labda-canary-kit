# lambda-canary-kit/tools/collect_evidence.py
"""Run every free, local step and save each output to its own file in evidence/.

  python tools/collect_evidence.py

Then send me evidence/ALL-evidence.txt (one file with everything). The separate
files stay in evidence/ in case you want to send a single one.

What it runs, in order (docker steps are skipped with a note if Docker is not running):
  tests, build both images, size report, cold-start smoke tests (3 cold runs each),
  budgets worked out from YOUR numbers, both gates passing, a copy of the repo with
  scipy added to the slim image so the size gate fails, the three canary simulations,
  and (if the gh CLI is set up) your latest GitHub Actions runs.

A failing step never stops the run. Its error is saved too, and that is what I need.
No AWS calls anywhere. Nothing from your environment variables is written down.
"""
import argparse
import math
import platform
import re
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MB = 1024 * 1024
FIRST_REQUEST = re.compile(r"first request \(includes init\): (\d+) ms")
HUGE_BUDGET_MS = "600000"      # "do not fail yet": the real budget is worked out from the runs
TRUNCATE_ABOVE = 120            # lines; longer outputs are cut to their tail inside ALL-evidence.txt
TAIL = 60


def real_run(cmd, cwd=None, timeout=1800):
    """Run a command, return (exit_code, combined_output, seconds). Never raises."""
    t0 = time.perf_counter()
    try:
        p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)
        out = (p.stdout or "") + (p.stderr or "")
        return p.returncode, out, time.perf_counter() - t0
    except FileNotFoundError as exc:
        return 127, f"command not found: {exc.filename}", time.perf_counter() - t0
    except subprocess.TimeoutExpired:
        return 124, f"timed out after {timeout} s", time.perf_counter() - t0


def parse_first_request_ms(text):
    """All 'first request' times (ms) found in a smoke-test output."""
    return [int(m) for m in FIRST_REQUEST.findall(text)]


def budgets(slim_bytes, first_request_ms):
    """Size budget: slim size + 10 percent. Cold-start budget: median first request + 50 percent."""
    size_mb = math.ceil(round(slim_bytes / MB * 1.10, 6))
    cold_ms = math.ceil(round(statistics.median(first_request_ms) * 1.5, 6))
    return size_mb, cold_ms


def shorten(text):
    lines = text.splitlines()
    if len(lines) <= TRUNCATE_ABOVE:
        return text.rstrip()
    cut = len(lines) - TAIL
    return f"[... {cut} earlier lines left out here; the full output is in the separate file ...]\n" + "\n".join(lines[-TAIL:])


class Evidence:
    def __init__(self, out_dir):
        self.out = out_dir
        self.out.mkdir(parents=True, exist_ok=True)
        self.results = []          # dicts: file, title, status, secs, body

    def record(self, filename, title, blocks, status, secs):
        """blocks: list of (command_text, exit_code, output). Writes one file."""
        parts = [f"# {title}", f"# when: {datetime.now().isoformat(timespec='seconds')}   status: {status}   took: {secs:.0f} s", ""]
        for cmd, code, output in blocks:
            parts += [f"$ {cmd}", f"(exit code {code})", output.rstrip(), ""]
        body = "\n".join(parts)
        (self.out / filename).write_text(body)
        self.results.append({"file": filename, "title": title, "status": status, "secs": secs, "body": body})
        print(f"  [{status}] {title} ({secs:.0f} s) -> evidence/{filename}")

    def skipped(self, filename, title, reason):
        self.record(filename, title, [("(not run)", "-", reason)], "SKIPPED", 0)

    def finish(self):
        lines = ["SUMMARY", "-" * 7]
        for r in self.results:
            lines.append(f"{r['status']:<22} {r['file']:<31} {r['title']}")
        summary = "\n".join(lines)
        (self.out / "00-summary.txt").write_text(summary + "\n")
        combined = [summary, ""]
        for r in self.results:
            combined += ["=" * 78, f"FILE: {r['file']}", "=" * 78, shorten(r["body"]), ""]
        (self.out / "ALL-evidence.txt").write_text("\n".join(combined))
        return summary


def collect(root, out_dir, run=real_run, runs=3, skip_gate_fail=False):
    ev = Evidence(out_dir)
    py = sys.executable
    n = [0]

    def step(filename, title, cmds, cwd=None, expect_fail=False, timeout=1800):
        """Run one or more commands into one file. Returns (ok, outputs list)."""
        n[0] += 1
        blocks, t0, codes, outs = [], time.perf_counter(), [], []
        print(f"[{n[0]}] {title} ...")
        for cmd in cmds:
            code, output, _ = run(cmd, cwd=cwd or root, timeout=timeout)
            blocks.append((" ".join(map(str, cmd)), code, output))
            codes.append(code)
            outs.append(output)
        failed = any(c != 0 for c in codes)
        if expect_fail:
            status = "FAILED AS EXPECTED" if failed else "DID NOT FAIL (unexpected)"
        else:
            status = "FAILED" if failed else "OK"
        ev.record(filename, title, blocks, status, time.perf_counter() - t0)
        return (not failed), outs

    # 00 environment: facts only, never environment variables
    code, docker_v, _ = run(["docker", "version", "--format", "client {{.Client.Version}}, server {{.Server.Version}}"], timeout=60)
    docker_ok = code == 0
    env_blocks = [("python", 0, sys.version.replace("\n", " ")),
                  ("platform", 0, f"{platform.system()} {platform.release()} {platform.machine()}"),
                  ("docker version", code, docker_v)]
    code2, git_head, _ = run(["git", "rev-parse", "--short", "HEAD"], cwd=root, timeout=30)
    if code2 == 0:
        env_blocks.append(("git commit", 0, git_head))
    ev.record("00-environment.txt", "Environment", env_blocks, "OK" if docker_ok else "NOTE: docker not available", 0)

    step("01-tests.txt", "Test suite", [[py, "-m", "pytest", "-q", "-p", "no:cacheprovider"]])

    built = {"bloated": False, "slim": False}
    if docker_ok:
        for kind in ("bloated", "slim"):
            ok, _ = step(f"02-build-{kind}.txt", f"Build {kind} image",
                         [["docker", "build", "--platform", "linux/amd64", "-f", f"docker/Dockerfile.{kind}",
                           "-t", f"canary-kit:{kind}", "."]])
            built[kind] = ok
    else:
        for kind in ("bloated", "slim"):
            ev.skipped(f"02-build-{kind}.txt", f"Build {kind} image", "Docker is not running or not installed")

    if all(built.values()):
        step("03-size-report.txt", "Image sizes and heaviest layers",
             [[py, "tools/size_report.py", "canary-kit:bloated", "canary-kit:slim"]])
    else:
        ev.skipped("03-size-report.txt", "Image sizes and heaviest layers", "needs both images built")

    first_ms = {}
    for kind in ("bloated", "slim"):
        fname = f"04-smoke-{kind}.txt"
        if built[kind]:
            cmds = [[py, "tools/cold_start_smoke.py", f"canary-kit:{kind}", "--max-cold-ms", HUGE_BUDGET_MS]
                    for _ in range(runs)]
            _, outs = step(fname, f"Cold-start smoke test, {kind} ({runs} fresh containers)", cmds)
            first_ms[kind] = parse_first_request_ms("\n".join(outs))
        else:
            ev.skipped(fname, f"Cold-start smoke test, {kind}", f"{kind} image was not built")

    size_budget = cold_budget = None
    if built["slim"] and first_ms.get("slim"):
        code, size_out, _ = run(["docker", "image", "inspect", "canary-kit:slim", "--format", "{{.Size}}"], timeout=60)
        try:
            slim_bytes = int(size_out.strip())
            size_budget, cold_budget = budgets(slim_bytes, first_ms["slim"])
        except ValueError:
            pass
    if size_budget:
        body = (f"slim image: {slim_bytes / MB:.1f} MB; first requests (ms): {first_ms['slim']}\n"
                f"SIZE_BUDGET_MB = {size_budget}   (slim size + 10 percent, rounded up)\n"
                f"COLD_START_BUDGET_MS = {cold_budget}   (median first request + 50 percent, rounded up)\n\n"
                "Set them as GitHub repository variables (Settings, Secrets and variables, Actions, Variables),\n"
                "or with the GitHub CLI inside your repo:\n"
                f"  gh variable set SIZE_BUDGET_MB --body {size_budget}\n"
                f"  gh variable set COLD_START_BUDGET_MS --body {cold_budget}\n")
        ev.record("05-budgets.txt", "Budgets worked out from your numbers", [("calculation", 0, body)], "OK", 0)
        step("06-gates-pass.txt", "Both gates on the slim image",
             [[py, "tools/size_gate.py", "canary-kit:slim", "--budget-mb", str(size_budget)],
              [py, "tools/cold_start_smoke.py", "canary-kit:slim", "--max-cold-ms", str(cold_budget)]])
    else:
        ev.skipped("05-budgets.txt", "Budgets worked out from your numbers", "needs the slim image and its smoke test")
        ev.skipped("06-gates-pass.txt", "Both gates on the slim image", "needs budgets")

    if size_budget and not skip_gate_fail:
        tmp = Path(tempfile.mkdtemp(prefix="canary-kit-scipy-"))
        work = tmp / "repo"
        try:
            shutil.copytree(root, work, ignore=shutil.ignore_patterns(
                ".git", "evidence", ".venv", "venv", "__pycache__", ".pytest_cache", "*.zip"))
            req = work / "app" / "requirements-slim.txt"
            req.write_text(req.read_text().rstrip("\n") + "\nscipy\n")
            ok, _ = step("07a-build-slim-with-scipy.txt", "Build a copy of the slim image with scipy added",
                         [["docker", "build", "--platform", "linux/amd64", "-f", "docker/Dockerfile.slim",
                           "-t", "canary-kit:slim-scipy", "."]], cwd=work)
            if ok:
                step("07b-gate-fails-with-scipy.txt", "Size gate on that image (this one should fail)",
                     [[py, "tools/size_gate.py", "canary-kit:slim-scipy", "--budget-mb", str(size_budget)]],
                     expect_fail=True)
            else:
                ev.skipped("07b-gate-fails-with-scipy.txt", "Size gate on that image", "the scipy image did not build")
            run(["docker", "rmi", "canary-kit:slim-scipy"], timeout=120)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    else:
        ev.skipped("07b-gate-fails-with-scipy.txt", "Size gate with scipy added",
                   "skipped by option" if skip_gate_fail else "needs budgets")

    for name in ("bad", "good"):
        step(f"08-simulate-{name}.txt", f"Local canary simulation, {name} release",
             [[py, "tools/local_canary.py", "--candidate", name]])
    step("08-simulate-quiet.txt", "Local canary simulation, bad release with no traffic",
         [[py, "tools/local_canary.py", "--candidate", "bad", "--requests-per-minute", "0"]])

    code, _, _ = run(["gh", "--version"], timeout=30)
    if code == 0 and (root / ".git").exists():
        step("09-github-actions.txt", "Latest GitHub Actions runs (optional)", [["gh", "run", "list", "--limit", "10"]])
    else:
        ev.skipped("09-github-actions.txt", "Latest GitHub Actions runs (optional)", "gh CLI not installed or not a git repo yet")

    return ev.finish()


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=str(ROOT / "evidence"))
    ap.add_argument("--runs", type=int, default=3, help="fresh containers per smoke test (default 3)")
    ap.add_argument("--skip-gate-fail", action="store_true", help="skip the scipy build (saves a few minutes)")
    args = ap.parse_args(argv)
    summary = collect(ROOT, Path(args.out), runs=args.runs, skip_gate_fail=args.skip_gate_fail)
    print("\n" + summary)
    print(f"\nSend me: {Path(args.out) / 'ALL-evidence.txt'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
