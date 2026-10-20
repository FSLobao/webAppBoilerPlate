"""Test readiness-scoped DNS record generation from Podman state."""

import subprocess
from typing import Any

import pytest

from scripts.gateway.dns_records import generate_dns_records

API_ID = "a" * 64


def _config() -> dict[str, Any]:
    """Return one configured DNS target."""
    return {
        "networks": [{"name": "project-a", "subnet": "10.89.1.0/24"}],
        "dns_records": [
            {
                "name": "api.project-a.dev.anatel",
                "container": "api",
                "network": "project-a",
            }
        ],
    }


def _podman_result(
    container: dict[str, Any], command: list[str], network_name: str
) -> subprocess.CompletedProcess[str]:
    """Return only minimal target readiness and requested network fields."""
    state = container["State"]
    networks = container["NetworkSettings"]["Networks"]
    address = networks.get(network_name, {}).get("IPAddress", "")
    fields = [
        container["Id"],
        container["Name"],
        str(state.get("Running", False)).lower(),
        state.get("Health", {}).get("Status", ""),
        address,
    ]
    return subprocess.CompletedProcess(command, 0, "|".join(fields), "")


def _inspection_command(command: list[str]) -> bool:
    """Return whether a runner received a scoped inspect command."""
    return (
        command[:4] == ["podman", "inspect", "--type", "container"]
        and len(command) == 7
        and command[4] == "--format"
    )


def test_generate_dns_records_uses_healthy_exact_container_identity() -> None:
    """Inspect the full ID and only the configured network's required fields."""
    inspected = {
        "Id": API_ID,
        "Name": "/api",
        "State": {"Running": True, "Health": {"Status": "healthy"}},
        "NetworkSettings": {"Networks": {"project-a": {"IPAddress": "10.89.1.5"}}},
    }
    calls: list[list[str]] = []

    def run_command(
        command: list[str], **kwargs: Any
    ) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        if command == ["podman", "container", "exists", API_ID]:
            return subprocess.CompletedProcess(command, 0, "", "")
        if _inspection_command(command):
            template = command[5]
            assert command[6] == API_ID
            assert '"project-a"' in template
            assert ".Config" not in template
            return _podman_result(inspected, command, "project-a")
        raise AssertionError(f"unexpected command: {command}")

    records = generate_dns_records(_config(), {"api": API_ID}, run_command=run_command)

    assert records == ["10.89.1.5 api.project-a.dev.anatel"]
    assert calls[0] == ["podman", "container", "exists", API_ID]
    assert calls[1][0:5] == [
        "podman",
        "inspect",
        "--type",
        "container",
        "--format",
    ]
    assert calls[1][5].find('"project-a"') >= 0
    assert calls[1][6] == API_ID


@pytest.mark.parametrize(
    ("state", "attached", "expected"),
    [
        ({"Running": False, "Health": {"Status": "healthy"}}, {}, []),
        ({"Running": True, "Health": {"Status": "starting"}}, {}, []),
        ({"Running": True}, {}, []),
        (
            {"Running": True, "Health": {"Status": "healthy"}},
            {"project-a": {"IPAddress": "10.89.1.5"}},
            ["10.89.1.5 api.project-a.dev.anatel"],
        ),
    ],
)
def test_unready_or_healthy_target_is_pending(
    state: dict[str, Any],
    attached: dict[str, Any],
    expected: list[str],
) -> None:
    """Do not publish targets until Podman reports running and healthy."""
    inspected = {
        "Id": API_ID,
        "Name": "/api",
        "State": state,
        "NetworkSettings": {"Networks": attached},
    }

    def run_command(
        command: list[str], **kwargs: Any
    ) -> subprocess.CompletedProcess[str]:
        if command == ["podman", "container", "exists", API_ID]:
            return subprocess.CompletedProcess(command, 0, "", "")
        if command == ["podman", "container", "exists", API_ID]:
            return subprocess.CompletedProcess(command, 0, "", "")
        if _inspection_command(command):
            return _podman_result(inspected, command, "project-a")
        raise AssertionError(f"unexpected command: {command}")

    assert generate_dns_records(_config(), {"api": API_ID}, run_command) == expected


def test_missing_target_identity_is_pending_without_podman_inspection() -> None:
    """An omitted configured target produces no record and needs no inspection."""
    calls: list[list[str]] = []

    def run_command(
        command: list[str], **kwargs: Any
    ) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        raise AssertionError("pending target must not be inspected")

    assert generate_dns_records(_config(), {}, run_command) == []
    assert calls == []


def test_missing_container_from_handoff_is_pending() -> None:
    """A target removed between readiness notification and inspection is pending."""

    def run_command(
        command: list[str], **kwargs: Any
    ) -> subprocess.CompletedProcess[str]:
        assert command == ["podman", "container", "exists", API_ID]
        return subprocess.CompletedProcess(command, 1, "", "")

    assert generate_dns_records(_config(), {"api": API_ID}, run_command) == []


def test_generate_dns_records_rejects_network_mismatch_before_output() -> None:
    """Reject a healthy target address outside its exact configured subnet."""
    inspected = {
        "Id": API_ID,
        "Name": "/api",
        "State": {"Running": True, "Health": {"Status": "healthy"}},
        "NetworkSettings": {"Networks": {"project-a": {"IPAddress": "10.90.1.5"}}},
    }

    def run_command(
        command: list[str], **kwargs: Any
    ) -> subprocess.CompletedProcess[str]:
        if command == ["podman", "container", "exists", API_ID]:
            return subprocess.CompletedProcess(command, 0, "", "")
        return _podman_result(inspected, command, "project-a")

    with pytest.raises(ValueError, match="invalid address"):
        generate_dns_records(_config(), {"api": API_ID}, run_command)


@pytest.mark.parametrize(
    "container",
    [
        {"Id": API_ID, "Name": "/replacement"},
        {"Id": "b" * 64, "Name": "/api"},
    ],
)
def test_stale_or_replaced_container_identity_is_pending(
    container: dict[str, Any],
) -> None:
    """Do not publish when an identity no longer names the configured target."""
    inspected = {
        **container,
        "State": {"Running": True, "Health": {"Status": "healthy"}},
        "NetworkSettings": {"Networks": {"project-a": {"IPAddress": "10.89.1.5"}}},
    }

    def run_command(
        command: list[str], **kwargs: Any
    ) -> subprocess.CompletedProcess[str]:
        if command == ["podman", "container", "exists", API_ID]:
            return subprocess.CompletedProcess(command, 0, "", "")
        return _podman_result(inspected, command, "project-a")

    if container["Id"] != API_ID:
        with pytest.raises(ValueError, match="identity changed"):
            generate_dns_records(_config(), {"api": API_ID}, run_command)
    else:
        assert generate_dns_records(_config(), {"api": API_ID}, run_command) == []


def test_dns_generator_rejects_gateway_networks_before_commands() -> None:
    """Reject the removed selector through the public DNS generation API."""
    calls: list[list[str]] = []

    def run_command(
        command: list[str], **kwargs: Any
    ) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        raise AssertionError("Podman must not be queried for an invalid config")

    with pytest.raises(ValueError, match="gateway.networks.*not supported"):
        generate_dns_records(
            {
                "gateway": {"networks": ["app-net"]},
                "networks": [{"name": "app-net", "subnet": "10.89.1.0/24"}],
                "dns_records": [],
            },
            {},
            run_command=run_command,
        )

    assert calls == []
