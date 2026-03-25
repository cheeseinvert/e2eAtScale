#!/bin/bash
# ---------------------------------------------------------------------------
# serve.sh — start the local test target app
# Usage: ./serve.sh [port]
# Default port: 8000
# ---------------------------------------------------------------------------

PORT=${1:-8000}

# Check if port is already in use
if lsof -ti tcp:$PORT > /dev/null 2>&1; then
  echo "⚠️  Port $PORT is already in use."
  echo "   Kill it with: lsof -ti tcp:$PORT | xargs kill -9"
  echo "   Or specify a different port: ./serve.sh 8080"
  exit 1
fi

echo "🚀  Serving e2eAtScale test target"
echo "   URL  : http://localhost:$PORT"
echo "   Press Ctrl+C to stop"
echo ""

# Open browser after a short delay to let the server start
(sleep 0.5 && open "http://localhost:$PORT") &

# Start the server
python3 -m http.server $PORT
