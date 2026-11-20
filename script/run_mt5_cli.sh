#!/usr/bin/env bash
# Run a command of backend/mt5/app/cli.py on a server's mt5 container,
# and download any files it writes into ./logs/<ssh-host>_<file>.
#
# Usage: script/run_mt5_cli.sh <ssh-host> <command> [args...]
#   script/run_mt5_cli.sh BabyCoinDigitalOcean1 account
#   script/run_mt5_cli.sh BabyCoinDigitalOcean1 positions
#   script/run_mt5_cli.sh BabyCoinDigitalOcean1 export-history [--from 2026-11-01] [--to 2026-11-20]
#   script/run_mt5_cli.sh BabyCoinDigitalOcean1 --help
set -euo pipefail

host="${1:?usage: $0 <ssh-host> <command> [args...]}"
shift
cli_args=$(printf '%q ' "$@")   # quoted so they survive the trip over ssh
logs_dir="$(cd "$(dirname "$0")/.." && pwd)/logs"

run_id="run.$$.$RANDOM"
container_out="/config/cli/out/$run_id"   # where cli.py writes files, inside the container
server_tmp="/tmp/mt5-cli.$run_id"          # copy of those files on the server

on_server() { ssh "$host" "$*"; }

cleanup() { on_server "docker exec mt5 rm -rf $container_out; rm -rf $server_tmp"; }
trap cleanup EXIT

# 1. Run the command in the container. Its output streams straight to this terminal.
status=0
on_server "docker exec -u abc mt5 mkdir -p $container_out"
on_server "docker exec -u abc -e CLI_OUT=$container_out -e WINEDEBUG=-all mt5 \
  wine python /app/cli.py $cli_args" || status=$?

# 2. Copy any files it wrote: container -> server -> ./logs
on_server "docker cp mt5:$container_out $server_tmp"
files=$(on_server "ls -A $server_tmp")
if [ -n "$files" ]; then
  mkdir -p "$logs_dir"
  for f in $files; do
    scp -q "$host:$server_tmp/$f" "$logs_dir/${host}_$f"
    echo "saved logs/${host}_$f"
  done
fi

exit "$status"
