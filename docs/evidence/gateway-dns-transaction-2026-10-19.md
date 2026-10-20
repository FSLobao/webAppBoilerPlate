# Gateway DNS race and rollback evidence (2026-10-19)

The DNS generator now rechecks a target after inspection failure. A confirmed
missing immutable ID becomes pending; permission, daemon, and inconclusive
recheck failures remain errors.

The host refresher rolls back interrupted publication while holding the
Gateway lock. Rollback retains only prior hosts still present in the published
candidate, so it does not reintroduce a removed target address. If safe restore
or reload fails, the script preserves the backup and reports its path. Verify
target readiness before any manual recovery.

## Checks

- `uv run --locked python -m pytest -q`: 188 passed, 1 skipped. The default
  skip is the separately gated SSH TUN integration test.
- `uv run --locked python -m pytest -q tests/scripts/test_gateway_development_dns_records.py tests/scripts/test_gateway_dns_transaction.py`:
  6 passed. The transaction tests use fake Podman commands and temporary DNS
  state. One sends `SIGTERM` after atomic publication and checks rollback,
  stale-address removal, and lock retention. Another confirms a failed
  rollback reload preserves the recovery backup.
- `bash tests/scripts/test-gateway-config.sh`: passed all configuration,
  preflight, source-wrapper, and no-mutation checks.
- `uv run --locked ruff check gateway/development/dns_records.py tests/scripts/test_gateway_development_dns_records.py tests/scripts/test_gateway_dns_transaction.py`:
  passed.
- `uv run --locked ruff format --check gateway/development/dns_records.py tests/scripts/test_gateway_development_dns_records.py tests/scripts/test_gateway_dns_transaction.py`:
  passed.
- `bash -n scripts/refresh-gateway-dns.sh` and `git diff --check`: passed.
- `shellcheck -s bash scripts/refresh-gateway-dns.sh`: not run; ShellCheck is
  unavailable in this environment.

No live Podman runtime test, production apply, profile access, or host security
change was performed.
