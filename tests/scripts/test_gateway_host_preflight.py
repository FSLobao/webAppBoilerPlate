"""Tests for Gateway host-preflight Python helpers."""

from __future__ import annotations

import errno
import json
import socket
import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import Mock

import pytest

from scripts.gateway import host_preflight, wireguard_kernel
from scripts.gateway.host_preflight import (
    cockpit_password_is_valid,
    host_platform_matches_target,
    main,
    podman_version_matches_target,
    selinux_mode_matches_target,
    validate_gateway_networks,
    validate_podman_state,
)

IP_ROUTE_COMMAND = ["ip", "-j", "-4", "route", "show", "table", "all"]


def test_wireguard_server_key_path_must_resolve_outside_repository(
    tmp_path: Path,
) -> None:
    """Reject key paths and parent symlinks that resolve into the source tree."""
    repository = tmp_path / "repository"
    secret_directory = repository / "secrets"
    secret_directory.mkdir(parents=True)
    repository_key = secret_directory / "server.key"
    repository_key.write_text("synthetic", encoding="ascii")
    external_directory = tmp_path / "host-secrets"
    external_directory.mkdir()
    external_key = external_directory / "server.key"
    external_key.write_text("synthetic", encoding="ascii")
    link_directory = tmp_path / "host-link"
    link_directory.symlink_to(secret_directory, target_is_directory=True)

    host_preflight._require_external_key_path(external_key, repository)
    with pytest.raises(ValueError, match="outside the Git repository"):
        host_preflight._require_external_key_path(repository_key, repository)
    with pytest.raises(ValueError, match="outside the Git repository"):
        host_preflight._require_external_key_path(
            link_directory / "server.key", repository
        )


