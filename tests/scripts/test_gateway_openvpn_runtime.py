"""Test the Gateway OpenVPN process and forwarding boundaries."""

from __future__ import annotations

import io
import json
import subprocess
from pathlib import Path

import pytest

from gateway.development.openvpn_runtime import (
    RuntimeErrorSafe,
    _cleanup_runtime_attempt,
    _netfilter_rules,
    _openvpn_config,
    _sanitized_diagnostic,
    _tunnel_route_up,
    _validate_assigned_address,
    _validate_route_candidates,
    build_openvpn_command,
    configure_forwarding,
    restore_forwarding,
    run_openvpn,
)


def _config(*, enabled: bool = True, profile_reviewed: bool = True) -> dict:
    """Build isolated OpenVPN runtime metadata."""
    return {
        "gateway": {
            "remote_access": {
                "openvpn": {
                    "enabled": enabled,
                    "profile_reviewed": profile_reviewed,
                    "protocol": "udp",
                    "port": 1194,
                    "device": "tun",
                    "topology": "subnet",
                    "client_to_client": True,
                    "auth": "SHA256",
                    "cipher": "AES-256-CBC",
                    "client_pool": "172.24.0.0/21",
                    "endpoint": "vpn.example.test",
                }
            }
        },
        "networks": [
            {
                "name": "shared",
                "subnet": "192.168.9.0/24",
                "gateway_address": "192.168.9.2",
            }
        ],
    }


def test_openvpn_runtime_requires_operator_profile_review() -> None:
    """Reject activation until an operator reviews the opaque profile."""
    with pytest.raises(RuntimeErrorSafe, match="operator-reviewed"):
        _openvpn_config(_config(profile_reviewed=False))


def test_disabled_openvpn_cannot_start_runtime() -> None:
    """Reject direct runtime invocation when configuration disables OpenVPN."""
    with pytest.raises(RuntimeErrorSafe, match="while disabled"):
        _openvpn_config(_config(enabled=False))


def test_enabled_openvpn_runtime_coexists_with_ssh_tun_configuration() -> None:
    """Allow both remote transports to share the forwarding lifecycle."""
    config = _config()
    config["gateway"]["remote_access"]["ssh_tun"] = {
        "enabled": True,
        "account": "gateway-tunnel",
        "address_pool": "198.18.0.0/24",
        "authorized_keys_path": "/test/authorized_keys",
        "max_sessions": 4,
    }

    assert _openvpn_config(config)["enabled"] is True


def test_openvpn_command_suppresses_route_changes_and_profile_logs() -> None:
    """Keep pushed route mutation and OpenVPN logging under runtime control."""
    command = build_openvpn_command(
        "/run/openvpn/client.ovpn",
        executable="/usr/sbin/openvpn",
        config_path="/etc/gateway/generated/config.json",
    )

    assert command[:3] == [
        "/usr/sbin/openvpn",
        "--config",
        "/run/openvpn/client.ovpn",
    ]
    assert "--ifconfig-noexec" in command
    assert "--route-noexec" in command
    assert "--block-ipv6" in command
    assert command[command.index("reject") - 1] == "--pull-filter"
    assert command[
        command.index("ifconfig-ipv6") - 2 : command.index("ifconfig-ipv6") + 1
    ] == [
        "--pull-filter",
        "reject",
        "ifconfig-ipv6",
    ]
    assert command[
        command.index("route-ipv6") - 2 : command.index("route-ipv6") + 1
    ] == [
        "--pull-filter",
        "reject",
        "route-ipv6",
    ]
    assert "--ifconfig-ipv6-noexec" not in command
    assert "--route-ipv6-noexec" not in command
    assert "--route-up-restart" in command
    assert command[command.index("--client")] == "--client"
    assert command[command.index("--dev") + 1] == "tun0"
    assert command[command.index("--topology") + 1] == "subnet"
    assert command[command.index("--auth") + 1] == "SHA256"
    assert command[command.index("--data-ciphers") + 1] == "AES-256-CBC"
    assert command[command.index("--remote-cert-tls") + 1] == "server"
    assert command[command.index("--up") + 1] == "/usr/local/bin/gateway-openvpn-up"
    assert command[command.index("--down") + 1] == "/usr/local/bin/gateway-openvpn-down"
    assert command[command.index("--route-up") + 1] == (
        "/usr/local/bin/gateway-openvpn-route-up"
    )
    assert command[command.index("--setenv") + 1 : command.index("--setenv") + 3] == [
        "GATEWAY_CONFIG",
        "/etc/gateway/generated/config.json",
    ]
    runtime_id = command[command.index("GATEWAY_RUNTIME_ID") + 1]
    assert len(runtime_id) == 64
    assert all(character in "0123456789abcdef" for character in runtime_id)
    assert "--auth-nocache" in command
    assert command[command.index("--log") + 1] == "/dev/stderr"
    assert command[command.index("--verb") + 1] == "0"


