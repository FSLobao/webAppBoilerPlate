"""Test revision-protected, readiness-scoped Gateway DNS handoffs."""

import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from gateway.development.dns_refresh import (
    effective_config_revision,
    main,
    merge_scoped_hosts,
    render_handoff,
    validate_handoff_request,
)

API_ID = "a" * 64
WORKER_ID = "b" * 64
NEW_API_ID = "c" * 64


def _config() -> dict[str, Any]:
    """Return a host config with two independent DNS targets."""
    return {
        "schema_version": 1,
        "networks": [
            {"name": "project-a-net", "subnet": "10.89.1.0/24"},
            {"name": "project-b-net", "subnet": "10.89.2.0/24"},
        ],
        "dns_records": [
            {
                "name": "api.project-a.dev.anatel",
                "container": "api",
                "network": "project-a-net",
            },
            {
                "name": "worker.project-b.dev.anatel",
                "container": "worker",
                "network": "project-b-net",
            },
        ],
    }


def _request(
    config: dict[str, Any],
    scope: list[str],
    ready: list[dict[str, str]],
) -> dict[str, Any]:
    """Build one revision-bound target-scope handoff."""
    return {
        "config_revision": effective_config_revision(config),
        "target_scope": scope,
        "ready_targets": ready,
    }


def _inspect_result(
    container_name: str,
    container_id: str,
    address: str,
    network: str,
) -> dict[str, Any]:
    """Return one healthy exact-ID Podman inspection."""
    return {
        "Id": container_id,
        "Name": f"/{container_name}",
        "State": {"Running": True, "Health": {"Status": "healthy"}},
        "NetworkSettings": {"Networks": {network: {"IPAddress": address}}},
    }


def _runner_for(
    container: dict[str, Any], target_id: str
) -> Callable[..., subprocess.CompletedProcess[str]]:
    """Return an isolated command runner for a target inspection."""

    def run_command(
        command: list[str], **kwargs: Any
    ) -> subprocess.CompletedProcess[str]:
        if command == ["podman", "container", "exists", target_id]:
            return subprocess.CompletedProcess(command, 0, "", "")
        if (
            command[:4] == ["podman", "inspect", "--type", "container"]
            and command[6] == target_id
        ):
            networks = container["NetworkSettings"]["Networks"]
            network_name = next(iter(networks))
            state = container["State"]
            address = networks[network_name].get("IPAddress", "")
            fields = [
                container["Id"],
                container["Name"],
                str(state.get("Running", False)).lower(),
                state.get("Health", {}).get("Status", ""),
                address,
            ]
            assert f'"{network_name}"' in command[5]
            assert ".Config" not in command[5]
            return subprocess.CompletedProcess(command, 0, "|".join(fields), "")
        raise AssertionError(f"unexpected Podman command: {command}")

    return run_command


def test_effective_revision_is_canonical_and_sensitive_to_config() -> None:
    """Hash effective configuration independent of JSON object key ordering."""
    config = _config()
    reordered = {
        "dns_records": config["dns_records"],
        "networks": config["networks"],
        "schema_version": config["schema_version"],
    }

    assert effective_config_revision(config) == effective_config_revision(reordered)
    reordered["dns_records"] = []
    assert effective_config_revision(config) != effective_config_revision(reordered)


def test_valid_handoff_updates_only_its_configured_target_scope() -> None:
    """Publish refreshed target while retaining unrelated configured app DNS."""
    config = _config()
    request = _request(config, ["api"], [{"container": "api", "id": API_ID}])
    current = (
        "# generated\n"
        "10.89.1.4 api.project-a.dev.anatel\n"
        "10.89.2.8 worker.project-b.dev.anatel\n"
    )
    inspected = _inspect_result("api", API_ID, "10.89.1.9", "project-a-net")

    result = render_handoff(
        config,
        request,
        current,
        _runner_for(inspected, API_ID),
    )

    assert "10.89.1.9 api.project-a.dev.anatel" in result
    assert "10.89.1.4 api.project-a.dev.anatel" not in result
    assert "10.89.2.8 worker.project-b.dev.anatel" in result


def test_stopped_or_failed_event_removes_scoped_old_record() -> None:
    """An empty app-ready list removes prior target address without app inspection."""
    config = _config()
    request = _request(config, ["api"], [])
    current = (
        "10.89.1.4 api.project-a.dev.anatel\n10.89.2.8 worker.project-b.dev.anatel\n"
    )

    def unexpected_command(
        command: list[str], **kwargs: Any
    ) -> subprocess.CompletedProcess[str]:
        raise AssertionError("empty readiness scope must not inspect a container")

    result = render_handoff(config, request, current, unexpected_command)

    assert "10.89.1.4 api.project-a.dev.anatel" not in result
    assert "# PENDING DNS target: api.project-a.dev.anatel" in result
    assert "10.89.2.8 worker.project-b.dev.anatel" in result


