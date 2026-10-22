# lambda-canary-kit/tools/deploy.py
"""Build the slim image, push it to ECR, and deploy it with SAM.

  python tools/deploy.py --release v1                 # first deploy
  python tools/deploy.py --release v2                 # a normal canary release
  python tools/deploy.py --release v3-bad             # (after `release.py bad`) the rollback demo
  python tools/deploy.py --release v0-bloated --stack canary-kit-bloated \\
         --dockerfile docker/Dockerfile.bloated --deploy-type AllAtOnce   # comparison stack

Needs the AWS CLI, Docker and the SAM CLI on PATH and working AWS credentials.
It creates one ECR repository (default: canary-kit) the first time.
"""
import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def run(cmd, **kw):
    print("$ " + " ".join(cmd))
    return subprocess.run(cmd, check=True, **kw)


def out(cmd):
    return subprocess.run(cmd, check=True, capture_output=True, text=True).stdout.strip()


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--release", required=True, help="label shown in every reply, e.g. v1, v2, v3-bad")
    ap.add_argument("--stack", default="canary-kit")
    ap.add_argument("--repo", default="canary-kit")
    ap.add_argument("--region", default=None, help="defaults to your AWS CLI region")
    ap.add_argument("--platform", default="linux/amd64")
    ap.add_argument("--dockerfile", default="docker/Dockerfile.slim", help="use docker/Dockerfile.bloated for the real-Lambda comparison")
    ap.add_argument("--deploy-type", default="Canary10Percent5Minutes")
    args = ap.parse_args(argv)

    region = args.region or subprocess.run(["aws", "configure", "get", "region"], capture_output=True, text=True).stdout.strip()
    if not region:
        print("No region: pass --region or run `aws configure`.")
        return 2
    account = out(["aws", "sts", "get-caller-identity", "--query", "Account", "--output", "text"])
    registry = f"{account}.dkr.ecr.{region}.amazonaws.com"
    uri = f"{registry}/{args.repo}:{args.release}"

    exists = subprocess.run(["aws", "ecr", "describe-repositories", "--repository-names", args.repo, "--region", region],
                            capture_output=True).returncode == 0
    if not exists:
        run(["aws", "ecr", "create-repository", "--repository-name", args.repo, "--region", region])

    password = out(["aws", "ecr", "get-login-password", "--region", region])
    subprocess.run(["docker", "login", "--username", "AWS", "--password-stdin", registry],
                   input=password, text=True, check=True)

    run(["docker", "build", "--platform", args.platform, "-f", args.dockerfile, "-t", uri, "."], cwd=ROOT)
    run(["docker", "push", uri])

    run(["sam", "deploy", "--template-file", "template.yaml", "--stack-name", args.stack,
         "--region", region, "--capabilities", "CAPABILITY_IAM", "--no-confirm-changeset",
         "--no-fail-on-empty-changeset",
         "--parameter-overrides", f"ImageUri={uri}", f"Release={args.release}", f"DeployType={args.deploy_type}"],
        cwd=ROOT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
