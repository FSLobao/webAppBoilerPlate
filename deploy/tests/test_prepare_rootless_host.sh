#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_SOURCE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)/scripts/prepare-rootless-host.sh"
readonly SCRIPT_SOURCE
TEST_ROOT=$(mktemp -d)
readonly TEST_ROOT
REAL_CMP=$(command -v cmp)
readonly REAL_CMP
REAL_STAT=$(command -v stat)
readonly REAL_STAT
REAL_MV=$(command -v mv)
readonly REAL_MV
REAL_CHMOD=$(command -v chmod)
readonly REAL_CHMOD
REAL_RM=$(command -v rm)
readonly REAL_RM
FIXTURE=""

# Removes the disposable test tree.
# Arguments: none.
# Output streams: none.
# Return status: 0.
cleanup() {
  "$REAL_RM" -rf -- "${TEST_ROOT}"
}
# ---------------------------------- #

# Reports a test failure and exits.
# Arguments: $1 - diagnostic.
# Output streams: stderr.
# Return status: exits with 1.
fail_test() {
  printf 'FAIL: %s\n' "$1" >&2
  exit 1
}
# ---------------------------------- #

# Creates an isolated copy of the script, fake sysctl, and command path.
# Arguments: $1 - fixture name.
# Global state changed: FIXTURE.
# Output streams: none.
# Return status: exits on setup failure.
make_fixture() {
  local command_name command_path
  FIXTURE="${TEST_ROOT}/$1"
  mkdir -p "${FIXTURE}/bin" "${FIXTURE}/sysctl.d"
  sed \
    -e "s|/etc/sysctl.d|${FIXTURE}/sysctl.d|g" \
    -e "s|/etc/selinux/config|${FIXTURE}/selinux/config|g" \
    "${SCRIPT_SOURCE}" > "${FIXTURE}/script.sh"
  mkdir -p "${FIXTURE}/selinux"
  printf 'SELINUX=disabled\n' > "${FIXTURE}/selinux/config"

  ln -s "$(command -v bash)" "${FIXTURE}/bin/bash"
  for command_name in mktemp chmod rm awk grep chown; do
    command_path=$(command -v "${command_name}")
    ln -s "${command_path}" "${FIXTURE}/bin/${command_name}"
  done
  ln -s "${FIXTURE}/bin/forbidden-command" "${FIXTURE}/bin/systemctl"
  ln -s "${FIXTURE}/bin/forbidden-command" "${FIXTURE}/bin/getenforce"
  ln -s "${FIXTURE}/bin/forbidden-command" "${FIXTURE}/bin/firewall-cmd"
  ln -s "${FIXTURE}/bin/forbidden-command" "${FIXTURE}/bin/setenforce"

  cat > "${FIXTURE}/bin/sysctl" <<'SYSCTL_FAKE'
#!/usr/bin/env bash
set -Eeuo pipefail
printf '%s\n' "$*" >> "${SYSCTL_LOG}"
case "${1:-}" in
  -n)
    if [[ "${FAIL_SYSCTL_READ:-}" == true ]]; then
      exit 42
    fi
    IFS= read -r runtime_value < "${SYSCTL_RUNTIME}"
    printf '%s\n' "${runtime_value}"
    ;;
  -p)
    if [[ "${FAIL_SYSCTL_APPLY:-}" == before ]]; then
      exit 43
    fi
    IFS='=' read -r key value < "${2}"
    if [[ "${key}" != net.ipv4.ip_unprivileged_port_start || -z "${value}" ]]; then
      exit 44
    fi
    printf '%s\n' "${value}" > "${SYSCTL_RUNTIME}"
    printf '%s = %s\n' "${key}" "${value}"
    if [[ "${FAIL_SYSCTL_APPLY:-}" == wrong ]]; then
      printf '444\n' > "${SYSCTL_RUNTIME}"
    fi
    if [[ "${FAIL_SYSCTL_APPLY:-}" == after ]]; then
      exit 45
    fi
    ;;
  -w)
    if [[ "${FAIL_SYSCTL_RESTORE:-}" == true ]]; then
      exit 46
    fi
    setting=${2#*=}
    printf '%s\n' "${setting}" > "${SYSCTL_RUNTIME}"
    ;;
  *)
    exit 47
    ;;
