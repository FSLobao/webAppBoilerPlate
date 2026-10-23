"""Test the host-side WireGuard peer onboarding script."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
ONBOARDING_SCRIPT = (
    REPOSITORY_ROOT / "scripts" / "gateway" / "onboard-wireguard-peer.sh"
)
FINGERPRINT = "a" * 64
PRIVATE_KEY = "p" * 43 + "="


def _fake_commands(
    tmp_path: Path,
    *,
    profile_directory: Path,
    approval_fails: bool = False,
    generation_status: int = 0,
    revocation_fails: bool = False,
    list_reports_approved: bool = False,
) -> tuple[dict[str, str], Path]:
    """Create fake host commands for one isolated onboarding run."""
    bin_directory = tmp_path / "bin"
    bin_directory.mkdir()
    podman_log = tmp_path / "podman.jsonl"
    jq = bin_directory / "jq"
    jq.write_text(
        """#!/usr/bin/env bash
set -Eeuo pipefail
if [[ "${1:-}" == "-j" ]]; then
  printf '%s\\0' "$WG_TEST_PROFILE_DIRECTORY" \\
    'development access' '192.168.7.149' 'home lab test' \\
    '2036-10-24T00:00:01+00:00'
  exit 0
fi
if [[ "${1:-}" == "-e" && "$#" == 3 ]]; then
  exit 0
fi
if [[ "${1:-}" == "-e" ]]; then
  [[ "${PODMAN_LIST_APPROVED:-0}" == "1" ]]
  exit
fi
exit 1
""",
        encoding="utf-8",
    )
    jq.chmod(0o755)
    podman = bin_directory / "podman"
    podman.write_text(
        f"""#!/usr/bin/env python3
import json
import os
import sys

arguments = sys.argv[1:]
with open(os.environ["PODMAN_LOG"], "a", encoding="utf-8") as log:
    log.write(json.dumps(arguments) + "\\n")
operation = arguments[6] if len(arguments) > 6 else ""
if operation == "generate":
    sys.stderr.write("PEER_CREATED\\tdevice-01\\t{FINGERPRINT}\\n")
    sys.stdout.write("[Interface]\\nPrivateKey = {PRIVATE_KEY}\\n")
    sys.stdout.write("Address = 198.18.0.2/32\\n\\n[Peer]\\n")
    sys.stdout.write("PublicKey = {FINGERPRINT}\\nEndpoint = 192.168.7.149:1194\\n")
    sys.stdout.write("AllowedIPs = 192.168.9.0/24\\n")
    raise SystemExit({generation_status})
if operation == "approve":
    if os.environ.get("PODMAN_APPROVE_FAIL") == "1":
        sys.stderr.write("mock approval error\\n")
        raise SystemExit(1)
    raise SystemExit(0)
if operation == "revoke":
    if os.environ.get("PODMAN_REVOKE_FAIL") == "1":
        sys.stderr.write("mock revocation error\\n")
        raise SystemExit(1)
    raise SystemExit(0)
if operation == "list":
    if os.environ.get("PODMAN_LIST_APPROVED") == "1":
        sys.stdout.write('{{"peers":[{{"id":"device-01",')
        sys.stdout.write('"public_fingerprint":"{FINGERPRINT}",')
        sys.stdout.write('"status":"approved"}}],"audit":[]}}\\n')
    else:
        sys.stdout.write('{{"peers":[],"audit":[]}}\\n')
    raise SystemExit(0)