def test_openvpn_assigned_address_is_validated_before_interface_mutation() -> None:
    """Accept only a server-assigned address inside the configured client pool."""
    openvpn = _openvpn_config(_config())
    environment = {
        "dev": "tun0",
        "ifconfig_local": "172.24.0.10",
        "ifconfig_remote_netmask": "255.255.248.0",
    }

    assert _validate_assigned_address(environment, openvpn) == ("172.24.0.10", 21)


@pytest.mark.parametrize(
    "environment",
    [
        {
            "dev": "tun0",
            "ifconfig_local": "172.25.0.10",
            "ifconfig_remote_netmask": "255.255.248.0",
        },
        {
            "dev": "tun0",
            "ifconfig_local": "172.24.0.10",
            "ifconfig_remote_netmask": "255.255.255.0",
        },
        {
            "dev": "tun0",
            "ifconfig_local": "172.24.0.0",
            "ifconfig_remote_netmask": "255.255.248.0",
        },
        {
            "dev": "tun0",
            "ifconfig_local": "172.24.7.255",
            "ifconfig_remote_netmask": "255.255.248.0",
        },
        {
            "dev": "tun1",
            "ifconfig_local": "172.24.0.10",
            "ifconfig_remote_netmask": "255.255.248.0",
        },
    ],
)
def test_openvpn_rejects_unexpected_address_or_tunnel(
    environment: dict[str, str],
) -> None:
    """Reject address, netmask, or interface changes before configuring TUN."""
    with pytest.raises(RuntimeErrorSafe):
        _validate_assigned_address(environment, _openvpn_config(_config()))


@pytest.mark.parametrize(
    "environment",
    [
        {"route_network_1": "0.0.0.0", "route_netmask_1": "0.0.0.0"},
        {"route_network_1": "10.0.0.0", "route_netmask_1": "255.0.0.0"},
        {"route_network_2": "10.0.0.0", "route_netmask_2": "255.0.0.0"},
        {"route_netmask_1": "255.0.0.0"},
        {"route_ipv6_network_1": "::", "route_ipv6_netbits_1": "0"},
        {"route_ipv6_network_1": "2001:db8::", "route_ipv6_netbits_1": "32"},
        {"ifconfig_ipv6_local": "2001:db8::2"},
    ],
)
def test_openvpn_rejects_route_candidates_before_route_changes(
    environment: dict[str, str],
) -> None:
    """Reject all pushed or profile routes because Podman paths are connected."""
    with pytest.raises(RuntimeErrorSafe, match="route"):
        _validate_route_candidates(environment)


def _route_environment(runtime_id: str) -> dict[str, str]:
    """Build one synthetic validated OpenVPN hook environment."""
    return {
        "GATEWAY_RUNTIME_ID": runtime_id,
        "dev": "tun0",
        "ifconfig_local": "172.24.0.10",
        "ifconfig_remote_netmask": "255.255.248.0",
    }


def test_invalid_initial_candidates_make_no_kernel_or_forwarding_changes(
    tmp_path: Path,
) -> None:
    """Reject IPv6 default routes before the tunnel or forwarding state changes."""
    environment = _route_environment("a" * 64)
    environment.update({"route_ipv6_network_1": "::", "route_ipv6_netbits_1": "0"})
    forwarding_path = tmp_path / "ip_forward"
    forwarding_path.write_text("0", encoding="ascii")
    calls: list[list[str]] = []

    def runner(arguments: list[str], **kwargs):
        calls.append(arguments)
        return subprocess.CompletedProcess(arguments, 0, "", "")

    with pytest.raises(RuntimeErrorSafe, match="IPv6"):
        _tunnel_route_up(
            environment,
            _config(),
            runner=runner,
            state_path=tmp_path / "private" / "state.json",
            forwarding_path=forwarding_path,
        )

    assert calls == []
    assert forwarding_path.read_text(encoding="ascii") == "0"
    assert not (tmp_path / "private").exists()


