#!/usr/bin/env bash
set -Eeuo pipefail

staged_file=""

# Cleans up temporary staged file if it still exists.
# Arguments: none.
# Global state read: staged_file.
# Global state changed: removes staged_file.
# Output streams: none.
# Return status: 0.
cleanup_staged_file() {
  [[ -n "${staged_file:-}" ]] && rm -f -- "${staged_file}"
}
# ---------------------------------- #

# Safely and atomically installs a file into a destination path without overwriting.
# Arguments:
#   $1 - source_path (file path, or "-" to read from standard input)
#   $2 - target_path (absolute destination file path)
#   $3 - file_mode (octal file permissions, e.g. 0644, 0600)
#   $4 - file_owner (target owner user name or numeric UID)
#   $5 - file_group (target owner group name or numeric GID)
# Global state read: none.
# Global state changed: staged_file.
# Output streams: error diagnostics to stderr.
# Return status: 0 on success, nonzero on error.
install_file() {
  local source_path=${1:-}
  local target_path=${2:-}
  local file_mode=${3:-}
  local file_owner=${4:-}
  local file_group=${5:-}

  if [[ -z "${source_path}" || -z "${target_path}" || -z "${file_mode}" || -z "${file_owner}" || -z "${file_group}" ]]; then
    printf 'Usage: %s <source_path|-> <target_path> <mode> <owner> <group>\n' "$0" >&2
    return 1
  fi

  if [[ -e "${target_path}" || -L "${target_path}" ]]; then
    printf 'Refusing to overwrite existing target: %s\n' "${target_path}" >&2
    return 1
  fi

  local target_directory
  target_directory=$(dirname -- "${target_path}")
  if [[ ! -d "${target_directory}" ]]; then
    printf 'Target directory does not exist: %s\n' "${target_directory}" >&2
    return 1
  fi

  staged_file=$(mktemp --tmpdir="${target_directory}" ".$(basename -- "${target_path}").XXXXXX")
  trap cleanup_staged_file EXIT INT TERM

  if [[ "${source_path}" == "-" ]]; then
    cat > "${staged_file}"
  else
    if [[ ! -f "${source_path}" || ! -r "${source_path}" ]]; then
      printf 'Source file not found or not readable: %s\n' "${source_path}" >&2
      return 1
    fi
    cat -- "${source_path}" > "${staged_file}"
  fi

  chown -- "${file_owner}:${file_group}" "${staged_file}"
  chmod -- "${file_mode}" "${staged_file}"

  mv -T --no-clobber -- "${staged_file}" "${target_path}"
  if [[ -e "${staged_file}" || -L "${staged_file}" ]]; then
    printf 'Refusing to overwrite existing target: %s\n' "${target_path}" >&2
    return 1
  fi

  staged_file=""
  trap - EXIT INT TERM
  return 0
}
# ---------------------------------- #

# Entry point coordinating CLI execution.
# Arguments: forwarded command-line arguments.
# Global state read: none.
# Global state changed: none.
# Output streams: usage/error messages to stderr.
# Return status: 0 on success, nonzero on error.
main() {
  if [[ $# -eq 1 && ( "$1" == "-h" || "$1" == "--help" ) ]]; then
    printf 'Usage: %s <source_path|-> <target_path> <mode> <owner> <group>\n' "$0"
    return 0
  fi

  if [[ $# -ne 5 ]]; then
    printf 'Usage: %s <source_path|-> <target_path> <mode> <owner> <group>\n' "$0" >&2
    return 1
  fi

  install_file "$@"
}
# ---------------------------------- #

main "$@"
