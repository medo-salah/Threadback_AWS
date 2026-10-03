#!/usr/bin/env bash
# =============================================================================
# scripts/dev-backend.sh
# Start the Threadback backend in development mode with hot-reload.
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
BACKEND_DIR="${REPO_ROOT}/backend"

echo "==> Starting Threadback backend (development)"
echo "    Directory : ${BACKEND_DIR}"
echo "    Endpoint  : http://localhost:8000"
echo "    Docs      : http://localhost:8000/docs"
echo ""

cd "${BACKEND_DIR}"

# Activate venv if it exists and is not already active
if [ -z "${VIRTUAL_ENV:-}" ] && [ -d ".venv" ]; then
    source .venv/bin/activate
fi

uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