def test_missing_wireguard_server_key_is_planned_for_apply(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Allow a missing external key during read-only preflight."""
    repository = tmp_path / "repository"
    repository.mkdir()
    key_path = tmp_path / "host-secrets" / "wireguard" / "server.key"
    messages: list[str] = []
    monkeypatch.setattr(
        host_preflight, "_validate_wireguard_key_directory", lambda _path: None
    )

    host_preflight._validate_wireguard_server_key_path(
        key_path, repository, messages.append
    )

    assert not key_path.exists()
    expected_message = (
        "[host-preflight] PENDING: WireGuard server key will be generated "
        f"during --apply at {key_path}."
    )
    assert messages == [expected_message]


def test_missing_wireguard_server_key_inside_repository_is_rejected(
    tmp_path: Path,
) -> None:
    """Keep planned key creation outside the source checkout."""
    repository = tmp_path / "repository"
    repository.mkdir()
    key_path = repository / "secrets" / "server.key"

    with pytest.raises(ValueError, match="outside the Git repository"):
        host_preflight._validate_wireguard_server_key_path(
            key_path, repository, lambda _message: None
        )


def test_wireguard_udp_preflight_probes_selected_bind_and_port(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Probe the configured UDP listener without retaining a host socket."""
    probe = Mock()
    probe.__enter__ = Mock(return_value=probe)
    probe.__exit__ = Mock(return_value=None)
    monkeypatch.setattr(host_preflight.socket, "socket", Mock(return_value=probe))

    host_preflight._validate_wireguard_udp_listener(
        {"host_bind_address": "0.0.0.0", "listen_port": 1194}
    )

    host_preflight.socket.socket.assert_called_once_with(
        socket.AF_INET, socket.SOCK_DGRAM
    )
    probe.bind.assert_called_once_with(("0.0.0.0", 1194))
    probe.__exit__.assert_called_once()


def test_wireguard_udp_preflight_rejects_occupied_port(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Report a UDP port already bound on the selected host address."""
    probe = Mock()
    probe.__enter__ = Mock(return_value=probe)
    probe.__exit__ = Mock(return_value=None)
    probe.bind.side_effect = OSError(errno.EADDRINUSE, "address already in use")
    monkeypatch.setattr(host_preflight.socket, "socket", Mock(return_value=probe))

    with pytest.raises(ValueError, match="UDP port 1194 is already in use"):
        host_preflight._validate_wireguard_udp_listener(
            {"host_bind_address": "0.0.0.0", "listen_port": 1194}
        )

    probe.__exit__.assert_called_once()


def test_wireguard_preflight_reuses_udp_port_of_active_gateway(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Skip the bind probe when the active Gateway already owns its listener."""
    monkeypatch.setattr(
        host_preflight, "check_wireguard_kernel_support", lambda **_kwargs: True
    )
    monkeypatch.setattr(
        host_preflight, "_validate_wireguard_server_key_path", lambda *_args: None
    )
    listener_probe = Mock(side_effect=AssertionError("unexpected UDP bind probe"))
    monkeypatch.setattr(
        host_preflight, "_validate_wireguard_udp_listener", listener_probe
    )
    wireguard = {
        "enabled": True,
        "host_bind_address": "0.0.0.0",
        "listen_port": 1194,
        "server_private_key_path": str(tmp_path / "server.key"),
    }

    host_preflight._validate_wireguard_inputs(
        {"gateway": {"remote_access": {"wireguard": wireguard}}},
        lambda _message: None,
        lambda *_args, **_kwargs: None,
        gateway_listener_active=True,
    )

    listener_probe.assert_not_called()


def test_wireguard_module_preflight_is_read_only_and_reports_load_plan(
    tmp_path: Path,
) -> None:
    """Dry-run modprobe when WireGuard is available but not yet loaded."""
    module_path = tmp_path / "sys" / "module" / "wireguard"
    modprobe_path = tmp_path / "usr" / "sbin" / "modprobe"
    calls: list[list[str]] = []

    def run_command(
        command: list[str], **kwargs: Any
    ) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        assert kwargs == {
            "check": False,
            "capture_output": True,
            "text": True,
        }
        return subprocess.CompletedProcess(
            command, 0, "insmod /lib/modules/wireguard.ko\n", ""
        )

    loaded = wireguard_kernel.check_wireguard_kernel_support(
        run_command=run_command,
        module_path=module_path,
        modprobe_path=modprobe_path,
    )

    assert not loaded
    assert not module_path.exists()
    assert calls == [
        [
            str(modprobe_path),
            "--use-blacklist",
            "--dry-run",
            "--verbose",
            "wireguard",
        ]
    ]


def test_wireguard_host_preflight_reports_planned_module_load(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Allow an unloaded, loadable module and report the apply action."""
    module_path = tmp_path / "sys" / "module" / "wireguard"
    modprobe_path = tmp_path / "usr" / "sbin" / "modprobe"
    calls: list[list[str]] = []

    def run_command(
        command: list[str], **kwargs: Any
    ) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        return subprocess.CompletedProcess(
            command, 0, "insmod /lib/modules/wireguard.ko\n", ""
        )

    monkeypatch.setattr(
        host_preflight,
        "check_wireguard_kernel_support",
        lambda *, run_command: wireguard_kernel.check_wireguard_kernel_support(
            run_command=run_command,
            module_path=module_path,
            modprobe_path=modprobe_path,
        ),
    )
    monkeypatch.setattr(
        host_preflight, "_validate_wireguard_server_key_path", lambda *_args: None
    )
    monkeypatch.setattr(
        host_preflight, "_validate_wireguard_udp_listener", lambda _wireguard: None
    )
    wireguard = {
        "enabled": True,
        "host_bind_address": "127.0.0.1",
        "listen_port": 1194,
        "server_private_key_path": str(tmp_path / "server.key"),
    }
    messages: list[str] = []

    host_preflight._validate_wireguard_inputs(
        {"gateway": {"remote_access": {"wireguard": wireguard}}},
        messages.append,
        run_command,
    )

    assert messages == [
        (
            "[host-preflight] PENDING: WireGuard kernel support will be loaded "
            "during --apply and each Gateway service start."
        )
    ]
    assert len(calls) == 1
    assert not module_path.exists()


def test_wireguard_module_preflight_rejects_unavailable_support(
    tmp_path: Path,
) -> None:
    """Reject an unloaded WireGuard module when modprobe cannot resolve it."""
    modprobe_path = tmp_path / "usr" / "sbin" / "modprobe"

    def run_command(
        command: list[str], **kwargs: Any
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            command, 1, "", "modprobe: FATAL: Module wireguard not found"
        )

    with pytest.raises(wireguard_kernel.WireGuardKernelError, match="not found"):
        wireguard_kernel.check_wireguard_kernel_support(
            run_command=run_command,
            module_path=tmp_path / "sys" / "module" / "wireguard",
            modprobe_path=modprobe_path,
        )


def test_wireguard_module_load_verifies_sysfs_after_modprobe(
    tmp_path: Path,
) -> None:
    """Load WireGuard and confirm the kernel exposes the module."""
    module_path = tmp_path / "sys" / "module" / "wireguard"
    modprobe_path = tmp_path / "usr" / "sbin" / "modprobe"
    calls: list[list[str]] = []

    def run_command(
        command: list[str], **kwargs: Any
    ) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        module_path.mkdir(parents=True)
        return subprocess.CompletedProcess(command, 0, "", "")

    loaded = wireguard_kernel.load_wireguard_kernel_support(
        run_command=run_command,
        module_path=module_path,
        modprobe_path=modprobe_path,
    )

    assert loaded
    assert calls == [[str(modprobe_path), "--use-blacklist", "wireguard"]]


def test_wireguard_module_load_is_idempotent_when_already_loaded(
    tmp_path: Path,
) -> None:
    """Do not invoke modprobe again when the kernel module is already loaded."""
    module_path = tmp_path / "sys" / "module" / "wireguard"
    module_path.mkdir(parents=True)

    def run_command(
        command: list[str], **kwargs: Any
    ) -> subprocess.CompletedProcess[str]:
        raise AssertionError(f"unexpected command: {command}")

    loaded = wireguard_kernel.load_wireguard_kernel_support(
        run_command=run_command,
        module_path=module_path,
        modprobe_path=tmp_path / "usr" / "sbin" / "modprobe",
    )

    assert not loaded


def test_wireguard_module_load_rejects_success_without_loaded_module(
    tmp_path: Path,
) -> None:
    """Reject modprobe success when WireGuard never appears in sysfs."""
    modprobe_path = tmp_path / "usr" / "sbin" / "modprobe"

    def run_command(
        command: list[str], **kwargs: Any
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(command, 0, "", "")

    with pytest.raises(
        wireguard_kernel.WireGuardKernelError, match="sys/module/wireguard is absent"
    ):
        wireguard_kernel.load_wireguard_kernel_support(
            run_command=run_command,
            module_path=tmp_path / "sys" / "module" / "wireguard",
            modprobe_path=modprobe_path,
        )


def _fake_ip_routes(
    command: list[str], routes: list[dict[str, Any]] | None = None
) -> subprocess.CompletedProcess[str] | None:
    """Return a deterministic response for the read-only ip route command."""
    if command != IP_ROUTE_COMMAND:
        return None
    return subprocess.CompletedProcess(command, 0, json.dumps(routes or []), "")


@pytest.mark.parametrize(
    "route",
    [
        {"dst": "10.89.1.0/24", "dev": "eth0", "table": "main"},
        {"dst": "10.89.0.0/16", "dev": "eth0", "table": "100"},
        {"type": "local", "dst": "10.89.1.25", "dev": "lo", "table": "local"},
    ],
)
def test_gateway_preflight_rejects_overlapping_host_routes(
    route: dict[str, Any],
) -> None:
    """Reject host subnet, supernet, and local-address route conflicts."""
    calls = []

    def run_command(*args, **kwargs):
        command = list(args[0])
        calls.append(command)
        if command == ["podman", "network", "ls", "--format", "{{.Name}}"]:
            return subprocess.CompletedProcess(command, 0, "", "")
        route_result = _fake_ip_routes(command, [route])
        if route_result is not None:
            return route_result
        raise AssertionError(f"unexpected command: {command}")

    with pytest.raises(ValueError, match="overlaps host IPv4 route"):
        validate_gateway_networks(
            {"networks": [{"name": "project-a", "subnet": "10.89.1.0/24"}]},
            run_command=run_command,
            announce=lambda message: None,
        )

    assert calls == [
        ["podman", "network", "ls", "--format", "{{.Name}}"],
        IP_ROUTE_COMMAND,
    ]


def test_gateway_preflight_ignores_default_route() -> None:
    """Ignore IPv4 default routes when checking declared network overlaps."""

    def run_command(*args, **kwargs):
        command = list(args[0])
        if command == ["podman", "network", "ls", "--format", "{{.Name}}"]:
            return subprocess.CompletedProcess(command, 0, "", "")
        route_result = _fake_ip_routes(
            command,
            [
                {"dst": "default", "gateway": "192.0.2.1", "dev": "eth0"},
                {"dst": "0.0.0.0/0", "gateway": "192.0.2.1", "dev": "eth0"},
            ],
        )
        if route_result is not None:
            return route_result
        raise AssertionError(f"unexpected command: {command}")

    validate_gateway_networks(
        {"networks": [{"name": "project-a", "subnet": "10.89.1.0/24"}]},
        run_command=run_command,
        announce=lambda message: None,
    )


def test_gateway_preflight_allows_exact_managed_podman_routes() -> None:
    """Allow exact connected, local, and broadcast routes from the Podman bridge."""

    def run_command(*args, **kwargs):
        command = list(args[0])
        if command == ["podman", "network", "ls", "--format", "{{.Name}}"]:
            return subprocess.CompletedProcess(command, 0, "project-a\n", "")
        if command == ["podman", "network", "inspect", "project-a"]:
            details = [
                {
                    "network_interface": "podman42",
                    "subnets": [{"subnet": "10.89.1.0/24", "gateway": "10.89.1.1"}],
                }
            ]
            return subprocess.CompletedProcess(command, 0, json.dumps(details), "")
        route_result = _fake_ip_routes(
            command,
            [
                {
                    "dst": "10.89.1.0/24",
                    "dev": "podman42",
                    "protocol": "kernel",
                    "scope": "link",
                    "table": "main",
                },
                {
                    "type": "local",
                    "dst": "10.89.1.1",
                    "dev": "podman42",
                    "protocol": "kernel",
                    "scope": "host",
                    "table": "local",
                },
                {
                    "type": "broadcast",
                    "dst": "10.89.1.255",
                    "dev": "podman42",
                    "protocol": "kernel",
                    "scope": "link",
                    "table": "local",
                },
            ],
        )
        if route_result is not None:
            return route_result
        raise AssertionError(f"unexpected command: {command}")

    validate_gateway_networks(
        {"networks": [{"name": "project-a", "subnet": "10.89.1.0/24"}]},
        run_command=run_command,
        announce=lambda message: None,
    )


@pytest.mark.parametrize(
    "route",
    [
        {
            "dst": "10.89.1.0/24",
            "dev": "podman99",
            "protocol": "kernel",
            "scope": "link",
            "table": "main",
        },
        {
            "dst": "10.89.1.0/24",
            "dev": "podman42",
            "protocol": "dhcp",
            "scope": "link",
            "table": "main",
        },
        {
            "dst": "10.89.1.0/24",
            "dev": "podman42",
            "protocol": "kernel",
            "scope": "link",
            "table": "100",
        },
        {
            "type": "broadcast",
            "dst": "10.89.1.254",
            "dev": "podman42",
            "protocol": "kernel",
            "scope": "link",
            "table": "local",
        },
    ],
)
def test_gateway_preflight_rejects_spoofed_or_ambiguous_podman_routes(
    route: dict[str, Any],
) -> None:
    """Reject routes that only resemble a declared Podman connected route."""

    def run_command(*args, **kwargs):
        command = list(args[0])
        if command == ["podman", "network", "ls", "--format", "{{.Name}}"]:
            return subprocess.CompletedProcess(command, 0, "project-a\n", "")
        if command == ["podman", "network", "inspect", "project-a"]:
            details = [
                {
                    "network_interface": "podman42",
                    "subnets": [{"subnet": "10.89.1.0/24", "gateway": "10.89.1.1"}],
                }
            ]
            return subprocess.CompletedProcess(command, 0, json.dumps(details), "")
        route_result = _fake_ip_routes(command, [route])
        if route_result is not None:
            return route_result
        raise AssertionError(f"unexpected command: {command}")

    with pytest.raises(ValueError, match="overlaps host IPv4 route"):
        validate_gateway_networks(
            {"networks": [{"name": "project-a", "subnet": "10.89.1.0/24"}]},
            run_command=run_command,
            announce=lambda message: None,
        )


def test_generic_preflight_rejects_host_route_before_container_inspection() -> None:
    """Apply host-route checks to generic configs before inspecting containers."""
    calls = []

    def run_command(*args, **kwargs):
        command = list(args[0])
        calls.append(command)
        if command == ["podman", "network", "ls", "--format", "{{.Name}}"]:
            return subprocess.CompletedProcess(command, 0, "database\n", "")
        if command == ["podman", "network", "inspect", "database"]:
            details = [
                {
                    "network_interface": "podman8",
                    "subnets": [{"subnet": "10.90.0.0/24", "gateway": "10.90.0.1"}],
                }
            ]
            return subprocess.CompletedProcess(command, 0, json.dumps(details), "")
        route_result = _fake_ip_routes(
            command,
            [{"dst": "10.90.0.0/16", "dev": "eth0", "table": "main"}],
        )
        if route_result is not None:
            return route_result
        raise AssertionError(f"unexpected command: {command}")

    with pytest.raises(ValueError, match="overlaps host IPv4 route"):
        validate_podman_state(
            {
                "networks": [{"name": "database", "subnet": "10.90.0.0/24"}],
                "containers": [{"name": "postgres", "networks": ["database"]}],
            },
            run_command=run_command,
        )

    assert all(command[:2] != ["podman", "container"] for command in calls)
    assert all(command[:2] != ["podman", "inspect"] for command in calls)


@pytest.mark.parametrize(
    ("returncode", "stdout", "stderr", "message"),
    [
        (2, "", "permission denied", "permission denied"),
        (0, "{broken", "", "Expecting property name"),
        (0, "{}", "", "JSON array"),
    ],
)
def test_gateway_preflight_fails_on_route_command_or_json_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    returncode: int,
    stdout: str,
    stderr: str,
    message: str,
) -> None:
    """Report route command and malformed route JSON errors as preflight failures."""
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps({"networks": [{"name": "project-a", "subnet": "10.89.1.0/24"}]}),
        encoding="utf-8",
    )
    calls = []

    def run_command(
        command: list[str], **kwargs: Any
    ) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        if command == ["podman", "network", "ls", "--format", "{{.Name}}"]:
            return subprocess.CompletedProcess(command, 0, "", "")
        return subprocess.CompletedProcess(command, returncode, stdout, stderr)

    monkeypatch.setattr(host_preflight.subprocess, "run", run_command)

    assert main(["gateway-networks", str(config_path)]) == 1
    assert message in capsys.readouterr().err
    assert calls == [
        ["podman", "network", "ls", "--format", "{{.Name}}"],
        IP_ROUTE_COMMAND,
    ]


def test_gateway_preflight_reports_missing_ip_command(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Fail clearly when the route-inspection command cannot launch."""
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps({"networks": [{"name": "project-a", "subnet": "10.89.1.0/24"}]}),
        encoding="utf-8",
    )
    calls = []

    def run_command(
        command: list[str], **kwargs: Any
    ) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        if command == ["podman", "network", "ls", "--format", "{{.Name}}"]:
            return subprocess.CompletedProcess(command, 0, "", "")
        raise FileNotFoundError("ip executable missing")

    monkeypatch.setattr(host_preflight.subprocess, "run", run_command)

    assert main(["gateway-networks", str(config_path)]) == 1
    assert "ip executable missing" in capsys.readouterr().err
    assert calls == [
        ["podman", "network", "ls", "--format", "{{.Name}}"],
        IP_ROUTE_COMMAND,
    ]


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
        (["selinux-mode", "Disabled"], 0),
        (["selinux-mode", "Enforcing"], 1),
        (["selinux-mode", "Permissive"], 1),
    ],
)
def test_target_cli_checks(arguments: list[str], status: int) -> None:
    """Return success only for the configured host and Podman targets."""
    assert main(arguments) == status


