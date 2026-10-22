# lambda-canary-kit/docs/article-outline.md

Working title: Ship Lambda Containers Safely: Slim Images, Auto-Rollback (57 characters)

Rules for the article: no em-dashes, no localhost links, wrap file names in backticks, numbers only from runs.

1. Hook: a 3.6 KB model shipped inside a very large image. The model is not the problem.
2. The bloated image: what each habit costs (table from `make report`, layer view).
3. The slim image: multi-stage, only what runs, the strip step, what did NOT help (`--no-deps`, 4 MB).
4. Proof it is the same service: 25 tests, both backends agree on all 1,797 digits.
5. Real cold starts: bloated vs slim, ten forced cold starts each (from `cold_samples.py`).
6. Gates so it stays slim: the size gate and the smoke test; the red PR with `scipy` added.
7. The release that looks fine and is not: float64, passes the scikit-learn test, fails the ONNX model.
8. The canary: alias, 10 percent, the alarm, and why it needs traffic.
9. The demo: `tools/local_canary.py` (labelled simulation: real handler, simulated router and alarm). The `template.yaml` canary is shown as the AWS config; say plainly it was not deployed by the author. Real CodeDeploy captures replace this only if the AWS steps are run.
10. What this does not protect you from (blunt alarm, no pre-traffic hook, local smoke is not real cold start).
11. Run it yourself: repo link, clean-up reminder.

Figures to produce (real captures only): report table, size gate FAIL, red PR, three local_canary outputs (bad, good, quiet),
local cold-start numbers. AWS-only figures (alarm in ALARM, CodeDeploy page, Lambda cold-start chart) only if those steps are run.
