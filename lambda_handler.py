"""
lambda_handler.py
-----------------
AWS Lambda entry point.

Responsibilities:
  1. Receive a payload specifying which test(s) to run and a run_id.
  2. Execute pytest programmatically with pytest-json-report.
  3. Parse the JSON report.
  4. Write per-test results to DynamoDB so the orchestrator can
     aggregate results across all parallel Lambda invocations.

Expected event payload:
  {
    "run_id":   "run-2024-06-01-001",   # Shared across all parallel lambdas
    "shard_id": "shard-0",              # Unique per Lambda invocation
    "tests":    ["test_login_flow.py::TestLoginFlow::test_successful_login"]
  }
"""

import json
import os
import subprocess
import boto3
from datetime import datetime, timezone


DYNAMODB_TABLE = os.environ.get("RESULTS_TABLE", "playwright-test-results")
RESULTS_STORE  = os.environ.get("RESULTS_STORE", "dynamo")  # local | dynamo | both
REPORT_DIR     = os.environ.get("REPORT_DIR", "/tmp")

# Only initialise the DynamoDB resource if we actually need it.
# This allows local_runner.py to use --store local without requiring
# AWS credentials to be present at all.
_dynamodb = None

def _get_table():
    global _dynamodb
    if _dynamodb is None:
        _dynamodb = boto3.resource("dynamodb")
    return _dynamodb.Table(DYNAMODB_TABLE)


def handler(event, context):
    run_id   = event["run_id"]
    shard_id = event.get("shard_id", "shard-0")
    tests    = event.get("tests", [])   # Empty list = run all tests

    report_path = f"{REPORT_DIR}/results-{shard_id}.json"

    # ------------------------------------------------------------------
    # Build pytest command
    # ------------------------------------------------------------------
    cmd = [
        "python", "-m", "pytest",
        "--json-report",
        f"--json-report-file={report_path}",
        "-v",
        "--tb=short",   # Concise tracebacks in the report
    ]

    if tests:
        cmd.extend(tests)
    else:
        cmd.append("test_login_flow.py")

    # ------------------------------------------------------------------
    # Run pytest as a subprocess.
    # We use subprocess rather than pytest.main() because pytest.main()
    # can leave global state that interferes with repeated Lambda warm
    # starts in the same container instance.
    # ------------------------------------------------------------------
    result = subprocess.run(
        cmd,
        cwd="/app",
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "TEST_EMAIL":    os.environ["TEST_EMAIL"],
            "TEST_PASSWORD": os.environ["TEST_PASSWORD"],
        }
    )

    # ------------------------------------------------------------------
    # Parse report and write each test result to DynamoDB
    # ------------------------------------------------------------------
    try:
        with open(report_path) as f:
            report = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        # If pytest failed to even start, write a sentinel failure record
        _write_error_record(run_id, shard_id, str(e), result.stderr)
        return {"statusCode": 500, "body": f"Report parse failed: {e}"}

    written = []
    for test in report.get("tests", []):
        record = {
            # Composite primary key: run_id (partition) + test nodeid (sort)
            "run_id":      run_id,
            "test_id":     test["nodeid"],
            "shard_id":    shard_id,
            "outcome":     test["outcome"],          # passed / failed / error
            "duration_s":  str(test["call"]["duration"]) if "call" in test else "0",
            "timestamp":   datetime.now(timezone.utc).isoformat(),
            # Capture failure detail for failed tests
            "longrepr":    test.get("call", {}).get("longrepr", ""),
        }
        if RESULTS_STORE in ("dynamo", "both"):
            _get_table().put_item(Item=record)
        written.append(record["test_id"])

    summary = report.get("summary", {})
    return {
        "statusCode": 200,
        "run_id":     run_id,
        "shard_id":   shard_id,
        "summary":    summary,
        "tests_written": written,
    }


def _write_error_record(run_id: str, shard_id: str, error: str, stderr: str):
    if RESULTS_STORE in ("dynamo", "both"):
        _get_table().put_item(Item={
            "run_id":     run_id,
            "test_id":    f"{shard_id}::STARTUP_FAILURE",
            "shard_id":   shard_id,
            "outcome":    "error",
            "duration_s": "0",
            "timestamp":  datetime.now(timezone.utc).isoformat(),
            "longrepr":   f"{error}\n\nSTDERR:\n{stderr}",
        })