@pytest.mark.parametrize(
    ("mode", "matches"),
    [
        ("Disabled", True),
        ("Enforcing", False),
        ("Permissive", False),
        ("unknown", False),
    ],
)
def test_selinux_mode_requirement(mode: str, matches: bool) -> None:
    """Accept only SELinux Disabled without changing its mode."""
    assert selinux_mode_matches_target(mode) is matches


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
        command = (
            list(args[0])
            if len(args) == 1 and isinstance(args[0], (list, tuple))
            else list(args)
        )
        calls.append(command)
        route_result = _fake_ip_routes(command)
        if route_result is not None:
            return route_result
        if command == ["podman", "network", "ls", "--format", "{{.Name}}"]:
            return subprocess.CompletedProcess(command, 0, "bridge\nproject-a\n", "")
        if command == ["podman", "network", "inspect", "bridge"]:
            return subprocess.CompletedProcess(
                command, 0, json.dumps([{"subnets": [{"subnet": "10.88.0.0/16"}]}]), ""
            )
        if command == ["podman", "network", "inspect", "project-a"]:
            return subprocess.CompletedProcess(
                command,
                0,
                json.dumps([{"subnets": [{"subnet": "10.89.1.0/24"}]}]),
                "",
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
                {
                    "name": "api.project-a.dev.anatel",
                    "container": "api",
                    "network": "project-a",
                }
            ],
        },
        run_command=run_command,
        announce=lambda message: None,
    )

    assert len(calls) == 6


