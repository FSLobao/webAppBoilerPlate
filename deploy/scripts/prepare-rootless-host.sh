#!/usr/bin/env bash
# Prepare host settings required by the approved rootless deployment.
#
# Usage: deploy/scripts/prepare-rootless-host.sh [--check|-h|--help]
# Applies host settings by default. --check is root-only and reports state without changing anything.
# Exit codes: 0 success, 1 error, 3 SELinux reboot required.
# Steps run in order (sysctl, firewall services, SELinux config); a failure stops the run and rerunning converges.
set -Eeuo pipefail

readonly SYSCTL_FILE=/etc/sysctl.d/90-rootless-ports.conf
readonly SYSCTL_KEY=net.ipv4.ip_unprivileged_port_start
readonly SYSCTL_VALUE=443
readonly SYSCTL_SETTING="${SYSCTL_KEY}=${SYSCTL_VALUE}"
readonly SELINUX_CONFIG=/etc/selinux/config
readonly SELINUX_SETTING=SELINUX=disabled
readonly FIREWALL_UNITS=(firewalld.service nftables.service)
declare -A FIREWALL_UNIT_FOUND=()
declare -A FIREWALL_ENABLED_STATE=()
declare -A FIREWALL_ACTIVE_STATE=()
declare -A FIREWALL_NEEDS_CHANGE=()

CHECK_ONLY=false
HELP_REQUESTED=false
TEMP_FILE=""
SELINUX_CONFIG_PRESENT=false
SELINUX_CONFIG_CURRENT=absent
SELINUX_RUNTIME=""
SELINUX_RUNTIME_SOURCE=""

# Prints an error message to stderr.
# Arguments: $1 - message.
# Output streams: stderr.
# Return status: 1.
fail() {
  printf 'ERROR: %s\n' "$1" >&2
  return 1
}
# ---------------------------------- #

# Prints a progress or summary line to stdout.
# Arguments: $1 - message.
# Output streams: stdout.
# Return status: 0.
log() {
  printf '%s\n' "$1"
}
# ---------------------------------- #

# Prints command usage.
# Arguments: none.
# Output streams: stdout.
# Return status: 0.
usage() {
  printf 'Usage: %s [--check|-h|--help]\n' "${BASH_SOURCE[0]}"
  printf 'Prepare rootless host settings; default mode applies changes.\n'
  printf -- '--check is root-only and reports state without changing anything.\n'
  printf 'Exit codes: 0 success, 1 error, 3 SELinux reboot required.\n'
  printf 'Exit code 3: apply found SELinux runtime not Disabled; --check predicts reboot only when config would change.\n'
}
# ---------------------------------- #

# Parses the supported command-line options.
# Arguments: the command-line arguments.
# Global state changed: CHECK_ONLY, HELP_REQUESTED.
# Output streams: stderr on invalid arguments.
# Return status: 0 on success, 1 on invalid arguments.
parse_args() {
  case "$#" in
    0)
      CHECK_ONLY=false
      ;;
    1)
      case "$1" in
        --check)
          CHECK_ONLY=true
          ;;
        -h|--help)
          HELP_REQUESTED=true
          ;;
        *)
          fail "Unknown argument: $1"
          return 1
          ;;
      esac
      ;;
    *)
      fail "Expected no arguments, --check, or -h|--help."
      return 1
      ;;
  esac
}
# ---------------------------------- #

# Removes only the temporary file created by this script and preserves exit status.
# Arguments: none.
# Global state read: TEMP_FILE.
# Output streams: stderr if cleanup fails.
# Return status: exits with the status active when the trap ran.
cleanup_temp() {
  local exit_status=$?
  trap - EXIT
  if [[ -n "${TEMP_FILE}" && -e "${TEMP_FILE}" ]]; then
    if ! rm -f -- "${TEMP_FILE}"; then
      printf 'ERROR: Could not remove temporary file %s.\n' "${TEMP_FILE}" >&2
      exit_status=1
    fi
  fi
  exit "${exit_status}"
}
# ---------------------------------- #

