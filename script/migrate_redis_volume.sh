#!/bin/sh
# One-time move of redis data from its old anonymous volume into the named
# volume `redis-data`. The anonymous volume isn't reused after `down`, so
# without this the bots' flags and settings would be lost. Safe to run again:
# it does nothing once the named volume exists.
set -eu
cd "$(dirname "$0")/.."
PROJECT=${COMPOSE_PROJECT_NAME:-$(basename "$PWD")}
NEW="${PROJECT}_redis-data"

if docker volume inspect "$NEW" >/dev/null 2>&1; then
    exit 0
fi
OLD=$(docker inspect -f '{{range .Mounts}}{{if eq .Destination "/data"}}{{.Name}}{{end}}{{end}}' redis 2>/dev/null || true)
if [ -z "$OLD" ] || [ "$OLD" = "$NEW" ]; then
    exit 0
fi

echo "Copying redis data from volume $OLD to $NEW"
# Redis only has a password on some hosts (dev sets one in the override), so
# try without it first.
out=$(docker exec redis redis-cli SAVE 2>&1 || true)
if [ "$out" != OK ]; then
    REDIS_PASSWORD=$(sed -n 's/^REDIS_PASSWORD=//p' .env 2>/dev/null | tr -d '"' || true)
    out=$(docker exec -e REDISCLI_AUTH="$REDIS_PASSWORD" redis redis-cli SAVE 2>&1 || true)
fi
if [ "$out" != OK ]; then
    echo "redis SAVE failed, not migrating: $out" >&2
    exit 1
fi
docker volume create \
    --label com.docker.compose.project="$PROJECT" \
    --label com.docker.compose.volume=redis-data \
    "$NEW" >/dev/null
docker run --rm -v "$OLD":/from:ro -v "$NEW":/to alpine cp -a /from/. /to/