def test_validate_podman_state_rejects_overlapping_existing_network() -> None:
    """Reject a declared subnet that overlaps an existing Podman network."""

    def run_command(*args, **kwargs):
        command = (
            list(args[0])
            if len(args) == 1 and isinstance(args[0], (list, tuple))
            else list(args)
        )
        route_result = _fake_ip_routes(command)
        if route_result is not None:
            return route_result
        if command == ["podman", "network", "ls", "--format", "{{.Name}}"]:
            return subprocess.CompletedProcess(command, 0, "other\n", "")
        if command == ["podman", "network", "inspect", "other"]:
            return subprocess.CompletedProcess(
                command,
                0,
                json.dumps([{"subnets": [{"subnet": "10.89.1.128/25"}]}]),
                "",
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
        command = (
            list(args[0])
            if len(args) == 1 and isinstance(args[0], (list, tuple))
            else list(args)
        )
        route_result = _fake_ip_routes(command)
        if route_result is not None:
            return route_result
        if command == ["podman", "network", "ls", "--format", "{{.Name}}"]:
            return subprocess.CompletedProcess(command, 0, "project-a\n", "")
        if command == ["podman", "network", "inspect", "project-a"]:
            return subprocess.CompletedProcess(
                command,
                0,
                json.dumps([{"subnets": [{"subnet": "10.89.1.0/24"}]}]),
                "",
            )
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
                {
                    "name": "api.project-a.dev.anatel",
                    "container": "api",
                    "network": "project-a",
                }
            ],
        },
        run_command=run_command,
        announce=messages.append,
    )

    assert messages == [
        "[host-preflight] PENDING DNS target: api.project-a.dev.anatel (api is stopped)"
    ]


