"""Tests for DNS host-record generation from Podman state."""

import json
import subprocess

import pytest

from scripts.gateway.dns_records import generate_dns_records, main


def test_generate_dns_records_uses_container_ipv4_address() -> None:
    """Render a configured name with its validated container IPv4 address."""
    def run_command(*args, **kwargs):
        command = list(args[0]) if len(args) == 1 and isinstance(args[0], list) else list(args)
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

    records = generate_dns_records(
        {
            "networks": [{"name": "project-a", "subnet": "10.89.1.0/24"}],
            "dns_records": [
                {"name": "api.project-a.dev.internal", "container": "api", "network": "project-a"}
            ],
        },
        run_command=run_command,
    )

    assert records == ["10.89.1.5 api.project-a.dev.internal"]


@pytest.mark.parametrize(
    ("container", "message"),
    [
        ({"State": {"Running": False}}, "stopped before DNS generation"),
        (
            {
                "State": {"Running": True},
                "NetworkSettings": {"Networks": {}},
            },
            "not attached to declared network",
        ),
        (
            {
                "State": {"Running": True},
                "NetworkSettings": {
                    "Networks": {"project-a": {"IPAddress": "10.90.1.5"}}
                },
            },
            "invalid address",
        ),
    ],
)
def test_generate_dns_records_rejects_invalid_target_state(container, message: str) -> None:
    """Reject stopped, unattached, and out-of-subnet DNS targets."""
    def run_command(*args, **kwargs):
        command = list(args[0]) if len(args) == 1 and isinstance(args[0], list) else list(args)
        if command == ["podman", "container", "exists", "api"]:
            return subprocess.CompletedProcess(command, 0, "", "")
        if command == ["podman", "inspect", "--type", "container", "api"]:
            return subprocess.CompletedProcess(command, 0, json.dumps([container]), "")
        raise AssertionError(f"unexpected command: {command}")

    with pytest.raises(ValueError, match=message):
        generate_dns_records(
            {
                "networks": [{"name": "project-a", "subnet": "10.89.1.0/24"}],
                "dns_records": [
                    {"name": "api.project-a.dev.internal", "container": "api", "network": "project-a"}
                ],
            },
            run_command=run_command,
        )


def test_dns_cli_rejects_duplicate_network_keys(tmp_path, capsys) -> None:
    """Reject duplicate config keys before DNS generation can inspect containers."""
    config_path = tmp_path / "config.json"
    config_path.write_text(
        '{"networks": [], "networks": [], "dns_records": []}',
        encoding="utf-8",
    )

    assert main([str(config_path)]) == 1
    assert "duplicate JSON object key" in capsys.readouterr().err


def test_dns_cli_rejects_gateway_networks_before_podman(tmp_path, capsys) -> None:
    """Reject the removed network selector before inspecting Podman."""
    config_path = tmp_path / "config.json"
    config_path.write_text(
        '{"gateway": {"networks": ["app-net"]}, '
        '"networks": [{"name": "app-net", "subnet": "10.89.1.0/24"}], '
        '"dns_records": []}',
        encoding="utf-8",
    )

    assert main([str(config_path)]) == 1
    assert "gateway.networks" in capsys.readouterr().err


def test_dns_generator_rejects_gateway_networks_before_commands() -> None:
    """Reject the removed selector through the public DNS generation API."""
    calls = []

    def run_command(*args, **kwargs):
        calls.append(args)
        raise AssertionError("Podman must not be queried for an invalid config")

    with pytest.raises(ValueError, match="gateway.networks.*not supported"):
        generate_dns_records(
            {
                "gateway": {"networks": ["app-net"]},
                "networks": [{"name": "app-net", "subnet": "10.89.1.0/24"}],
                "dns_records": [],
            },
            run_command=run_command,
        )

    assert calls == []