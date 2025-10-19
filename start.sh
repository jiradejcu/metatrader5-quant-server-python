export PASSWORD="72eZA1MY7zEh"
export TRAEFIK_HASHED_PASSWORD=$(openssl passwd -apr1 $PASSWORD)
docker network create traefik-public
docker-compose down
docker-compose up -d