def test_validate_podman_state_checks_generic_container_networks() -> None:
    """Check declared containers even when the host config has no gateway."""
    calls = []

    def run_command(*args, **kwargs):
        command = (
            list(args[0])
            if len(args) == 1 and isinstance(args[0], (list, tuple))
            else list(args)
        )
        calls.append(command)
        route_result = _fake_ip_routes(command)
        if route_result is not None:
            return route_result
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

    assert len(calls) == 5


def test_validate_podman_state_rejects_missing_generic_network() -> None:
    """Require declared networks to exist during generic host checks."""

    def run_command(*args, **kwargs):
        command = (
            list(args[0])
            if len(args) == 1 and isinstance(args[0], (list, tuple))
            else list(args)
        )
        route_result = _fake_ip_routes(command)
        if route_result is not None:
            return route_result
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
        route_result = _fake_ip_routes(command)
        if route_result is not None:
            return route_result
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
            "http_proxy": {
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


def test_gateway_preflight_is_read_only_without_application_targets(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Report planned networks and pending DNS without querying app containers."""
    config_path = tmp_path / "gateway-config.json"
    config_path.write_text(
        json.dumps(
            {
                "gateway": {"name": "gateway"},
                "networks": [{"name": "project-a", "subnet": "10.89.1.0/24"}],
                "containers": [
                    {"name": "api", "networks": ["project-a"]},
                    {"name": "nginx", "networks": ["project-a"]},
                ],
                "dns_records": [
                    {
                        "name": "api.project-a.dev.anatel",
                        "container": "api",
                        "network": "project-a",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    calls = []

    def run_command(
        command: tuple[str, ...] | list[str], **kwargs: Any
    ) -> subprocess.CompletedProcess[str]:
        normalized = list(command)
        calls.append(normalized)
        route_result = _fake_ip_routes(normalized)
        if route_result is not None:
            return route_result
        assert normalized == [
            "podman",
            "network",
            "ls",
            "--format",
            "{{.Name}}",
        ]
        return subprocess.CompletedProcess(normalized, 0, "", "")

    monkeypatch.setattr(host_preflight.subprocess, "run", run_command)

    assert main(["gateway-networks", str(config_path)]) == 0

    captured = capsys.readouterr()
    assert (
        "[host-preflight] PENDING network creation: project-a (10.89.1.0/24)"
        in captured.out
    )
    assert (
        "[host-preflight] PENDING DNS target: api.project-a.dev.anatel "
        "(api readiness/unverified)"
    ) in captured.out
    assert calls == [
        ["podman", "network", "ls", "--format", "{{.Name}}"],
        IP_ROUTE_COMMAND,
    ]
    assert captured.err == ""


def test_gateway_networks_cli_accepts_active_gateway_listener(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Pass active Gateway ownership through the read-only preflight CLI."""
    received: dict[str, Any] = {}

    monkeypatch.setattr(host_preflight, "load_host_config", lambda _path: {})
    monkeypatch.setattr(
        host_preflight,
        "validate_gateway_networks",
        lambda config, run_command, *, gateway_listener_active=False: received.update(
            config=config,
            run_command=run_command,
            gateway_listener_active=gateway_listener_active,
        ),
    )

    assert (
        main(
            [
                "gateway-networks",
                "/tmp/host_config.json",
                "--gateway-listener-active",
            ]
        )
        == 0
    )
    assert received["gateway_listener_active"] is True
    assert received["run_command"] is subprocess.run


@pytest.mark.parametrize(
    ("existing_name", "existing_subnet", "message"),
    [
        ("other", "10.89.1.128/25", "overlaps existing Podman network"),
        ("project-a", "10.90.0.0/24", "does not match declared subnet"),
    ],
)
def test_gateway_preflight_rejects_incompatible_network_before_mutation(
    existing_name: str, existing_subnet: str, message: str
) -> None:
    """Reject network overlap or mismatch before any mutating Podman command."""
    calls = []

    def run_command(
        command: tuple[str, ...] | list[str], **kwargs: Any
    ) -> subprocess.CompletedProcess[str]:
        normalized = list(command)
        calls.append(normalized)
        if normalized == ["podman", "network", "ls", "--format", "{{.Name}}"]:
            return subprocess.CompletedProcess(normalized, 0, f"{existing_name}\n", "")
        if normalized == ["podman", "network", "inspect", existing_name]:
            output = json.dumps([{"subnets": [{"subnet": existing_subnet}]}])
            return subprocess.CompletedProcess(normalized, 0, output, "")
        raise AssertionError(f"unexpected command: {normalized}")

    with pytest.raises(ValueError, match=message):
        validate_gateway_networks(
            {"networks": [{"name": "project-a", "subnet": "10.89.1.0/24"}]},
            run_command=run_command,
            announce=lambda message: None,
        )

    assert calls == [
        ["podman", "network", "ls", "--format", "{{.Name}}"],
        ["podman", "network", "inspect", existing_name],
    ]
