"""Tests for Gateway host-preflight Python helpers."""

import json
import subprocess

import pytest

from scripts.gateway.host_preflight import (
    cockpit_password_is_valid,
    podman_version_supported,
    validate_podman_state,
)


@pytest.mark.parametrize(
    ("version", "supported"),
    [("v4.4.0", True), ("5.0.1", True), ("4.3.9", False), ("invalid", False)],
)
def test_podman_version_requirement(version: str, supported: bool) -> None:
    """Accept Podman 4.4 or newer and reject older or malformed versions."""
    assert podman_version_supported(version) is supported


@pytest.mark.parametrize(
    ("contents", "valid"),
    [
        (b"secret\n", True),
        (b"secret\n\n", True),
        (b"", False),
        (b"secret\nsecond", False),
        (b"secret\r", False),
        (b"secret\0", False),
    ],
)
def test_cockpit_password_file_content(tmp_path, contents: bytes, valid: bool) -> None:
    """Accept only non-empty single-line secret files."""
    password_path = tmp_path / "password"
    password_path.write_bytes(contents)

    assert cockpit_password_is_valid(password_path) is valid


def test_validate_podman_state_accepts_valid_running_target() -> None:
    """Accept non-overlapping Podman networks and an attached target container."""
    calls = []

    def run_command(*args, **kwargs):
        command = list(args[0]) if len(args) == 1 and isinstance(args[0], list) else list(args)
        calls.append(command)
        if command == ["podman", "network", "ls", "--format", "{{.Name}}"]:
            return subprocess.CompletedProcess(command, 0, "bridge\n", "")
        if command == ["podman", "network", "inspect", "bridge"]:
            return subprocess.CompletedProcess(
                command, 0, json.dumps([{"subnets": [{"subnet": "10.88.0.0/16"}]}]), ""
            )
        if command == ["podman", "container", "exists", "api"]:
            return subprocess.CompletedProcess(command, 0, "", "")
        if command == ["podman", "inspect", "--type", "container", "api"]:
            details = {
                "State": {"Running": True},
                "NetworkSettings": {
                    "Networks": {"project-a": {"IPAddress": "10.89.1.5"}}
                },
            }
            return subprocess.CompletedProcess(command, 0, json.dumps([details]), "")
        raise AssertionError(f"unexpected command: {command}")

    validate_podman_state(
        {
            "gateway": {"networks": ["project-a"]},
            "networks": [{"name": "project-a", "subnet": "10.89.1.0/24"}],
            "dns_records": [
                {"name": "api.project-a.dev.internal", "container": "api", "network": "project-a"}
            ],
        },
        run_command=run_command,
        announce=lambda message: None,
    )

    assert len(calls) == 4


def test_validate_podman_state_rejects_overlapping_existing_network() -> None:
    """Reject a declared subnet that overlaps an existing Podman network."""
    def run_command(*args, **kwargs):
        command = list(args[0]) if len(args) == 1 and isinstance(args[0], list) else list(args)
        if command == ["podman", "network", "ls", "--format", "{{.Name}}"]:
            return subprocess.CompletedProcess(command, 0, "other\n", "")
        if command == ["podman", "network", "inspect", "other"]:
            return subprocess.CompletedProcess(
                command, 0, json.dumps([{"subnets": [{"subnet": "10.89.1.128/25"}]}]), ""
            )
        raise AssertionError(f"unexpected command: {command}")

    with pytest.raises(ValueError, match="overlaps existing Podman network"):
        validate_podman_state(
            {
                "gateway": {"networks": ["project-a"]},
                "networks": [{"name": "project-a", "subnet": "10.89.1.0/24"}],
                "dns_records": [],
            },
            run_command=run_command,
        )


def test_validate_podman_state_reports_stopped_target_as_pending() -> None:
    """Report stopped DNS targets without mutation or failure."""
    def run_command(*args, **kwargs):
        command = list(args[0]) if len(args) == 1 and isinstance(args[0], list) else list(args)
        if command == ["podman", "network", "ls", "--format", "{{.Name}}"]:
            return subprocess.CompletedProcess(command, 0, "", "")
        if command == ["podman", "container", "exists", "api"]:
            return subprocess.CompletedProcess(command, 0, "", "")
        if command == ["podman", "inspect", "--type", "container", "api"]:
            return subprocess.CompletedProcess(
                command, 0, json.dumps([{"State": {"Running": False}}]), ""
            )
        raise AssertionError(f"unexpected command: {command}")

    messages = []
    validate_podman_state(
        {
            "gateway": {"networks": ["project-a"]},
            "networks": [{"name": "project-a", "subnet": "10.89.1.0/24"}],
            "dns_records": [
                {"name": "api.project-a.dev.internal", "container": "api", "network": "project-a"}
            ],
        },
        run_command=run_command,
        announce=messages.append,
    )

    assert messages == [
        "[host-preflight] PENDING DNS target: api.project-a.dev.internal (api is stopped)"
    ]


def test_validate_podman_state_checks_generic_container_networks() -> None:
    """Check declared containers even when the host config has no gateway."""
    calls = []

    def run_command(*args, **kwargs):
        command = list(args[0]) if len(args) == 1 and isinstance(args[0], list) else list(args)
        calls.append(command)
        if command == ["podman", "network", "ls", "--format", "{{.Name}}"]:
            return subprocess.CompletedProcess(command, 0, "database\n", "")
        if command == ["podman", "network", "inspect", "database"]:
            return subprocess.CompletedProcess(
                command, 0, json.dumps([{"subnets": [{"subnet": "10.90.0.0/24"}]}]), ""
            )
        if command == ["podman", "container", "exists", "postgres"]:
            return subprocess.CompletedProcess(command, 0, "", "")
        if command == ["podman", "inspect", "--type", "container", "postgres"]:
            details = {
                "State": {"Running": True},
                "NetworkSettings": {
                    "Networks": {"database": {"IPAddress": "10.90.0.5"}}
                },
            }
            return subprocess.CompletedProcess(command, 0, json.dumps([details]), "")
        raise AssertionError(f"unexpected command: {command}")

    validate_podman_state(
        {
            "networks": [{"name": "database", "subnet": "10.90.0.0/24"}],
            "containers": [{"name": "postgres", "networks": ["database"]}],
        },
        run_command=run_command,
    )

    assert len(calls) == 4


def test_validate_podman_state_rejects_missing_generic_network() -> None:
    """Require declared networks to exist during generic host checks."""
    def run_command(*args, **kwargs):
        command = list(args[0]) if len(args) == 1 and isinstance(args[0], list) else list(args)
        if command == ["podman", "network", "ls", "--format", "{{.Name}}"]:
            return subprocess.CompletedProcess(command, 0, "", "")
        raise AssertionError(f"unexpected command: {command}")

    with pytest.raises(ValueError, match="declared host network 'database' is absent"):
        validate_podman_state(
            {"networks": [{"name": "database", "subnet": "10.90.0.0/24"}]},
            run_command=run_command,
        )