raise SystemExit(64)
""",
        encoding="utf-8",
    )
    podman.chmod(0o755)
    environment = os.environ.copy()
    environment["PATH"] = f"{bin_directory}:{environment['PATH']}"
    environment["PODMAN_LOG"] = str(podman_log)
    environment["WG_TEST_PROFILE_DIRECTORY"] = str(profile_directory)
    if approval_fails:
        environment["PODMAN_APPROVE_FAIL"] = "1"
    if revocation_fails:
        environment["PODMAN_REVOKE_FAIL"] = "1"
    if list_reports_approved:
        environment["PODMAN_LIST_APPROVED"] = "1"
    return environment, podman_log


def _run_onboarding(
    tmp_path: Path,
    *,
    approval_fails: bool = False,
    generation_status: int = 0,
    revocation_fails: bool = False,
    list_reports_approved: bool = False,
    device_id: str = "device-01",
    existing_profile: bool = False,
    profile_mode: int | None = None,
) -> tuple[subprocess.CompletedProcess[str], Path, Path]:
    """Run the host onboarding script with fake Podman and config values."""
    profile_directory = tmp_path / "profiles"
    if existing_profile or profile_mode is not None:
        mode = profile_mode if profile_mode is not None else 0o700
        profile_directory.mkdir(mode=mode)
        profile_directory.chmod(mode)
    if existing_profile:
        (profile_directory / f"peer-{device_id}.conf").write_text(
            "existing profile\n",
            encoding="ascii",
        )
    environment, podman_log = _fake_commands(
        tmp_path,
        profile_directory=profile_directory,
        approval_fails=approval_fails,
        generation_status=generation_status,
        revocation_fails=revocation_fails,
        list_reports_approved=list_reports_approved,
    )
    result = subprocess.run(
        [str(ONBOARDING_SCRIPT), device_id, "owner-01"],
        check=False,
        capture_output=True,
        text=True,
        env=environment,
        timeout=15,
    )
    return result, profile_directory, podman_log


@pytest.mark.skipif(os.geteuid() != 0, reason="host onboarding requires root")
def test_onboarding_approves_and_atomically_stores_one_private_profile(
    tmp_path: Path,
) -> None:
    """Store one approved profile with root-only permissions and quiet output."""
    result, profile_directory, podman_log = _run_onboarding(tmp_path)

    profile_path = profile_directory / "peer-device-01.conf"
    assert result.returncode == 0
    assert result.stdout == f"Created WireGuard profile: {profile_path}\n"
    assert result.stderr == ""
    assert profile_directory.stat().st_uid == 0
    assert profile_directory.stat().st_gid == 0
    assert profile_directory.stat().st_mode & 0o777 == 0o700
    assert profile_path.stat().st_uid == 0
    assert profile_path.stat().st_gid == 0
    assert profile_path.stat().st_mode & 0o777 == 0o600
    assert f"PrivateKey = {PRIVATE_KEY}" in profile_path.read_text(encoding="ascii")
    assert PRIVATE_KEY not in result.stdout + result.stderr
    calls = [json.loads(line) for line in podman_log.read_text().splitlines()]
    assert [call[6] for call in calls] == ["generate", "approve"]
    assert "--profile-stdout" in calls[0]
    assert calls[0][calls[0].index("--owner") + 1] == "owner-01"
    assert calls[1][calls[1].index("--expected-fingerprint") + 1] == FINGERPRINT
    assert sorted(path.name for path in profile_directory.iterdir()) == [
        ".onboarding.lock",
        "peer-device-01.conf",
    ]


@pytest.mark.skipif(os.geteuid() != 0, reason="host onboarding requires root")
def test_approval_failure_revokes_pending_peer_and_removes_profile_staging(
    tmp_path: Path,
) -> None:
    """Revoke a generated peer and remove its private profile after approval fails."""
    result, profile_directory, podman_log = _run_onboarding(
        tmp_path,
        approval_fails=True,
    )

    assert result.returncode != 0
    assert "peer approval failed" in result.stderr
    assert PRIVATE_KEY not in result.stdout + result.stderr
    assert not list(profile_directory.glob("peer-device-01.conf"))
    calls = [json.loads(line) for line in podman_log.read_text().splitlines()]
    assert [call[6] for call in calls] == ["generate", "approve", "list", "revoke"]
    assert calls[-1][calls[-1].index("--expected-fingerprint") + 1] == FINGERPRINT
    assert sorted(path.name for path in profile_directory.iterdir()) == [
        ".onboarding.lock",
    ]


@pytest.mark.skipif(os.geteuid() != 0, reason="host onboarding requires root")
def test_lost_approval_response_recovers_approved_peer_state(tmp_path: Path) -> None:
    """Publish the profile when inventory confirms approval despite a lost response."""
    result, profile_directory, podman_log = _run_onboarding(
        tmp_path,
        approval_fails=True,
        list_reports_approved=True,
    )

    assert result.returncode == 0
    assert result.stdout == (
        f"Created WireGuard profile: {profile_directory}/peer-device-01.conf\n"
    )
    assert result.stderr == ""
    calls = [json.loads(line) for line in podman_log.read_text().splitlines()]
    assert [call[6] for call in calls] == ["generate", "approve", "list"]


@pytest.mark.skipif(os.geteuid() != 0, reason="host onboarding requires root")
def test_generation_failure_revokes_only_marked_peer(tmp_path: Path) -> None:
    """Use the generated fingerprint to revoke a peer after partial profile output."""
    result, profile_directory, podman_log = _run_onboarding(
        tmp_path,
        generation_status=1,
    )

    assert result.returncode != 0
    assert "peer generation failed" in result.stderr
    assert PRIVATE_KEY not in result.stdout + result.stderr
    calls = [json.loads(line) for line in podman_log.read_text().splitlines()]
    assert [call[6] for call in calls] == ["generate", "revoke"]
    assert not list(profile_directory.glob("peer-device-01.conf"))
    assert sorted(path.name for path in profile_directory.iterdir()) == [
        ".onboarding.lock",
    ]


@pytest.mark.skipif(os.geteuid() != 0, reason="host onboarding requires root")
def test_revocation_failure_keeps_profile_staging_root_only(tmp_path: Path) -> None:
    """Keep protected staging when compensation cannot revoke the generated peer."""
    result, profile_directory, podman_log = _run_onboarding(
        tmp_path,
        approval_fails=True,
        revocation_fails=True,
    )

    assert result.returncode != 0
    assert "automatic revocation failed" in result.stderr
    assert PRIVATE_KEY not in result.stdout + result.stderr
    staged_profiles = list(profile_directory.glob(".peer-device-01.*"))
    assert len(staged_profiles) == 1
    assert staged_profiles[0].stat().st_uid == 0
    assert staged_profiles[0].stat().st_mode & 0o777 == 0o600
    calls = [json.loads(line) for line in podman_log.read_text().splitlines()]
    assert [call[6] for call in calls] == ["generate", "approve", "list", "revoke"]


@pytest.mark.skipif(os.geteuid() != 0, reason="host onboarding requires root")
def test_existing_profile_is_never_overwritten(tmp_path: Path) -> None:
    """Reject a duplicate profile path before invoking peer administration."""
    result, profile_directory, podman_log = _run_onboarding(
        tmp_path,
        existing_profile=True,
    )

    profile_path = profile_directory / "peer-device-01.conf"
    assert result.returncode != 0
    assert "refusing to overwrite" in result.stderr
    assert profile_path.read_text(encoding="ascii") == "existing profile\n"
    assert not podman_log.exists()


@pytest.mark.skipif(os.geteuid() != 0, reason="host onboarding requires root")
def test_unsafe_profile_directory_fails_without_chmod_or_peer_creation(
    tmp_path: Path,
) -> None:
    """Reject an existing permissive directory without changing its mode."""
    result, profile_directory, podman_log = _run_onboarding(
        tmp_path,
        profile_mode=0o755,
    )

    assert result.returncode != 0
    assert "must be root-owned with mode 0700" in result.stderr
    assert profile_directory.stat().st_mode & 0o777 == 0o755
    assert not podman_log.exists()