def test_invalid_reconnect_preserves_owned_state_and_cleanup_preserves_unrelated_ip(
    tmp_path: Path,
) -> None:
    """Keep a valid session intact on invalid reconnect and clean only its address."""
    runtime_id = "b" * 64
    environment = _route_environment(runtime_id)
    state_path = tmp_path / "private" / "state.json"
    forwarding_path = tmp_path / "ip_forward"
    forwarding_path.write_text("0", encoding="ascii")
    addresses: list[str] = []
    calls: list[list[str]] = []
    firewall_exists = False
    firewall_comment: str | None = None
    link_up = False

    def runner(arguments: list[str], input=None, **kwargs):
        nonlocal firewall_exists, firewall_comment, link_up
        calls.append(arguments)
        if arguments == ["ip", "-j", "-4", "address", "show", "dev", "tun0"]:
            rows = [
                {
                    "addr_info": [
                        {"family": "inet", "local": value} for value in addresses
                    ]
                }
            ]
            return subprocess.CompletedProcess(arguments, 0, json.dumps(rows), "")
        if arguments == ["ip", "-j", "-4", "address", "show"]:
            rows = [
                {
                    "ifname": "eth0",
                    "addr_info": [
                        {"family": "inet", "local": "192.168.9.2"},
                    ],
                }
            ]
            return subprocess.CompletedProcess(arguments, 0, json.dumps(rows), "")
        if arguments == ["ip", "-j", "link", "show", "dev", "tun0"]:
            flags = ["UP"] if link_up else []
            rows = [{"ifname": "tun0", "flags": flags}]
            return subprocess.CompletedProcess(arguments, 0, json.dumps(rows), "")
        if arguments == ["nft", "-j", "list", "tables"]:
            return subprocess.CompletedProcess(
                arguments,
                0,
                json.dumps(
                    {
                        "nftables": (
                            [
                                {
                                    "table": {
                                        "family": "inet",
                                        "name": "gateway_remote_access",
                                    }
                                }
                            ]
                            if firewall_exists
                            else []
                        )
                    }
                ),
                "",
            )
        if arguments == [
            "nft",
            "-j",
            "-a",
            "list",
            "table",
            "inet",
            "gateway_remote_access",
        ]:
            return subprocess.CompletedProcess(
                arguments,
                0,
                json.dumps(
                    {
                        "nftables": [
                            {
                                "table": {
                                    "family": "inet",
                                    "name": "gateway_remote_access",
                                    "comment": firewall_comment,
                                    "handle": 41,
                                }
                            }
                        ]
                    }
                ),
                "",
            )
        if arguments == ["nft", "-f", "-"]:
            firewall_exists = True
            firewall_comment = f"gateway-runtime:{runtime_id}"
        elif arguments == ["nft", "delete", "table", "inet", "handle", "41"]:
            firewall_exists = False
            firewall_comment = None
        elif arguments[:3] == ["ip", "address", "add"]:
            addresses.append(arguments[3].split("/")[0])
        elif arguments[:3] == ["ip", "address", "del"]:
            address = arguments[3].split("/")[0]
            if address in addresses:
                addresses.remove(address)
        elif arguments == ["ip", "link", "set", "dev", "tun0", "up"]:
            link_up = True
        elif arguments == ["ip", "link", "set", "dev", "tun0", "down"]:
            link_up = False
        return subprocess.CompletedProcess(arguments, 0, "", "")

    _tunnel_route_up(
        environment,
        _config(),
        runner=runner,
        state_path=state_path,
        forwarding_path=forwarding_path,
    )
    assert addresses == ["172.24.0.10"]
    assert forwarding_path.read_text(encoding="ascii") == "1"
    saved_state = state_path.read_text(encoding="utf-8")

    reconnect = _route_environment(runtime_id)
    reconnect.update({"route_ipv6_network_1": "::", "route_ipv6_netbits_1": "0"})
    calls.clear()
    with pytest.raises(RuntimeErrorSafe, match="IPv6"):
        _tunnel_route_up(
            reconnect,
            _config(),
            runner=runner,
            state_path=state_path,
            forwarding_path=forwarding_path,
        )

    assert calls == []
    assert state_path.read_text(encoding="utf-8") == saved_state
    assert addresses == ["172.24.0.10"]
    assert forwarding_path.read_text(encoding="ascii") == "1"
    assert firewall_exists

    _tunnel_route_up(
        environment,
        _config(),
        runner=runner,
        state_path=state_path,
        forwarding_path=forwarding_path,
    )
    assert addresses == ["172.24.0.10"]
    assert forwarding_path.read_text(encoding="ascii") == "1"

    addresses.append("172.24.0.11")
    _cleanup_runtime_attempt(
        runtime_id,
        runner=runner,
        state_path=state_path,
        forwarding_path=forwarding_path,
    )
    assert addresses == ["172.24.0.11"]
    assert link_up
    assert forwarding_path.read_text(encoding="ascii") == "0"
    assert not firewall_exists
    assert not state_path.exists()


