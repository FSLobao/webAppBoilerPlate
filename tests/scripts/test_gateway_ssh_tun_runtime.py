"""Test SSH TUN key reservation and per-session resource ownership."""

from __future__ import annotations

import base64
import concurrent.futures
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from gateway.development import ssh_tun_runtime as runtime
from gateway.development.remote_forwarding import ForwardingRollbackError


def _config(*, max_sessions: int = 2) -> dict[str, Any]:
    """Build a test-only SSH TUN configuration."""
    return {
        "gateway": {
            "remote_access": {
                "openvpn": {"enabled": False, "client_pool": "172.24.0.0/21"},
                "ssh_tun": {
                    "enabled": True,
                    "account": "gateway-tunnel",
                    "address_pool": "198.18.0.0/24",
                    "authorized_keys_path": "/test/authorized_keys",
                    "max_sessions": max_sessions,
                },
            }
        },
        "networks": [
            {
                "name": "shared",
                "subnet": "192.0.2.0/24",
                "gateway_address": "192.0.2.2",
            }
        ],
    }


def test_ssh_tun_overlap_check_requires_configured_openvpn_pool() -> None:
    """Skip allocation overlap checks only when OpenVPN pool is unknown."""
    config = _config()
    del config["gateway"]["remote_access"]["openvpn"]["client_pool"]
    runtime._enabled_config(config)

    config["gateway"]["remote_access"]["openvpn"]["client_pool"] = "198.18.0.0/24"
    with pytest.raises(runtime.TunnelRuntimeError, match="overlaps the OpenVPN"):
        runtime._enabled_config(config)


def _key() -> str:
    """Return a structurally valid synthetic Ed25519 public-key blob."""
    raw = (
        len(b"ssh-ed25519").to_bytes(4, "big")
        + b"ssh-ed25519"
        + (32).to_bytes(4, "big")
        + bytes(range(32))
    )
    return base64.b64encode(raw).decode("ascii")


def _paths(tmp_path: Path) -> runtime.RuntimePaths:
    """Create isolated state and authorized-key paths."""
    key_path = tmp_path / "authorized_keys"
    key_path.write_text(f"ssh-ed25519 {_key()} synthetic\n", encoding="ascii")
    key_path.chmod(0o644)
    return runtime.RuntimePaths(
        state_directory=tmp_path / "reservations",
        forwarding_state_directory=tmp_path / "forwarding",
        authorized_keys_path=key_path,
    )


def _reserve(
    config: dict[str, Any],
    paths: runtime.RuntimePaths,
    client_port: int,
    *,
    now: float = 100.0,
) -> str:
    """Reserve one test connection through the same key-command path."""
    return runtime.authorize_key(
        config,
        "gateway-tunnel",
        "ssh-ed25519",
        _key(),
        "203.0.113.10",
        "22",
        "192.0.2.20",
        str(client_port),
        paths=paths,
        now=now,
    )


def _read_reservations(paths: runtime.RuntimePaths) -> list[dict[str, Any]]:
    """Read test-owned root state."""
    state_path = paths.state_directory / "state.json"
    if not state_path.exists():
        return []
    return json.loads(state_path.read_text(encoding="utf-8"))["reservations"]


def test_repeated_key_query_keeps_connection_reservation_and_normalizes_order(
    tmp_path: Path,
) -> None:
    """Bind repeated and endpoint-reversed queries to one slot."""
    config = _config()
    paths = _paths(tmp_path)

    first = _reserve(config, paths, 41000)
    second = runtime.authorize_key(
        config,
        "gateway-tunnel",
        "ssh-ed25519",
        _key(),
        "192.0.2.20",
        "41000",
        "203.0.113.10",
        "22",
        paths=paths,
        now=101.0,
    )

    assert first == second
    assert 'tunnel="0"' in first
    assert len(_read_reservations(paths)) == 1


def test_same_key_concurrent_connections_receive_distinct_slots(
    tmp_path: Path,
) -> None:
    """Allocate independent slots for two simultaneous sessions with one key."""
    config = _config()
    paths = _paths(tmp_path)

    first = _reserve(config, paths, 41000)
    second = _reserve(config, paths, 41001)

    assert 'tunnel="0"' in first
    assert 'tunnel="1"' in second
    assert len(_read_reservations(paths)) == 2


def test_concurrent_reservation_writes_never_allocate_the_same_slot(
    tmp_path: Path,
) -> None:
    """Serialize independent auth-key lookups through one root-owned lock."""
    config = _config()
    paths = _paths(tmp_path)
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(_reserve, config, paths, port) for port in (41000, 41001)
        ]
        outputs = [future.result() for future in futures]

    assert {"0", "1"} == {
        output.split('tunnel="', 1)[1].split('"', 1)[0] for output in outputs
    }


