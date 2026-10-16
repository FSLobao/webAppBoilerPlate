"""Tests for Gateway host-preflight Python helpers."""

import json
import subprocess

import pytest

from scripts.gateway.host_preflight import (
    cockpit_password_is_valid,
    host_platform_matches_target,
    main,
    podman_version_matches_target,
    validate_podman_state,
)


@pytest.mark.parametrize(
    ("os_id", "os_version", "matches"),
    [
        ("rhel", "9.8", True),
        ("rhel", "9.7", False),
        ("rhel", "9.9", False),
        ("rocky", "9.8", False),
    ],
)
def test_host_platform_requirement(os_id: str, os_version: str, matches: bool) -> None:
    """Accept only RHEL 9.8 as the host deployment target."""
    assert host_platform_matches_target(os_id, os_version) is matches


@pytest.mark.parametrize(
    ("version", "matches"),
    [
        ("v5.8.2", True),
        ("5.8.2", True),
        ("5.8.1", False),
        ("5.9.0", False),
        ("5.8.2-dev", False),
        ("invalid", False),
    ],
)
def test_podman_version_requirement(version: str, matches: bool) -> None:
    """Accept only Podman 5.8.2 for host deployment."""
    assert podman_version_matches_target(version) is matches


@pytest.mark.parametrize(
    ("arguments", "status"),
    [
        (["host-platform", "rhel", "9.8"], 0),
        (["host-platform", "rhel", "9.9"], 1),
        (["podman-version", "5.8.2"], 0),
        (["podman-version", "5.8.1"], 1),
    ],
)
def test_target_cli_checks(arguments: list[str], status: int) -> None:
    """Return success only for the configured host and Podman targets."""
    assert main(arguments) == status


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


def test_validate_podman_state_checks_every_declared_podman_network() -> None:
    """Check each declared Podman network without treating routes as networks."""
    inspected_networks = []
    declarations = [
        {"name": "shared", "subnet": "10.89.1.0/24"},
        {"name": "application-net", "subnet": "10.89.2.0/24"},
        {"name": "newly-added-net", "subnet": "10.89.3.0/24"},
    ]

    def run_command(*args, **kwargs):
        command = list(args[0]) if len(args) == 1 else list(args)
        if command == ["podman", "network", "ls", "--format", "{{.Name}}"]:
            names = "\n".join(entry["name"] for entry in declarations)
            return subprocess.CompletedProcess(command, 0, names, "")
        if command[:3] == ["podman", "network", "inspect"]:
            network_name = command[3]
            inspected_networks.append(network_name)
            subnet = next(
                entry["subnet"]
                for entry in declarations
                if entry["name"] == network_name
            )
            details = [{"subnets": [{"subnet": subnet}]}]
            return subprocess.CompletedProcess(command, 0, json.dumps(details), "")
        raise AssertionError(f"unexpected command: {command}")

    validate_podman_state(
        {
            "networks": declarations,
            "application_gateway": {
                "enabled": True,
                "routes": [
                    {"frontend": "frontend-container", "backend": "external-service"}
                ],
            },
        },
        run_command=run_command,
    )

    assert inspected_networks == [
        "shared",
        "application-net",
        "newly-added-net",
    ]


def test_host_preflight_cli_rejects_nested_duplicate_keys(tmp_path, capsys) -> None:
    """Reject duplicate nested keys before invoking Podman during preflight."""
    config_path = tmp_path / "config.json"
    config_path.write_text(
        '{"schema_version": 1, "networks": [], '
        '"gateway": {"name": "invalid", "name": "gateway"}}',
        encoding="utf-8",
    )

    assert main(["podman-state", str(config_path)]) == 1
    assert "duplicate JSON object key" in capsys.readouterr().err


def test_host_preflight_cli_rejects_gateway_networks_before_podman(
    tmp_path, capsys
) -> None:
    """Reject the removed network selector before querying Podman."""
    config_path = tmp_path / "config.json"
    config_path.write_text(
        '{"gateway": {"networks": ["app-net"]}, "networks": []}',
        encoding="utf-8",
    )

    assert main(["podman-state", str(config_path)]) == 1
    assert "gateway.networks" in capsys.readouterr().err


def test_validate_podman_state_rejects_gateway_networks_before_commands() -> None:
    """Reject the removed network selector before any Podman command."""
    calls = []

    def run_command(*args, **kwargs):
        calls.append(args)
        raise AssertionError("Podman must not be queried for an invalid config")

    with pytest.raises(ValueError, match="gateway.networks.*not supported"):
        validate_podman_state(
            {
                "gateway": {"networks": ["app-net"]},
                "networks": [{"name": "app-net", "subnet": "10.89.1.0/24"}],
            },
            run_command=run_command,
        )

    assert calls == []