def test_matching_preexisting_tunnel_address_is_never_claimed_or_deleted(
    tmp_path: Path,
) -> None:
    """Reject even a matching unowned address and leave it untouched."""
    addresses = ["172.24.0.10"]
    calls: list[list[str]] = []
    state_path = tmp_path / "private" / "state.json"
    forwarding_path = tmp_path / "ip_forward"
    forwarding_path.write_text("0", encoding="ascii")

    def runner(arguments: list[str], **kwargs):
        calls.append(arguments)
        rows = [
            {"addr_info": [{"family": "inet", "local": value} for value in addresses]}
        ]
        return subprocess.CompletedProcess(arguments, 0, json.dumps(rows), "")

    with pytest.raises(RuntimeErrorSafe, match="unowned"):
        _tunnel_route_up(
            _route_environment("c" * 64),
            _config(),
            runner=runner,
            state_path=state_path,
            forwarding_path=forwarding_path,
        )

    assert addresses == ["172.24.0.10"]
    assert calls == [["ip", "-j", "-4", "address", "show", "dev", "tun0"]]
    assert not state_path.exists()
    assert forwarding_path.read_text(encoding="ascii") == "0"


def test_forwarding_rules_preserve_sources_and_deny_application_forwarding() -> None:
    """Allow tunnel-to-Podman and established replies without NAT or app peering."""
    runtime_id = "c" * 64
    rules = _netfilter_rules(("eth0", "eth1"), runtime_id)

    assert "create table inet gateway_remote_access" in rules
    assert f'comment "gateway-runtime:{runtime_id}"' in rules
    assert "destroy table" not in rules
    assert "policy drop" in rules
    assert 'iifname { "eth0", "eth1" } oifname { "eth0", "eth1" } drop' in rules
    assert "ct state established,related accept" in rules
    assert 'iifname "tun*" oifname { "eth0", "eth1" } accept' in rules
    assert "snat" not in rules.lower()
    assert "masquerade" not in rules.lower()
    assert "0.0.0.0/0" not in rules


