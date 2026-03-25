"""
reporter.py
-----------
Queries DynamoDB for all test results belonging to a given run_id and
prints a formatted summary to stdout.

Usage:
    python reporter.py --run-id run-20240601-120000-abc123
    python reporter.py --run-id run-20240601-120000-abc123 --failures-only
"""

import argparse
import boto3
from boto3.dynamodb.conditions import Key
from collections import defaultdict


DYNAMODB_TABLE = "playwright-test-results"


def fetch_results(table, run_id: str) -> list[dict]:
    """Page through all DynamoDB results for the given run_id."""
    items = []
    kwargs = {
        "KeyConditionExpression": Key("run_id").eq(run_id)
    }

    while True:
        resp = table.query(**kwargs)
        items.extend(resp["Items"])
        # DynamoDB paginates at 1MB — follow the cursor if needed
        if "LastEvaluatedKey" not in resp:
            break
        kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]

    return items


def render_report(items: list[dict], failures_only: bool = False):
    if not items:
        print("No results found for this run_id.")
        return

    # Group by shard for a structured view
    by_shard = defaultdict(list)
    for item in items:
        by_shard[item["shard_id"]].append(item)

    total = passed = failed = errored = 0

    for shard_id in sorted(by_shard):
        shard_items = sorted(by_shard[shard_id], key=lambda x: x["test_id"])

        print(f"\n  ┌─ {shard_id} ({len(shard_items)} tests)")
        for item in shard_items:
            outcome  = item["outcome"]
            test_id  = item["test_id"].split("::")[-1]   # Short name only
            duration = float(item.get("duration_s", 0))

            total += 1
            if outcome == "passed":
                passed += 1
            elif outcome == "failed":
                failed += 1
            else:
                errored += 1

            if failures_only and outcome == "passed":
                continue

            icon = {"passed": "✓", "failed": "✗", "error": "!"}.get(outcome, "?")
            print(f"  │   {icon}  {test_id:<55}  {duration:.2f}s")

            if outcome in ("failed", "error") and item.get("longrepr"):
                # Print first 3 lines of the traceback for quick triage
                lines = item["longrepr"].strip().splitlines()
                for line in lines[:3]:
                    print(f"  │       {line}")
                if len(lines) > 3:
                    print(f"  │       … ({len(lines) - 3} more lines)")

        print(f"  └─────")

    # ------------------------------------------------------------------
    # Summary footer
    # ------------------------------------------------------------------
    print(f"""
  ╔══════════════════════════════╗
  ║  TOTAL   {total:>3}  passed {passed:>3}  failed {failed:>3}  errors {errored:>3}  ║
  ╚══════════════════════════════╝
""")


def main():
    parser = argparse.ArgumentParser(description="Fetch and display test run results from DynamoDB")
    parser.add_argument("--run-id",       required=True,        help="The run_id to report on")
    parser.add_argument("--failures-only", action="store_true", help="Only show failed/errored tests")
    parser.add_argument("--region",        default="us-east-1", help="AWS region")
    args = parser.parse_args()

    dynamodb = boto3.resource("dynamodb", region_name=args.region)
    table    = dynamodb.Table(DYNAMODB_TABLE)

    print(f"\n  Report for run_id: {args.run_id}")
    print(f"  Table: {DYNAMODB_TABLE}")
    print(f"  {'(failures only)' if args.failures_only else ''}")

    items = fetch_results(table, args.run_id)
    render_report(items, failures_only=args.failures_only)


if __name__ == "__main__":
    main()
