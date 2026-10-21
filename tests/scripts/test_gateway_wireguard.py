"""Test WireGuard configuration, one-time delivery, and peer lifecycle."""

from __future__ import annotations

import errno
import hashlib
import io
import ipaddress
import json
import os
import pty
import select
import signal
import subprocess
import time
from pathlib import Path
from typing import Any

import pytest

from gateway.development import wireguard
from scripts.gateway.remote_access import validate_remote_access_config

PRIVATE_KEY = "p" * 43 + "="
PEER_PUBLIC_KEY = "a" * 43 + "="
SERVER_PUBLIC_KEY = "b" * 43 + "="


def _config() -> dict[str, Any]:
    """Return a test-only IPv4 WireGuard deployment declaration."""
    return {
        "gateway": {
            "remote_access": {
                "openvpn": {
                    "enabled": False,
                    "profile_path": "/etc/gateway/openvpn/client.ovpn",
                    "client_pool": "172.24.0.0/21",
                },
                "ssh_tun": {"enabled": False},
                "wireguard": {
                    "enabled": True,
                    "host_bind_address": "0.0.0.0",
                    "listen_port": 54000,
                    "address_pool": "198.18.0.0/24",
                    "server_address": "10.254.0.1",
                    "dns_server": "192.168.9.2",
                    "server_private_key_path": "/etc/gateway/wireguard/server.key",
                },
            }
        },
        "networks": [
            {
                "name": "shared",
                "subnet": "192.168.9.0/24",
                "gateway_address": "192.168.9.2",
            },
            {
                "name": "database",
                "subnet": "192.168.8.0/29",
                "gateway_address": "192.168.8.2",
            },
        ],
    }


def _state_paths(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Point persistent peer metadata at an isolated test directory."""
    state = tmp_path / "state"
    state.mkdir(mode=0o700)
    monkeypatch.setattr(wireguard, "STATE_DIRECTORY", state)
    monkeypatch.setattr(wireguard, "PEERS_PATH", state / "peers.json")


def test_enabled_wireguard_requires_every_explicit_deployment_input() -> None:
    """Reject activation without operator-selected network and secret paths."""
    config = _config()
    validate_remote_access_config(config)
    config["gateway"]["remote_access"]["wireguard"] = {"enabled": True}

    with pytest.raises(ValueError, match="explicit host bind"):
        validate_remote_access_config(config)


def test_peer_allocator_reserves_server_address_inside_peer_pool() -> None:
    """Start peer assignments after the reserved server and DNS address."""
    config = _config()
    wg_settings = config["gateway"]["remote_access"]["wireguard"]
    wg_settings["address_pool"] = "192.168.10.0/24"
    wg_settings["server_address"] = "192.168.10.1"
    wg_settings["dns_server"] = "192.168.10.1"
    wireguard_config = wireguard._enabled(config)

    assert wireguard._peer_address(wireguard_config, []) == ipaddress.IPv4Address(
        "192.168.10.2"
    )


def test_runtime_rejects_pool_network_address_as_wireguard_server() -> None:
    """Reject a network or broadcast address as the server tunnel address."""
    config = _config()
    wg_settings = config["gateway"]["remote_access"]["wireguard"]
    wg_settings["address_pool"] = "192.168.10.0/24"
    wg_settings["server_address"] = "192.168.10.0"
    wg_settings["dns_server"] = "192.168.10.0"

    with pytest.raises(wireguard.WireGuardError, match="pool or UDP port is invalid"):
        wireguard._enabled(config)


def test_peer_generation_rejects_invalid_client_endpoint_before_state_changes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reject an invalid client endpoint before generating or storing a peer."""
    monkeypatch.setattr(
        wireguard, "_run", lambda *_args, **_kwargs: pytest.fail("unexpected command")
    )

    with pytest.raises(wireguard.WireGuardError, match="endpoint is invalid"):
        wireguard.generate_peer(
            _config(), "peer-invalid", "owner", "purpose", "bad endpoint"
        )


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("address_pool", "192.168.9.0/24", "overlaps Podman network"),
        ("address_pool", "172.24.0.0/24", "overlaps OpenVPN client pool"),
        ("dns_server", "192.168.9.9", "match a configured Gateway network address"),
        ("host_bind_address", "host.invalid", "must be an IPv4 address"),
    ],
)
def test_wireguard_rejects_conflicting_or_invalid_inputs(
    field: str, value: str, message: str
) -> None:
    """Reject invalid WireGuard pools, DNS addresses, and host bind values."""
    config = _config()
    config["gateway"]["remote_access"]["wireguard"][field] = value

    with pytest.raises(ValueError, match=message):
        validate_remote_access_config(config)


