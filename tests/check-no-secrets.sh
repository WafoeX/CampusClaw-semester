#!/bin/sh
set -eu

if grep -R -E 'SESSION_HMAC_KEY|DEMO_[A-Z_]*_PASSWORD|postgresql(\+psycopg)?://' frontend/dist >/dev/null 2>&1; then
  echo "server-only configuration leaked into frontend/dist" >&2
  exit 1
fi

echo "frontend bundle contains no known server-only configuration markers"