def test_replacement_identity_publishes_new_address_without_old_fallback() -> None:
    """Replace a container ID and address within one scoped handoff."""
    config = _config()
    request = _request(config, ["api"], [{"container": "api", "id": NEW_API_ID}])
    current = "10.89.1.4 api.project-a.dev.anatel\n"
    inspected = _inspect_result("api", NEW_API_ID, "10.89.1.11", "project-a-net")

    result = render_handoff(
        config,
        request,
        current,
        _runner_for(inspected, NEW_API_ID),
    )

    assert "10.89.1.11 api.project-a.dev.anatel" in result
    assert "10.89.1.4 api.project-a.dev.anatel" not in result


@pytest.mark.parametrize(
    ("state", "expected_address"),
    [
        ({"Running": False, "Health": {"Status": "healthy"}}, None),
        ({"Running": True, "Health": {"Status": "unhealthy"}}, None),
        ({"Running": True, "Health": {"Status": "healthy"}}, "10.89.1.9"),
    ],
)
def test_unready_handoff_removes_old_address_and_never_falls_back(
    state: dict[str, Any], expected_address: str | None
) -> None:
    """Publish only running healthy target addresses after reinspection."""
    config = _config()
    request = _request(config, ["api"], [{"container": "api", "id": API_ID}])
    inspected = _inspect_result("api", API_ID, "10.89.1.9", "project-a-net")
    inspected["State"] = state

    result = render_handoff(
        config,
        request,
        "10.89.1.4 api.project-a.dev.anatel\n",
        _runner_for(inspected, API_ID),
    )

    assert "10.89.1.4 api.project-a.dev.anatel" not in result
    if expected_address:
        assert f"{expected_address} api.project-a.dev.anatel" in result
    else:
        assert "# PENDING DNS target: api.project-a.dev.anatel" in result


@pytest.mark.parametrize(
    ("scope", "ready", "message"),
    [
        ([], [], "target_scope"),
        (["missing"], [], "target_scope"),
        (["api"], [{"container": "worker", "id": WORKER_ID}], "outside target_scope"),
        (["api"], [{"container": "api", "id": "short"}], "full ID"),
        (
            ["api"],
            [
                {"container": "api", "id": API_ID},
                {"container": "api", "id": NEW_API_ID},
            ],
            "duplicate",
        ),
    ],
)
def test_invalid_handoff_scope_fails_before_inspection(
    scope: list[str],
    ready: list[dict[str, str]],
    message: str,
) -> None:
    """Reject unknown, out-of-scope, malformed, and duplicate target identities."""
    config = _config()
    with pytest.raises(ValueError, match=message):
        validate_handoff_request(config, _request(config, scope, ready))


def test_stale_revision_fails_before_target_inspection() -> None:
    """Reject old host config revision before asking Podman for app state."""
    config = _config()
    request = _request(config, ["api"], [{"container": "api", "id": API_ID}])
    request["config_revision"] = "sha256:" + ("0" * 64)

    def unexpected_command(
        command: list[str], **kwargs: Any
    ) -> subprocess.CompletedProcess[str]:
        raise AssertionError("stale configuration must fail before inspection")

    with pytest.raises(ValueError, match="stale"):
        render_handoff(config, request, "", unexpected_command)


def test_merge_drops_unconfigured_host_entries() -> None:
    """Do not preserve entries outside the single configured DNS inventory."""
    result = merge_scoped_hosts(
        _config(),
        "10.89.1.4 api.project-a.dev.anatel\n192.0.2.4 unmanaged.example\n",
        ["api"],
        [],
    )

    assert "unmanaged.example" not in result
    assert "10.89.1.4 api.project-a.dev.anatel" not in result


def test_request_revision_cli_rejects_duplicate_keys(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Reject duplicate readiness envelope keys before returning a revision."""
    request_path = tmp_path / "request.json"
    request_path.write_text(
        '{"config_revision":"sha256:'
        + "0" * 64
        + '","target_scope":[],"target_scope":[],"ready_targets":[]}',
        encoding="utf-8",
    )

    assert main(["request-revision", str(request_path)]) == 1
    assert "duplicate JSON object key" in capsys.readouterr().err
