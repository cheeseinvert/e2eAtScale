# e2eAtScale

End-to-end UI test automation at scale — Playwright + Python, containerised with Docker, deployed to AWS Lambda, orchestrated in parallel, and reported through DynamoDB. Triggered on every git commit via a Jenkins pipeline.

---

## Architecture

```
Git Commit
    │
    ▼
Jenkins Pipeline
    │
    ├── Build & push Docker image → AWS ECR
    │
    ├── Invoke N Lambda shards in parallel (orchestrator.py)
    │       │
    │       ├── Lambda shard-0 → pytest → DynamoDB
    │       ├── Lambda shard-1 → pytest → DynamoDB
    │       ├── Lambda shard-2 → pytest → DynamoDB
    │       └── Lambda shard-N → pytest → DynamoDB
    │
    ├── reporter.py → query DynamoDB → consolidated results
    │
    └── Gate: pass or fail the build
```

Each Lambda invocation runs an isolated subset of tests inside the same Docker container that was built and pushed earlier in the pipeline. Results are written to DynamoDB keyed by `run_id`, making the full run queryable as a single operation regardless of how many shards ran.

---

## Project Structure

```
e2eAtScale/
├── pages/
│   ├── base_page.py        # Shared Playwright wrappers (navigate, fill, click, wait)
│   ├── login_page.py       # Login screen POM — selectors + idempotent login logic
│   └── dashboard_page.py   # Post-login POM — interactions, logout
├── conftest.py             # pytest fixtures — browser lifecycle, credentials
├── test_login_flow.py      # Test suite — login, interaction, logout, error handling
├── lambda_handler.py       # AWS Lambda entry point — runs pytest, writes to DynamoDB
├── orchestrator.py         # Fans out N Lambda invocations in parallel
├── reporter.py             # Queries DynamoDB, renders consolidated run report
├── local_runner.py         # Run the suite locally in Docker (mirrors Lambda exactly)
├── push_to_ecr.py          # boto3 script — build image and push to AWS ECR
├── Dockerfile              # Multi-stage Playwright + Python image
├── Jenkinsfile             # Declarative CI/CD pipeline
├── requirements.txt        # Pinned Python dependencies
└── .env.example            # Credential template for local development
```

---

## Key Design Decisions

**Page Object Model** — Selectors live in page classes, never in test files. A DOM change requires one update in one place.

**Idempotent login** — `LoginPage.login()` checks whether the session is already authenticated before attempting the login flow. In a parallel execution environment where test setup order is non-deterministic, this prevents false failures caused by surviving session cookies.

**Isolated browser contexts** — Each test receives a function-scoped `BrowserContext` with fresh cookies and local storage. A session-scoped `Browser` instance is shared for fast startup. Tests cannot bleed state into one another.

**subprocess over pytest.main()** — The Lambda handler invokes pytest as a subprocess rather than calling `pytest.main()`. This prevents pytest's global state from persisting across invocations on a warm Lambda container.

**DynamoDB composite key** — Results are stored with `run_id` as the partition key and `test_id` as the sort key. The entire result set for any run is retrievable with a single query — no scatter-gather across shards.

**Local/Lambda parity** — `local_runner.py` builds and runs the same Docker image locally that Lambda runs in production. There is no separate local execution path.

---

## Prerequisites

- Python 3.11+
- Docker
- AWS CLI configured (`aws configure`)
- An AWS account with ECR, Lambda, and DynamoDB access
- A DynamoDB table named `playwright-test-results` with `run_id` (String) as partition key and `test_id` (String) as sort key

---

## Local Development

### 1. Install Python dependencies

```bash
pip install -r requirements.txt
playwright install chromium
```

### 2. Configure credentials

```bash
cp .env.example .env
# Edit .env — fill in TEST_EMAIL and TEST_PASSWORD
```

### 3. Run locally in Docker

```bash
# Run all tests — results written to ./local_results/
python local_runner.py

# Run a single test
python local_runner.py --test "test_login_flow.py::TestLoginFlow::test_logout"

# Run with results going to DynamoDB
python local_runner.py --store dynamo

# Run with results going to both local JSON and DynamoDB
python local_runner.py --store both --report

# Mirror the full parallel Lambda run (4 shards)
python local_runner.py --shards 4 --store both --report

# Skip Docker rebuild on subsequent runs
python local_runner.py --no-build --report
```