# Queries and validates a firewall unit's enabled and active states.
# Arguments: $1 - systemd service unit; $2 - optional state-query context.
# Global state changed: FIREWALL_ENABLED_STATE, FIREWALL_ACTIVE_STATE.
# Output streams: stderr on failure.
# Return status: 0 on success, 1 on query or validation failure.
query_firewall_service_state() {
  local unit=$1 context=${2:-} enabled_output active_output state_status
  local enabled_state active_state
  if [[ -n "${context}" ]]; then
    context=" ${context}"
  fi

  if enabled_output=$(systemctl is-enabled "${unit}" 2>&1); then
    state_status=0
  else
    state_status=$?
  fi
  enabled_state=${enabled_output%%$'\n'*}
  case "${enabled_state}" in
    enabled|enabled-runtime|linked|linked-runtime|alias|disabled|masked|masked-runtime|static|indirect|generated|transient|bad|not-found)
      ;;
    *)
      fail "Could not verify enabled state for ${unit}${context} (status ${state_status}): ${enabled_output}"
      return 1
      ;;
  esac

  if active_output=$(systemctl is-active "${unit}" 2>&1); then
    state_status=0
  else
    state_status=$?
  fi
  active_state=${active_output%%$'\n'*}
  case "${active_state}" in
    active|activating|reloading|deactivating|inactive|failed|unknown|not-found)
      ;;
    *)
      fail "Could not verify active state for ${unit}${context} (status ${state_status}): ${active_output}"
      return 1
      ;;
  esac

  FIREWALL_ENABLED_STATE["${unit}"]=${enabled_state}
  FIREWALL_ACTIVE_STATE["${unit}"]=${active_state}
}
# ---------------------------------- #

# Lists a firewall unit and inspects its state during preflight.
# Arguments: $1 - systemd service unit.
# Global state read: FIREWALL_ENABLED_STATE, FIREWALL_ACTIVE_STATE.
# Global state changed: FIREWALL_UNIT_FOUND, FIREWALL_ENABLED_STATE, FIREWALL_ACTIVE_STATE, FIREWALL_NEEDS_CHANGE.
# Output streams: stderr on failure.
# Return status: 0 on success, 1 on query or validation failure.
inspect_firewall_service() {
  local unit=$1 unit_files awk_status enabled_state active_state needs_change=false
  FIREWALL_UNIT_FOUND["${unit}"]=false
  FIREWALL_NEEDS_CHANGE["${unit}"]=false
  if ! unit_files=$(systemctl list-unit-files --type=service --no-legend --no-pager "${unit}"); then
    fail "Could not list unit file ${unit}."
    return 1
  fi
  if awk -v unit="${unit}" '$1 == unit { found=1 } END { exit !found }' <<< "${unit_files}"; then
    FIREWALL_UNIT_FOUND["${unit}"]=true
  else
    awk_status=$?
    if (( awk_status != 1 )); then
      fail "Could not inspect systemd unit listing for ${unit}."
      return 1
    fi
    FIREWALL_ENABLED_STATE["${unit}"]=absent
    FIREWALL_ACTIVE_STATE["${unit}"]=absent
    return 0
  fi

  query_firewall_service_state "${unit}" || return
  enabled_state=${FIREWALL_ENABLED_STATE["${unit}"]}
  active_state=${FIREWALL_ACTIVE_STATE["${unit}"]}
  case "${enabled_state}" in
    enabled|enabled-runtime|linked|linked-runtime|alias) needs_change=true ;;
  esac
  case "${active_state}" in
    active|activating|reloading|deactivating) needs_change=true ;;
  esac
  FIREWALL_NEEDS_CHANGE["${unit}"]=${needs_change}
}
# ---------------------------------- #
# Verifies required commands and host paths before any changes.
# Arguments: none.
# Global state read: SYSCTL_FILE, SELINUX_CONFIG, FIREWALL_UNITS.
# Global state changed: FIREWALL_UNIT_FOUND, FIREWALL_ENABLED_STATE, FIREWALL_ACTIVE_STATE, FIREWALL_NEEDS_CHANGE, SELINUX_CONFIG_PRESENT, SELINUX_CONFIG_CURRENT, SELINUX_RUNTIME, SELINUX_RUNTIME_SOURCE.
# Output streams: stderr on failure.
# Return status: 0 when prerequisites are available, 1 otherwise.
preflight() {
  local command_name unit
  for command_name in sysctl systemctl cmp mktemp mv chmod stat rm awk grep chown; do
    if ! command -v "${command_name}" >/dev/null 2>&1; then
      fail "Missing command: ${command_name}"
      return 1
    fi
  done
  if [[ ! -d /etc/sysctl.d ]]; then
    fail "/etc/sysctl.d is missing or not a directory."
    return 1
  fi
  if [[ -e "${SYSCTL_FILE}" || -L "${SYSCTL_FILE}" ]]; then
    if [[ ! -f "${SYSCTL_FILE}" || -L "${SYSCTL_FILE}" ]]; then
      fail "${SYSCTL_FILE} must be a regular file, not a symlink."
      return 1
    fi
  fi
  if [[ -e "${SELINUX_CONFIG}" || -L "${SELINUX_CONFIG}" ]]; then
    if [[ ! -f "${SELINUX_CONFIG}" || -L "${SELINUX_CONFIG}" ]]; then
      fail "${SELINUX_CONFIG} must be a regular file, not a symlink."
      return 1
    fi
  fi
  if ! systemctl list-unit-files --type=service --no-legend --no-pager >/dev/null; then
    fail "Could not query systemd unit files."
    return 1
  fi
  for unit in "${FIREWALL_UNITS[@]}"; do
    inspect_firewall_service "${unit}" || return
  done
  inspect_selinux_config || return
  inspect_selinux_runtime || return
}
# ---------------------------------- #

