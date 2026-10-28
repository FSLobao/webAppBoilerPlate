#!/usr/bin/env bash
set -Eeuo pipefail

validation_container=""
validation_image=""
validation_passed=false
validation_image_was_present=false

# Cleans up the temporary validation container and removes newly downloaded images upon failure.
# Arguments: none.
# Global state read: validation_container, validation_image, validation_passed, validation_image_was_present.
# Global state changed: removes container and optional image via podman.
# Output streams: error diagnostics to stderr.
# Return status: 0.
cleanup_validation() {
  local exit_status=$?
  trap - EXIT INT TERM

  if [[ -n "${validation_container}" ]] && podman container exists "${validation_container}" 2>/dev/null; then
    if ! podman rm --force "${validation_container}" >/dev/null 2>&1; then
      printf 'Warning: failed to remove temporary validation container: %s\n' "${validation_container}" >&2
    fi
  fi

  if [[ "${validation_passed}" != true && "${validation_image_was_present}" != true && -n "${validation_image}" ]]; then
    if podman image exists "${validation_image}" 2>/dev/null; then
      if ! podman image rm "${validation_image}" >/dev/null 2>&1; then
        printf 'Warning: failed to remove newly pulled validation image: %s\n' "${validation_image}" >&2
      fi
    fi
  fi

  return "${exit_status}"
}
# ---------------------------------- #

# Runs an isolated container to validate Headplane configuration and secret with its healthcheck.
# Arguments:
#   $1 - candidate_config (path to headplane.yaml)
#   $2 - candidate_secret (path to headplane-cookie-secret)
#   $3 - containerfile_or_image (optional, path to Containerfile or image tag)
# Global state read: none.
# Global state changed: sets validation_container, validation_image, validation_passed, validation_image_was_present.
# Output streams: status to stdout, errors/logs to stderr.
# Return status: 0 on valid config, 1 on invalid config or execution error.
validate_headplane() {
  local candidate_config=${1:-}
  local candidate_secret=${2:-}
  local image_or_containerfile=${3:-"deploy/gateway/v1/Containerfile"}

  if [[ -z "${candidate_config}" || -z "${candidate_secret}" ]]; then
    printf 'Usage: %s <candidate_config> <candidate_secret> [containerfile_or_image]\n' "$0" >&2
    return 1
  fi

  if [[ ! -f "${candidate_config}" || ! -r "${candidate_config}" ]]; then
    printf 'Candidate configuration file not found or not readable: %s\n' "${candidate_config}" >&2
    return 1
  fi

  if [[ ! -f "${candidate_secret}" || ! -r "${candidate_secret}" ]]; then
    printf 'Candidate secret file not found or not readable: %s\n' "${candidate_secret}" >&2
    return 1
  fi

  local secret_content
  secret_content=$(cat -- "${candidate_secret}")
  if [[ ! "${secret_content}" =~ ^[[:xdigit:]]{32}$ ]]; then
    printf 'Candidate secret does not contain exactly 32 hexadecimal characters.\n' >&2
    return 1
  fi
  unset secret_content

  if ! command -v podman >/dev/null 2>&1; then
    printf 'podman command is required for validation but not found in PATH.\n' >&2
    return 1
  fi

  if [[ -f "${image_or_containerfile}" ]]; then
    validation_image=$(awk '$1 == "FROM" && $3 == "AS" && $4 == "headplane" { print $2; exit }' "${image_or_containerfile}")
    if [[ -z "${validation_image}" ]]; then
      printf 'Failed to locate pinned Headplane image in Containerfile: %s\n' "${image_or_containerfile}" >&2
      return 1
    fi
  else
    validation_image="${image_or_containerfile}"
  fi

  if podman image exists "${validation_image}" 2>/dev/null; then
    validation_image_was_present=true
  fi

  local container_name
  container_name="headplane-config-check-$(openssl rand -hex 8)"
  validation_container="${container_name}"

  trap cleanup_validation EXIT INT TERM

  local run_args=(
    run
    --pull=missing
    --detach
    --name "${validation_container}"
    --network none
    --volume "${candidate_config}:/etc/headplane/config.yaml:ro"
    --volume "${candidate_secret}:/run/secrets/headplane-cookie-secret:ro"
    "--tmpfs=/var/lib/headplane:rw,size=32m,mode=1777"
    "${validation_image}"
  )

  if ! podman "${run_args[@]}" >/dev/null; then
    printf 'Failed to start temporary Headplane validation container.\n' >&2
    return 1
  fi

  local attempt
  local container_status
  for ((attempt = 1; attempt <= 20; attempt++)); do
    if podman healthcheck run "${validation_container}" >/dev/null 2>&1; then
      validation_passed=true
      break
    fi
    container_status=$(podman inspect --format '{{.State.Status}}' "${validation_container}" 2>/dev/null || echo "stopped")
    [[ "${container_status}" == "running" ]] || break
    sleep 1
  done

  if [[ "${validation_passed}" != true ]]; then
    printf 'Headplane validation failed. Container logs:\n' >&2
    podman logs "${validation_container}" >&2 || true
    return 1
  fi

  printf 'Headplane configuration and cookie secret validated successfully (healthcheck passed).\n'
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
    printf 'Usage: %s <candidate_config> <candidate_secret> [containerfile_or_image]\n' "$0"
    return 0
  fi

  if [[ $# -lt 2 || $# -gt 3 ]]; then
    printf 'Usage: %s <candidate_config> <candidate_secret> [containerfile_or_image]\n' "$0" >&2
    return 1
  fi

  validate_headplane "$@"
}
# ---------------------------------- #

main "$@"
