#!/usr/bin/env bash
# Production start (B1 from the deploy-readiness report). No --reload.
# The compliance scheduler is spawned by the app itself with an absolute cwd,
# so this works from any host that installed backend/requirements.txt.
set -euo pipefail
cd "$(dirname "$0")"
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"