Results land in `./local_results/` as JSON files, one per shard plus a `summary-<run_id>.json`.

---

## AWS Deployment

### 1. Push the image to ECR

```bash
python push_to_ecr.py --repo e2e-at-scale --region us-east-1
```

This will create the ECR repository if it doesn't exist, authenticate Docker, build the image tagged with the current git SHA, and push.

### 2. Create the Lambda function

```bash
aws lambda create-function \
  --function-name e2e-test-runner \
  --package-type Image \
  --code ImageUri=<account>.dkr.ecr.us-east-1.amazonaws.com/e2e-at-scale:latest \
  --role arn:aws:iam::<account>:role/lambda-execution-role \
  --timeout 900 \
  --memory-size 2048 \
  --environment Variables="{TEST_EMAIL=<email>,TEST_PASSWORD=<password>,RESULTS_TABLE=playwright-test-results}"
```

### 3. Run the orchestrator

```bash
python orchestrator.py \
  --function e2e-test-runner \
  --shards 4 \
  --region us-east-1
```

### 4. View results

```bash
python reporter.py --run-id <run_id> --region us-east-1

# Failures only
python reporter.py --run-id <run_id> --failures-only
```

Or query DynamoDB directly:

```bash
aws dynamodb query \
  --table-name playwright-test-results \
  --key-condition-expression 'run_id = :r' \
  --expression-attribute-values '{":r": {"S": "<run_id>"}}'
```

---

## CI/CD — Jenkins

The `Jenkinsfile` defines a six-stage declarative pipeline:

| Stage | What it does |
|---|---|
| Checkout | SCM pull — git SHA becomes the image tag |
| Install Deps | `pip install requirements.txt` on the agent |
| Build & Push ECR | Calls `push_to_ecr.py` with the commit SHA tag |
| Run Tests | Calls `orchestrator.py` — N parallel Lambda shards |
| Report Results | Calls `reporter.py` — always runs, even on test failure |
| Gate | Fails the build if any tests failed — blocks merge |

**Required Jenkins setup:**
- A credentials entry named `aws-ecr-credentials` (Username/Password) with `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY`
- Docker available on the build agent
- Python 3.11+ on the build agent

Pipeline parameters (`ECR_REPO`, `LAMBDA_FUNCTION`, `AWS_REGION`, `SHARDS`) can be overridden at build time without code changes.

---

## Environment Variables

| Variable | Required | Description |
|---|---|---|
| `TEST_EMAIL` | Yes | Test account email |
| `TEST_PASSWORD` | Yes | Test account password |
| `RESULTS_TABLE` | No | DynamoDB table name (default: `playwright-test-results`) |
| `RESULTS_STORE` | No | `local`, `dynamo`, or `both` (default: `dynamo`) |
| `AWS_REGION` | No | AWS region (default: `us-east-1`) |
| `REPORT_DIR` | No | Directory for pytest JSON reports (default: `/tmp`) |

---

## Running the Tests Directly

For development without Docker:

```bash
export TEST_EMAIL=your@email.com
export TEST_PASSWORD=yourpassword

pytest test_login_flow.py -v
pytest test_login_flow.py -v --json-report --json-report-file=results.json
```

---

## Tech Stack

| Layer | Technology |
|---|---|
| Test framework | pytest + pytest-playwright + pytest-json-report |
| Browser automation | Playwright (Python, sync API) |
| Container | Docker — `mcr.microsoft.com/playwright/python:v1.44.0-jammy` |
| Image registry | AWS ECR |
| Execution | AWS Lambda (container image) |
| Parallelism | Python `ThreadPoolExecutor` |
| Results store | AWS DynamoDB |
| AWS SDK | boto3 |
| CI/CD | Jenkins (declarative pipeline) |

---

## Lambda Considerations

- **Memory**: 2048MB recommended — Chromium is memory-hungry
- **Timeout**: 900s (15 min) max — size shards so each completes well within this
- **Cold starts**: First invocation per container can take 10–15s; use provisioned concurrency for time-sensitive pipelines
- **Shared memory**: `--disable-dev-shm-usage` is set in `conftest.py` to work within Lambda's `/dev/shm` limit
- **Sandbox**: `--no-sandbox` is required — Lambda's execution environment does not support Chrome's default sandbox

---

## License

MIT