# Checks whether a file contains exactly one expected line and no other content.
# Arguments: $1 - file path; $2 - expected line.
# Output streams: stderr on comparison errors.
# Return status: 0 for an exact match, 1 for different content, 2 on error.
compare_file_line() {
  local path=$1 expected=$2 compare_status
  if cmp -s <(printf '%s\n' "${expected}") "${path}"; then
    return 0
  else
    compare_status=$?
  fi
  if (( compare_status == 1 )); then
    return 1
  fi
  fail "Could not compare ${path}."
  return 2
}
# ---------------------------------- #

# Installs the sysctl setting with an atomic replacement when content differs.
# Arguments: none.
# Global state read or changed: SYSCTL_FILE, SYSCTL_SETTING, TEMP_FILE.
# Output streams: stderr on failure.
# Return status: 0 on success, 1 on failure.
write_sysctl_config() {
  if ! TEMP_FILE=$(mktemp --tmpdir=/etc/sysctl.d .90-rootless-ports.conf.XXXXXX); then
    fail "Could not create a temporary sysctl file."
    return 1
  fi
  if ! printf '%s\n' "${SYSCTL_SETTING}" > "${TEMP_FILE}"; then
    fail "Could not write ${TEMP_FILE}."
    return 1
  fi
  if ! chmod 0644 -- "${TEMP_FILE}"; then
    fail "Could not set mode 0644 on ${TEMP_FILE}."
    return 1
  fi
  if ! mv -T -- "${TEMP_FILE}" "${SYSCTL_FILE}"; then
    fail "Could not install ${SYSCTL_FILE}."
    return 1
  fi
  TEMP_FILE=""
}
# ---------------------------------- #

# Applies or reports the sysctl file and runtime value.
# Arguments: none.
# Global state read or changed: CHECK_ONLY, SYSCTL_FILE, SYSCTL_KEY, SYSCTL_VALUE, SYSCTL_SETTING, TEMP_FILE.
# Output streams: summary to stdout, diagnostics to stderr.
# Return status: 0 on success, 1 on failure.
prepare_sysctl() {
  local runtime_before file_display=file-missing file_mode=missing
  local file_changed=true mode_changed=true changed=false compare_status runtime_after
  if ! runtime_before=$(sysctl -n "${SYSCTL_KEY}"); then
    fail "Could not read ${SYSCTL_KEY}."
    return 1
  fi

  if [[ -f "${SYSCTL_FILE}" ]]; then
    local file_content
    if ! file_content=$(<"${SYSCTL_FILE}"); then
      fail "Could not read ${SYSCTL_FILE}."
      return 1
    fi
    printf -v file_display '%q' "${file_content}"
    if compare_file_line "${SYSCTL_FILE}" "${SYSCTL_SETTING}"; then
      file_changed=false
    else
      compare_status=$?
      if (( compare_status != 1 )); then
        return 1
      fi
    fi
    if ! file_mode=$(stat -c '%a' -- "${SYSCTL_FILE}"); then
      fail "Could not read mode for ${SYSCTL_FILE}."
      return 1
    fi
    if [[ "${file_mode}" == 644 ]]; then
      mode_changed=false
    fi
  fi

  if [[ "${file_changed}" == true || "${mode_changed}" == true || "${runtime_before}" != "${SYSCTL_VALUE}" ]]; then
    changed=true
  fi
  if [[ "${CHECK_ONLY}" == true ]]; then
    if [[ "${changed}" == true ]]; then
      log "Sysctl: would change (file=${file_display}, mode=${file_mode}, runtime=${runtime_before}; desired file=${SYSCTL_SETTING}, mode=0644, runtime=${SYSCTL_VALUE})."
    else
      log "Sysctl: unchanged (file=${file_display}, mode=0644, runtime=${runtime_before})."
    fi
    return 0
  fi

  if [[ "${file_changed}" == true ]]; then
    write_sysctl_config || return
  elif [[ "${mode_changed}" == true ]]; then
    if ! chmod 0644 -- "${SYSCTL_FILE}"; then
      fail "Could not set mode 0644 on ${SYSCTL_FILE}."
      return 1
    fi
  fi
  if ! sysctl -p "${SYSCTL_FILE}"; then
    fail "Could not apply ${SYSCTL_FILE}."
    return 1
  fi
  if ! runtime_after=$(sysctl -n "${SYSCTL_KEY}"); then
    fail "Could not verify ${SYSCTL_KEY}."
    return 1
  fi
  if [[ "${runtime_after}" != "${SYSCTL_VALUE}" ]]; then
    fail "${SYSCTL_KEY} is ${runtime_after}; expected ${SYSCTL_VALUE}."
    return 1
  fi
  if [[ "${changed}" == true ]]; then
    log "Sysctl: changed (file=${SYSCTL_SETTING}, mode=0644, runtime=${runtime_after}; was ${runtime_before})."
  else
    log "Sysctl: unchanged (file=${SYSCTL_SETTING}, mode=0644, runtime=${runtime_after})."
  fi
}
# ---------------------------------- #