esac
SYSCTL_FAKE
  chmod 0755 "${FIXTURE}/bin/sysctl"

  cat > "${FIXTURE}/bin/forbidden-command" <<'FORBIDDEN_FAKE'
#!/usr/bin/env bash
set -Eeuo pipefail
command_name=${0##*/}
printf '%s %s\n' "${command_name}" "$*" >> "${FORBIDDEN_LOG}"
case "${command_name}" in
  systemctl)
    case "${1:-}" in
      list-unit-files) printf 'firewalld.service enabled\nnftables.service enabled\n' ;;
      is-enabled) printf 'enabled\n' ;;
      is-active) printf 'active\n' ;;
      *) exit 97 ;;
    esac
    ;;
  getenforce) printf 'Enforcing\n' ;;
  *) exit 97 ;;
esac
FORBIDDEN_FAKE
  chmod 0755 "${FIXTURE}/bin/forbidden-command"

  cat > "${FIXTURE}/bin/cmp" <<'CMP_FAKE'
#!/usr/bin/env bash
set -Eeuo pipefail
if [[ "${FAIL_CMP:-}" == true ]]; then
  exit 2
fi
exec "${FAKE_REAL_CMP}" "$@"
CMP_FAKE
  chmod 0755 "${FIXTURE}/bin/cmp"

  cat > "${FIXTURE}/bin/stat" <<'STAT_FAKE'
#!/usr/bin/env bash
set -Eeuo pipefail
if [[ "${FAIL_STAT:-}" == true ]]; then
  exit 2
fi
exec "${FAKE_REAL_STAT}" "$@"
STAT_FAKE
  chmod 0755 "${FIXTURE}/bin/stat"

  cat > "${FIXTURE}/bin/mv" <<'MV_FAKE'
#!/usr/bin/env bash
set -Eeuo pipefail
if [[ "${FAIL_MV_ROLLBACK:-}" == true ]]; then
  if [[ -e "${MV_FIRST_CALL}" ]]; then
    exit 48
  fi
  : > "${MV_FIRST_CALL}"
fi
exec "${FAKE_REAL_MV}" "$@"
MV_FAKE
  chmod 0755 "${FIXTURE}/bin/mv"
}
# ---------------------------------- #

# Runs the disposable script with its fake command environment.
# Arguments: script arguments.
# Output streams: script stdout/stderr.
# Return status: the script's status.
run_script() {
  PATH="${FIXTURE}/bin" \
    SYSCTL_RUNTIME="${FIXTURE}/runtime" \
    SYSCTL_LOG="${FIXTURE}/sysctl.log" \
    FORBIDDEN_LOG="${FIXTURE}/forbidden.log" \
    MV_FIRST_CALL="${FIXTURE}/mv-first-call" \
    FAKE_REAL_CMP="${REAL_CMP}" \
    FAKE_REAL_STAT="${REAL_STAT}" \
    FAKE_REAL_MV="${REAL_MV}" \
    /bin/bash "${FIXTURE}/script.sh" "$@"
}
# ---------------------------------- #

# Initializes a prior file and runtime value for state-comparison tests.
# Arguments: $1 - initial runtime value.
# Global state read: FIXTURE.
# Output streams: none.
# Return status: 0.
initialize_state() {
  printf 'custom=prior\n\n' > "${FIXTURE}/sysctl.d/90-rootless-ports.conf"
  "${REAL_CHMOD}" 0600 "${FIXTURE}/sysctl.d/90-rootless-ports.conf"
  printf '%s\n' "$1" > "${FIXTURE}/runtime"
  : > "${FIXTURE}/sysctl.log"
  : > "${FIXTURE}/forbidden.log"
}
# ---------------------------------- #