def test_generate_peer_stores_public_metadata_only_and_builds_exact_split_routes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Keep client private material out of persistent state and route data."""
    _state_paths(monkeypatch, tmp_path)
    server_key = tmp_path / "server.key"
    server_key.write_text("server-private-test-data", encoding="ascii")
    monkeypatch.setattr(wireguard, "SERVER_KEY_PATH", server_key)
    monkeypatch.setattr(
        wireguard, "_direct_tty", lambda: os.open("/dev/null", os.O_WRONLY)
    )
    calls: list[tuple[list[str], str | None]] = []

    def run(arguments: list[str], *, input_text: str | None = None) -> str:
        calls.append((arguments, input_text))
        if arguments[:3] == ["ip", "link", "show"]:
            return ""
        if arguments == ["wg", "genkey"]:
            return PRIVATE_KEY
        if arguments == ["wg", "pubkey"]:
            return (
                SERVER_PUBLIC_KEY
                if input_text == "server-private-test-data"
                else PEER_PUBLIC_KEY
            )
        raise AssertionError(f"unexpected command: {arguments}")

    monkeypatch.setattr(wireguard, "_run", run)
    profile, fingerprint, terminal = wireguard.generate_peer(
        _config(),
        "peer-001",
        "person@example.test",
        "workstation access",
        "vpn.example.test",
    )
    os.close(terminal)

    assert PRIVATE_KEY in profile
    assert "DNS =" not in profile
    assert (
        "# Split DNS resolver; apply OS-specific dev.anatel settings: 192.168.9.2"
        in profile
    )
    assert "AllowedIPs = 192.168.9.0/24, 192.168.8.0/29" in profile
    assert "0.0.0.0/0" not in profile
    assert "198.18.0.1/32" in profile
    assert "Endpoint = vpn.example.test:54000" in profile
    assert fingerprint == hashlib.sha256(PEER_PUBLIC_KEY.encode()).hexdigest()

    persistent = wireguard.PEERS_PATH.read_text(encoding="utf-8")
    assert PRIVATE_KEY not in persistent
    assert "server-private-test-data" not in persistent
    assert PEER_PUBLIC_KEY in persistent
    assert "actor_uid" in persistent
    assert all(PRIVATE_KEY not in " ".join(call[0]) for call in calls)


def test_one_time_output_writes_only_to_supplied_terminal_fd() -> None:
    """Write a profile once without routing it through stdout or a file."""
    read_fd, write_fd = os.pipe()
    try:
        wireguard._write_profile_once("PrivateKey = one-time\n", write_fd)
        assert os.read(read_fd, 128) == b"PrivateKey = one-time\n"
    finally:
        os.close(read_fd)


def test_direct_terminal_guard_fails_closed_for_piped_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reject pipes before one-time profile output."""
    monkeypatch.setattr(wireguard.sys, "stdin", io.StringIO())
    monkeypatch.setattr(wireguard.sys, "stdout", io.StringIO())

    with pytest.raises(wireguard.WireGuardError, match="direct terminal"):
        wireguard._direct_tty()


