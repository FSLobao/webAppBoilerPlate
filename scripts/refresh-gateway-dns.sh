#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

readonly SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
readonly REPO_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd -P)"
readonly GENERATED_CONFIG=/var/lib/gateway/generated/config.json
readonly DNS_DIR=/var/lib/gateway/dns
readonly DNS_HOSTS_FILE="$DNS_DIR/hosts"
readonly GATEWAY_LOCK=/run/lock/gateway-config.lock
readonly CONTAINER_NAME=gateway
STAGED_DNS=''
BACKUP_DNS=''
ROLLBACK_DNS=''
GATEWAY_LOCK_FD=''
TRANSACTION_ACTIVE=0
PRESERVE_BACKUP=0

# Report an operator-facing error and exit non-zero.
# Arguments: diagnostic. Reads no global state.
# Output: one error line to stderr.
fail() {
  printf '[gateway-dns] ERROR: %s\n' "$*" >&2
  exit 1
}
# ---------------------------------- #

# Print CLI usage.
# Arguments: none.
# Output: usage text to stdout.
usage() {
  printf 'Usage: %s --revision | --handoff REQUEST.json\n' "${0##*/}"
}
# ---------------------------------- #

# Run the shared Gateway DNS module on the host.
# Arguments: module arguments. Reads REPO_ROOT.
# Output: module stdout and stderr; returns its status.
run_dns_module() {
  PYTHONPATH="$REPO_ROOT${PYTHONPATH:+:$PYTHONPATH}" \
    python3 "$REPO_ROOT/gateway/development/dns_refresh.py" "$@"
}
# ---------------------------------- #

