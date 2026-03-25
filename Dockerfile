# ---------------------------------------------------------------------------
# Stage 1: Dependency installer
# ---------------------------------------------------------------------------
# We use the official Playwright Python image as a base — it ships with
# all system-level browser dependencies pre-installed, which avoids the
# painful apt-get dance required on a bare Ubuntu image.
FROM mcr.microsoft.com/playwright/python:v1.44.0-jammy AS builder

WORKDIR /app

# Copy and install Python dependencies first (layer caching: this layer
# only rebuilds when requirements.txt changes, not on every code change).
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright browser binaries into the image.
# --with-deps ensures all OS-level shared libraries are present.
RUN playwright install chromium --with-deps


# ---------------------------------------------------------------------------
# Stage 2: Runtime image
# ---------------------------------------------------------------------------
FROM mcr.microsoft.com/playwright/python:v1.44.0-jammy

WORKDIR /app

# Copy installed packages from builder stage
COPY --from=builder /usr/local/lib/python3.11/dist-packages /usr/local/lib/python3.11/dist-packages
COPY --from=builder /root/.cache/ms-playwright /root/.cache/ms-playwright

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

# Default entry point for local Docker runs (overridden by Lambda runtime)
CMD ["python", "-m", "pytest", "test_login_flow.py", \
     "--json-report", "--json-report-file=/tmp/results.json", \
     "-v"]
