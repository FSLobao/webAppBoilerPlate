#!/usr/bin/env bash
set -Eeuo pipefail

enroll_container=""
enroll_authkey_path=""

# Cleans up the temporary Tailscale authkey file from the gateway container.
# Arguments: none.
# Global state read: enroll_container, enroll_authkey_path.
# Global state changed: removes authkey file inside container.
# Output streams: none.
# Return status: 0.
cleanup_authkey() {
  local exit_status=$?
  trap - EXIT INT TERM

  if [[ -n "${enroll_container}" && -n "${enroll_authkey_path}" ]]; then
    podman exec "${enroll_container}" rm -f -- "${enroll_authkey_path}" >/dev/null 2>&1 || true
  fi

  return "${exit_status}"
}
# ---------------------------------- #

# Discovers and validates a single IPv4 CIDR from the specified Podman network.
# Arguments:
#   $1 - network_name (defaults to "podman")
# Global state read: none.
# Global state changed: none.
# Output streams: prints validated IPv4 CIDR to stdout; errors to stderr.
# Return status: 0 on valid single CIDR, 1 otherwise.
discover_podman_cidr() {
  local network_name=${1:-"podman"}
  local cidr_result

  cidr_result=$(
    podman network inspect --format '{{range .Subnets}}{{.Subnet}}{{"\n"}}{{end}}' "${network_name}" 2>/dev/null |
      awk -F'[./]' '
        NF == 5 &&
        $1 ~ /^[0-9]+$/ && $2 ~ /^[0-9]+$/ &&
        $3 ~ /^[0-9]+$/ && $4 ~ /^[0-9]+$/ && $5 ~ /^[0-9]+$/ &&
        $1 <= 255 && $2 <= 255 && $3 <= 255 && $4 <= 255 &&
        $5 >= 1 && $5 <= 32 {
          count++
          cidr = $0
        }
        END {
          if (count != 1) {
            print "Expected exactly one valid IPv4 CIDR from podman network inspect; inspect network." > "/dev/stderr"
            exit 1
          }
          print cidr
        }
      '
  ) || return 1

  printf '%s\n' "${cidr_result}"
  return 0
}
# ---------------------------------- #

# Enrolls the gateway container in Headscale via tailscale up without SNAT.
# Arguments:
#   $1 - headscale_fqdn (required Headscale FQDN, e.g. vpn.example.com)
#   $2 - container_name (optional, defaults to "gateway")
#   $3 - network_name (optional, defaults to "podman")
#   $4 - authkey_path (optional, defaults to "/run/tailscale-auth/authkey")
# Global state read: none.
# Global state changed: sets enroll_container, enroll_authkey_path; runs tailscale up in container.
# Output streams: status to stdout, errors to stderr.
# Return status: 0 on success, nonzero on error.
enroll_gateway() {
  local headscale_fqdn=${1:-}
  local container_name=${2:-"gateway"}
  local network_name=${3:-"podman"}
  local authkey_path=${4:-"/run/tailscale-auth/authkey"}

  if [[ -z "${headscale_fqdn}" ]]; then
    printf 'Usage: %s <headscale_fqdn> [container_name] [network_name] [authkey_path]\n' "$0" >&2
    return 1
  fi

  if ! command -v podman >/dev/null 2>&1; then
    printf 'podman command is required but not found in PATH.\n' >&2
    return 1
  fi

  if ! podman container exists "${container_name}" 2>/dev/null; then
    printf 'Target container does not exist: %s\n' "${container_name}" >&2
    return 1
  fi

  enroll_container="${container_name}"
  enroll_authkey_path="${authkey_path}"
  trap cleanup_authkey EXIT INT TERM

  if ! podman exec "${container_name}" test -f "${authkey_path}" 2>/dev/null; then
    printf 'Tailscale authkey file not found inside container: %s\n' "${authkey_path}" >&2
    return 1
  fi

  local podman_cidr
  if ! podman_cidr=$(discover_podman_cidr "${network_name}"); then
    printf 'Failed to validate a single IPv4 Podman CIDR from network: %s\n' "${network_name}" >&2
    return 1
  fi

  printf 'Validated single IPv4 Podman CIDR: %s\n' "${podman_cidr}"

  local tailscale_args=(
    tailscale up
    "--auth-key=file:${authkey_path}"
    "--login-server=https://${headscale_fqdn}"
    "--advertise-routes=${podman_cidr}"
    --snat-subnet-routes=false
    --advertise-exit-node=false
    --exit-node=
    --accept-dns=false
    --accept-routes=false
  )

  if ! podman exec "${container_name}" "${tailscale_args[@]}"; then
    printf 'tailscale up failed inside container: %s\n' "${container_name}" >&2
    return 1
  fi

  # Explicitly trigger cleanup of the authkey
  cleanup_authkey

  printf 'Gateway container successfully enrolled.\n'
  printf 'Approve advertised routes on Headscale using:\n'
  printf '  podman exec %s headscale nodes approve-routes --identifier <NODE_ID> --routes "%s"\n' \
    "${container_name}" "${podman_cidr}"
  return 0
}
# ---------------------------------- #

# Entry point coordinating CLI execution.
# Arguments: forwarded command-line arguments.
# Global state read: none.
# Global state changed: none.
# Output streams: status to stdout, error messages to stderr.
# Return status: 0 on success, nonzero on error.
main() {
  if [[ $# -ge 1 && ( "$1" == "-h" || "$1" == "--help" ) ]]; then
    printf 'Usage: %s <headscale_fqdn> [container_name] [network_name] [authkey_path]\n' "$0"
    return 0
  fi

  if [[ $# -lt 1 || $# -gt 4 ]]; then
    printf 'Usage: %s <headscale_fqdn> [container_name] [network_name] [authkey_path]\n' "$0" >&2
    return 1
  fi

  enroll_gateway "$@"
}
# ---------------------------------- #

main "$@"