# Require root-owned generated state and a bounded, protected handoff request.
# Arguments: readiness request path. Reads host ownership and mode metadata.
# Output: none. Returns nonzero when the request is unsafe.
validate_request_file() {
  local request=$1 mode owner size

  [[ -f "$request" && ! -L "$request" && -r "$request" ]] || \
    fail "Readiness request is missing or unsafe: $request"
  owner=$(stat -c %u "$request")
  mode=$(stat -c %a "$request")
  size=$(stat -c %s "$request")
  [[ "$owner" == 0 ]] || fail 'Readiness request must be owned by root.'
  (( (8#$mode & 0077) == 0 )) || fail 'Readiness request must have private permissions (for example, 0600).'
  (( size <= 16384 )) || fail 'Readiness request exceeds 16 KiB.'
}
# ---------------------------------- #

# Restore only prior records still present in the published candidate.
# Arguments: none. Reads BACKUP_DNS, DNS_HOSTS_FILE, and CONTAINER_NAME.
# Output: rollback diagnostics to stderr; returns nonzero if restore or reload fails.
restore_previous_hosts() {
  [[ -n "$BACKUP_DNS" && -f "$BACKUP_DNS" && ! -L "$BACKUP_DNS" ]] || {
    printf '[gateway-dns] ERROR: rollback backup is missing or unsafe.\n' >&2
    return 1
  }
  ROLLBACK_DNS=$(mktemp "$DNS_DIR/.hosts-recovery.XXXXXX") || return 1
  if ! awk '
    NR == FNR {
      if (NF >= 2 && $1 !~ /^#/) {
        current[$1 " " $2] = 1
      }
      next
    }
    NF == 0 || $1 ~ /^#/ {
      print
      next
    }
    NF >= 2 && (($1 " " $2) in current) {
      print $1, $2
    }
  ' "$DNS_HOSTS_FILE" "$BACKUP_DNS" > "$ROLLBACK_DNS"; then
    printf '[gateway-dns] ERROR: could not filter prior DNS hosts safely.\n' >&2
    return 1
  fi
  chmod 0644 "$ROLLBACK_DNS" || return 1
  mv -f -- "$ROLLBACK_DNS" "$DNS_HOSTS_FILE" || return 1
  ROLLBACK_DNS=''
  if ! podman exec "$CONTAINER_NAME" pkill -HUP dnsmasq; then
    printf '[gateway-dns] ERROR: prior safe DNS hosts were restored but DNSMasq reload failed.\n' >&2
    return 1
  fi
  TRANSACTION_ACTIVE=0
  if ! rm -f -- "$BACKUP_DNS"; then
    PRESERVE_BACKUP=1
    printf '[gateway-dns] WARNING: rollback completed; backup remains at %s.\n' \
      "$BACKUP_DNS" >&2
  else
    BACKUP_DNS=''
  fi
}
# ---------------------------------- #

# Print revision from the active generated Gateway configuration.
# Arguments: none. Reads GENERATED_CONFIG.
# Output: canonical SHA-256 revision on stdout.
print_revision() {
  [[ -f "$GENERATED_CONFIG" && ! -L "$GENERATED_CONFIG" ]] || \
    fail 'Gateway has no generated host configuration; apply Gateway first.'
  [[ "$(stat -c %u "$GENERATED_CONFIG")" == 0 ]] || \
    fail 'Gateway generated host configuration must be owned by root.'
  run_dns_module revision "$GENERATED_CONFIG"
}
# ---------------------------------- #

# Atomically publish one validated readiness-scoped candidate and signal DNSMasq.
# Arguments: readiness request path. Reads generated configuration and current hosts.
# Output: status only; does not inspect, start, or stop application containers.
refresh_dns() {
  local request=$1 request_revision active_revision candidate current_revision
  local dnsmasq_candidate dns_mode config_mode hosts_mode

  [[ "$EUID" -eq 0 ]] || fail 'Run the DNS readiness handoff as root.'
  validate_request_file "$request"
  [[ -f "$GENERATED_CONFIG" && ! -L "$GENERATED_CONFIG" ]] || \
    fail 'Gateway has no generated host configuration; apply Gateway first.'
  [[ -f "$DNS_HOSTS_FILE" && ! -L "$DNS_HOSTS_FILE" ]] || \
    fail 'Gateway generated DNS hosts file is missing or unsafe.'
  [[ -d "$DNS_DIR" && ! -L "$DNS_DIR" && "$(stat -c %u "$DNS_DIR")" == 0 ]] || \
    fail 'Gateway DNS directory must be a root-owned real directory.'
  [[ "$(stat -c %u "$GENERATED_CONFIG")" == 0 && \
    "$(stat -c %u "$DNS_HOSTS_FILE")" == 0 ]] || \
    fail 'Gateway generated configuration and DNS hosts must be owned by root.'
  dns_mode=$(stat -c %a "$DNS_DIR")
  config_mode=$(stat -c %a "$GENERATED_CONFIG")
  hosts_mode=$(stat -c %a "$DNS_HOSTS_FILE")
  (( (8#$dns_mode & 0022) == 0 && (8#$config_mode & 0022) == 0 && \
    (8#$hosts_mode & 0022) == 0 )) || \
    fail 'Gateway generated DNS state must not be group/world writable.'
  command -v flock >/dev/null 2>&1 || fail 'flock is required to serialize Gateway configuration changes.'
  command -v podman >/dev/null 2>&1 || fail 'Podman is required for the Gateway DNS handoff.'
  [[ -d /run/lock && ! -L /run/lock && "$(stat -c %u /run/lock)" == 0 ]] || \
    fail 'The host lock directory must be root-owned and safe.'
  [[ ! -L "$GATEWAY_LOCK" ]] || fail 'Gateway configuration lock must not be a symlink.'

  exec {GATEWAY_LOCK_FD}>"$GATEWAY_LOCK"
  flock -x "$GATEWAY_LOCK_FD" || fail 'Could not lock Gateway configuration for DNS refresh.'
  request_revision=$(run_dns_module request-revision "$request") || \
    fail 'Readiness request is invalid.'
  active_revision=$(print_revision) || fail 'Could not calculate active Gateway configuration revision.'
  [[ "$request_revision" == "$active_revision" ]] || \
    fail 'Readiness request uses a stale Gateway configuration revision.'

  [[ "$(podman inspect --format '{{.State.Running}}' "$CONTAINER_NAME")" == true ]] || \
    fail 'Existing Gateway container is not running.'
  candidate=$(podman exec --interactive "$CONTAINER_NAME" \
    python3 /usr/local/lib/gateway/dns_refresh.py handoff \
    --config /etc/gateway/generated/config.json \
    --hosts /run/gateway/dns/hosts < "$request") || \
    fail 'Gateway rejected the readiness handoff or target inspection.'

  current_revision=$(print_revision) || fail 'Could not recheck active Gateway configuration revision.'
  [[ "$current_revision" == "$request_revision" ]] || \
    fail 'Gateway configuration changed during DNS refresh.'

  STAGED_DNS=$(mktemp "$DNS_DIR/.hosts.XXXXXX")
  chmod 0644 "$STAGED_DNS"
  printf '%s\n' "$candidate" > "$STAGED_DNS"
  dnsmasq_candidate="/run/gateway/dns/$(basename -- "$STAGED_DNS")"
  podman exec "$CONTAINER_NAME" dnsmasq --test --no-resolv --no-hosts \
    --bind-dynamic --addn-hosts="$dnsmasq_candidate" >/dev/null || \
    fail 'Candidate DNS records failed DNSMasq validation.'
  BACKUP_DNS=$(mktemp "$DNS_DIR/.hosts-rollback.XXXXXX")
  cp -p -- "$DNS_HOSTS_FILE" "$BACKUP_DNS"
  TRANSACTION_ACTIVE=1
  mv -f -- "$STAGED_DNS" "$DNS_HOSTS_FILE"
  STAGED_DNS=''
  if ! podman exec "$CONTAINER_NAME" pkill -HUP dnsmasq; then
    fail 'DNSMasq reload failed; transaction trap will restore safe prior DNS hosts.'
  fi
  TRANSACTION_ACTIVE=0
  if ! rm -f -- "$BACKUP_DNS"; then
    PRESERVE_BACKUP=1
    fail "DNS refresh succeeded but rollback backup remains at $BACKUP_DNS."
  fi
  BACKUP_DNS=''
  printf '[gateway-dns] Readiness-scoped DNS records refreshed.\n'
}
# ---------------------------------- #

# Parse the explicit revision or handoff command.
# Arguments: --revision, or --handoff REQUEST. Reads command-line arguments.
# Output: revision or refresh status.
main() {
  if [[ "${1:-}" == --help || "${1:-}" == -h ]]; then
    [[ $# == 1 ]] || fail 'Help accepts no extra arguments.'
    usage
    return 0
  fi
  [[ "$EUID" -eq 0 ]] || fail 'Run this root-controlled Gateway command as root.'
  case "${1:-}" in
    --revision)
      [[ $# == 1 ]] || fail 'Use --help for command usage.'
      print_revision
      ;;
    --handoff)
      [[ $# == 2 ]] || fail 'Use --help for command usage.'
      refresh_dns "$2"
      ;;
    *)
      fail 'Unknown command; use --help for command usage.'
      ;;
  esac
}
# ---------------------------------- #

# Exit through transaction cleanup after an unhandled command error.
# Arguments: triggering command status. Reads no global state.
# Output: none.
handle_error() {
  local status=$1
  exit "$status"
}
# ---------------------------------- #

# Exit through the transaction-aware cleanup path on a termination signal.
# Arguments: signal exit status. Reads no global state.
# Output: none.
handle_signal() {
  local status=$1
  exit "$status"
}
# ---------------------------------- #

# Clean temporary files and roll back incomplete publication while retaining the lock.
# Arguments: none. Reads transaction globals and preserves the triggering status.
# Output: rollback diagnostics to stderr; exits with original status.
cleanup() {
  local status=$?
  trap - EXIT ERR INT TERM
  if (( TRANSACTION_ACTIVE )); then
    if cmp -s -- "$DNS_HOSTS_FILE" "$BACKUP_DNS"; then
      TRANSACTION_ACTIVE=0
    elif ! restore_previous_hosts; then
      PRESERVE_BACKUP=1
      printf '[gateway-dns] ERROR: rollback failed; backup preserved at %s. ' \
        "$BACKUP_DNS" >&2
      printf 'Verify target readiness before any manual recovery.\n' >&2
    fi
  fi
  [[ -z "$STAGED_DNS" ]] || rm -f -- "$STAGED_DNS"
  [[ -z "$ROLLBACK_DNS" ]] || rm -f -- "$ROLLBACK_DNS"
  if [[ -n "$BACKUP_DNS" ]] && (( ! PRESERVE_BACKUP )); then
    rm -f -- "$BACKUP_DNS"
  fi
  exit "$status"
}
# ---------------------------------- #

trap 'cleanup' EXIT
trap 'handle_error "$?"' ERR
trap 'handle_signal 130' INT
trap 'handle_signal 143' TERM
main "$@"
