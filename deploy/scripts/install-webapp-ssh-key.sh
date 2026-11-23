#!/usr/bin/env bash
# Install one public key in the shared webapp authorized_keys file.
#
# Usage: install-webapp-ssh-key.sh --public-key-file FILE [--target-file FILE]
#
# The target defaults to /etc/webapp/secrets/authorized_keys when run as root
# and to ~/.local/share/webapp/secrets/authorized_keys for rootless Podman.
set -Eeuo pipefail

PUBLIC_KEY_FILE=""
TARGET_FILE=""

# Prints a usage summary.
# Arguments: none.
# Output streams: stdout.
# Return status: 0.
usage() {
  cat <<'EOF'
Usage: install-webapp-ssh-key.sh --public-key-file FILE [--target-file FILE]

Install one SSH public key without printing its content. Existing unrelated keys
are preserved and an identical key is not duplicated.
EOF
}
# ---------------------------------- #

# Prints an actionable error.
# Arguments: $1 - message.
# Output streams: stderr.
# Return status: 1.
fail() {
  printf 'ERROR: %s\n' "$1" >&2
  return 1
}
# ---------------------------------- #

# Parses CLI options.
# Arguments: CLI arguments.
# Global state changed: PUBLIC_KEY_FILE, TARGET_FILE.
# Output streams: diagnostics to stderr.
# Return status: 0 on success, nonzero otherwise.
parse_args() {
  while (( $# > 0 )); do
    case "$1" in
      --public-key-file)
        (( $# >= 2 )) || {
          fail "Missing value for --public-key-file."
          return 1
        }
        PUBLIC_KEY_FILE=$2
        shift 2
        ;;
      --target-file)
        (( $# >= 2 )) || {
          fail "Missing value for --target-file."
          return 1
        }
        TARGET_FILE=$2
        shift 2
        ;;
      -h|--help)
        usage
        exit 0
        ;;
      *)
        fail "Unknown argument: $1"
        return 1
        ;;
    esac
  done

  [[ -n "${PUBLIC_KEY_FILE}" ]] || {
    fail "--public-key-file is required."
    return 1
  }
  if [[ -z "${TARGET_FILE}" ]]; then
    if (( EUID == 0 )); then
      TARGET_FILE=/etc/webapp/secrets/authorized_keys
    else
      [[ -n "${HOME:-}" && "${HOME}" == /* ]] || {
        fail "HOME must be an absolute path."
        return 1
      }
      TARGET_FILE="${HOME}/.local/share/webapp/secrets/authorized_keys"
    fi
  fi
}
# ---------------------------------- #

# Validates that the input contains exactly one supported public-key line.
# Arguments: none.
# Global state read: PUBLIC_KEY_FILE.
# Output streams: diagnostics to stderr.
# Return status: 0 on success, nonzero otherwise.
validate_public_key() {
  [[ -f "${PUBLIC_KEY_FILE}" && ! -L "${PUBLIC_KEY_FILE}" ]] || {
    fail "Public key must be a regular file without a symlink: ${PUBLIC_KEY_FILE}"
    return 1
  }

  local key
  key=$(<"${PUBLIC_KEY_FILE}")
  [[ -n "${key}" && "${key}" != *$'\n'* ]] || {
    fail "Public key file must contain exactly one non-empty line."
    return 1
  }
  case "${key%% *}" in
    ssh-ed25519|ssh-rsa|ecdsa-sha2-nistp256|ecdsa-sha2-nistp384|ecdsa-sha2-nistp521|sk-ssh-ed25519@openssh.com|sk-ecdsa-sha2-nistp256@openssh.com)
      ;;
    *)
      fail "Unsupported SSH public key type."
      return 1
      ;;
  esac
  ssh-keygen -l -f "${PUBLIC_KEY_FILE}" >/dev/null 2>&1 || {
    fail "Invalid SSH public key: ${PUBLIC_KEY_FILE}"
    return 1
  }
}
# ---------------------------------- #

# Adds the validated key to the shared target without overwriting other keys.
# Arguments: none.
# Global state read: PUBLIC_KEY_FILE, TARGET_FILE.
# Output streams: progress to stdout; diagnostics to stderr.
# Return status: 0 on success, nonzero otherwise.
install_key() {
  local parent
  parent=$(dirname -- "${TARGET_FILE}") || return
  [[ ! -L "${parent}" ]] || {
    fail "Target directory must not be a symlink: ${parent}"
    return 1
  }
  install -d -m 0700 -- "${parent}" || return

  if [[ -e "${TARGET_FILE}" || -L "${TARGET_FILE}" ]]; then
    [[ -f "${TARGET_FILE}" && ! -L "${TARGET_FILE}" ]] || {
      fail "Target must be a regular file without a symlink: ${TARGET_FILE}"
      return 1
    }
  else
    install -m 0600 /dev/null "${TARGET_FILE}" || return
  fi
  chmod 0600 -- "${TARGET_FILE}" || return

  local key
  key=$(<"${PUBLIC_KEY_FILE}")
  if grep -Fqx -- "${key}" "${TARGET_FILE}"; then
    log "Key already present in ${TARGET_FILE}"
  else
    printf '%s\n' "${key}" >> "${TARGET_FILE}" || return
    log "Added key to ${TARGET_FILE}"
  fi
}
# ---------------------------------- #

# Prints a progress line.
# Arguments: $1 - message.
# Output streams: stdout.
# Return status: 0.
log() {
  printf '==> %s\n' "$1"
}
# ---------------------------------- #

# Coordinates validation and installation.
# Arguments: CLI arguments.
# Output streams: progress to stdout; diagnostics to stderr.
# Return status: 0 on success, nonzero otherwise.
main() {
  local command_name
  for command_name in chmod dirname grep install ssh-keygen; do
    command -v "${command_name}" >/dev/null || {
      fail "Missing command: ${command_name}"
      return 1
    }
  done
  parse_args "$@" || return
  validate_public_key || return
  install_key
}
# ---------------------------------- #

main "$@"
