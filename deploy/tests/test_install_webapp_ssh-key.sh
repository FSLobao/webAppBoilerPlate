#!/usr/bin/env bash
set -Eeuo pipefail

REPO_ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)
readonly REPO_ROOT
SCRIPT="${REPO_ROOT}/deploy/scripts/install-webapp-ssh-key.sh"
readonly SCRIPT
TEST_ROOT=$(mktemp -d)
readonly TEST_ROOT

# Removes the disposable test tree.
# Arguments: none.
# Output streams: none.
# Return status: 0.
cleanup() {
  rm -rf -- "${TEST_ROOT}"
}
# ---------------------------------- #

# Reports a failed assertion and exits.
# Arguments: $1 - message.
# Output streams: stderr.
# Return status: exits with 1.
fail_test() {
  printf 'FAIL: %s\n' "$1" >&2
  exit 1
}
# ---------------------------------- #

trap cleanup EXIT

KEY_FILE="${TEST_ROOT}/operator"
KEY_PUBLIC="${KEY_FILE}.pub"
TARGET="${TEST_ROOT}/secrets/authorized_keys"
ssh-keygen -q -t ed25519 -N '' -C operator@webapp -f "${KEY_FILE}"

"${SCRIPT}" --public-key-file "${KEY_PUBLIC}" --target-file "${TARGET}"
KEY_COUNT=$(grep -c '^ssh-ed25519 ' "${TARGET}") \
  || fail_test "installed key is not present"
[[ "${KEY_COUNT}" == 1 ]] || fail_test "expected one installed key"
[[ "$(stat -c '%a' "${TARGET}")" == 600 ]] \
  || fail_test "authorized_keys mode is not 0600"

"${SCRIPT}" --public-key-file "${KEY_PUBLIC}" --target-file "${TARGET}"
KEY_COUNT=$(grep -c '^ssh-ed25519 ' "${TARGET}") \
  || fail_test "idempotent key is not present"
[[ "${KEY_COUNT}" == 1 ]] || fail_test "duplicate key was appended"

INVALID_KEY="${TEST_ROOT}/invalid.pub"
printf 'not-an-ssh-key\n' > "${INVALID_KEY}"
if "${SCRIPT}" --public-key-file "${INVALID_KEY}" --target-file "${TARGET}" \
  >/dev/null 2>&1; then
  fail_test "invalid public key unexpectedly succeeded"
fi
KEY_COUNT=$(grep -c '^ssh-ed25519 ' "${TARGET}") \
  || fail_test "valid key disappeared after invalid input"
[[ "${KEY_COUNT}" == 1 ]] || fail_test "invalid input changed the target"

SYMLINK_TARGET="${TEST_ROOT}/linked-authorized-keys"
ln -s "${TARGET}" "${SYMLINK_TARGET}"
if "${SCRIPT}" --public-key-file "${KEY_PUBLIC}" --target-file "${SYMLINK_TARGET}" \
  >/dev/null 2>&1; then
  fail_test "symlink target unexpectedly succeeded"
fi

printf 'PASS: install-webapp-ssh-key\n'
