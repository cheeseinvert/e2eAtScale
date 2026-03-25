"""
local_runner.py
---------------
Runs the Playwright test suite locally inside Docker, mirroring the Lambda
execution environment exactly. Supports writing results to either a local
JSON file or DynamoDB (or both).

Usage examples:

  # Run all tests, results to local JSON only
  python local_runner.py

  # Run all tests, results to DynamoDB only
  python local_runner.py --store dynamo

  # Run all tests, results to both
  python local_runner.py --store both

  # Run a specific test
  python local_runner.py --test "test_login_flow.py::TestLoginFlow::test_logout"

  # Run with N shards (mirrors orchestrator behaviour)
  python local_runner.py --shards 2 --store both

  # Skip Docker build (reuse last image)
  python local_runner.py --no-build

  # Show results summary after run
  python local_runner.py --report

Prerequisites:
  - Docker daemon running
  - .env file in project root (see .env.example)
  - AWS credentials in environment or ~/.aws if using --store dynamo/both
"""

import argparse
import json
import os
import subprocess
import sys
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

IMAGE_NAME   = "playwright-tests-local"
IMAGE_TAG    = "dev"
RESULTS_DIR  = Path("./local_results")
DYNAMO_TABLE = os.environ.get("RESULTS_TABLE", "playwright-test-results")
AWS_REGION   = os.environ.get("AWS_REGION", "us-east-1")

ALL_TESTS = [
    "test_login_flow.py::TestLoginFlow::test_successful_login",
    "test_login_flow.py::TestLoginFlow::test_create_room_after_login",
    "test_login_flow.py::TestLoginFlow::test_logout",
    "test_login_flow.py::TestLoginFlow::test_invalid_login_shows_error",
]


# ---------------------------------------------------------------------------
# Docker helpers
# ---------------------------------------------------------------------------

def build_image():
    """Build the Docker image from the local Dockerfile."""
    print(f"\n[BUILD] Building {IMAGE_NAME}:{IMAGE_TAG} ...")
    result = subprocess.run(
        ["docker", "build", "-t", f"{IMAGE_NAME}:{IMAGE_TAG}", "."],
        capture_output=False
    )
    if result.returncode != 0:
        print("[ERROR] Docker build failed.")
        sys.exit(result.returncode)
    print("[BUILD] Done.\n")


def run_shard_in_docker(shard_id: str, tests: list[str], run_id: str, store: str) -> dict:
    """
    Run a single test shard inside a Docker container.

    Mounts the local_results directory so JSON reports are written to the
    host filesystem, then calls lambda_handler.handler() via a small inline
    Python invocation — exactly replicating what Lambda does.
    """
    RESULTS_DIR.mkdir(exist_ok=True)
    report_filename = f"results-{shard_id}.json"

    # Build the event payload exactly as orchestrator.py does
    event = {
        "run_id":   run_id,
        "shard_id": shard_id,
        "tests":    tests,
    }

    # Inline Python that imports and calls the handler, then writes the
    # response to a file we can read back on the host.
    inline_script = f"""
import json, sys
sys.path.insert(0, '/app')

# Override the report path to land in our mounted volume
import os
os.environ['REPORT_DIR'] = '/results'

from lambda_handler import handler

class FakeContext:
    function_name = 'local-dev'
    aws_request_id = '{shard_id}'

event = {json.dumps(event)}
result = handler(event, FakeContext())

with open('/results/{report_filename}', 'w') as f:
    json.dump(result, f, indent=2)

print(json.dumps(result, indent=2))
"""

    # Load credentials from .env if present, else pass through from shell
    env_vars = _load_env_vars()
    
    # Always tell the handler where to store results
    env_vars["RESULTS_STORE"]   = store
    # Conditionally pass AWS vars if writing to Dynamo
    if store in ("dynamo", "both"):
        for key in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_DEFAULT_REGION"):
            val = os.environ.get(key)
            if val:
                env_vars[key] = val
        env_vars["RESULTS_TABLE"]   = DYNAMO_TABLE

    docker_cmd = [
        "docker", "run", "--rm",
        "--ipc=host",                            # Shared memory for Chromium
        "-v", f"{RESULTS_DIR.resolve()}:/results",  # Mount results dir
        *_env_flags(env_vars),
        f"{IMAGE_NAME}:{IMAGE_TAG}",
        "python3", "-c", inline_script,
    ]

    print(f"[RUN] {shard_id} → {len(tests)} test(s)")
    result = subprocess.run(docker_cmd, capture_output=True, text=True)

    if result.returncode != 0:
        print(f"[ERROR] {shard_id} container exited {result.returncode}")
        print(result.stderr[-2000:])  # Last 2000 chars of stderr
        return {"shard_id": shard_id, "_error": result.stderr[-500:]}

    # Read the response JSON written by the inline script
    report_path = RESULTS_DIR / report_filename
    try:
        with open(report_path) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"[WARN] Could not read {report_path}: {e}")
        return {"shard_id": shard_id, "_parse_error": str(e)}


def _load_env_vars() -> dict:
    """Load TEST_EMAIL and TEST_PASSWORD from a .env file if present."""
    env = {}
    env_file = Path(".env")
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, val = line.partition("=")
                env[key.strip()] = val.strip().strip('"').strip("'")
    # Shell environment takes precedence over .env file
    for key in ("TEST_EMAIL", "TEST_PASSWORD"):
        if os.environ.get(key):
            env[key] = os.environ[key]
    return env


