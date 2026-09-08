#!/bin/bash
# Run from WSL host. Executes the log analysis inside the django container,
# starting a temporary one via `docker compose run` if it isn't already running.
# usage: ./analyze_log.sh quant.log.20xx-xx-xx
#    or: ./analyze_log.sh /path/to/quant.log.20xx-xx-xx (any path, only the filename is used)

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../../.." && pwd)"

LOG_ARG="$1"
if [ -z "$LOG_ARG" ]; then
    echo "usage: $0 <log_file>"
    exit 1
fi

LOG_FILENAME="$(basename "$LOG_ARG")"
LOG_VOLUME="$(grep -E '^LOG_VOLUME=' "$REPO_ROOT/.env" | cut -d '=' -f2- | tr -d '\r')"
HOST_LOG_PATH="$LOG_VOLUME/$LOG_FILENAME"

if [ ! -f "$HOST_LOG_PATH" ]; then
    echo "log file not found: $HOST_LOG_PATH"
    exit 1
fi

CONTAINER_LOG_PATH="/app/logs/$LOG_FILENAME"

cd "$REPO_ROOT"

RUN_CMD="exec django"
if [ -z "$(docker compose ps --status running --services django 2>/dev/null)" ]; then
    RUN_CMD="run --rm --no-deps django"
fi

docker compose $RUN_CMD bash -c "
    cd /app/app/utils &&
    python plots.py --price-diff '$CONTAINER_LOG_PATH' &&
    python plots.py --stale-age '$CONTAINER_LOG_PATH' &&
    python plots.py --ticker-lag '$CONTAINER_LOG_PATH' primary &&
    python plots.py --atr '$CONTAINER_LOG_PATH' &&
    python analyze_orders.py '$CONTAINER_LOG_PATH'
"