def test_forwarding_mutation_is_scoped_and_restores_prior_namespace_state(
    tmp_path,
) -> None:
    """Install one owned nft table, enable forwarding, then restore only it."""
    forwarding_path = tmp_path / "ip_forward"
    forwarding_path.write_text("0", encoding="ascii")
    calls: list[tuple[list[str], str | None]] = []
    runtime_id = "d" * 64
    firewall_exists = False
    firewall_comment: str | None = None

    def runner(arguments: list[str], *, input=None, **kwargs):
        nonlocal firewall_exists, firewall_comment
        calls.append((arguments, input))
        if arguments == ["nft", "-j", "list", "tables"]:
            tables = (
                [
                    {
                        "table": {
                            "family": "inet",
                            "name": "gateway_remote_access",
                        }
                    }
                ]
                if firewall_exists
                else []
            )
            return subprocess.CompletedProcess(
                arguments, 0, json.dumps({"nftables": tables}), ""
            )
        if arguments == [
            "nft",
            "-j",
            "-a",
            "list",
            "table",
            "inet",
            "gateway_remote_access",
        ]:
            return subprocess.CompletedProcess(
                arguments,
                0,
                json.dumps(
                    {
                        "nftables": [
                            {
                                "table": {
                                    "family": "inet",
                                    "name": "gateway_remote_access",
                                    "comment": firewall_comment,
                                    "handle": 41,
                                }
                            }
                        ]
                    }
                ),
                "",
            )
        if arguments == ["nft", "-f", "-"]:
            firewall_exists = True
            firewall_comment = f"gateway-runtime:{runtime_id}"
        elif arguments == ["nft", "delete", "table", "inet", "handle", "41"]:
            firewall_exists = False
            firewall_comment = None
        return subprocess.CompletedProcess(arguments, 0, "", "")

    previous = configure_forwarding(
        ("eth0", "eth1"),
        runtime_id=runtime_id,
        runner=runner,
        forwarding_path=forwarding_path,
    )

    assert previous == "0"
    assert forwarding_path.read_text(encoding="ascii") == "1"
    install_call = next(call for call in calls if call[0] == ["nft", "-f", "-"])
    assert install_call[1] is not None
    assert "create table inet gateway_remote_access" in install_call[1]
    assert "iifname { " in install_call[1]
    assert 'iifname "tun*"' in install_call[1]
    assert "masquerade" not in install_call[1]

    restore_forwarding(
        previous,
        runtime_id=runtime_id,
        runner=runner,
        forwarding_path=forwarding_path,
    )

    assert calls[-1][0] == ["nft", "delete", "table", "inet", "handle", "41"]
    assert forwarding_path.read_text(encoding="ascii") == "0"


def test_forwarding_create_does_not_mutate_preexisting_firewall_table(
    tmp_path,
) -> None:
    """Leave a pre-existing table and sysctl untouched when exclusive create fails."""
    forwarding_path = tmp_path / "ip_forward"
    forwarding_path.write_text("0", encoding="ascii")
    calls: list[tuple[list[str], str | None]] = []
    runtime_id = "e" * 64
    occupied_table = {"comment": "foreign-owner", "rules": ["foreign rule"]}

    def runner(arguments: list[str], *, input=None, **kwargs):
        calls.append((arguments, input))
        if arguments == ["nft", "-j", "list", "tables"]:
            tables = [
                {
                    "table": {
                        "family": "inet",
                        "name": "gateway_remote_access",
                    }
                }
            ]
            return subprocess.CompletedProcess(
                arguments, 0, json.dumps({"nftables": tables}), ""
            )
        if arguments == ["nft", "-f", "-"]:
            assert occupied_table == {
                "comment": "foreign-owner",
                "rules": ["foreign rule"],
            }
            return subprocess.CompletedProcess(arguments, 1, "", "table exists")
        return subprocess.CompletedProcess(arguments, 0, "", "")

    with pytest.raises(RuntimeErrorSafe, match="without an ownership record"):
        configure_forwarding(
            ("eth0", "eth1"),
            runtime_id=runtime_id,
            runner=runner,
            forwarding_path=forwarding_path,
        )

    assert calls == [
        (
            ["nft", "-j", "list", "tables"],
            None,
        )
    ]
    assert occupied_table == {"comment": "foreign-owner", "rules": ["foreign rule"]}
    assert forwarding_path.read_text(encoding="ascii") == "0"


def test_interleaved_foreign_table_creation_fails_exclusive_install_without_mutation(
    tmp_path: Path,
) -> None:
    """Preserve a foreign table created after runtime starts its atomic install."""
    forwarding_path = tmp_path / "ip_forward"
    forwarding_path.write_text("0", encoding="ascii")
    runtime_id = "f" * 64
    foreign_table: dict[str, object] | None = None
    calls: list[tuple[list[str], str | None]] = []

    def runner(arguments: list[str], *, input=None, **kwargs):
        nonlocal foreign_table
        calls.append((arguments, input))
        if arguments == ["nft", "-j", "list", "tables"]:
            return subprocess.CompletedProcess(
                arguments, 0, json.dumps({"nftables": []}), ""
            )
        if arguments == ["nft", "-f", "-"]:
            foreign_table = {"comment": "foreign-owner", "rules": ["foreign rule"]}
            return subprocess.CompletedProcess(arguments, 1, "", "table exists")
        return subprocess.CompletedProcess(arguments, 0, "", "")

    with pytest.raises(RuntimeErrorSafe, match="Could not install"):
        configure_forwarding(
            ("eth0",),
            runtime_id=runtime_id,
            runner=runner,
            forwarding_path=forwarding_path,
        )

    assert calls == [
        (
            ["nft", "-j", "list", "tables"],
            None,
        ),
        (
            ["nft", "-f", "-"],
            _netfilter_rules(("eth0",), runtime_id),
        ),
    ]
    assert foreign_table == {"comment": "foreign-owner", "rules": ["foreign rule"]}
    assert forwarding_path.read_text(encoding="ascii") == "0"


