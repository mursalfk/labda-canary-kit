# instructions.md: lambda-canary-kit, start to finish

## The $0 path (do this one)

Steps 1 to 5 plus step 4b cost nothing and never touch AWS: Docker builds and tests on your machine, a local
canary simulation, and GitHub Actions on a PUBLIC repo (free minutes, as far as I know; check GitHub's current plan page).
Steps 6 to 10 deploy to AWS and could bill your card. **Skip them.** Do not run `make deploy`, `sam deploy`, or anything
with `aws` in it. Do not add AWS keys anywhere. The article will say plainly that the AWS part was not run.

**Fast way (recommended):** do step 1 and step 2, then run one command:

```bash
python tools/collect_evidence.py     # make evidence
```

It does steps 3, 4 and 4b by itself (both image builds, sizes, three cold-start runs per image, your budgets, both gates
passing, the scipy size-gate failure, the three canary simulations) and saves every output in its own file inside
`evidence/`, plus one combined file, `evidence/ALL-evidence.txt`. Docker Desktop must be running. It takes a while,
mostly Docker builds (I have not timed them), and the scipy step builds a second image. Add `--skip-gate-fail` to skip
that one. A failing step does not stop it: the error is saved in the file, which is exactly what I need.
Then do step 5 (GitHub), using the two numbers in `evidence/05-budgets.txt`, and jump to step 11.
Steps 3, 4 and 4b below are the same things by hand, only needed if the script itself breaks.

If any step fails, copy the exact error and send it to me. Nothing in the repo was run against Docker yet,
so the first failures are expected and cheap to fix.

## 1. Prerequisites

- Python 3.12 (3.13 works for the local parts), Git
- Docker Desktop or Docker Engine, running
- AWS CLI v2 with credentials (`aws sts get-caller-identity` must work)
- AWS SAM CLI (`sam --version`)
- Optional: `make`. On Windows without make, use the plain command shown next to each `make` line.

## 2. Local setup and tests

```bash
cd lambda-canary-kit
python -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt  # make install
pytest -q                            # make test  -> expect 25 passed
```

## 3. Build both images and write the numbers down

```bash
make report
# without make:
docker build --platform linux/amd64 -f docker/Dockerfile.bloated -t canary-kit:bloated .
docker build --platform linux/amd64 -f docker/Dockerfile.slim    -t canary-kit:slim .
python tools/size_report.py canary-kit:bloated canary-kit:slim
```

Save the full output: it is the before/after table for the article. If the bloated build fails on
`microdnf`, send me the error (the package manager name in the Lambda base image is the likeliest snag).

Then check both images answer correctly under the Lambda emulator:

```bash
python tools/cold_start_smoke.py canary-kit:bloated --max-cold-ms 60000
python tools/cold_start_smoke.py canary-kit:slim    --max-cold-ms 60000
```

(The huge budget just means "do not fail yet". Write down both first-request times.)

## 4. Pick budgets from your own numbers

(`collect_evidence.py` works these out for you in `evidence/05-budgets.txt`. The rule is below.)

- `SIZE_BUDGET_MB` = the slim image size from step 3, plus about 10 percent, rounded up.
- `COLD_START_BUDGET_MS` = the slim first-request time from step 3, plus about 50 percent. Local timing is noisy.

Try the gates locally:

```bash
python tools/size_gate.py canary-kit:slim --budget-mb <your number>
python tools/cold_start_smoke.py canary-kit:slim --max-cold-ms <your number>
```

Then show the gate doing its job. Add `scipy` on a new line in `app/requirements-slim.txt`, rebuild the slim image,
run the size gate again, and capture the FAIL line. Remove the line afterwards.

## 4b. Canary rollback, locally (free)

```bash
make simulate-bad
make simulate-good
make simulate-quiet
# without make:
python tools/local_canary.py --candidate bad
python tools/local_canary.py --candidate good
python tools/local_canary.py --candidate bad --requests-per-minute 0
```

It runs the real handler and model for every simulated request, with a simulated router, clock and alarm that copy the
rules in `template.yaml` (10 percent canary for 5 minutes, alarm on any error in 2 consecutive 1-minute periods).
Expected: `bad` ends in ALARM after minute 2 and rolls back, `good` is promoted after minute 5, `quiet` promotes the bad
release because no request ever reached the canary (the lesson: an error alarm needs traffic).
Capture all three outputs. The first line of the output says SIMULATION, keep it in the screenshot.

This proves the release logic. It does not prove CodeDeploy or CloudWatch behaviour, and the article must say so.

## 5. Put it on GitHub and turn CI on

```bash
git init
git add .
git commit -m "Lambda canary kit: slim image, CI gates, canary rollback"
git branch -M main
git remote add origin https://github.com/mursalfk/lambda-canary-kit.git
git push -u origin main
```

In the GitHub repo: Settings, Secrets and variables, Actions, **Variables** tab, add:

| Variable | Value |
|---|---|
| `SIZE_BUDGET_MB` | your number from step 4 |
| `COLD_START_BUDGET_MS` | your number from step 4 |

Open a pull request with any small change (for example add `scipy` to `app/requirements-slim.txt`). The `image-gates`
job should fail on size. Capture that red check, then close the PR. The green run on `main` is the other screenshot.

# STOP HERE FOR THE $0 PATH. Steps 6 to 10 use AWS.

Only continue if you have checked, in Billing, Credits, that your credit is redeemed, unexpired, and that ECR,
CloudWatch, CodeDeploy, Lambda and CloudFormation are on its eligible list, and you have set an AWS Budget alert at $1.
Anything not covered is charged to your card.

## 6. First deploy (release v1)

```bash
python tools/deploy.py --release v1       # make deploy RELEASE=v1
```

It creates an ECR repo called `canary-kit`, builds and pushes the slim image, and deploys the SAM stack.
When it finishes, note the `FunctionName` stack output:

```bash
aws cloudformation describe-stacks --stack-name canary-kit --query "Stacks[0].Outputs"
```

Quick check that it answers (replace the name):

```bash
aws lambda invoke --function-name <FunctionName>:live --cli-binary-format raw-in-base64-out \
  --payload "{\"pixels\": [0,0,5,13,9,1,0,0,0,0,13,15,10,15,5,0,0,3,15,2,0,11,8,0,0,4,12,0,0,8,8,0,0,5,8,0,0,9,8,0,0,4,11,0,1,12,7,0,0,2,14,5,10,12,0,0,0,0,6,13,10,0,0,0]}" out.json && cat out.json
```

(That payload is a hand-drawn "0". Any 64 numbers from 0 to 16 work.)

## 7. A good canary release (v2)

Terminal A: `python tools/traffic.py --function <FunctionName> --seconds 600 --rps 4`
Terminal B: `python tools/deploy.py --release v2`
Terminal C (start once the deploy begins): `python tools/watch_deploy.py --stack canary-kit`

Watch Terminal A: first everything is answered by `v1`, then a small share by `v2`, then all `v2`.
Terminal C ends in `Succeeded`. Capture A and C.

## 8. The bad release (v3-bad): the rollback demo

```bash
python tools/release.py bad          # make ship-bad
pytest -q                            # one test now fails on purpose: the good-copy check. Read why.
```

Same three terminals, but Terminal B runs `python tools/deploy.py --release v3-bad`.

What you should see: `ERROR` counts appear in Terminal A for the share of traffic hitting the new version,
the alarm goes to ALARM after about two minutes, Terminal C shows `Stopped` or `Failed` plus the rollback message,
and Terminal A returns to 100 percent `v2`. Then restore the good code:

```bash
python tools/release.py good         # make ship-good
```

Screenshots to capture: Terminal A during the canary, Terminal C ending in a rollback, the CloudWatch alarm in ALARM
(CloudWatch, Alarms), and the CodeDeploy deployment page showing the rollback (CodeDeploy, Deployments).

## 8b. Real Lambda cold starts, bloated vs slim (optional but this is the strongest chart)

```bash
python tools/deploy.py --release v0-bloated --stack canary-kit-bloated \
  --dockerfile docker/Dockerfile.bloated --deploy-type AllAtOnce
aws cloudformation describe-stacks --stack-name canary-kit-bloated --query "Stacks[0].Outputs"
python tools/cold_samples.py --function <bloated FunctionName> --samples 10
python tools/cold_samples.py --function <slim FunctionName>    --samples 10
```

Each run forces ten genuine cold starts and prints the Init Duration Lambda itself reported. Send me both outputs.
This edits the function configuration outside CloudFormation, so run it last and then clean up (step 10).

Or read cold starts from CloudWatch Logs Insights on `/aws/lambda/<FunctionName>`:

```
filter @type = "REPORT" and ispresent(@initDuration)
| stats count() as coldStarts, pct(@initDuration, 50) as p50, max(@initDuration) as worst
```

## 9. Optional: a GitHub deploy button with no stored AWS keys

1. IAM, Identity providers, Add provider: type OpenID Connect, URL `https://token.actions.githubusercontent.com`, audience `sts.amazonaws.com`.
2. Create an IAM role with this trust policy (replace ACCOUNT and OWNER):

```json
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Principal": {"Federated": "arn:aws:iam::ACCOUNT:oidc-provider/token.actions.githubusercontent.com"},
    "Action": "sts:AssumeRoleWithWebIdentity",
    "Condition": {
      "StringEquals": {"token.actions.githubusercontent.com:aud": "sts.amazonaws.com"},
      "StringLike": {"token.actions.githubusercontent.com:sub": "repo:OWNER/lambda-canary-kit:ref:refs/heads/main"}
    }
  }]
}
```

3. Give the role the permissions a SAM deploy needs (CloudFormation, Lambda, IAM role creation, ECR, CodeDeploy, CloudWatch
   alarms, S3 for the SAM artifacts bucket). Start broad to get it working, then narrow it using the access advisor.
4. Add repository variables `AWS_DEPLOY_ROLE_ARN` and `AWS_REGION`, then run Actions, deploy, Run workflow with a release label.

Check the current AWS and GitHub OIDC docs for the exact provider setup before you rely on step 1.

## 10. Clean up (stops all cost)

```bash
make destroy
# without make:
sam delete --stack-name canary-kit --no-prompts
sam delete --stack-name canary-kit-bloated --no-prompts
aws ecr delete-repository --repository-name canary-kit --force
```

## 11. What to send me for the article

$0 path: send me **one file**, `evidence/ALL-evidence.txt`. It already contains the test run, both builds, the
size report, the smoke tests, your budgets, both gates, the scipy size-gate failure, the three canary simulations and
your latest GitHub Actions runs (if you have the `gh` CLI). If a step failed, its error is inside the file.
The separate files in `evidence/` hold the same content in full, if you want to send one on its own.

Optional extra: a screenshot of the red pull-request check from step 5 (the script cannot take that one).

Only if you ran the AWS steps: Terminal A and Terminal C captures from steps 7 and 8, the alarm and CodeDeploy
screenshots, and both `cold_samples.py` outputs (step 8b).

I will write the article only from numbers you ran. `docs/article-outline.md` has the planned structure.

## Cost, honestly (AWS steps 6 to 10 only; the $0 path has none)

Lambda's free tier covers the traffic here (about 2,400 requests per 10-minute run). CodeDeploy for Lambda has no charge. One
standard CloudWatch alarm is inside the free allowance. The only real line item is ECR image storage for a couple of
hundred megabytes for a few hours, which is a few cents at most. Check current ECR pricing before you leave anything running.