# Reads the SELINUX setting while rejecting ambiguous duplicate entries.
# Arguments: none.
# Global state read or changed: SELINUX_CONFIG, SELINUX_CONFIG_PRESENT, SELINUX_CONFIG_CURRENT.
# Output streams: stderr on failure.
# Return status: 0 on success, 1 on failure.
inspect_selinux_config() {
  local setting_count grep_status
  SELINUX_CONFIG_PRESENT=false
  SELINUX_CONFIG_CURRENT=absent
  if [[ ! -e "${SELINUX_CONFIG}" && ! -L "${SELINUX_CONFIG}" ]]; then
    return 0
  fi
  if [[ ! -f "${SELINUX_CONFIG}" || -L "${SELINUX_CONFIG}" ]]; then
    fail "${SELINUX_CONFIG} must be a regular file, not a symlink."
    return 1
  fi
  SELINUX_CONFIG_PRESENT=true
  if setting_count=$(grep -c '^SELINUX=' "${SELINUX_CONFIG}"); then
    :
  else
    grep_status=$?
    if (( grep_status == 1 )); then
      setting_count=0
    else
      fail "Could not read SELINUX setting from ${SELINUX_CONFIG}."
      return 1
    fi
  fi
  if (( setting_count > 1 )); then
    fail "${SELINUX_CONFIG} has multiple SELINUX= lines; refusing an ambiguous edit."
    return 1
  fi
  if (( setting_count == 1 )); then
    if ! SELINUX_CONFIG_CURRENT=$(grep -m 1 '^SELINUX=' "${SELINUX_CONFIG}"); then
      fail "Could not read SELINUX setting from ${SELINUX_CONFIG}."
      return 1
    fi
  else
    SELINUX_CONFIG_CURRENT=missing
  fi
}
# ---------------------------------- #

# Reads SELinux runtime mode or verifies the disabled fallback when getenforce is absent.
# Arguments: none.
# Global state changed: SELINUX_RUNTIME, SELINUX_RUNTIME_SOURCE.
# Output streams: stderr on failure.
# Return status: 0 on success, 1 when runtime mode cannot be verified.
inspect_selinux_runtime() {
  SELINUX_RUNTIME_SOURCE=getenforce
  if command -v getenforce >/dev/null 2>&1; then
    if ! SELINUX_RUNTIME=$(getenforce); then
      fail "getenforce failed."
      return 1
    fi
    if [[ -z "${SELINUX_RUNTIME}" ]]; then
      fail "getenforce returned an empty mode."
      return 1
    fi
    return 0
  fi
  if [[ -e /sys/fs/selinux || -L /sys/fs/selinux ]]; then
    fail "getenforce is absent while /sys/fs/selinux exists; cannot verify SELinux is Disabled."
    return 1
  fi
  SELINUX_RUNTIME=Disabled
  SELINUX_RUNTIME_SOURCE='getenforce absent; /sys/fs/selinux absent'
}
# ---------------------------------- #

