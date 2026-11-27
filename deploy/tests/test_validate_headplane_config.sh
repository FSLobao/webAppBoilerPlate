#!/usr/bin/env bash
set -Eeuo pipefail

TEST_DIR=$(mktemp -d --tmpdir=/tmp validate-headplane.XXXXXX)
trap 'rm -rf -- "${TEST_DIR}"' EXIT

fail_test() {
  printf 'FAIL: %s\n' "$1" >&2
  exit 1
}
# ---------------------------------- #

candidate_config="${TEST_DIR}/headplane.yaml"
candidate_secret="${TEST_DIR}/headplane-cookie-secret"
fake_bin="${TEST_DIR}/bin"
podman_log="${TEST_DIR}/podman-args.txt"
output_file="${TEST_DIR}/output.txt"

mkdir -p -- "${fake_bin}"
printf '%s\n' 'server: {}' > "${candidate_config}"
printf '%s' '0123456789abcdef0123456789abcdef' > "${candidate_secret}"
chmod 0600 -- "${candidate_config}"
chmod 0444 -- "${candidate_secret}"

cat > "${fake_bin}/podman" <<'EOF'
#!/usr/bin/env bash
set -Eeuo pipefail

case "${1:-}" in
  image)
    exit 0
    ;;
  run)
    printf '%s\n' "$@" > "${FAKE_PODMAN_LOG}"
    exit 0
    ;;
  healthcheck)
    exit 0
    ;;
  container)
    exit 1
    ;;
esac

exit 2
EOF
chmod 0755 -- "${fake_bin}/podman"

PATH="${fake_bin}:${PATH}" FAKE_PODMAN_LOG="${podman_log}" \
  deploy/scripts/validate-headplane-config.sh \
  "${candidate_config}" "${candidate_secret}" example.invalid/headplane:test \
  > "${output_file}"

grep -F -- '--health-cmd' "${podman_log}" >/dev/null \
  || fail_test "temporary container did not configure a health command"
grep -F -- '/usr/local/sbin/gateway-healthcheck' "${podman_log}" >/dev/null \
  || fail_test "temporary container did not use the Gateway healthcheck"
grep -F -- "${candidate_config}:/tmp/headplane-candidate-config.yaml:ro" \
  "${podman_log}" >/dev/null \
  || fail_test "candidate config was not mounted at its staging path"
grep -F -- 'install -o headplane -g headplane -m 0400 /tmp/headplane-candidate-config.yaml /etc/headplane/config.yaml' \
  "${podman_log}" >/dev/null \
  || fail_test "candidate config was not installed for the Headplane UID"
grep -F -- 'install -o headplane -g headplane -m 0400 /tmp/headplane-candidate-secret /run/secrets/headplane-cookie-secret' \
  "${podman_log}" >/dev/null \
  || fail_test "candidate secret was not installed for the Headplane UID"
grep -F -- "${candidate_config}:/etc/headplane/config.yaml:ro" "${podman_log}" \
  >/dev/null && fail_test "candidate config remained directly bind-mounted"
[[ $(stat -c '%a' -- "${candidate_config}") == 600 ]] \
  || fail_test "host candidate config permissions changed"
grep -F -- 'validated successfully (healthcheck passed)' "${output_file}" >/dev/null \
  || fail_test "successful validation message was not emitted"

printf 'PASS: Headplane validation stages private candidates for UID 20002\n'
