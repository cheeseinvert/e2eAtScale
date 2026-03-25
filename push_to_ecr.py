"""
push_to_ecr.py
--------------
Builds the Docker image and pushes it to AWS ECR using boto3.

Usage:
    python push_to_ecr.py --repo playwright-tests --tag latest

Prerequisites:
    - Docker daemon running locally
    - AWS credentials configured (env vars, ~/.aws/credentials, or IAM role)
    - The ECR repository already exists (script will create it if not)
"""

import argparse
import base64
import subprocess
import sys
import boto3
from botocore.exceptions import ClientError


def get_or_create_repo(ecr_client, repo_name: str) -> str:
    """Return the repository URI, creating the repo if it doesn't exist."""
    try:
        resp = ecr_client.describe_repositories(repositoryNames=[repo_name])
        uri = resp["repositories"][0]["repositoryUri"]
        print(f"[ECR] Repository exists: {uri}")
        return uri
    except ClientError as e:
        if e.response["Error"]["Code"] == "RepositoryNotFoundException":
            print(f"[ECR] Creating repository: {repo_name}")
            resp = ecr_client.create_repository(
                repositoryName=repo_name,
                imageScanningConfiguration={"scanOnPush": True},
                encryptionConfiguration={"encryptionType": "AES256"},
            )
            uri = resp["repository"]["repositoryUri"]
            print(f"[ECR] Created: {uri}")
            return uri
        raise


def get_ecr_login_token(ecr_client, registry: str) -> tuple[str, str]:
    """Retrieve a short-lived ECR auth token and decode it."""
    resp = ecr_client.get_authorization_token()
    token = resp["authorizationData"][0]["authorizationToken"]
    decoded = base64.b64decode(token).decode("utf-8")
    username, password = decoded.split(":", 1)
    return username, password


def run(cmd: list[str], **kwargs):
    """Run a shell command, streaming output. Raises on non-zero exit."""
    print(f"[CMD] {' '.join(cmd)}")
    result = subprocess.run(cmd, **kwargs)
    if result.returncode != 0:
        print(f"[ERROR] Command failed with exit code {result.returncode}")
        sys.exit(result.returncode)


def main():
    parser = argparse.ArgumentParser(description="Build and push image to ECR")
    parser.add_argument("--repo",   default="playwright-tests",  help="ECR repository name")
    parser.add_argument("--tag",    default="latest",            help="Image tag")
    parser.add_argument("--region", default="us-east-1",         help="AWS region")
    parser.add_argument("--context", default=".",                help="Docker build context path")
    args = parser.parse_args()

    # ------------------------------------------------------------------
    # 1. Resolve AWS account ID and ECR registry URL
    # ------------------------------------------------------------------
    sts = boto3.client("sts", region_name=args.region)
    account_id = sts.get_caller_identity()["Account"]
    registry   = f"{account_id}.dkr.ecr.{args.region}.amazonaws.com"
    repo_uri   = f"{registry}/{args.repo}"
    full_tag   = f"{repo_uri}:{args.tag}"

    print(f"[INFO] Account : {account_id}")
    print(f"[INFO] Registry: {registry}")
    print(f"[INFO] Image   : {full_tag}")

    # ------------------------------------------------------------------
    # 2. Ensure ECR repository exists
    # ------------------------------------------------------------------
    ecr = boto3.client("ecr", region_name=args.region)
    get_or_create_repo(ecr, args.repo)

    # ------------------------------------------------------------------
    # 3. Authenticate Docker with ECR
    # ------------------------------------------------------------------
    username, password = get_ecr_login_token(ecr, registry)
    run([
        "docker", "login",
        "--username", username,
        "--password-stdin",
        registry
    ], input=password.encode(), capture_output=False)

    # ------------------------------------------------------------------
    # 4. Build the image
    # ------------------------------------------------------------------
    run([
        "docker", "build",
        "--platform", "linux/amd64",  # Lambda runs on x86_64
        "-t", full_tag,
        args.context
    ])

    # ------------------------------------------------------------------
    # 5. Push to ECR
    # ------------------------------------------------------------------
    run(["docker", "push", full_tag])

    print(f"\n[DONE] Successfully pushed: {full_tag}")
    print(f"[INFO] Use this URI in your Lambda function configuration:")
    print(f"       {full_tag}")


if __name__ == "__main__":
    main()
