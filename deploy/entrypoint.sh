#!/usr/bin/env bash
set -euo pipefail
cd /app
python3 -m ops.r9700 init --root /app
python3 -m ops.r9700 schedule --root /app &
ops_pid=$!
node dist/server/entry.mjs &
web_pid=$!
cleanup() { kill "$ops_pid" "$web_pid" 2>/dev/null || true; wait || true; }
trap cleanup TERM INT EXIT
wait -n "$ops_pid" "$web_pid"
# A failed worker restarts the whole managed container instead of appearing healthy.
exit 1