def test_forwarding_cleanup_preserves_table_with_changed_owner(
    tmp_path: Path,
) -> None:
    """Do not delete or alter forwarding for a table whose ownership changed."""
    forwarding_path = tmp_path / "ip_forward"
    forwarding_path.write_text("1", encoding="ascii")
    runtime_id = "1" * 64
    table_exists = False
    table_comment: str | None = None
    calls: list[list[str]] = []

    def runner(arguments: list[str], *, input=None, **kwargs):
        nonlocal table_exists, table_comment
        calls.append(arguments)
        if arguments == ["nft", "-j", "list", "tables"]:
            tables = (
                [{"table": {"family": "inet", "name": "gateway_remote_access"}}]
                if table_exists
                else []
            )
            output = {"nftables": tables}
            return subprocess.CompletedProcess(arguments, 0, json.dumps(output), "")
        if arguments == [
            "nft",
            "-j",
            "-a",
            "list",
            "table",
            "inet",
            "gateway_remote_access",
        ]:
            output = {
                "nftables": [
                    {
                        "table": {
                            "family": "inet",
                            "name": "gateway_remote_access",
                            "comment": table_comment,
                            "handle": 52,
                        }
                    }
                ]
            }
            return subprocess.CompletedProcess(arguments, 0, json.dumps(output), "")
        if arguments == ["nft", "-f", "-"]:
            table_exists = True
            table_comment = f"gateway-runtime:{runtime_id}"
            return subprocess.CompletedProcess(arguments, 0, "", "")
        pytest.fail("Changed-ownership cleanup must not mutate the table.")

    previous = configure_forwarding(
        ("eth0",),
        runtime_id=runtime_id,
        runner=runner,
        forwarding_path=forwarding_path,
    )
    table_comment = "gateway-runtime:" + "2" * 64

    with pytest.raises(RuntimeErrorSafe, match="ownership changed"):
        restore_forwarding(
            previous,
            runtime_id=runtime_id,
            runner=runner,
            forwarding_path=forwarding_path,
        )

    assert calls[-2:] == [
        ["nft", "-j", "list", "tables"],
        ["nft", "-j", "-a", "list", "table", "inet", "gateway_remote_access"],
    ]
    assert forwarding_path.read_text(encoding="ascii") == "1"


