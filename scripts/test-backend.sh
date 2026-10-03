#!/usr/bin/env bash
# =============================================================================
# scripts/test-backend.sh
# Run the backend test suite.
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
BACKEND_DIR="${REPO_ROOT}/backend"

echo "==> Running Threadback backend tests"
echo "    Directory : ${BACKEND_DIR}"
echo ""

cd "${BACKEND_DIR}"

if [ -z "${VIRTUAL_ENV:-}" ] && [ -d ".venv" ]; then
    source .venv/bin/activate
fi

pytest tests/ -v
