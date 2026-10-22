# lambda-canary-kit/tests/test_tools.py
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import cold_samples  # noqa: E402
import cold_start_smoke  # noqa: E402
import release  # noqa: E402
import size_gate  # noqa: E402

MB = 1024 * 1024


def test_size_gate_passes_under_budget_and_fails_over():
    ok, msg = size_gate.verdict(300 * MB, 350)
    assert ok and "OK" in msg
    ok, msg = size_gate.verdict(351 * MB, 350)
    assert not ok and "FAIL" in msg


def test_size_gate_exit_codes_without_docker():
    assert size_gate.main(["x", "--budget-mb", "10", "--bytes", str(5 * MB)]) == 0
    assert size_gate.main(["x", "--budget-mb", "10", "--bytes", str(50 * MB)]) == 1


def test_check_reply_flags_wrong_digit_and_bad_status():
    assert cold_start_smoke.check_reply({"statusCode": 200, "digit": 4}, 4) == []
    assert cold_start_smoke.check_reply({"statusCode": 200, "digit": 5}, 4)
    assert cold_start_smoke.check_reply({"statusCode": 400}, 4)
    assert cold_start_smoke.check_reply({"errorMessage": "boom"}, 4)


def test_release_tool_swaps_and_restores(tmp_path):
    (tmp_path / "app").mkdir()
    (tmp_path / "releases").mkdir()
    for name in ("preprocess_good.py", "preprocess_bad.py"):
        shutil.copy(ROOT / "releases" / name, tmp_path / "releases" / name)
    shutil.copy(ROOT / "app" / "preprocess.py", tmp_path / "app" / "preprocess.py")

    assert release.active(tmp_path) == "good"
    assert release.main(["bad", "--root", str(tmp_path)]) == 0
    assert release.active(tmp_path) == "bad"
    assert release.main(["good", "--root", str(tmp_path)]) == 0
    assert release.active(tmp_path) == "good"


def test_parse_init_ms_reads_a_report_line_and_ignores_warm_ones():
    cold = "REPORT RequestId: abc Duration: 4.3 ms Billed Duration: 5 ms Memory Size: 512 MB Max Memory Used: 140 MB Init Duration: 812.45 ms"
    warm = "REPORT RequestId: abc Duration: 4.3 ms Billed Duration: 5 ms Memory Size: 512 MB Max Memory Used: 140 MB"
    assert cold_samples.parse_init_ms(cold) == 812.45
    assert cold_samples.parse_init_ms(warm) is None


def test_local_canary_rolls_back_bad_and_promotes_good():
    import local_canary
    bad = local_canary.simulate(ROOT, "bad", requests_per_minute=60)
    assert bad["outcome"] == "rolled_back"
    assert bad["rows"][-1]["alarm"] == "ALARM" and len(bad["rows"]) == 2
    assert all(r["old_errors"] == 0 for r in bad["rows"])
    good = local_canary.simulate(ROOT, "good", requests_per_minute=60)
    assert good["outcome"] == "promoted" and len(good["rows"]) == 5
    assert all(r["new_errors"] == 0 for r in good["rows"])


def test_local_canary_without_traffic_promotes_the_bad_release():
    import local_canary
    quiet = local_canary.simulate(ROOT, "bad", requests_per_minute=0)
    assert quiet["outcome"] == "promoted"
    assert "never received a request" in local_canary.render(quiet)


# --- collect_evidence -------------------------------------------------------

import collect_evidence  # noqa: E402


