#!/bin/sh
set -e

# Graceful shutdown: forward SIGTERM to child process
trap 'kill -TERM $PID; wait $PID' TERM INT

MODE="${DOCFOLD_MODE:-api}"

case "$MODE" in
  api)
    echo "Starting docfold API server on port ${DOCFOLD_PORT:-8000}"
    python -m uvicorn docfold.api.app:app \
      --host "${DOCFOLD_HOST:-0.0.0.0}" \
      --port "${DOCFOLD_PORT:-8000}" \
      --log-level "${DOCFOLD_LOG_LEVEL:-info}" \
      --timeout-graceful-shutdown 30 &
    PID=$!
    wait $PID
    ;;
  worker)
    echo "Starting docfold worker"
    python -m docfold.api.workers.tasks &
    PID=$!
    wait $PID
    ;;
  *)
    echo "Unknown mode: $MODE (expected 'api' or 'worker')"
    exit 1
    ;;
esac
