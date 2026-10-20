"""Test readiness-scoped DNS records against Podman races and failures."""

import subprocess
from typing import Any

import pytest

from gateway.development.dns_records import generate_dns_records

API_ID = "a" * 64


def _config() -> dict[str, Any]:
    """Return one configured DNS target."""
    return {
        "networks": [{"name": "project-a", "subnet": "10.89.1.0/24"}],
        "dns_records": [
            {
                "name": "api.project-a.dev.internal",
                "container": "api",
                "network": "project-a",
            }
        ],
    }


def test_target_removed_between_exists_and_inspect_is_pending() -> None:
    """Recheck disappearance after inspect fails so old records are removed."""
    calls = 0

    def run_command(
        command: list[str], **kwargs: Any
    ) -> subprocess.CompletedProcess[str]:
        nonlocal calls
        calls += 1
        if command == ["podman", "container", "exists", API_ID]:
            if calls == 1:
                return subprocess.CompletedProcess(command, 0, "", "")
            return subprocess.CompletedProcess(command, 1, "", "no such container")
        if command[:4] == ["podman", "inspect", "--type", "container"]:
            return subprocess.CompletedProcess(command, 125, "", "no such container")
        raise AssertionError(f"unexpected command: {command}")

    assert generate_dns_records(_config(), {"api": API_ID}, run_command) == []
    assert calls == 3


def test_replaced_target_identity_is_not_treated_as_disappearance() -> None:
    """Reject an inspection that reports another immutable container identity."""
    inspected = subprocess.CompletedProcess(
        ["podman", "inspect"],
        0,
        f"{'b' * 64}|/api|true|healthy|10.89.1.5",
        "",
    )

    def run_command(
        command: list[str], **kwargs: Any
    ) -> subprocess.CompletedProcess[str]:
        if command == ["podman", "container", "exists", API_ID]:
            return subprocess.CompletedProcess(command, 0, "", "")
        if command[:4] == ["podman", "inspect", "--type", "container"]:
            return inspected
        raise AssertionError(f"unexpected command: {command}")

    with pytest.raises(ValueError, match="identity changed"):
        generate_dns_records(_config(), {"api": API_ID}, run_command)


def test_inspection_error_is_reported_when_target_still_exists() -> None:
    """Do not convert a permission or daemon failure into a pending target."""

    def run_command(
        command: list[str], **kwargs: Any
    ) -> subprocess.CompletedProcess[str]:
        if command == ["podman", "container", "exists", API_ID]:
            return subprocess.CompletedProcess(command, 0, "", "")
        if command[:4] == ["podman", "inspect", "--type", "container"]:
            return subprocess.CompletedProcess(command, 125, "", "permission denied")
        raise AssertionError(f"unexpected command: {command}")

    with pytest.raises(RuntimeError, match="permission denied"):
        generate_dns_records(_config(), {"api": API_ID}, run_command)


def test_recheck_failure_is_reported_instead_of_marking_target_pending() -> None:
    """Treat an inconclusive existence recheck as a Podman failure."""
    exists_calls = 0

    def run_command(
        command: list[str], **kwargs: Any
    ) -> subprocess.CompletedProcess[str]:
        nonlocal exists_calls
        if command == ["podman", "container", "exists", API_ID]:
            exists_calls += 1
            if exists_calls == 1:
                return subprocess.CompletedProcess(command, 0, "", "")
            return subprocess.CompletedProcess(
                command, 125, "", "Podman daemon unavailable"
            )
        if command[:4] == ["podman", "inspect", "--type", "container"]:
            return subprocess.CompletedProcess(command, 125, "", "inspect failed")
        raise AssertionError(f"unexpected command: {command}")

    with pytest.raises(RuntimeError, match="Podman daemon unavailable"):
        generate_dns_records(_config(), {"api": API_ID}, run_command)