# Verifies the configured setting has the exact content, mode, and runtime value.
# Arguments: none.
# Global state read: FIXTURE.
# Output streams: none.
# Return status: exits on assertion failure.
assert_desired_state() {
  local content mode runtime_value
  content=$("${REAL_CMP}" -s <(printf 'net.ipv4.ip_unprivileged_port_start=443\n') \
    "${FIXTURE}/sysctl.d/90-rootless-ports.conf") || fail_test "sysctl file did not have exact desired bytes"
  mode=$("${REAL_STAT}" -c '%a' -- "${FIXTURE}/sysctl.d/90-rootless-ports.conf")
  IFS= read -r runtime_value < "${FIXTURE}/runtime"
  [[ "${mode}" == 644 ]] || fail_test "expected mode 644, got ${mode}"
  [[ "${runtime_value}" == 443 ]] || fail_test "expected runtime 443, got ${runtime_value}"
  [[ -z "${content}" ]] || fail_test "unexpected content comparison output"
}
# ---------------------------------- #

# Verifies the previously saved file and runtime state are unchanged.
# Arguments: $1 - expected runtime value.
# Global state read: FIXTURE.
# Output streams: none.
# Return status: exits on assertion failure.
assert_prior_state() {
  local expected_runtime=$1 runtime_value mode
  printf 'custom=prior\n\n' | "${REAL_CMP}" -s - "${FIXTURE}/sysctl.d/90-rootless-ports.conf" \
    || fail_test "prior file contents changed"
  mode=$("${REAL_STAT}" -c '%a' -- "${FIXTURE}/sysctl.d/90-rootless-ports.conf")
  IFS= read -r runtime_value < "${FIXTURE}/runtime"
  [[ "${mode}" == 600 ]] || fail_test "prior file mode changed: ${mode}"
  [[ "${runtime_value}" == "${expected_runtime}" ]] \
    || fail_test "prior runtime changed: expected ${expected_runtime}, got ${runtime_value}"
}
# ---------------------------------- #

# Checks apply success, repeat-run idempotency, exact output, and isolation.
# Arguments: none.
# Output streams: test progress.
# Return status: exits on assertion failure.
test_success_and_idempotency() {
  local output first_log expected_changed expected_unchanged
  make_fixture success
  initialize_state 818
  if ! output=$(run_script --sysctl-only 2>"${FIXTURE}/stderr"); then
    fail_test "sysctl-only apply failed: $(<"${FIXTURE}/stderr")"
  fi
  expected_changed=$(printf '%s\n' \
    'net.ipv4.ip_unprivileged_port_start = 443' \
    'Sysctl: changed (file=net.ipv4.ip_unprivileged_port_start=443, mode=0644, runtime=443; was 818).')
  [[ "${output}" == "${expected_changed}" ]] || fail_test "changed-run stdout differed from expected output"
  [[ ! -s "${FIXTURE}/stderr" ]] || fail_test "changed run unexpectedly wrote to stderr"
  assert_desired_state
  first_log=$(<"${FIXTURE}/sysctl.log")
  if ! output=$(run_script --sysctl-only 2>"${FIXTURE}/stderr"); then
    fail_test "repeat apply failed: $(<"${FIXTURE}/stderr")"
  fi
  expected_unchanged=$(printf '%s\n' \
    'net.ipv4.ip_unprivileged_port_start = 443' \
    'Sysctl: unchanged (file=net.ipv4.ip_unprivileged_port_start=443, mode=0644, runtime=443).')
  [[ "${output}" == "${expected_unchanged}" ]] || fail_test "unchanged-run stdout differed from expected output"
  [[ ! -s "${FIXTURE}/stderr" ]] || fail_test "unchanged run unexpectedly wrote to stderr"
  assert_desired_state
  [[ -z "$(<"${FIXTURE}/forbidden.log")" ]] || fail_test "sysctl-only invoked a forbidden host inspector"
  [[ "$(<"${FIXTURE}/sysctl.log")" == "${first_log}"$'\n'"${first_log}" ]] \
    || fail_test "unexpected sysctl operation sequence"
}
# ---------------------------------- #

