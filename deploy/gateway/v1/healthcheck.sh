#!/usr/bin/env bash
set -Eeuo pipefail

for service_name in headscale headplane nginx tailscaled; do
  case "${service_name}" in
    headscale)
      expected_executable=/usr/local/bin/headscale
      service_user=headscale
      ;;
    headplane)
      expected_executable=/nodejs/bin/node
      service_user=headplane
      ;;
    nginx)
      expected_executable=/usr/sbin/nginx
      service_user=root
      ;;
    tailscaled)
      expected_executable=/usr/local/bin/tailscaled
      service_user=root
      ;;
  esac

  if ! IFS= read -r service_pid < "/run/gateway/${service_name}.pid"; then
    exit 1
  fi
  [[ "${service_pid}" =~ ^[0-9]+$ ]] || exit 1
  kill -0 "${service_pid}" 2>/dev/null || exit 1

  service_executable=$(setpriv --reuid="${service_user}" --regid="${service_user}" \
    --clear-groups -- readlink -f -- "/proc/${service_pid}/exe") || exit 1
  [[ "${service_executable}" == "${expected_executable}" ]] || exit 1

  if ! IFS= read -r process_stat < "/proc/${service_pid}/stat"; then
    exit 1
  fi
  process_state=${process_stat##*) }
  process_state=${process_state%% *}
  [[ "${process_state}" != Z && "${process_state}" != X ]] || exit 1
done

exec /usr/local/bin/hp_healthcheck