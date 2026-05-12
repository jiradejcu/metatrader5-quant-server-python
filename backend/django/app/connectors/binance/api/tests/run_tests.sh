#!/usr/bin/env bash
# Run from repo root. All commands execute inside the django container.

CONTAINER="django"
WORKDIR="/app"
BASE="app/connectors/binance/api/tests"

# ---------------------------------------------------------------------------
# Unit tests (mocked SDK — no real API calls)
# ---------------------------------------------------------------------------

docker exec -w $WORKDIR $CONTAINER \
  python -m pytest $BASE/test_order.py -v

# ---------------------------------------------------------------------------
# Integration tests (real Binance API — requires API_KEY_BINANCE in env)
# Separate docker exec so unit-test SDK stubs don't leak into this process.
# ---------------------------------------------------------------------------

docker exec -w $WORKDIR $CONTAINER \
  python -m pytest $BASE/test_order_integration.py -v -s
