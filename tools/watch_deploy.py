# lambda-canary-kit/tools/watch_deploy.py
"""Follow the newest CodeDeploy deployment of the stack and print every state change.

  python tools/watch_deploy.py --stack canary-kit

Prints a timestamped line each time the deployment changes state and, if it ends
in Failed or Stopped, the rollback details CodeDeploy recorded. Screenshot-friendly.
"""
import argparse
import sys
import time
from datetime import datetime

import boto3


def find_group(cfn, stack):
    app = group = None
    for res in cfn.describe_stack_resources(StackName=stack)["StackResources"]:
        if res["ResourceType"] == "AWS::CodeDeploy::Application":
            app = res["PhysicalResourceId"]
        if res["ResourceType"] == "AWS::CodeDeploy::DeploymentGroup":
            group = res["PhysicalResourceId"]
    if not app or not group:
        raise SystemExit("No CodeDeploy application found in the stack yet. Deploy once with a DeploymentPreference first.")
    return app, group


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--stack", default="canary-kit")
    ap.add_argument("--region", default=None)
    ap.add_argument("--wait-for-new", type=int, default=120, help="seconds to wait for a deployment to appear")
    args = ap.parse_args(argv)

    cfn = boto3.client("cloudformation", region_name=args.region)
    cd = boto3.client("codedeploy", region_name=args.region)
    app, group = find_group(cfn, args.stack)

    deadline = time.time() + args.wait_for_new
    dep_id = None
    while time.time() < deadline and not dep_id:
        ids = cd.list_deployments(applicationName=app, deploymentGroupName=group).get("deployments", [])
        dep_id = ids[0] if ids else None
        if not dep_id:
            time.sleep(3)
    if not dep_id:
        raise SystemExit("No deployment appeared.")

    print(f"watching {dep_id}")
    seen = None
    while True:
        info = cd.get_deployment(deploymentId=dep_id)["deploymentInfo"]
        status = info["status"]
        if status != seen:
            print(f"{datetime.now():%H:%M:%S}  {status}", flush=True)
            seen = status
        if status in ("Succeeded", "Failed", "Stopped"):
            if info.get("errorInformation"):
                print("error:", info["errorInformation"].get("message"))
            if info.get("rollbackInfo"):
                print("rollback:", info["rollbackInfo"].get("rollbackMessage"))
            return 0 if status == "Succeeded" else 1
        time.sleep(5)


if __name__ == "__main__":
    sys.exit(main())
