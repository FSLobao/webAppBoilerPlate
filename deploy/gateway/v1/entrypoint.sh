#!/usr/bin/env bash
set -Eeuo pipefail

declare -A running_services=()

# Starts one named service and records its process ID for restart and shutdown handling.
# Arguments: service name. Reads the fixed service commands below; writes service logs to container streams.
start_service() {
  local service_name=$1
  local service_pid

  case "${service_name}" in
    headscale)
      setpriv --reuid=headscale --regid=headscale --clear-groups -- \
        /usr/local/bin/headscale serve &
      ;;
    tailscaled)
      /usr/local/bin/tailscaled \
        --state=/var/lib/tailscale/tailscaled.state \
        --socket=/run/tailscale/tailscaled.sock \
        --tun=tailscale0 &
      ;;
    nginx)
      /usr/sbin/nginx -g 'daemon off;' -c /etc/nginx/nginx.conf &
      ;;
    headplane)
      setpriv --reuid=headplane --regid=headplane --clear-groups -- \
        /nodejs/bin/node /app/build/server/index.js &
      ;;
    *)
      printf 'Unknown Gateway service: %s\n' "${service_name}" >&2
      return 2
      ;;
  esac

  service_pid=$!
  running_services["${service_pid}"]=${service_name}
  printf '%s\n' "${service_pid}" > "/run/gateway/${service_name}.pid"
}
# ---------------------------------- #

# Stops child processes while preserving the original exit status.
# Arguments: none. Reads running_services; sends TERM and waits; writes no normal output.
stop_services() {
  local exit_status=$?
  local service_pid
  local service_name

  trap - EXIT INT TERM
  for service_pid in "${!running_services[@]}"; do
    kill -TERM "${service_pid}" 2>/dev/null || :
  done
  for service_pid in "${!running_services[@]}"; do
    wait "${service_pid}" 2>/dev/null || :
  done
  for service_pid in "${!running_services[@]}"; do
    service_name=${running_services["${service_pid}"]}
    rm -f -- "/run/gateway/${service_name}.pid"
  done
  exit "${exit_status}"
}
# ---------------------------------- #

trap stop_services EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

install -d -m 0755 /run/gateway /run/tailscale
/usr/local/bin/headscale configtest
/usr/sbin/nginx -t -c /etc/nginx/nginx.conf

start_service headscale
start_service tailscaled
start_service nginx
start_service headplane

while true; do
  finished_pid=
  if wait -n -p finished_pid "${!running_services[@]}"; then
    exit_status=0
  else
    exit_status=$?
  fi

  [[ -n "${finished_pid}" ]] || continue
  service_name=${running_services["${finished_pid}"]}
  unset 'running_services[$finished_pid]'
  rm -f -- "/run/gateway/${service_name}.pid"
  printf 'Gateway service %s exited with status %s; restarting it.\n' \
    "${service_name}" "${exit_status}" >&2
  sleep 2
  start_service "${service_name}"
done