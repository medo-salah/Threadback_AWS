#!/usr/bin/env bash
# =============================================================================
# scripts/dev-frontend.sh
# Start the Threadback frontend in development mode.
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
FRONTEND_DIR="${REPO_ROOT}/frontend"

echo "==> Starting Threadback frontend (development)"
echo "    Directory : ${FRONTEND_DIR}"
echo "    URL       : http://localhost:5173"
echo ""

cd "${FRONTEND_DIR}"
npm run dev