# Checks that read and prerequisite failures do not mutate saved state.
# Arguments: none.
# Output streams: test progress.
# Return status: exits on assertion failure.
test_preflight_failures_are_non_mutating() {
  local output
  make_fixture preflight
  initialize_state 817

  output=$(FAIL_SYSCTL_READ=true run_script --sysctl-only 2>&1) && fail_test "runtime read failure unexpectedly succeeded"
  assert_prior_state 817

  output=$(FAIL_STAT=true run_script --sysctl-only 2>&1) && fail_test "mode read failure unexpectedly succeeded"
  assert_prior_state 817

  output=$(FAIL_CMP=true run_script --sysctl-only 2>&1) && fail_test "content compare failure unexpectedly succeeded"
  assert_prior_state 817

  : > "${FIXTURE}/sysctl.log"
  "${REAL_RM}" -- "${FIXTURE}/bin/chmod"
  output=$(run_script --sysctl-only 2>&1) && fail_test "missing prerequisite unexpectedly succeeded"
  [[ "${output}" == *'Missing command: chmod'* ]] || fail_test "missing prerequisite diagnostic was unclear"
  assert_prior_state 817
  [[ -z "$(<"${FIXTURE}/sysctl.log")" ]] || fail_test "missing prerequisite invoked sysctl"
}
# ---------------------------------- #

# Checks absent-file rollback and rejects symlink targets before runtime reads.
# Arguments: none.
# Output streams: test progress.
# Return status: exits on assertion failure.
test_absent_and_unsafe_target_states() {
  local output
  make_fixture absent
  printf '819\n' > "${FIXTURE}/runtime"
  : > "${FIXTURE}/sysctl.log"
  : > "${FIXTURE}/forbidden.log"
  if output=$(FAIL_SYSCTL_APPLY=after run_script --sysctl-only 2>&1); then
    fail_test "failed apply with initially absent file unexpectedly succeeded"
  fi
  [[ ! -e "${FIXTURE}/sysctl.d/90-rootless-ports.conf" ]] \
    || fail_test "rollback did not restore prior file absence"
  local runtime_value
  IFS= read -r runtime_value < "${FIXTURE}/runtime"
  [[ "${runtime_value}" == 819 ]] || fail_test "runtime was not restored for absent prior file"

  printf 'outside\n' > "${FIXTURE}/outside"
  ln -s "${FIXTURE}/outside" "${FIXTURE}/sysctl.d/90-rootless-ports.conf"
  : > "${FIXTURE}/sysctl.log"
  output=$(run_script --sysctl-only 2>&1) && fail_test "symlink target unexpectedly succeeded"
  [[ "${output}" == *'must be a regular file, not a symlink'* ]] \
    || fail_test "symlink target diagnostic was missing"
  [[ -L "${FIXTURE}/sysctl.d/90-rootless-ports.conf" ]] || fail_test "symlink target was changed"
  [[ -z "$(<"${FIXTURE}/sysctl.log")" ]] || fail_test "unsafe target invoked sysctl"
}
# ---------------------------------- #

