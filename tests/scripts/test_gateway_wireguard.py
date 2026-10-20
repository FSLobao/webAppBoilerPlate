"""Test WireGuard configuration, one-time delivery, and peer lifecycle."""

from __future__ import annotations

import hashlib
import io
import json
import os
import subprocess
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
                    "protocol": "udp",
                    "port": 1194,
                    "device": "tun",
                    "topology": "subnet",
                    "client_to_client": True,
                    "auth": "SHA256",
                    "cipher": "AES-256-CBC",
                    "client_pool": "172.24.0.0/21",
                    "push_domains": ["anatel.gov.br"],
                },
                "ssh_tun": {"enabled": False},
                "wireguard": {
                    "enabled": True,
                    "host_bind_address": "0.0.0.0",
                    "listen_port": 54000,
                    "endpoint": "vpn.example.test",
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
        _config(), "peer-001", "person@example.test", "workstation access"
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
