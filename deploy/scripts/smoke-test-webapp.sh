#!/usr/bin/env bash
# End-to-end CRUD smoke test of the webapp through the shared NGINX proxy.
#
# Usage: deploy/scripts/smoke-test-webapp.sh [BASE_URL]
#   BASE_URL defaults to http://localhost:8080/webapp
#
# Creates one user with a unique email, uploads an image, downloads it through
# NGINX, updates and deletes the user. Leaves no data behind on success.
# Requires: curl, jq, cmp. Prints "Smoke test passed" and exits 0 on success.
set -Eeuo pipefail

BASE_URL=${1:-http://localhost:8080/webapp}
BASE_URL=${BASE_URL%/}
readonly BASE_URL
readonly API="${BASE_URL}/api"
# 1x1 transparent PNG.
readonly PNG_BASE64='iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII='

work_dir=""
user_id=""

# Removes temporary files and the test user if a step failed midway.
# Arguments: none.
# Global state read: work_dir, user_id, API.
# Output streams: none.
# Return status: 0.
cleanup() {
  if [[ -n "${user_id}" ]]; then
    curl --silent --output /dev/null -X DELETE "${API}/users/${user_id}" || true
  fi
  [[ -n "${work_dir}" ]] && rm -rf -- "${work_dir}"
  return 0
}
# ---------------------------------- #

# Fails the test with a message.
# Arguments: $1 - message.
# Output streams: stderr.
# Return status: 1.
fail() {
  printf 'FAIL: %s\n' "$1" >&2
  return 1
}
# ---------------------------------- #

# Performs an HTTP request and checks the status code.
# Arguments: $1 - expected status; $2 - output file; remaining - curl arguments.
# Output streams: stdout "ok <status> <args>"; stderr body on mismatch.
# Return status: 0 when the status matches, 1 otherwise.
request() {
  local expected=$1 output=$2
  shift 2
  local status
  status=$(curl --silent --show-error --max-time 10 --output "${output}" \
    --write-out '%{http_code}' "$@") || return
  if [[ "${status}" != "${expected}" ]]; then
    cat -- "${output}" >&2 || true
    fail "Expected ${expected}, got ${status}: $*"
    return
  fi
  printf 'ok %s %s\n' "${status}" "${*: -1}"
}
# ---------------------------------- #

# Runs the CRUD scenario.
# Arguments: none.
# Global state changed: work_dir, user_id.
# Output streams: stdout progress, stderr diagnostics.
# Return status: 0 on success, nonzero on the first failed step.
main() {
  work_dir=$(mktemp -d)
  trap cleanup EXIT
  local body="${work_dir}/body" image="${work_dir}/pixel.png" email
  email="smoke-$(date +%s)-${RANDOM}@example.com"
  base64 -d <<<"${PNG_BASE64}" > "${image}"

  request 200 "${body}" "${API}/health"
  request 200 "${body}" "${BASE_URL}/index.html"
  grep -qi '<html' "${body}" || fail "index.html is not HTML"

  request 201 "${body}" -H 'Content-Type: application/json' \
    -d "{\"name\":\"Smoke Test\",\"email\":\"${email}\",\"location\":\"Brasília\"}" \
    "${API}/users"
  user_id=$(jq -er '.id' "${body}")

  request 409 "${body}" -H 'Content-Type: application/json' \
    -d "{\"name\":\"Dup\",\"email\":\"${email^^}\"}" "${API}/users"
  request 422 "${body}" -H 'Content-Type: application/json' \
    -d '{"name":"","email":"bad"}' "${API}/users"

  request 200 "${body}" "${API}/users"
  jq -e --argjson id "${user_id}" 'any(.[]; .id == $id)' "${body}" >/dev/null \
    || fail "User ${user_id} missing from list"

  request 200 "${body}" -X PUT -H 'Content-Type: application/json' \
    -d "{\"name\":\"Smoke Edited\",\"email\":\"${email}\",\"location\":null}" \
    "${API}/users/${user_id}"
  [[ "$(jq -r '.name' "${body}")" == "Smoke Edited" ]] || fail "Update not applied"

  request 200 "${body}" -X PUT -F "file=@${image};type=image/png" "${API}/users/${user_id}/image"
  local image_url
  image_url=$(jq -er '.image_url' "${body}")
  local origin=${BASE_URL%/webapp}
  request 200 "${work_dir}/download" "${origin}${image_url}"
  cmp -s -- "${image}" "${work_dir}/download" || fail "Downloaded image differs"

  request 415 "${body}" -X PUT -F "file=@${body};type=image/png" "${API}/users/${user_id}/image"
  request 404 "${body}" "${BASE_URL}/files/"

  request 200 "${body}" -X DELETE "${API}/users/${user_id}/image"
  request 404 "${body}" "${origin}${image_url}"

  request 204 "${body}" -X DELETE "${API}/users/${user_id}"
  user_id=""
  request 404 "${body}" "${API}/users/$(jq -n "${RANDOM} + 1000000")"

  printf 'Smoke test passed\n'
}
# ---------------------------------- #

main "$@"
