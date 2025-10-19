export PASSWORD="72eZA1MY7zEh"
export TRAEFIK_HASHED_PASSWORD=$(openssl passwd -apr1 $PASSWORD)
docker network inspect traefik-public >/dev/null 2>&1 || docker network create traefik-public