def test_direct_terminal_guard_fails_closed_when_tiocgdev_is_unsupported(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reject terminal verification when TIOCGDEV returns an unsupported-ioctl error."""
    master, slave = pty.openpty()
    stdin = os.fdopen(os.dup(slave), "r", encoding="ascii")
    stdout = os.fdopen(os.dup(slave), "w", encoding="ascii")
    monkeypatch.setattr(wireguard.sys, "stdin", stdin)
    monkeypatch.setattr(wireguard.sys, "stdout", stdout)

    def unsupported_ioctl(*args: Any, **kwargs: Any) -> None:
        raise OSError(errno.ENOTTY, "unsupported ioctl")

    monkeypatch.setattr(wireguard.fcntl, "ioctl", unsupported_ioctl)
    try:
        with pytest.raises(wireguard.WireGuardError, match="Could not verify a direct"):
            wireguard._direct_tty()
    finally:
        stdin.close()
        stdout.close()
        os.close(master)
        os.close(slave)


def test_peer_generate_cli_delivers_profile_to_controlling_pty(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Accept a real controlling PTY and keep generated private material transient."""
    _state_paths(monkeypatch, tmp_path)
    server_key = tmp_path / "server.key"
    server_key.write_text("server-private-test-data", encoding="ascii")
    monkeypatch.setattr(wireguard, "SERVER_KEY_PATH", server_key)
    monkeypatch.setattr(wireguard, "load_host_config", lambda _: _config())
    monkeypatch.setattr(wireguard.os, "geteuid", lambda: 0)
    private_key = bytearray(PRIVATE_KEY.encode("ascii"))

    def run(arguments: list[str], *, input_text: str | None = None) -> str:
        if arguments == ["ip", "link", "show", "dev", wireguard.INTERFACE]:
            return ""
        if arguments == ["wg", "genkey"]:
            return private_key.decode("ascii")
        if arguments == ["wg", "pubkey"]:
            return (
                SERVER_PUBLIC_KEY
                if input_text == "server-private-test-data"
                else PEER_PUBLIC_KEY
            )
        raise AssertionError("unexpected WireGuard command")

    monkeypatch.setattr(wireguard, "_run", run)
    child, terminal = pty.fork()
    if child == 0:
        wireguard.sys.stdin = os.fdopen(0, "r", encoding="ascii", closefd=False)
        wireguard.sys.stdout = os.fdopen(1, "w", encoding="ascii", closefd=False)
        wireguard.sys.stderr = os.fdopen(2, "w", encoding="ascii", closefd=False)
        exit_code = wireguard.main(
            [
                "peer",
                "generate",
                "--id",
                "peer-pty",
                "--owner",
                "person@example.test",
                "--purpose",
                "PTY regression",
                "--endpoint",
                "vpn.example.test",
            ]
        )
        private_key.clear()
        wireguard.sys.stderr.flush()
        os._exit(exit_code)

    output = bytearray()
    child_reaped = False
    try:
        read_deadline = time.monotonic() + 10
        while True:
            remaining = read_deadline - time.monotonic()
            if remaining <= 0:
                pytest.fail("peer generation did not finish reading the PTY profile.")
            readable, _, _ = select.select([terminal], [], [], remaining)
            if not readable:
                pytest.fail("peer generation did not finish reading the PTY profile.")
            try:
                chunk = os.read(terminal, 4096)
            except OSError as error:
                if error.errno == errno.EIO:
                    break
                if error.errno == errno.EINTR:
                    continue
                raise
            if not chunk:
                break
            output.extend(chunk)

        wait_deadline = time.monotonic() + 5
        while True:
            finished, status = os.waitpid(child, os.WNOHANG)
            if finished == child:
                child_reaped = True
                break
            remaining = wait_deadline - time.monotonic()
            if remaining <= 0:
                pytest.fail(
                    "peer generation did not exit after writing the PTY profile."
                )
            time.sleep(min(0.01, remaining))

        expected_profile = (
            b"[Interface]",
            b"PrivateKey = ",
            b"Address = 198.18.0.1/32",
            b"[Peer]",
            b"PublicKey = " + SERVER_PUBLIC_KEY.encode("ascii"),
            b"Endpoint = vpn.example.test:54000",
            b"AllowedIPs = 192.168.9.0/24, 192.168.8.0/29",
        )
        if (
            os.waitstatus_to_exitcode(status) != 0
            or any(fragment not in output for fragment in expected_profile)
            or private_key not in output
        ):
            pytest.fail("peer generation did not deliver the expected PTY profile.")

        state = json.loads(wireguard.PEERS_PATH.read_bytes())
        peer = state["peers"][0]
        if (
            private_key in wireguard.PEERS_PATH.read_bytes()
            or "private_key" in peer
            or peer["public_key"] != PEER_PUBLIC_KEY
        ):
            pytest.fail("persistent peer state contains unexpected key material.")
    finally:
        try:
            if not child_reaped:
                try:
                    os.kill(child, signal.SIGTERM)
                except ProcessLookupError:
                    pass

                reap_deadline = time.monotonic() + 1
                while time.monotonic() < reap_deadline:
                    try:
                        finished, _ = os.waitpid(child, os.WNOHANG)
                    except ChildProcessError:
                        child_reaped = True
                        break
                    if finished == child:
                        child_reaped = True
                        break
                    time.sleep(0.01)

                if not child_reaped:
                    try:
                        os.kill(child, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    try:
                        os.waitpid(child, 0)
                    except ChildProcessError:
                        pass
        finally:
            try:
                os.close(terminal)
            finally:
                output.clear()
                private_key.clear()
                server_key.unlink(missing_ok=True)


def test_peer_generate_cli_rejects_redirected_pipes_before_keygen(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Reject redirected input and output pipes before generating peer keys."""
    _state_paths(monkeypatch, tmp_path)
    monkeypatch.setattr(wireguard, "load_host_config", lambda _: _config())
    monkeypatch.setattr(wireguard.os, "geteuid", lambda: 0)
    stdin_read, stdin_write = os.pipe()
    stdout_read, stdout_write = os.pipe()
    stderr_read, stderr_write = os.pipe()
    commands_read, commands_write = os.pipe()

    def run(arguments: list[str], *, input_text: str | None = None) -> str:
        if arguments == ["wg", "genkey"]:
            os.write(commands_write, b"G")
            return PRIVATE_KEY
        if arguments == ["ip", "link", "show", "dev", wireguard.INTERFACE]:
            os.write(commands_write, b"I")
            return ""
        raise AssertionError("unexpected WireGuard command")

    monkeypatch.setattr(wireguard, "_run", run)
    child = os.fork()
    if child == 0:
        os.close(stdin_write)
        os.close(stdout_read)
        os.close(stderr_read)
        os.close(commands_read)
        os.dup2(stdin_read, 0)
        os.close(stdin_read)
        os.dup2(stdout_write, 1)
        os.close(stdout_write)
        os.dup2(stderr_write, 2)
        os.close(stderr_write)
        wireguard.sys.stdin = os.fdopen(0, "r", encoding="ascii", closefd=False)
        wireguard.sys.stdout = os.fdopen(1, "w", encoding="ascii", closefd=False)
        wireguard.sys.stderr = os.fdopen(2, "w", encoding="ascii", closefd=False)
        exit_code = wireguard.main(
            [
                "peer",
                "generate",
                "--id",
                "peer-pipe",
                "--owner",
                "person@example.test",
                "--purpose",
                "pipe regression",
                "--endpoint",
                "vpn.example.test",
            ]
        )
        wireguard.sys.stderr.flush()
        os._exit(exit_code)

    os.close(stdin_read)
    os.close(stdin_write)
    os.close(stdout_write)
    os.close(stderr_write)
    os.close(commands_write)
    output = bytearray()
    diagnostics = bytearray()
    observed_commands = bytearray()
    try:
        while chunk := os.read(stdout_read, 4096):
            output.extend(chunk)
        while chunk := os.read(stderr_read, 4096):
            diagnostics.extend(chunk)
        while chunk := os.read(commands_read, 4096):
            observed_commands.extend(chunk)
        _, status = os.waitpid(child, 0)
        if (
            os.waitstatus_to_exitcode(status) != 1
            or output
            or b"direct terminal" not in diagnostics
            or observed_commands != b"I"
            or wireguard.PEERS_PATH.exists()
        ):
            pytest.fail("pipe rejection did not precede key generation and output.")
    finally:
        os.close(stdout_read)
        os.close(stderr_read)
        os.close(commands_read)
        output.clear()
        diagnostics.clear()
        observed_commands.clear()


def test_approval_and_revocation_change_only_the_selected_public_peer(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Activate and revoke one peer while persisting no private key."""
    _state_paths(monkeypatch, tmp_path)
    state = {
        "schema_version": 1,
        "peers": [
            {
                "id": "peer-001",
                "owner": "person@example.test",
                "purpose": "test",
                "address": "198.18.0.1",
                "public_key": PEER_PUBLIC_KEY,
                "status": "pending",
            },
            {
                "id": "peer-002",
                "owner": "another@example.test",
                "purpose": "test",
                "address": "198.18.0.2",
                "public_key": SERVER_PUBLIC_KEY,
                "status": "pending",
            },
        ],
        "audit": [],
    }
    wireguard._write_peers(state)
    calls: list[list[str]] = []
    routes: set[str] = set()

    def run(arguments: list[str], **kwargs: Any) -> str:
        calls.append(arguments)
        if arguments[:6] == ["ip", "-4", "route", "add", "198.18.0.1/32", "dev"]:
            routes.add("198.18.0.1/32")
            return ""
        if arguments[:6] == ["ip", "-j", "-4", "route", "show", "exact"]:
            destination = arguments[6]
            if destination in routes:
                return json.dumps(
                    [
                        {
                            "dst": destination,
                            "dev": "wg0",
                            "protocol": "186",
                        }
                    ]
                )
            return "[]"
        if arguments[:5] == ["ip", "-4", "route", "del", "198.18.0.1/32"]:
            routes.discard("198.18.0.1/32")
            return ""
        return ""

    monkeypatch.setattr(wireguard, "_run", run)

    fingerprint = wireguard.approve_peer(
        _config(), "peer-001", "change-123", "2099-01-01T00:00:00Z"
    )
    approved = json.loads(wireguard.PEERS_PATH.read_text(encoding="utf-8"))
    assert approved["peers"][0]["status"] == "approved"
    assert approved["peers"][1]["status"] == "pending"
    assert approved["peers"][0]["approval_reference"] == "change-123"
    assert fingerprint == hashlib.sha256(PEER_PUBLIC_KEY.encode()).hexdigest()
    assert calls[-2] == [
        "wg",
        "set",
        "wg0",
        "peer",
        PEER_PUBLIC_KEY,
        "allowed-ips",
        "198.18.0.1/32",
    ]
    assert calls[-1] == [
        "ip",
        "-4",
        "route",
        "add",
        "198.18.0.1/32",
        "dev",
        "wg0",
        "proto",
        "186",
    ]

    wireguard.revoke_peer("peer-001", "device lost")
    revoked = json.loads(wireguard.PEERS_PATH.read_text(encoding="utf-8"))
    assert revoked["peers"][0]["status"] == "revoked"
    assert revoked["peers"][1]["status"] == "pending"
    assert calls[-3:] == [
        ["wg", "set", "wg0", "peer", PEER_PUBLIC_KEY, "remove"],
        ["ip", "-j", "-4", "route", "show", "exact", "198.18.0.1/32"],
        [
            "ip",
            "-4",
            "route",
            "del",
            "198.18.0.1/32",
            "dev",
            "wg0",
            "proto",
            "186",
        ],
    ]
    assert PRIVATE_KEY not in wireguard.PEERS_PATH.read_text(encoding="utf-8")


@pytest.mark.parametrize(
    ("fallback", "message", "marker_expected"),
    [
        ("delete", "CRITICAL: wg0 was deleted", False),
        ("down", "CRITICAL: wg0 was taken down", False),
        (
            "both-fail",
            "CRITICAL: wg0 could not be deleted or taken down",
            True,
        ),
        (
            "both-fail-no-nft",
            "CRITICAL: wg0 could not be deleted or taken down",
            True,
        ),
    ],
)
def test_approval_uses_fail_closed_fallback_when_peer_rollback_fails(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    fallback: str,
    message: str,
    marker_expected: bool,
) -> None:
    """Keep approval pending and stop runtime when peer rollback fails."""
    _state_paths(monkeypatch, tmp_path)
    state = {
        "schema_version": 1,
        "peers": [
            {
                "id": "peer-001",
                "owner": "person@example.test",
                "purpose": "test",
                "address": "198.18.0.1",
                "public_key": PEER_PUBLIC_KEY,
                "status": "pending",
            }
        ],
        "audit": [],
    }
    wireguard._write_peers(state)
    calls: list[list[str]] = []
    routes = {"198.18.0.1/32"}
    active_peers = {PEER_PUBLIC_KEY, SERVER_PUBLIC_KEY}
    interface_exists = True
    nft_rules: str | None = None

    def run(arguments: list[str], **kwargs: Any) -> str:
        nonlocal interface_exists, nft_rules
        calls.append(arguments)
        if arguments == ["nft", "-f", "-"]:
            nft_rules = kwargs.get("input_text")
            if fallback == "both-fail-no-nft":
                raise wireguard.WireGuardError("WireGuard command failed: nft")
            return ""
        if arguments[:4] == ["wg", "set", "wg0", "peer"]:
            if arguments[-1] == "remove":
                raise wireguard.WireGuardError("WireGuard command failed: wg")
            active_peers.add(arguments[4])
            return ""
        if arguments[:4] == ["ip", "-4", "route", "add"]:
            raise wireguard.WireGuardError("WireGuard command failed: ip")
        if arguments[:6] == ["ip", "-j", "-4", "route", "show", "exact"]:
            destination = arguments[6]
            return json.dumps(
                [{"dst": destination, "dev": "wg0", "protocol": "186"}]
                if destination in routes
                else []
            )
        if arguments[:4] == ["ip", "-4", "route", "del"]:
            routes.discard(arguments[4])
            return ""
        if arguments[:4] == ["ip", "link", "del", "dev"]:
            if fallback != "delete":
                raise wireguard.WireGuardError("WireGuard command failed: ip")
            interface_exists = False
            active_peers.clear()
            return ""
        if arguments == ["ip", "link", "set", "dev", "wg0", "down"]:
            if fallback != "down":
                raise wireguard.WireGuardError("WireGuard command failed: ip")
            return ""
        if arguments == ["ip", "-j", "link", "show", "dev", "wg0"]:
            return json.dumps([{"ifname": "wg0", "flags": []}])
        return ""

    monkeypatch.setattr(wireguard, "_run", run)

    with pytest.raises(
        wireguard.WireGuardError,
        match=message,
    ) as error:
        wireguard.approve_peer(
            _config(), "peer-001", "change-123", "2099-01-01T00:00:00Z"
        )

    persisted = json.loads(wireguard.PEERS_PATH.read_text(encoding="utf-8"))
    assert persisted["peers"][0]["status"] == "pending"
    assert "approval_reference" not in persisted["peers"][0]
    assert interface_exists is (fallback != "delete")
    assert (not active_peers) is (fallback == "delete")
    assert not routes
    assert [
        "ip",
        "-4",
        "route",
        "del",
        "198.18.0.1/32",
        "dev",
        "wg0",
        "proto",
        "186",
    ] in calls
    assert ["ip", "link", "del", "dev", "wg0"] in calls
    assert (["ip", "link", "set", "dev", "wg0", "down"] in calls) is (
        fallback != "delete"
    )
    marker = wireguard._fail_stop_marker_path()
    assert marker.exists() is marker_expected
    if marker_expected:
        details = marker.stat()
        assert details.st_uid == 0
        assert details.st_mode & 0o777 == 0o600
        assert calls[-1] == ["nft", "-f", "-"]
        assert "ip saddr 198.18.0.1 drop" in nft_rules
        assert 'iifname "wg0"' in nft_rules
    if fallback == "both-fail-no-nft":
        assert "peer-specific nft drop rule could not be installed" in str(error.value)
        assert "Live tunnel traffic may remain active" in str(error.value)
    if fallback == "down":
        with pytest.raises(wireguard.WireGuardError, match="runtime is unhealthy"):
            wireguard._assert_interface_up()


def test_approval_route_failure_with_successful_peer_rollback_keeps_server_running(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Keep wg0 up and peer pending when route failure rollback succeeds."""
    _state_paths(monkeypatch, tmp_path)
    state = {
        "schema_version": 1,
        "peers": [
            {
                "id": "peer-001",
                "owner": "person@example.test",
                "purpose": "test",
                "address": "198.18.0.1",
                "public_key": PEER_PUBLIC_KEY,
                "status": "pending",
            }
        ],
        "audit": [],
    }
    wireguard._write_peers(state)
    calls: list[list[str]] = []
    interface_exists = True
    active_peers: set[str] = set()

    def run(arguments: list[str], **kwargs: Any) -> str:
        nonlocal interface_exists
        calls.append(arguments)
        if arguments[:4] == ["wg", "set", "wg0", "peer"]:
            if arguments[-1] == "remove":
                active_peers.discard(arguments[4])
                return ""
            active_peers.add(arguments[4])
            return ""
        if arguments[:4] == ["ip", "-4", "route", "add"]:
            raise wireguard.WireGuardError("WireGuard command failed: ip")
        if arguments[:4] == ["ip", "link", "del", "dev"]:
            interface_exists = False
            return ""
        if arguments[:4] == ["ip", "link", "set", "dev"]:
            interface_exists = False
            return ""
        return ""

    monkeypatch.setattr(wireguard, "_run", run)

    with pytest.raises(wireguard.WireGuardError, match="WireGuard command failed: ip"):
        wireguard.approve_peer(
            _config(), "peer-001", "change-123", "2099-01-01T00:00:00Z"
        )

    persisted = json.loads(wireguard.PEERS_PATH.read_text(encoding="utf-8"))
    assert persisted["peers"][0]["status"] == "pending"
    assert interface_exists
    assert not active_peers
    assert ["ip", "link", "del", "dev", "wg0"] not in calls
    assert ["ip", "link", "set", "dev", "wg0", "down"] not in calls


def test_fail_stop_marker_is_root_owned_private_and_exclusive(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Create the persistent marker once with strict root-only permissions."""
    _state_paths(monkeypatch, tmp_path)

    wireguard._create_fail_stop_marker()
    marker = wireguard._fail_stop_marker_path()
    first = marker.stat()
    contents = marker.read_bytes()
    wireguard._create_fail_stop_marker()
    second = marker.stat()

    assert first.st_uid == 0
    assert first.st_mode & 0o777 == 0o600
    assert second.st_ino == first.st_ino
    assert marker.read_bytes() == contents


def test_fail_stop_marker_blocks_health_and_startup_before_configuration(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Refuse server startup and health when persistent failure state exists."""
    _state_paths(monkeypatch, tmp_path)
    wireguard._create_fail_stop_marker()
    calls: list[list[str]] = []
    monkeypatch.setattr(
        wireguard, "_run", lambda arguments, **kwargs: calls.append(arguments)
    )
    monkeypatch.setattr(
        wireguard,
        "_configure_server",
        lambda *args, **kwargs: pytest.fail("server configured despite marker"),
    )

    with pytest.raises(wireguard.WireGuardError, match="CRITICAL:.*fail-stop marker"):
        wireguard._assert_interface_up()
    with pytest.raises(wireguard.WireGuardError, match="CRITICAL:.*fail-stop marker"):
        wireguard.run_server(_config())

    assert calls == []
    assert wireguard._fail_stop_marker_path().exists()


def test_fail_stop_command_creates_owned_table_with_all_interface_drops(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Keep the marker and block wg0 plus IPv4 or IPv6 UDP transport egress."""
    _state_paths(monkeypatch, tmp_path)
    wireguard._create_fail_stop_marker()
    calls: list[tuple[list[str], str | None]] = []

    def run(arguments: list[str], *, input_text: str | None = None) -> str:
        calls.append((arguments, input_text))
        return ""

    monkeypatch.setattr(wireguard, "_run", run)
    wireguard._install_fail_stop_drop(
        _config()["gateway"]["remote_access"]["wireguard"]
    )

    assert calls[0] == (["nft", "list", "tables"], None)
    assert calls[1][0] == ["nft", "-f", "-"]
    rules = calls[1][1]
    assert rules is not None
    token = wireguard._require_fail_stop_marker()
    assert (
        f"add table inet gateway_wireguard_fail_stop {{ comment "
        f'"{wireguard.FAIL_STOP_OWNERSHIP_PREFIX}{token}"; }}'
    ) in rules
    assert "delete table inet gateway_wireguard_fail_stop" not in rules
    assert 'input iifname "wg0" drop' in rules
    assert "input udp dport 54000 drop" in rules
    assert 'forward iifname "wg0" drop' in rules
    assert 'forward oifname "wg0" drop' in rules
    assert 'output oifname "wg0" drop' in rules
    assert "output meta l4proto udp udp sport 54000 drop" in rules
    assert "output ip protocol udp udp sport 54000 drop" not in rules
    assert "output ip6 nexthdr udp udp sport 54000 drop" not in rules
    assert rules.count("sport 54000") == 1
    assert "output udp drop" not in rules
    assert "udp sport 54001" not in rules
    assert wireguard._fail_stop_marker_path().exists()


def test_fail_stop_command_verifies_owned_table_without_replacing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Accept an exact owned table on restart without adding or deleting rules."""
    _state_paths(monkeypatch, tmp_path)
    wireguard._create_fail_stop_marker()
    token = wireguard._require_fail_stop_marker()
    table_listing = "\n".join(
        [
            "table inet gateway_wireguard_fail_stop { # handle 1",
            f'comment "{wireguard.FAIL_STOP_OWNERSHIP_PREFIX}{token}";',
            "chain input { # handle 2",
            "type filter hook input priority -300; policy accept;",
            'iifname "wg0" drop # handle 3',
            "udp dport 54000 drop # handle 4",
            "}",
            "chain forward { # handle 5",
            "type filter hook forward priority -300; policy accept;",
            'iifname "wg0" drop # handle 6',
            'oifname "wg0" drop # handle 7',
            "}",
            "chain output { # handle 8",
            "type filter hook output priority -300; policy accept;",
            'oifname "wg0" drop # handle 9',
            "meta l4proto udp udp sport 54000 drop # handle 10",
            "}",
            "}",
        ]
    )
    calls: list[list[str]] = []

    def run(arguments: list[str], **kwargs: Any) -> str:
        calls.append(arguments)
        if arguments == ["nft", "list", "tables"]:
            return "table inet gateway_wireguard_fail_stop"
        if arguments == [
            "nft",
            "-a",
            "list",
            "table",
            "inet",
            "gateway_wireguard_fail_stop",
        ]:
            return table_listing
        raise AssertionError(f"unexpected command: {arguments}")

    monkeypatch.setattr(wireguard, "_run", run)
    wireguard._install_fail_stop_drop(
        _config()["gateway"]["remote_access"]["wireguard"]
    )
    wireguard._install_fail_stop_drop(
        _config()["gateway"]["remote_access"]["wireguard"]
    )

    assert (
        calls
        == [
            ["nft", "list", "tables"],
            ["nft", "-a", "list", "table", "inet", "gateway_wireguard_fail_stop"],
        ]
        * 2
    )


def test_fail_stop_collision_is_preserved_when_table_is_foreign(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Reject a foreign same-name table without modifying it."""
    _state_paths(monkeypatch, tmp_path)
    wireguard._create_fail_stop_marker()
    table_listing = (
        "table inet gateway_wireguard_fail_stop { # handle 1\n"
        'comment "unrelated-table";\n}'
    )
    calls: list[list[str]] = []

    def run(arguments: list[str], **kwargs: Any) -> str:
        calls.append(arguments)
        if arguments == ["nft", "list", "tables"]:
            return "table inet gateway_wireguard_fail_stop"
        if arguments[0:2] == ["nft", "-a"]:
            return table_listing
        raise AssertionError(f"unexpected command: {arguments}")

    monkeypatch.setattr(wireguard, "_run", run)
    with pytest.raises(
        wireguard.WireGuardError, match="existing WireGuard fail-stop table is invalid"
    ):
        wireguard._install_fail_stop_drop(
            _config()["gateway"]["remote_access"]["wireguard"]
        )

    assert calls == [
        ["nft", "list", "tables"],
        ["nft", "-a", "list", "table", "inet", "gateway_wireguard_fail_stop"],
    ]
    assert wireguard._fail_stop_marker_path().exists()


def test_fail_stop_owned_table_with_ipv4_only_rule_is_preserved(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Reject an IPv4-only transport rule rather than accepting owned-table drift."""
    _state_paths(monkeypatch, tmp_path)
    wireguard._create_fail_stop_marker()
    token = wireguard._require_fail_stop_marker()
    table_listing = "\n".join(
        [
            "table inet gateway_wireguard_fail_stop { # handle 1",
            f'comment "{wireguard.FAIL_STOP_OWNERSHIP_PREFIX}{token}";',
            "chain input { # handle 2",
            "type filter hook input priority -300; policy accept;",
            'iifname "wg0" drop # handle 3',
            "udp dport 54000 drop # handle 4",
            "}",
            "chain forward { # handle 5",
            "type filter hook forward priority -300; policy accept;",
            'iifname "wg0" drop # handle 6',
            'oifname "wg0" drop # handle 7',
            "}",
            "chain output { # handle 8",
            "type filter hook output priority -300; policy accept;",
            'oifname "wg0" drop # handle 9',
            "ip protocol udp udp sport 54000 drop # handle 10",
            "}",
            "}",
        ]
    )
    calls: list[list[str]] = []

    def run(arguments: list[str], **kwargs: Any) -> str:
        calls.append(arguments)
        if arguments == ["nft", "list", "tables"]:
            return "table inet gateway_wireguard_fail_stop"
        return table_listing

    monkeypatch.setattr(wireguard, "_run", run)
    with pytest.raises(
        wireguard.WireGuardError, match="existing WireGuard fail-stop table is invalid"
    ):
        wireguard._install_fail_stop_drop(
            _config()["gateway"]["remote_access"]["wireguard"]
        )

    assert calls == [
        ["nft", "list", "tables"],
        ["nft", "-a", "list", "table", "inet", "gateway_wireguard_fail_stop"],
    ]


def test_fail_stop_marker_rejects_invalid_ownership_token(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Reject marker content that cannot safely identify the nft owner."""
    _state_paths(monkeypatch, tmp_path)
    marker = wireguard._fail_stop_marker_path()
    marker.write_text("Critical WireGuard rollback failure\n", encoding="ascii")
    marker.chmod(0o600)

    with pytest.raises(wireguard.WireGuardError, match="fail-stop marker is invalid"):
        wireguard._require_fail_stop_marker()


def test_fail_stop_marker_creation_failure_reports_critical(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Report inability to persist fail-stop state as a critical failure."""
    _state_paths(monkeypatch, tmp_path)
    original_open = wireguard.os.open

    def fail_marker_open(path: Any, flags: int, mode: int = 0o777) -> int:
        if path == wireguard._fail_stop_marker_path():
            raise PermissionError("test-only failure")
        return original_open(path, flags, mode)

    monkeypatch.setattr(wireguard.os, "open", fail_marker_open)

    with pytest.raises(wireguard.WireGuardError, match="CRITICAL: could not create"):
        wireguard._create_fail_stop_marker()


def test_server_brings_interface_up_before_adding_approved_peer_route(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Install the forwarding policy and raise wg0 before adding peer routes."""
    _state_paths(monkeypatch, tmp_path)
    server_key = tmp_path / "server.key"
    server_key.write_text("test-only-server-key", encoding="ascii")
    server_key.chmod(0o600)
    monkeypatch.setattr(wireguard, "SERVER_KEY_PATH", server_key)
    original_is_dir = Path.is_dir

    def is_dir(path: Path) -> bool:
        if path in {
            Path("/sys/module/wireguard"),
            Path("/var/lib/gateway/wireguard"),
        }:
            return True
        return original_is_dir(path)

    monkeypatch.setattr(Path, "is_dir", is_dir)
    config = _config()
    wireguard._write_peers(
        {
            "schema_version": 1,
            "peers": [
                {
                    "id": "peer-001",
                    "owner": "test",
                    "purpose": "test",
                    "address": "198.18.0.1",
                    "public_key": PEER_PUBLIC_KEY,
                    "status": "approved",
                    "expires_at": "2099-01-01T00:00:00Z",
                }
            ],
            "audit": [],
        }
    )
    events: list[str] = []
    interface_up = False

    def run(arguments: list[str], **kwargs: Any) -> str:
        nonlocal interface_up
        if arguments == ["ip", "-j", "-4", "address", "show"]:
            return json.dumps(
                [
                    {
                        "ifname": "eth0",
                        "addr_info": [{"family": "inet", "local": "192.168.9.2"}],
                    },
                    {
                        "ifname": "eth1",
                        "addr_info": [{"family": "inet", "local": "192.168.8.2"}],
                    },
                ]
            )
        if arguments == ["ip", "link", "add", "dev", "wg0", "type", "wireguard"]:
            events.append("create-interface")
            return ""
        if arguments[:2] == ["wg", "set"]:
            if arguments[2:4] == ["wg0", "peer"]:
                assert interface_up
                events.append("add-peer")
            return ""
        if arguments[:4] == ["ip", "-4", "address", "add"]:
            events.append("add-server-address")
            return ""
        if arguments == ["ip", "link", "set", "dev", "wg0", "up"]:
            assert events[-1] == "acquire-forwarding"
            interface_up = True
            events.append("raise-interface")
            return ""
        if arguments[:4] == ["ip", "-4", "route", "add"]:
            assert interface_up
            events.append("add-peer-route")
            return ""
        raise AssertionError(f"unexpected command: {arguments}")

    def acquire(owner_id: str, interfaces: tuple[str, ...]) -> str:
        assert interfaces == ("eth0", "eth1")
        events.append("acquire-forwarding")
        return "0"

    monkeypatch.setattr(wireguard, "_run", run)
    monkeypatch.setattr(wireguard, "acquire_forwarding", acquire)

    previous_forwarding = wireguard._configure_server(
        config, wireguard._enabled(config)
    )

    assert previous_forwarding == "0"
    assert events.index("acquire-forwarding") < events.index("raise-interface")
    assert events.index("raise-interface") < events.index("add-peer")
    assert events.index("add-peer") < events.index("add-peer-route")


def test_server_removes_interface_when_forwarding_acquire_fails(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Remove the new wg0 without releasing a lease that was never acquired."""
    _state_paths(monkeypatch, tmp_path)
    server_key = tmp_path / "server.key"
    server_key.write_text("test-only-server-key", encoding="ascii")
    server_key.chmod(0o600)
    monkeypatch.setattr(wireguard, "SERVER_KEY_PATH", server_key)
    original_is_dir = Path.is_dir

    def is_dir(path: Path) -> bool:
        if path in {
            Path("/sys/module/wireguard"),
            Path("/var/lib/gateway/wireguard"),
        }:
            return True
        return original_is_dir(path)

    monkeypatch.setattr(Path, "is_dir", is_dir)
    config = _config()
    wireguard._write_peers({"schema_version": 1, "peers": [], "audit": []})
    inventory = wireguard.PEERS_PATH.read_bytes()
    calls: list[list[str]] = []
    acquisitions: list[tuple[str, tuple[str, ...]]] = []
    releases: list[tuple[str, str]] = []

    def run(arguments: list[str], **kwargs: Any) -> str:
        calls.append(arguments)
        if arguments == ["ip", "-j", "-4", "address", "show"]:
            return json.dumps(
                [
                    {
                        "ifname": "eth0",
                        "addr_info": [{"family": "inet", "local": "192.168.9.2"}],
                    },
                    {
                        "ifname": "eth1",
                        "addr_info": [{"family": "inet", "local": "192.168.8.2"}],
                    },
                ]
            )
        if arguments == ["ip", "link", "add", "dev", "wg0", "type", "wireguard"]:
            return ""
        if arguments[:2] == ["wg", "set"]:
            return ""
        if arguments[:4] == ["ip", "-4", "address", "add"]:
            return ""
        if arguments == ["ip", "link", "del", "dev", "wg0"]:
            return ""
        raise AssertionError(f"unexpected command: {arguments}")

    def acquire(owner_id: str, interfaces: tuple[str, ...]) -> str:
        acquisitions.append((owner_id, interfaces))
        raise wireguard.ForwardingError("test-only forwarding failure")

    def release(owner_id: str, previous_forwarding: str) -> None:
        releases.append((owner_id, previous_forwarding))

    monkeypatch.setattr(wireguard, "_run", run)
    monkeypatch.setattr(wireguard, "acquire_forwarding", acquire)
    monkeypatch.setattr(wireguard, "release_forwarding", release)

    with pytest.raises(
        wireguard.WireGuardError, match="Could not safely activate the WireGuard server"
    ):
        wireguard._configure_server(config, wireguard._enabled(config))

    assert calls[-1] == ["ip", "link", "del", "dev", "wg0"]
    assert calls.count(["ip", "link", "del", "dev", "wg0"]) == 1
    assert acquisitions == [(wireguard.OWNER_ID, ("eth0", "eth1"))]
    assert releases == []
    assert wireguard.PEERS_PATH.read_bytes() == inventory


def test_server_fail_stops_when_shared_forwarding_rollback_fails(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Persist WireGuard fail-stop and drop traffic after shared rollback failure."""
    _state_paths(monkeypatch, tmp_path)
    server_key = tmp_path / "server.key"
    server_key.write_text("test-only-server-key", encoding="ascii")
    server_key.chmod(0o600)
    monkeypatch.setattr(wireguard, "SERVER_KEY_PATH", server_key)
    original_is_dir = Path.is_dir

    def is_dir(path: Path) -> bool:
        if path in {
            Path("/sys/module/wireguard"),
            Path("/var/lib/gateway/wireguard"),
        }:
            return True
        return original_is_dir(path)

    monkeypatch.setattr(Path, "is_dir", is_dir)
    config = _config()
    wireguard._write_peers({"schema_version": 1, "peers": [], "audit": []})
    events: list[str] = []
    releases: list[tuple[str, str]] = []

    def run(arguments: list[str], **kwargs: Any) -> str:
        if arguments == ["ip", "-j", "-4", "address", "show"]:
            return json.dumps(
                [
                    {
                        "ifname": "eth0",
                        "addr_info": [{"family": "inet", "local": "192.168.9.2"}],
                    },
                    {
                        "ifname": "eth1",
                        "addr_info": [{"family": "inet", "local": "192.168.8.2"}],
                    },
                ]
            )
        if arguments == ["ip", "link", "add", "dev", "wg0", "type", "wireguard"]:
            events.append("create")
            return ""
        if arguments[:2] == ["wg", "set"]:
            return ""
        if arguments[:4] == ["ip", "-4", "address", "add"]:
            return ""
        if arguments == ["ip", "link", "del", "dev", "wg0"]:
            events.append("delete")
            return ""
        raise AssertionError(f"unexpected command: {arguments}")

    def acquire(owner_id: str, interfaces: tuple[str, ...]) -> str:
        assert interfaces == ("eth0", "eth1")
        raise wireguard.ForwardingRollbackError(owner_id, ("table",))

    monkeypatch.setattr(wireguard, "_run", run)
    monkeypatch.setattr(wireguard, "acquire_forwarding", acquire)
    monkeypatch.setattr(
        wireguard, "_create_fail_stop_marker", lambda: events.append("marker")
    )
    monkeypatch.setattr(
        wireguard,
        "_install_fail_stop_drop",
        lambda metadata: events.append(f"drop:{metadata['listen_port']}"),
    )
    monkeypatch.setattr(
        wireguard,
        "release_forwarding",
        lambda owner_id, previous: releases.append((owner_id, previous)),
    )

    with pytest.raises(wireguard.WireGuardError, match="fail-stop drops are installed"):
        wireguard._configure_server(config, wireguard._enabled(config))

    assert events == ["create", "marker", "drop:54000", "delete"]
    assert releases == []


def test_server_cleanup_failure_reports_critical_without_release(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Report failed wg0 removal without claiming cleanup or releasing forwarding."""
    _state_paths(monkeypatch, tmp_path)
    server_key = tmp_path / "server.key"
    server_key.write_text("test-only-server-key", encoding="ascii")
    server_key.chmod(0o600)
    monkeypatch.setattr(wireguard, "SERVER_KEY_PATH", server_key)
    original_is_dir = Path.is_dir

    def is_dir(path: Path) -> bool:
        if path in {
            Path("/sys/module/wireguard"),
            Path("/var/lib/gateway/wireguard"),
        }:
            return True
        return original_is_dir(path)

    monkeypatch.setattr(Path, "is_dir", is_dir)
    config = _config()
    wireguard._write_peers({"schema_version": 1, "peers": [], "audit": []})
    inventory = wireguard.PEERS_PATH.read_bytes()
    calls: list[list[str]] = []
    acquisitions: list[tuple[str, tuple[str, ...]]] = []
    releases: list[tuple[str, str]] = []

    def run(arguments: list[str], **kwargs: Any) -> str:
        calls.append(arguments)
        if arguments == ["ip", "-j", "-4", "address", "show"]:
            return json.dumps(
                [
                    {
                        "ifname": "eth0",
                        "addr_info": [{"family": "inet", "local": "192.168.9.2"}],
                    },
                    {
                        "ifname": "eth1",
                        "addr_info": [{"family": "inet", "local": "192.168.8.2"}],
                    },
                ]
            )
        if arguments == ["ip", "link", "add", "dev", "wg0", "type", "wireguard"]:
            return ""
        if arguments[:2] == ["wg", "set"]:
            return ""
        if arguments[:4] == ["ip", "-4", "address", "add"]:
            return ""
        if arguments == ["ip", "link", "del", "dev", "wg0"]:
            raise wireguard.WireGuardError("test-only deletion failure")
        raise AssertionError(f"unexpected command: {arguments}")

    def acquire(owner_id: str, interfaces: tuple[str, ...]) -> str:
        acquisitions.append((owner_id, interfaces))
        raise wireguard.ForwardingError("test-only forwarding failure")

    def release(owner_id: str, previous_forwarding: str) -> None:
        releases.append((owner_id, previous_forwarding))

    monkeypatch.setattr(wireguard, "_run", run)
    monkeypatch.setattr(wireguard, "acquire_forwarding", acquire)
    monkeypatch.setattr(wireguard, "release_forwarding", release)

    with pytest.raises(
        wireguard.WireGuardError, match="CRITICAL: could not remove wg0"
    ):
        wireguard._configure_server(config, wireguard._enabled(config))

    assert calls[-1] == ["ip", "link", "del", "dev", "wg0"]
    assert acquisitions == [(wireguard.OWNER_ID, ("eth0", "eth1"))]
    assert releases == []
    assert wireguard.PEERS_PATH.read_bytes() == inventory


@pytest.mark.parametrize(
    "records",
    [
        [],
        [{"ifname": "wg0", "flags": []}],
        [{"ifname": "wg1", "flags": ["UP"]}],
    ],
)
def test_runtime_health_fails_when_wg0_is_missing_or_down(
    monkeypatch: pytest.MonkeyPatch, records: list[dict[str, Any]]
) -> None:
    """Fail supervised WireGuard health checks when wg0 is absent or down."""
    monkeypatch.setattr(
        wireguard, "_run", lambda arguments, **kwargs: json.dumps(records)
    )

    with pytest.raises(wireguard.WireGuardError, match="runtime is unhealthy"):
        wireguard._assert_interface_up()


def test_command_failure_does_not_echo_private_command_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sanitize subprocess stderr even when it contains private test data."""

    def fail_command(*args: Any, **kwargs: Any) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            args[0], 1, "", f"secret leaked: {PRIVATE_KEY}"
        )

    monkeypatch.setattr(wireguard.subprocess, "run", fail_command)
    with pytest.raises(wireguard.WireGuardError) as error:
        wireguard._run(["wg", "genkey"])

    assert PRIVATE_KEY not in str(error.value)