# Checks post-mutation rollback and reports rollback failures without hiding failure.
# Arguments: none.
# Output streams: test progress.
# Return status: exits on assertion failure.
test_rollback_and_rollback_failure() {
  local output status
  make_fixture rollback
  initialize_state 816

  if output=$(FAIL_SYSCTL_APPLY=after run_script --sysctl-only 2>&1); then
    fail_test "apply failure after runtime mutation unexpectedly succeeded"
  else
    status=$?
  fi
  [[ "${status}" == 1 ]] || fail_test "original operation failure status was not preserved: ${status}"
  assert_prior_state 816
  [[ "$(<"${FIXTURE}/sysctl.log")" == *'-w net.ipv4.ip_unprivileged_port_start=816'* ]] \
    || fail_test "runtime rollback was not attempted"

  initialize_state 816
  if output=$(FAIL_SYSCTL_APPLY=wrong run_script --sysctl-only 2>&1); then
    fail_test "runtime verification failure unexpectedly succeeded"
  fi
  assert_prior_state 816

  initialize_state 815
  if output=$(FAIL_SYSCTL_APPLY=after FAIL_SYSCTL_RESTORE=true run_script --sysctl-only 2>&1); then
    fail_test "operation with rollback failure unexpectedly succeeded"
  else
    status=$?
  fi
  [[ "${status}" == 1 ]] || fail_test "rollback failure replaced original status: ${status}"
  [[ "${output}" == *'Could not restore runtime sysctl value'* ]] \
    || fail_test "rollback failure diagnostic was missing"
  printf 'custom=prior\n\n' | "${REAL_CMP}" -s - "${FIXTURE}/sysctl.d/90-rootless-ports.conf" \
    || fail_test "file restoration was not attempted independently"

  initialize_state 813
  if output=$(FAIL_SYSCTL_APPLY=after FAIL_MV_ROLLBACK=true run_script --sysctl-only 2>&1); then
    fail_test "operation with file rollback failure unexpectedly succeeded"
  fi
  [[ "${output}" == *'Could not restore '* ]] || fail_test "file rollback failure diagnostic was missing"
  [[ "$(<"${FIXTURE}/sysctl.log")" == *'-w net.ipv4.ip_unprivileged_port_start=813'* ]] \
    || fail_test "runtime restoration was skipped after file rollback failure"
  IFS= read -r runtime_value < "${FIXTURE}/runtime"
  [[ "${runtime_value}" == 813 ]] || fail_test "runtime was not restored after file rollback failure"
}
# ---------------------------------- #

# Checks that legacy apply/check/help/argument/root guards remain distinct.
# Arguments: none.
# Output streams: test progress.
# Return status: exits on assertion failure.
test_cli_compatibility() {
  local output
  make_fixture cli
  initialize_state 814

  output=$(run_script --help 2>&1) || fail_test "help failed"
  [[ "${output}" == *'--sysctl-only'* ]] || fail_test "help omitted --sysctl-only"
  output=$(run_script --unknown 2>&1) && fail_test "invalid argument unexpectedly succeeded"
  output=$(run_script --check 2>&1) || fail_test "legacy --check failed: ${output}"
  [[ "$(<"${FIXTURE}/forbidden.log")" == *'systemctl list-unit-files'* ]] \
    || fail_test "--check no longer follows the broad read-only path"

  : > "${FIXTURE}/forbidden.log"
  output=$(run_script 2>&1) && fail_test "legacy apply unexpectedly succeeded against failing service fake"
  [[ "$(<"${FIXTURE}/forbidden.log")" == *'systemctl list-unit-files'* ]] \
    || fail_test "no-argument mode no longer follows broad preflight"

  sed -i 's/if (( EUID != 0 )); then/if (( 0 == 0 )); then/' "${FIXTURE}/script.sh"
  : > "${FIXTURE}/sysctl.log"
  output=$(run_script --sysctl-only 2>&1) && fail_test "root guard bypass test unexpectedly succeeded"
  [[ "${output}" == *'Run this script as root.'* ]] || fail_test "root guard diagnostic changed"
  [[ -z "$(<"${FIXTURE}/sysctl.log")" ]] || fail_test "root guard was bypassed"
}
# ---------------------------------- #

# Runs each isolated behavior test.
# Arguments: none.
# Output streams: test progress.
# Return status: 0 on success, nonzero on assertion failure.
main() {
  trap cleanup EXIT
  test_success_and_idempotency
  test_preflight_failures_are_non_mutating
  test_absent_and_unsafe_target_states
  test_rollback_and_rollback_failure
  test_cli_compatibility
  printf 'PASS: prepare-rootless-host behavior tests\n'
}
# ---------------------------------- #

main "$@"