# Reports the firewall unit state captured during preflight.
# Arguments: $1 - systemd service unit name.
# Global state read: FIREWALL_UNIT_FOUND, FIREWALL_ENABLED_STATE, FIREWALL_ACTIVE_STATE, FIREWALL_NEEDS_CHANGE.
# Output streams: summary to stdout.
# Return status: 0 on success.
report_service() {
  local unit=$1 enabled_state active_state
  if [[ "${FIREWALL_UNIT_FOUND[${unit}]}" == false ]]; then
    log "${unit}: unchanged (unit absent)."
    return 0
  fi
  enabled_state=${FIREWALL_ENABLED_STATE["${unit}"]}
  active_state=${FIREWALL_ACTIVE_STATE["${unit}"]}
  if [[ "${FIREWALL_NEEDS_CHANGE[${unit}]}" == true ]]; then
    log "${unit}: would change (enabled=${enabled_state}, active=${active_state}; desired disabled/inactive)."
  else
    log "${unit}: unchanged (enabled=${enabled_state}, active=${active_state})."
  fi
}
# ---------------------------------- #

# Disables and stops an installed firewall service when preflight found it necessary.
# Arguments: $1 - systemd service unit name.
# Global state read: FIREWALL_UNIT_FOUND, FIREWALL_NEEDS_CHANGE.
# Output streams: stderr on failure.
# Return status: 0 on success, 1 on action failure.
prepare_service() {
  local unit=$1
  if [[ "${FIREWALL_UNIT_FOUND[${unit}]}" != true || "${FIREWALL_NEEDS_CHANGE[${unit}]}" != true ]]; then
    return 0
  fi
  if ! systemctl disable --now "${unit}"; then
    fail "Could not disable and stop ${unit}."
    return 1
  fi
}
# ---------------------------------- #

# Verifies and reports a firewall service's state after preparation.
# Arguments: $1 - systemd service unit name.
# Global state read or changed: FIREWALL_UNIT_FOUND, FIREWALL_ENABLED_STATE, FIREWALL_ACTIVE_STATE, FIREWALL_NEEDS_CHANGE.
# Output streams: summary to stdout, diagnostics to stderr.
# Return status: 0 on success, 1 on query or verification failure.
verify_service() {
  local unit=$1 enabled_state active_state
  if [[ "${FIREWALL_UNIT_FOUND[${unit}]}" == false ]]; then
    log "${unit}: unchanged (unit absent)."
    return 0
  fi
  query_firewall_service_state "${unit}" 'after action' || return
  enabled_state=${FIREWALL_ENABLED_STATE["${unit}"]}
  active_state=${FIREWALL_ACTIVE_STATE["${unit}"]}
  case "${enabled_state}" in
    enabled|enabled-runtime|linked|linked-runtime|alias)
      fail "${unit} remains enabled (${enabled_state})."
      return 1
      ;;
  esac
  case "${active_state}" in
    active|activating|reloading|deactivating)
      fail "${unit} remains active (${active_state})."
      return 1
      ;;
  esac
  if [[ "${FIREWALL_NEEDS_CHANGE[${unit}]}" == true ]]; then
    log "${unit}: changed (enabled=${enabled_state}, active=${active_state})."
  else
    log "${unit}: unchanged (enabled=${enabled_state}, active=${active_state})."
  fi
}
# ---------------------------------- #

# Rewrites only the SELINUX setting through an atomic same-directory temporary file.
# Arguments: none.
# Global state read or changed: SELINUX_CONFIG, SELINUX_SETTING, TEMP_FILE.
# Output streams: stderr on failure.
# Return status: 0 on success, 1 on failure.
write_selinux_config() {
  if ! TEMP_FILE=$(mktemp --tmpdir=/etc/selinux .config.XXXXXX); then
    fail "Could not create a temporary SELinux config file."
    return 1
  fi
  if ! awk -v desired="${SELINUX_SETTING}" '
    /^SELINUX=/ {
      print desired
      found=1
      next
    }
    { print }
    END {
      if (!found) print desired
    }
  ' "${SELINUX_CONFIG}" > "${TEMP_FILE}"; then
    fail "Could not rewrite ${SELINUX_CONFIG}."
    return 1
  fi
  if ! chown --reference="${SELINUX_CONFIG}" -- "${TEMP_FILE}"; then
    fail "Could not preserve ownership on ${TEMP_FILE}."
    return 1
  fi
  if ! chmod --reference="${SELINUX_CONFIG}" -- "${TEMP_FILE}"; then
    fail "Could not preserve mode on ${TEMP_FILE}."
    return 1
  fi
  if ! mv -T -- "${TEMP_FILE}" "${SELINUX_CONFIG}"; then
    fail "Could not install ${SELINUX_CONFIG}."
    return 1
  fi
  TEMP_FILE=""
}
# ---------------------------------- #

