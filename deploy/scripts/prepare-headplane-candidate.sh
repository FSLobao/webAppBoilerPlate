#!/usr/bin/env bash
set -Eeuo pipefail

# Prepares a safe candidate staging directory with template configuration and a 32-hex cookie secret.
# Arguments:
#   $1 - candidate_dir (optional, defaults to creating a secure directory in /tmp)
#   $2 - template_file (optional, defaults to deploy/gateway/v1/config/headplane.yaml)
# Global state read: none.
# Global state changed: creates staging directory and files.
# Output streams: prints staging directory path to stdout; instructions to stderr.
# Return status: 0 on success, nonzero on error.
prepare_candidate() {
  local candidate_dir=${1:-}
  local template_file=${2:-"deploy/gateway/v1/config/headplane.yaml"}

  if [[ ! -f "${template_file}" || ! -r "${template_file}" ]]; then
    printf 'Template configuration file not found or not readable: %s\n' "${template_file}" >&2
    return 1
  fi

  if ! command -v openssl >/dev/null 2>&1; then
    printf 'Required command openssl not found in PATH.\n' >&2
    return 1
  fi

  if [[ -z "${candidate_dir}" ]]; then
    candidate_dir=$(mktemp -d --tmpdir=/tmp gateway-headplane.XXXXXX)
  else
    if [[ ! -d "${candidate_dir}" ]]; then
      mkdir -p -- "${candidate_dir}"
    fi
  fi
  chmod 0700 -- "${candidate_dir}"

  local candidate_config="${candidate_dir}/headplane.yaml"
  local candidate_secret="${candidate_dir}/headplane-cookie-secret"

  cp -- "${template_file}" "${candidate_config}"
  chmod 0600 -- "${candidate_config}"

  local candidate_cookie_secret
  candidate_cookie_secret=$(openssl rand -hex 16)
  if [[ ! "${candidate_cookie_secret}" =~ ^[[:xdigit:]]{32}$ ]]; then
    printf 'Generated Headplane cookie secret is not 32 hexadecimal characters.\n' >&2
    return 1
  fi

  printf '%s' "${candidate_cookie_secret}" > "${candidate_secret}"
  unset candidate_cookie_secret
  chmod 0444 -- "${candidate_secret}"

  printf '%s\n' "${candidate_dir}"
  printf 'Headplane candidate staged in: %s\n' "${candidate_dir}" >&2
  printf 'Edit candidate configuration before validating: %s\n' "${candidate_config}" >&2
  return 0
}
# ---------------------------------- #

# Entry point coordinating CLI execution.
# Arguments: forwarded command-line arguments.
# Global state read: none.
# Global state changed: none.
# Output streams: candidate directory to stdout, diagnostics to stderr.
# Return status: 0 on success, nonzero on error.
main() {
  if [[ $# -ge 1 && ( "$1" == "-h" || "$1" == "--help" ) ]]; then
    printf 'Usage: %s [candidate_dir] [template_file]\n' "$0"
    return 0
  fi

  if [[ $# -gt 2 ]]; then
    printf 'Usage: %s [candidate_dir] [template_file]\n' "$0" >&2
    return 1
  fi

  prepare_candidate "$@"
}
# ---------------------------------- #

main "$@"