def test_unlisted_key_is_rejected_before_creating_a_reservation(
    tmp_path: Path,
) -> None:
    """Match the root-managed public key before allocating a slot."""
    config = _config()
    paths = _paths(tmp_path)
    unauthorized_blob = bytearray(base64.b64decode(_key()))
    unauthorized_blob[-1] ^= 1
    unauthorized = base64.b64encode(unauthorized_blob).decode("ascii")

    with pytest.raises(runtime.TunnelRuntimeError, match="not authorized"):
        runtime.authorize_key(
            config,
            "gateway-tunnel",
            "ssh-ed25519",
            unauthorized,
            "203.0.113.10",
            "22",
            "192.0.2.20",
            "41000",
            paths=paths,
        )

    assert _read_reservations(paths) == []


def test_pending_reservations_expire_and_release_capacity(
    tmp_path: Path,
) -> None:
    """Expire unauthenticated keys on the next lifecycle operation."""
    config = _config(max_sessions=1)
    paths = _paths(tmp_path)
    _reserve(config, paths, 41000, now=100.0)

    result = _reserve(config, paths, 41001, now=161.0)

    assert 'tunnel="0"' in result
    records = _read_reservations(paths)
    assert len(records) == 1
    assert records[0]["created_at"] == 161.0


def test_authkeys_cli_parses_openssh_connection_token_as_one_argument(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Pass OpenSSH's four-field %C expansion as one command argument."""
    calls = []
    monkeypatch.setattr(runtime.os, "geteuid", lambda: 0)
    monkeypatch.setattr(runtime, "load_host_config", lambda _path: {})

    def authorize_key(*args: object) -> str:
        calls.append(args)
        return "synthetic-authorized-key"

    monkeypatch.setattr(runtime, "authorize_key", authorize_key)

    assert (
        runtime.main(
            [
                "authkeys",
                "gateway-tunnel",
                "ssh-ed25519",
                _key(),
                "203.0.113.10 22 192.0.2.20 41000",
            ]
        )
        == 0
    )
    assert calls == [
        (
            {},
            "gateway-tunnel",
            "ssh-ed25519",
            _key(),
            "203.0.113.10",
            "22",
            "192.0.2.20",
            "41000",
        )
    ]
    assert capsys.readouterr().out == "synthetic-authorized-key\n"


def test_interface_ownership_accepts_iproute_numeric_uid_and_peer_address(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Match the numeric UID and peer shape emitted by Gateway iproute2."""
    monkeypatch.setattr(
        runtime.pwd,
        "getpwnam",
        lambda _account: SimpleNamespace(pw_uid=994),
    )

    def run(
        arguments: list[str], **_kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        if arguments == ["ip", "tuntap", "show", "dev", "tun0"]:
            output = "tun0: tun persist user 994"
        elif arguments == ["ip", "-j", "-4", "address", "show", "dev", "tun0"]:
            output = json.dumps(
                [
                    {
                        "addr_info": [
                            {
                                "family": "inet",
                                "local": "198.18.0.0",
                                "address": "198.18.0.1",
                                "prefixlen": 32,
                            }
                        ]
                    }
                ]
            )
        else:
            raise AssertionError(f"unexpected command: {arguments}")
        return subprocess.CompletedProcess(arguments, 0, output, "")

    assert runtime._interface_matches(
        "tun0",
        "198.18.0.0",
        "198.18.0.1",
        account="gateway-tunnel",
        runner=run,
    )


def test_forced_session_rejects_client_commands_and_unallocated_tunnels() -> None:
    """Reject arbitrary original commands and tunnel IDs outside the pool."""
    config = _config()

    assert (
        runtime._hold_for_disconnect(
            {"SSH_ORIGINAL_COMMAND": "id", "SSH_TUNNEL": "tun0"},
            config,
        )
        == 1
    )
    assert (
        runtime._hold_for_disconnect(
            {"SSH_ORIGINAL_COMMAND": "", "SSH_TUNNEL": "tun2"},
            config,
        )
        == 1
    )
    assert runtime.main(["session", "untrusted-argument"]) == 1


class FakeNetwork:
    """Model only the interfaces and routes touched by the lifecycle tests."""

    def __init__(self) -> None:
        self.devices: dict[str, dict[str, str]] = {}
        self.route: str | None = None
        self.mutations: list[list[str]] = []

    def run(
        self, arguments: list[str], **_kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        """Return deterministic iproute output and record mutations."""
        if arguments == ["ip", "-j", "-4", "address", "show"]:
            output = [
                {
                    "ifname": "eth0",
                    "addr_info": [{"family": "inet", "local": "192.0.2.2"}],
                }
            ]
        elif arguments == ["ip", "-j", "link", "show"]:
            output = [{"ifname": name} for name in self.devices]
        elif arguments == ["ip", "-j", "-4", "route", "show", "table", "all"]:
            output = [] if self.route is None else [{"dst": self.route}]
        elif arguments[:4] == ["ip", "tuntap", "add", "dev"]:
            self.mutations.append(arguments)
            name = arguments[4]
            self.devices[name] = {"user": arguments[-1]}
            output = ""
        elif arguments[:4] == ["ip", "address", "add", "local"]:
            self.mutations.append(arguments)
            name = arguments[-1]
            self.devices[name].update(local=arguments[4], peer=arguments[6])
            output = ""
        elif arguments[:4] == ["ip", "link", "set", "dev"]:
            self.mutations.append(arguments)
            output = ""
        elif arguments[:4] == ["ip", "tuntap", "show", "dev"]:
            name = arguments[-1]
            output = (
                f"{name}: tun persist user {self.devices[name]['user']}"
                if name in self.devices
                else ""
            )
        elif arguments[:6] == ["ip", "-j", "-4", "address", "show", "dev"]:
            name = arguments[-1]
            device = self.devices[name]
            output = [
                {
                    "addr_info": [
                        {
                            "family": "inet",
                            "local": device.get("local"),
                            "peer": device.get("peer"),
                        }
                    ]
                }
            ]
        elif arguments[:4] == ["ip", "tuntap", "del", "dev"]:
            self.mutations.append(arguments)
            self.devices.pop(arguments[4], None)
            output = ""
        else:
            raise AssertionError(f"unexpected command: {arguments}")
        return subprocess.CompletedProcess(
            arguments, 0, json.dumps(output) if isinstance(output, list) else output, ""
        )


def test_close_removes_only_its_tunnel_and_preserves_another_session(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Keep concurrent same-key TUN devices and forwarding owners isolated."""
    config = _config()
    paths = _paths(tmp_path)
    first_options = _reserve(config, paths, 41000)
    second_options = _reserve(config, paths, 41001)
    network = FakeNetwork()
    network.devices["tun9"] = {"user": "unrelated"}
    leases: set[str] = set()
    monkeypatch.setattr(
        runtime,
        "acquire_forwarding",
        lambda owner_id, interfaces, **kwargs: leases.add(owner_id) or "0",
    )
    monkeypatch.setattr(
        runtime,
        "release_forwarding",
        lambda owner_id, previous, **kwargs: leases.remove(owner_id),
    )
    first_connection = "192.0.2.20 41000 203.0.113.10 22"
    second_connection = "192.0.2.20 41001 203.0.113.10 22"

    runtime.pam_lifecycle(
        config,
        {
            "PAM_USER": "gateway-tunnel",
            "PAM_TYPE": "open_session",
            "SSH_CONNECTION": first_connection,
        },
        paths=paths,
        runner=network.run,
        now=102.0,
    )
    runtime.pam_lifecycle(
        config,
        {
            "PAM_USER": "gateway-tunnel",
            "PAM_TYPE": "open_session",
            "SSH_CONNECTION": second_connection,
        },
        paths=paths,
        runner=network.run,
        now=103.0,
    )
    first_id = _read_reservations(paths)[0]["connection_id"]
    second_id = _read_reservations(paths)[1]["connection_id"]
    assert first_options != second_options
    assert set(network.devices) == {"tun0", "tun1", "tun9"}
    assert leases == {first_id, second_id}

    runtime.pam_lifecycle(
        config,
        {
            "PAM_USER": "gateway-tunnel",
            "PAM_TYPE": "close_session",
            "SSH_CONNECTION": first_connection,
        },
        paths=paths,
        runner=network.run,
        now=104.0,
    )

    assert set(network.devices) == {"tun1", "tun9"}
    assert leases == {second_id}
    assert [record["connection_id"] for record in _read_reservations(paths)] == [
        second_id
    ]


def test_route_conflict_fails_before_interface_or_forwarding_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Reject a peer route collision before creating a TUN or firewall lease."""
    config = _config()
    paths = _paths(tmp_path)
    _reserve(config, paths, 41000)
    network = FakeNetwork()
    network.route = "198.18.0.0/24"
    leases: list[str] = []
    monkeypatch.setattr(
        runtime,
        "acquire_forwarding",
        lambda *args, **kwargs: leases.append("acquired") or "0",
    )

    with pytest.raises(runtime.TunnelRuntimeError, match="conflicts"):
        runtime.pam_lifecycle(
            config,
            {
                "PAM_USER": "gateway-tunnel",
                "PAM_TYPE": "open_session",
                "SSH_CONNECTION": "192.0.2.20 41000 203.0.113.10 22",
            },
            paths=paths,
            runner=network.run,
            now=102.0,
        )

    assert network.mutations == []
    assert leases == []


def test_critical_forwarding_rollback_aborts_ssh_tun_open(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Surface critical lease failure and remove the uncommitted SSH TUN."""
    config = _config()
    paths = _paths(tmp_path)
    _reserve(config, paths, 41000)
    network = FakeNetwork()

    def fail_acquire(
        owner_id: str, interfaces: tuple[str, ...], **kwargs: object
    ) -> str:
        raise ForwardingRollbackError(owner_id, ("table",))

    monkeypatch.setattr(runtime, "acquire_forwarding", fail_acquire)

    with pytest.raises(ForwardingRollbackError) as error:
        runtime.pam_lifecycle(
            config,
            {
                "PAM_USER": "gateway-tunnel",
                "PAM_TYPE": "open_session",
                "SSH_CONNECTION": "192.0.2.20 41000 203.0.113.10 22",
            },
            paths=paths,
            runner=network.run,
            now=102.0,
        )

    assert error.value.critical is True
    assert error.value.owner_id
    assert network.devices == {}
    reservation = _read_reservations(paths)
    assert len(reservation) == 1
    assert reservation[0]["status"] == "pending"