# Sets or reports the persistent SELinux setting.
# Arguments: none.
# Global state read or changed: CHECK_ONLY, SELINUX_CONFIG, SELINUX_SETTING, SELINUX_CONFIG_PRESENT, SELINUX_CONFIG_CURRENT, TEMP_FILE.
# Output streams: summary to stdout, diagnostics to stderr.
# Return status: 0 on success, 1 on failure.
prepare_selinux_config() {
  if ! inspect_selinux_config; then
    return 1
  fi
  if [[ "${SELINUX_CONFIG_PRESENT}" == false ]]; then
    log "SELinux config: unchanged (config absent; desired setting not applicable)."
    return 0
  fi
  if [[ "${SELINUX_CONFIG_CURRENT}" == "${SELINUX_SETTING}" ]]; then
    log "SELinux config: unchanged (${SELINUX_CONFIG_CURRENT})."
    return 0
  fi
  if [[ "${CHECK_ONLY}" == true ]]; then
    log "SELinux config: would change (current=${SELINUX_CONFIG_CURRENT}, desired=${SELINUX_SETTING})."
    return 0
  fi
  write_selinux_config || return
  log "SELinux config: changed (current=${SELINUX_SETTING}; was ${SELINUX_CONFIG_CURRENT})."
}
# ---------------------------------- #

# Reports runtime SELinux mode and signals when reboot is required or would be required after a check-mode config change.
# Arguments: none.
# Global state read: CHECK_ONLY, SELINUX_CONFIG_PRESENT, SELINUX_CONFIG_CURRENT, SELINUX_SETTING, SELINUX_RUNTIME, SELINUX_RUNTIME_SOURCE.
# Output streams: summary and check-mode reboot notice to stdout; apply-mode reboot notice to stderr.
# Return status: 0 when no reboot is required, 3 when reboot is required or predicted, 1 on verification failure.
finish_selinux() {
  if ! inspect_selinux_runtime; then
    return 1
  fi
  if [[ "${SELINUX_RUNTIME}" != Disabled ]]; then
    if [[ "${CHECK_ONLY}" == true ]]; then
      if [[ "${SELINUX_CONFIG_PRESENT}" == true && "${SELINUX_CONFIG_CURRENT}" != "${SELINUX_SETTING}" ]]; then
        log "SELinux runtime mode is ${SELINUX_RUNTIME}; a reboot would be required after the change"
        return 3
      fi
      log "SELinux runtime: unchanged (mode=${SELINUX_RUNTIME}; source=${SELINUX_RUNTIME_SOURCE})."
      return 0
    fi
    log "SELinux runtime: reboot required (mode=${SELINUX_RUNTIME})."
    printf 'SELinux runtime mode is %s; reboot required to complete\n' "${SELINUX_RUNTIME}" >&2
    return 3
  fi
  log "SELinux runtime: unchanged (mode=Disabled; source=${SELINUX_RUNTIME_SOURCE})."
}
# ---------------------------------- #

# Runs argument handling, root validation, preflight, and host preparation in order.
# Arguments: the command-line arguments.
# Global state read: EUID, CHECK_ONLY, HELP_REQUESTED, FIREWALL_UNITS.
# Global state changed: CHECK_ONLY, HELP_REQUESTED (set by parse_args), TEMP_FILE, FIREWALL_* and SELINUX_* arrays and values.
# Output streams: help, progress, and summaries to stdout; errors to stderr.
# Return status: 0 on success, 1 on error, 3 when SELinux reboot is required.
main() {
  if ! parse_args "$@"; then
    usage >&2
    return 1
  fi
  if [[ "${HELP_REQUESTED}" == true ]]; then
    usage
    return 0
  fi
  if (( EUID != 0 )); then
    fail "Run this script as root."
    return 1
  fi
  trap cleanup_temp EXIT
  preflight || return
  prepare_sysctl || return
  local unit
  for unit in "${FIREWALL_UNITS[@]}"; do
    if [[ "${CHECK_ONLY}" == true ]]; then
      report_service "${unit}" || return
    else
      prepare_service "${unit}" || return
      verify_service "${unit}" || return
    fi
  done
  prepare_selinux_config || return
  if finish_selinux; then
    return 0
  else
    local exit_status=$?
    return "${exit_status}"
  fi
}
# ---------------------------------- #

main "$@"
