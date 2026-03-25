# ---------------------------------------------------------------------------
# Single-stage — the official Playwright image already has Chromium.
# No need to install or copy browsers — they ship with the base image.
# ---------------------------------------------------------------------------
FROM mcr.microsoft.com/playwright/python:v1.44.0-jammy

WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY pages/       ./pages/
COPY conftest.py  .
COPY test_login_flow.py .
COPY lambda_handler.py  .

# ---------------------------------------------------------------------------
# Lambda compatibility
# ---------------------------------------------------------------------------
# AWS Lambda requires the handler to live at /var/task when using a
# container image. We set the working directory and entry point accordingly.
# The CMD is overridden by the Lambda function configuration.

ENV PYTHONPATH=/app

CMD ["python", "-m", "pytest", "test_login_flow.py", \
     "--json-report", "--json-report-file=/tmp/results.json", \
     "-v"]
