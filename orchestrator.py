"""
orchestrator.py
---------------
Kicks off N AWS Lambda invocations in parallel, one shard per invocation.
Each Lambda runs a subset of tests and writes results to DynamoDB.

This script:
  1. Partitions the test list into N shards.
  2. Invokes all Lambdas concurrently using Python ThreadPoolExecutor.
  3. Polls until all invocations complete.
  4. Prints a high-level summary. Full results are in DynamoDB.

Usage:
    python orchestrator.py \
        --function  playwright-tests \
        --shards    4 \
        --run-id    run-2024-06-01-001 \
        --region    us-east-1
"""

import argparse
import json
import uuid
import boto3
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone


# Full list of test node IDs to distribute across shards.
# In a real pipeline this could be discovered dynamically via
# `pytest --collect-only -q` run in a lightweight pre-step.
ALL_TESTS = [
    "test_login_flow.py::TestLoginFlow::test_successful_login",
    "test_login_flow.py::TestLoginFlow::test_create_room_after_login",
    "test_login_flow.py::TestLoginFlow::test_logout",
    "test_login_flow.py::TestLoginFlow::test_invalid_login_shows_error",
]


def partition(lst: list, n: int) -> list[list]:
    """Split a list into n roughly equal chunks."""
    k, m = divmod(len(lst), n)
    return [lst[i * k + min(i, m):(i + 1) * k + min(i + 1, m)] for i in range(n)]


def invoke_lambda(lambda_client, function_name: str, payload: dict) -> dict:
    """
    Synchronously invoke a single Lambda function (RequestResponse).
    Returns the parsed response payload.
    """
    shard_id = payload["shard_id"]
    print(f"[INVOKE] {shard_id} → tests: {payload['tests']}")

    response = lambda_client.invoke(
        FunctionName=function_name,
        InvocationType="RequestResponse",   # Wait for completion
        Payload=json.dumps(payload).encode(),
    )

    raw = response["Payload"].read()
    result = json.loads(raw)

    # Lambda wraps unhandled exceptions in a FunctionError field
    if response.get("FunctionError"):
        print(f"[ERROR] {shard_id} Lambda error: {result}")
        result["_lambda_error"] = True

    return result


def main():
    parser = argparse.ArgumentParser(description="Run Playwright tests in parallel Lambda shards")
    parser.add_argument("--function", required=True,          help="Lambda function name or ARN")
    parser.add_argument("--shards",   type=int, default=4,    help="Number of parallel Lambda invocations")
    parser.add_argument("--run-id",   default=None,           help="Unique run identifier (auto-generated if omitted)")
    parser.add_argument("--region",   default="us-east-1",    help="AWS region")
    args = parser.parse_args()

    run_id = args.run_id or f"run-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"
    print(f"\n{'='*60}")
    print(f"  Run ID  : {run_id}")
    print(f"  Shards  : {args.shards}")
    print(f"  Function: {args.function}")
    print(f"{'='*60}\n")

    # ------------------------------------------------------------------
    # Partition tests across shards
    # ------------------------------------------------------------------
    shards = partition(ALL_TESTS, args.shards)
    payloads = [
        {
            "run_id":   run_id,
            "shard_id": f"shard-{i}",
            "tests":    shard,
        }
        for i, shard in enumerate(shards)
    ]

    # ------------------------------------------------------------------
    # Invoke all Lambdas in parallel
    # ------------------------------------------------------------------
    lambda_client = boto3.client("lambda", region_name=args.region)
    results = []

    with ThreadPoolExecutor(max_workers=args.shards) as pool:
        futures = {
            pool.submit(invoke_lambda, lambda_client, args.function, p): p["shard_id"]
            for p in payloads
        }
        for future in as_completed(futures):
            shard_id = futures[future]
            try:
                result = future.result()
                results.append(result)
                summary = result.get("summary", {})
                print(
                    f"[DONE] {shard_id}: "
                    f"passed={summary.get('passed', 0)}  "
                    f"failed={summary.get('failed', 0)}  "
                    f"errors={summary.get('errors', 0)}"
                )
            except Exception as exc:
                print(f"[FAIL] {shard_id} raised an exception: {exc}")
                results.append({"shard_id": shard_id, "_exception": str(exc)})

    # ------------------------------------------------------------------
    # Aggregate totals across shards
    # ------------------------------------------------------------------
    total_passed = sum(r.get("summary", {}).get("passed", 0) for r in results)
    total_failed = sum(r.get("summary", {}).get("failed", 0) for r in results)
    total_errors = sum(r.get("summary", {}).get("errors", 0) for r in results)

    print(f"\n{'='*60}")
    print(f"  RUN COMPLETE — run_id: {run_id}")
    print(f"  Passed : {total_passed}")
    print(f"  Failed : {total_failed}")
    print(f"  Errors : {total_errors}")
    print(f"{'='*60}")
    print(f"\n  Full results in DynamoDB:")
    print(f"  aws dynamodb query --table-name playwright-test-results \\")
    print(f"      --key-condition-expression 'run_id = :r' \\")
    print(f"      --expression-attribute-values '{{\":r\": {{\"S\": \"{run_id}\"}}}}'\n")

    # Exit non-zero if any tests failed (useful for CI)
    if total_failed > 0 or total_errors > 0:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
