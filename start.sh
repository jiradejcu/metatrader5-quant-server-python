set -e

# Build before stopping anything, so the running bots keep trading while the
# images build. They only stop between `down` and `up`.
. ./script/traefik_network.sh
docker compose build
./script/migrate_redis_volume.sh
. ./stop.sh
docker compose up -d