def _fake_runner(docker_up=True, scipy_fails=True):
    calls = []

    def run(cmd, cwd=None, timeout=0):
        calls.append(cmd)
        text = " ".join(map(str, cmd))
        if cmd[0] == "docker" and cmd[1] == "version":
            return (0, "client 27, server 27", 0) if docker_up else (127, "command not found: docker", 0)
        if cmd[0] == "docker":
            if cmd[1] == "image":
                return 0, str(700 * MB), 0
            return 0, "ok", 0
        if cmd[0] == "git":
            return 0, "abc1234", 0
        if cmd[0] == "gh":
            return 127, "command not found: gh", 0
        if "pytest" in text:
            return 0, "27 passed", 0
        if "cold_start_smoke" in text:
            ms = 1800 if "bloated" in text else 400
            return 0, f"first request (includes init): {ms} ms   reported init_ms: 5\nOK", 0
        if "size_gate" in text:
            return (1, "FAIL: too big", 0) if "slim-scipy" in text and scipy_fails else (0, "OK", 0)
        return 0, "output of " + text, 0

    return run, calls


def test_parse_first_request_and_budgets():
    out = "first request (includes init): 410 ms   x\nfirst request (includes init): 380 ms   x\n"
    assert collect_evidence.parse_first_request_ms(out) == [410, 380]
    assert collect_evidence.budgets(700 * MB, [400, 380, 420]) == (770, 600)


def test_shorten_keeps_the_tail_of_long_output():
    text = "\n".join(f"line {i}" for i in range(300))
    short = collect_evidence.shorten(text)
    assert "line 299" in short and "line 0\n" not in short and "left out" in short
    assert collect_evidence.shorten("a\nb") == "a\nb"


def test_collect_writes_one_file_per_step_and_one_combined_file(tmp_path):
    run, _ = _fake_runner()
    summary = collect_evidence.collect(ROOT, tmp_path, run=run, runs=2)
    names = {p.name for p in tmp_path.iterdir()}
    for expected in ("00-environment.txt", "01-tests.txt", "02-build-slim.txt", "03-size-report.txt",
                     "04-smoke-slim.txt", "05-budgets.txt", "06-gates-pass.txt", "07a-build-slim-with-scipy.txt",
                     "07b-gate-fails-with-scipy.txt", "08-simulate-bad.txt", "08-simulate-quiet.txt",
                     "00-summary.txt", "ALL-evidence.txt"):
        assert expected in names, expected
    assert "SIZE_BUDGET_MB = 770" in (tmp_path / "05-budgets.txt").read_text()
    assert "COLD_START_BUDGET_MS = 600" in (tmp_path / "05-budgets.txt").read_text()
    assert "FAILED AS EXPECTED" in (tmp_path / "07b-gate-fails-with-scipy.txt").read_text()
    assert "09-github-actions.txt" in names and "SKIPPED" in (tmp_path / "09-github-actions.txt").read_text()
    combined = (tmp_path / "ALL-evidence.txt").read_text()
    assert "FILE: 06-gates-pass.txt" in combined and "SUMMARY" in summary


def test_collect_flags_a_gate_that_did_not_fail(tmp_path):
    run, _ = _fake_runner(scipy_fails=False)
    collect_evidence.collect(ROOT, tmp_path, run=run, runs=1)
    assert "DID NOT FAIL" in (tmp_path / "07b-gate-fails-with-scipy.txt").read_text()


def test_collect_without_docker_skips_docker_steps_but_still_runs_the_rest(tmp_path):
    run, calls = _fake_runner(docker_up=False)
    collect_evidence.collect(ROOT, tmp_path, run=run, runs=1)
    assert "SKIPPED" in (tmp_path / "02-build-slim.txt").read_text()
    assert "SKIPPED" in (tmp_path / "05-budgets.txt").read_text()
    assert "output of" in (tmp_path / "08-simulate-bad.txt").read_text()
    assert not any(c[:2] == ["docker", "build"] for c in calls)


def test_dockerfiles_do_not_rely_on_find_which_the_lambda_base_image_lacks():
    for name in ("Dockerfile.slim", "Dockerfile.bloated"):
        run_lines = [ln for ln in (ROOT / "docker" / name).read_text().splitlines() if "find " in ln and not ln.lstrip().startswith("#")]
        assert run_lines == [], f"{name} uses find: {run_lines}"