def test_forwarding_cleanup_delete_does_not_remove_replacement_table(
    tmp_path: Path,
) -> None:
    """Use the inspected kernel handle so a foreign replacement survives."""
    forwarding_path = tmp_path / "ip_forward"
    forwarding_path.write_text("1", encoding="ascii")
    runtime_id = "3" * 64
    table_handle = 73
    table_exists = False
    table_comment: str | None = None
    foreign_table: dict[str, object] | None = None
    calls: list[list[str]] = []

    def runner(arguments: list[str], *, input=None, **kwargs):
        nonlocal foreign_table, table_exists, table_comment
        calls.append(arguments)
        if arguments == ["nft", "-j", "list", "tables"]:
            tables = (
                [{"table": {"family": "inet", "name": "gateway_remote_access"}}]
                if table_exists
                else []
            )
            output = {"nftables": tables}
            return subprocess.CompletedProcess(arguments, 0, json.dumps(output), "")
        if arguments == [
            "nft",
            "-j",
            "-a",
            "list",
            "table",
            "inet",
            "gateway_remote_access",
        ]:
            output = {
                "nftables": [
                    {
                        "table": {
                            "family": "inet",
                            "name": "gateway_remote_access",
                            "comment": table_comment,
                            "handle": table_handle,
                        }
                    }
                ]
            }
            return subprocess.CompletedProcess(arguments, 0, json.dumps(output), "")
        if arguments == ["nft", "-f", "-"]:
            table_exists = True
            table_comment = f"gateway-runtime:{runtime_id}"
            return subprocess.CompletedProcess(arguments, 0, "", "")
        if arguments == [
            "nft",
            "delete",
            "table",
            "inet",
            "handle",
            str(table_handle),
        ]:
            foreign_table = {
                "name": "gateway_remote_access",
                "comment": "foreign-owner",
                "handle": table_handle + 1,
                "rules": ["foreign rule"],
            }
            return subprocess.CompletedProcess(
                arguments, 1, "", "table handle no longer exists"
            )
        pytest.fail("Cleanup must delete only the verified table handle.")

    previous = configure_forwarding(
        ("eth0",),
        runtime_id=runtime_id,
        runner=runner,
        forwarding_path=forwarding_path,
    )

    with pytest.raises(RuntimeErrorSafe, match="Could not remove Gateway forwarding"):
        restore_forwarding(
            previous,
            runtime_id=runtime_id,
            runner=runner,
            forwarding_path=forwarding_path,
        )

    assert foreign_table == {
        "name": "gateway_remote_access",
        "comment": "foreign-owner",
        "handle": table_handle + 1,
        "rules": ["foreign rule"],
    }
    assert calls[-1] == [
        "nft",
        "delete",
        "table",
        "inet",
        "handle",
        str(table_handle),
    ]
    assert forwarding_path.read_text(encoding="ascii") == "1"


def test_openvpn_error_output_is_reduced_to_fixed_safe_messages() -> None:
    """Never forward raw paths, credentials, profile text, or OpenVPN logs."""
    diagnostic = _sanitized_diagnostic(
        "Cannot open file /etc/gateway/private/secret.key: permission denied"
    )

    assert diagnostic == (
        "OpenVPN could not open a configured external input; "
        "check the root-managed read-only mounts."
    )
    assert "/etc/gateway/private/secret.key" not in diagnostic
    assert _sanitized_diagnostic("remote peer supplied certificate detail") is None


def test_openvpn_supervisor_uses_fake_transport_and_sanitizes_its_output(
    monkeypatch,
    capsys,
) -> None:
    """Exercise a synthetic client process without reading its profile."""
    captured: dict[str, object] = {}

    class FakeProcess:
        """Return synthetic OpenVPN output without launching a process."""

        def __init__(self, command, **kwargs):
            captured["command"] = command
            captured["stderr"] = kwargs["stderr"]
            self.stderr = io.StringIO(
                "Cannot open file /etc/gateway/private/secret.key: private detail\n"
            )

        def poll(self):
            return 0

        def wait(self):
            return 0

    monkeypatch.setattr(
        "gateway.development.openvpn_runtime._profile_is_safe",
        lambda path, runner: captured.setdefault("profile", path),
    )
    monkeypatch.setattr(
        "gateway.development.openvpn_runtime._require_tun_capability",
        lambda: None,
    )
    monkeypatch.setattr(
        "gateway.development.openvpn_runtime._gateway_interfaces",
        lambda config, runner: ("eth0", "eth1"),
    )
    monkeypatch.setattr(
        "gateway.development.openvpn_runtime.configure_forwarding",
        lambda *args, **kwargs: pytest.fail(
            "Forwarding must wait until the route-up candidates pass."
        ),
    )
    monkeypatch.setattr(
        "gateway.development.openvpn_runtime.shutil.which",
        lambda executable: "/usr/sbin/openvpn",
    )
    monkeypatch.setattr(
        "gateway.development.openvpn_runtime.subprocess.Popen",
        FakeProcess,
    )

    status = run_openvpn(
        _config(),
        profile_path=Path("/run/openvpn/client.ovpn"),
    )

    output = capsys.readouterr()
    assert status == 0
    assert captured["profile"] == Path("/run/openvpn/client.ovpn")
    assert captured["stderr"] is subprocess.PIPE
    assert "/etc/gateway/private/secret.key" not in output.err
    assert "private detail" not in output.err
    assert "configured external input" in output.err
