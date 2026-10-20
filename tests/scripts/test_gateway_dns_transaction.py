"""Test host DNS publication rollback with isolated fake Podman commands."""

import os
import re
import shlex
import subprocess
from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
REFRESH_SCRIPT = REPOSITORY_ROOT / "scripts/refresh-gateway-dns.sh"
DNS_NAME = "api.project-a.dev.anatel"
OLD_ADDRESS = "10.89.1.4"
REVISION = f"sha256:{'a' * 64}"
CANDIDATE = (
    "# Managed by readiness-scoped Gateway DNS refresh\n"
    f"# PENDING DNS target: {DNS_NAME} (api readiness/unverified)"
)


def _write_executable(path: Path, contents: str) -> None:
    """Write one executable fake command."""
    path.write_text(contents, encoding="utf-8")
    path.chmod(0o755)


def _prepare_fixture(tmp_path: Path, mode: str) -> tuple[Path, dict[str, str]]:
    """Create isolated DNS state, a path-adjusted script copy, and fake commands."""
    root = tmp_path / "state"
    dns_directory = root / "dns"
    generated_directory = root / "generated"
    lock_directory = root / "lock"
    fake_bin = root / "bin"
    for directory in (dns_directory, generated_directory, lock_directory, fake_bin):
        directory.mkdir(parents=True)

    config = generated_directory / "config.json"
    config.write_text("{}\n", encoding="utf-8")
    hosts = dns_directory / "hosts"
    hosts.write_text(
        "# Managed by readiness-scoped Gateway DNS refresh\n"
        f"{OLD_ADDRESS} {DNS_NAME}\n",
        encoding="utf-8",
    )
    request = root / "request.json"
    request.write_text("{}\n", encoding="utf-8")
    request.chmod(0o600)

    script_contents = REFRESH_SCRIPT.read_text(encoding="utf-8")
    replacements = {
        "readonly GENERATED_CONFIG=/var/lib/gateway/generated/config.json": f"readonly GENERATED_CONFIG={shlex.quote(str(config))}",
        "readonly DNS_DIR=/var/lib/gateway/dns": f"readonly DNS_DIR={shlex.quote(str(dns_directory))}",
        "readonly GATEWAY_LOCK=/run/lock/gateway-config.lock": f"readonly GATEWAY_LOCK={shlex.quote(str(lock_directory / 'gateway-config.lock'))}",
    }
    for original, replacement in replacements.items():
        assert original in script_contents
        script_contents = script_contents.replace(original, replacement, 1)
    script = root / "refresh-gateway-dns.sh"
    script.write_text(script_contents, encoding="utf-8")
    script.chmod(0o755)

    _write_executable(
        fake_bin / "python3",
        f"""#!/usr/bin/env bash
set -Eeuo pipefail
case "$*" in
  *request-revision*) printf '%s\\n' {shlex.quote(REVISION)} ;;
  *dns_refresh.py*handoff*) printf '%s\\n' "$FAKE_CANDIDATE" ;;
  *revision*) printf '%s\\n' {shlex.quote(REVISION)} ;;
  *) printf 'unexpected fake python3 call: %s\\n' "$*" >&2; exit 2 ;;
esac
""",
    )
    _write_executable(
        fake_bin / "podman",
        """#!/usr/bin/env bash
set -Eeuo pipefail
printf '%s\\n' "$*" >> "$FAKE_LOG"
case "$*" in
  *"inspect --format"*) printf 'true\\n' ;;
  *"dnsmasq --test"*) exit 0 ;;
  *"pkill -HUP dnsmasq"*)
    count=0
    if [[ -f "$FAKE_RELOAD_COUNT" ]]; then
      read -r count < "$FAKE_RELOAD_COUNT"
    fi
    count=$((count + 1))
    printf '%s\\n' "$count" > "$FAKE_RELOAD_COUNT"
    if (( count == 2 )); then
      if flock -n "$FAKE_LOCK_PATH" -c true; then
        printf 'lock was released before rollback completed\\n' >> "$FAKE_LOG"
      else
        printf 'rollback lock held\\n' >> "$FAKE_LOG"
      fi
    fi
    if [[ "$FAKE_MODE" == interrupt && "$count" == 1 ]]; then
      if grep -Fq "$FAKE_OLD_ADDRESS" "$FAKE_HOSTS_PATH"; then
        printf 'candidate was not published before signal test\\n' >&2
        exit 3
      fi
      printf 'candidate published before signal\\n' >> "$FAKE_LOG"
      kill -TERM "$PPID"
      sleep 0.1
      exit 0
    fi
    if [[ "$FAKE_MODE" == fail ]]; then
      exit 1
    fi
    ;;
  *"dns_refresh.py handoff"*) printf '%s\\n' "$FAKE_CANDIDATE" ;;
  *) printf 'unexpected fake Podman call: %s\\n' "$*" >&2; exit 2 ;;
esac
""",
    )

    environment = os.environ.copy()
    environment.update(
        {
            "PATH": f"{fake_bin}:{environment['PATH']}",
            "FAKE_CANDIDATE": CANDIDATE,
            "FAKE_LOG": str(root / "podman.log"),
            "FAKE_HOSTS_PATH": str(hosts),
            "FAKE_LOCK_PATH": str(lock_directory / "gateway-config.lock"),
            "FAKE_MODE": mode,
            "FAKE_OLD_ADDRESS": OLD_ADDRESS,
            "FAKE_RELOAD_COUNT": str(root / "reload-count"),
        }
    )
    return script, environment


@pytest.mark.skipif(os.geteuid() != 0, reason="host DNS handoff requires root")
def test_signal_after_atomic_publish_rolls_back_without_stale_target(
    tmp_path: Path,
) -> None:
    """Restore safe prior records after TERM and keep the config lock through reload."""
    script, environment = _prepare_fixture(tmp_path, "interrupt")
    request = tmp_path / "state/request.json"

    result = subprocess.run(
        ["bash", str(script), "--handoff", str(request)],
        check=False,
        capture_output=True,
        text=True,
        env=environment,
    )

    hosts = tmp_path / "state/dns/hosts"
    assert result.returncode == 143
    assert OLD_ADDRESS not in hosts.read_text(encoding="utf-8")
    log = (tmp_path / "state/podman.log").read_text(encoding="utf-8")
    assert "candidate published before signal" in log
    assert "rollback lock held" in log
    assert not list((tmp_path / "state/dns").glob(".hosts-rollback.*"))


@pytest.mark.skipif(os.geteuid() != 0, reason="host DNS handoff requires root")
def test_failed_rollback_reload_preserves_recovery_backup(tmp_path: Path) -> None:
    """Keep raw backup for operator recovery when rollback reload also fails."""
    script, environment = _prepare_fixture(tmp_path, "fail")
    request = tmp_path / "state/request.json"

    result = subprocess.run(
        ["bash", str(script), "--handoff", str(request)],
        check=False,
        capture_output=True,
        text=True,
        env=environment,
    )

    hosts = tmp_path / "state/dns/hosts"
    assert result.returncode != 0
    assert OLD_ADDRESS not in hosts.read_text(encoding="utf-8")
    match = re.search(
        r"backup preserved at (.+?)\. Verify target readiness", result.stderr
    )
    assert match is not None
    backup = Path(match.group(1))
    assert backup.is_file()
    assert OLD_ADDRESS in backup.read_text(encoding="utf-8")
