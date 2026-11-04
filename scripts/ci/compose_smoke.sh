#!/usr/bin/env bash
# End-to-end check of the compose stack with one broker:
#   scripts/ci/compose_smoke.sh <broker>     (any brokers/<broker>.env, e.g. redis)
# Starts the stack with brokers/<name>.env, places an order through orders-api and
# waits for notifier-worker to log the confirmation, then tears everything down.
set -euo pipefail

broker="${1:?usage: $0 <broker>  (one of: $(cd brokers && ls *.env | sed "s/\.env$//" | tr "\n" " "))}"
env_file="brokers/${broker}.env"
[ -f "$env_file" ] || { echo "no such broker env file: $env_file" >&2; exit 2; }
compose=(docker compose --env-file "$env_file")

cleanup() {
  status=$?
  if [ "$status" -ne 0 ]; then
    "${compose[@]}" ps -a || true
    "${compose[@]}" logs --no-color --tail 100 || true
  fi
  "${compose[@]}" down --volumes --remove-orphans >/dev/null 2>&1 || true
  exit "$status"
}
trap cleanup EXIT

"${compose[@]}" up --build --detach --wait

email="smoke-${broker}-$RANDOM@example.com"
curl --fail --silent --show-error --retry 10 --retry-connrefused --retry-delay 1 \
  -X POST localhost:8002/orders -H 'content-type: application/json' \
  -d "{\"customer_email\":\"$email\",\"items\":[{\"sku\":\"MUG-001\",\"quantity\":2}]}"
echo

for _ in $(seq 1 30); do
  if "${compose[@]}" logs notifier-worker 2>&1 | grep -q "notify to=$email"; then
    echo "OK: notifier-worker received the order over $broker"
    exit 0
  fi
  sleep 1
done
echo "FAIL: notifier-worker never logged a notification for $email" >&2
exit 1