def _env_flags(env: dict) -> list[str]:
    """Convert a dict to a flat list of -e KEY=VALUE docker flags."""
    flags = []
    for k, v in env.items():
        flags.extend(["-e", f"{k}={v}"])
    return flags


# ---------------------------------------------------------------------------
# Results helpers
# ---------------------------------------------------------------------------

def partition(lst: list, n: int) -> list[list]:
    k, m = divmod(len(lst), n)
    return [lst[i * k + min(i, m):(i + 1) * k + min(i + 1, m)] for i in range(n)]


def write_local_summary(run_id: str, results: list[dict]):
    """Merge all shard responses into a single local summary JSON."""
    summary_path = RESULTS_DIR / f"summary-{run_id}.json"
    summary = {
        "run_id":    run_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "shards":    results,
        "totals": {
            "passed": sum(r.get("summary", {}).get("passed", 0) for r in results),
            "failed": sum(r.get("summary", {}).get("failed", 0) for r in results),
            "errors": sum(r.get("summary", {}).get("errors", 0) for r in results),
        }
    }
    with open(summary_path, "w") as f:
        json.dump(summary, f, indent=2)
    print(f"\n[LOCAL] Summary written → {summary_path}")
    return summary


def print_local_report(run_id: str):
    """Print a quick summary from the local JSON files."""
    summary_path = RESULTS_DIR / f"summary-{run_id}.json"
    if not summary_path.exists():
        print(f"[WARN] No local summary found at {summary_path}")
        return
    with open(summary_path) as f:
        summary = json.load(f)

    totals = summary["totals"]
    print(f"""
  ╔══════════════════════════════════════════╗
  ║  LOCAL RUN SUMMARY                       ║
  ║  run_id : {run_id:<30} ║
  ║  passed : {totals['passed']:<3}  failed : {totals['failed']:<3}  errors : {totals['errors']:<3}  ║
  ╚══════════════════════════════════════════╝
""")


def print_dynamo_report(run_id: str):
    """Delegate to reporter.py for DynamoDB results."""
    subprocess.run(
        ["python3", "reporter.py", "--run-id", run_id, "--region", AWS_REGION]
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Run Playwright tests locally in Docker")
    parser.add_argument("--test",     default=None,    help="Single test node ID to run (default: all)")
    parser.add_argument("--shards",   type=int, default=1, help="Number of parallel Docker containers")
    parser.add_argument("--store",    choices=["local", "dynamo", "both"], default="local",
                        help="Where to write results (default: local)")
    parser.add_argument("--run-id",   default=None,    help="Override run ID (auto-generated if omitted)")
    parser.add_argument("--no-build", action="store_true", help="Skip Docker build step")
    parser.add_argument("--report",   action="store_true", help="Print results summary after run")
    args = parser.parse_args()

    run_id = args.run_id or f"local-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"

    print(f"\n{'='*55}")
    print(f"  LOCAL RUNNER")
    print(f"  Run ID : {run_id}")
    print(f"  Shards : {args.shards}")
    print(f"  Store  : {args.store}")
    print(f"{'='*55}\n")

    # Validate .env / credentials
    env_vars = _load_env_vars()
    if not env_vars.get("TEST_EMAIL") or not env_vars.get("TEST_PASSWORD"):
        print("[ERROR] TEST_EMAIL and TEST_PASSWORD must be set in .env or environment.")
        print("        Copy .env.example to .env and fill in your credentials.")
        sys.exit(1)

    # Build image unless skipped
    if not args.no_build:
        build_image()

    # Resolve test list
    tests = [args.test] if args.test else ALL_TESTS
    shards = partition(tests, args.shards)
    payloads = [
        {"shard_id": f"shard-{i}", "tests": shard}
        for i, shard in enumerate(shards)
    ]

    # Run shards (parallel if > 1)
    results = []
    if args.shards == 1:
        p = payloads[0]
        result = run_shard_in_docker(p["shard_id"], p["tests"], run_id, args.store)
        results.append(result)
    else:
        with ThreadPoolExecutor(max_workers=args.shards) as pool:
            futures = {
                pool.submit(run_shard_in_docker, p["shard_id"], p["tests"], run_id, args.store): p["shard_id"]
                for p in payloads
            }
            for future in as_completed(futures):
                shard_id = futures[future]
                try:
                    results.append(future.result())
                except Exception as exc:
                    print(f"[FAIL] {shard_id}: {exc}")
                    results.append({"shard_id": shard_id, "_exception": str(exc)})

    # Write local summary if applicable
    if args.store in ("local", "both"):
        summary = write_local_summary(run_id, results)

    # Print report if requested
    if args.report:
        if args.store in ("local", "both"):
            print_local_report(run_id)
        if args.store in ("dynamo", "both"):
            print_dynamo_report(run_id)

    # Exit non-zero if failures (mirrors CI behaviour)
    total_failed = sum(r.get("summary", {}).get("failed", 0) for r in results)
    total_errors = sum(r.get("summary", {}).get("errors", 0) for r in results)
    if total_failed > 0 or total_errors > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
