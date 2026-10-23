"""Test remote-access metadata validation and owned route planning."""

from __future__ import annotations

import ipaddress
import subprocess
from pathlib import Path

import pytest

from gateway.development.host_config_validation import load_host_config
from scripts.gateway.host_preflight import (
    _validate_remote_access_routes,
    validate_gateway_networks,
)
from scripts.gateway.remote_access import (
    GatewayNetwork,
    OwnedRoute,
    RouteOwner,
    RoutePlan,
    RouteSpec,
    apply_route_plan,
    plan_remote_routes,
    reconcile_remote_routes,
    validate_activation_addresses,
    validate_remote_access_config,
    validate_remote_access_host_routes,
)

PODMAN_NETWORKS = [
    {"name": "shared", "subnet": "192.168.9.0/24", "gateway_address": "192.168.9.2"},
    {"name": "webApp", "subnet": "192.168.8.0/29", "gateway_address": "192.168.8.2"},
]
OPENVPN_CONFIG = {
    "enabled": False,
    "profile_path": "/etc/gateway/openvpn/ERMXDF02.ovpn",
    "client_pool": "172.24.0.0/21",
}


def _config(
    *,
    openvpn: dict[str, object] | None = None,
    ssh_tun: dict[str, object] | None = None,
) -> dict[str, object]:
    """Build a test configuration with isolated remote-access pools."""
    return {
        "networks": PODMAN_NETWORKS,
        "gateway": {
            "remote_access": {
                "openvpn": openvpn or OPENVPN_CONFIG.copy(),
                "ssh_tun": ssh_tun or {"enabled": False},
                "wireguard": {"enabled": False},
            }
        },
    }


def _wireguard_config(**overrides: object) -> dict[str, object]:
    """Return synthetic, fully explicit WireGuard activation values."""
    return {
        "enabled": True,
        "host_bind_address": "127.0.0.1",
        "listen_port": 54000,
        "address_pool": "198.18.1.0/24",
        "server_address": "10.254.0.1",
        "dns_server": "192.168.9.2",
        "server_private_key_path": "/etc/gateway/wireguard/server.key",
        **overrides,
    }


def _networks() -> list[GatewayNetwork]:
    """Return only test Gateway network addresses."""
    return [
        GatewayNetwork(
            "shared",
            ipaddress.ip_network("192.168.9.0/24"),
            ipaddress.ip_address("192.168.9.2"),
        ),
        GatewayNetwork(
            "webApp",
            ipaddress.ip_network("192.168.8.0/29"),
            ipaddress.ip_address("192.168.8.2"),
        ),
    ]


def test_accepts_optional_remote_access_metadata_without_reading_profile() -> None:
    """Accept disabled metadata and retain schema version one declarations."""
    config = {"schema_version": 1, **_config()}

    validate_remote_access_config(config)


def test_enabled_openvpn_needs_no_extra_confirmation_field() -> None:
    """Accept enabled OpenVPN metadata without a separate confirmation field."""
    openvpn = OPENVPN_CONFIG.copy() | {"enabled": True}

    validate_remote_access_config(
        _config(openvpn=openvpn),
        announce=lambda _message: None,
    )


def test_checked_in_config_omits_retired_openvpn_fields() -> None:
    """Validate canonical OpenVPN config without duplicated server settings."""
    config_path = Path(__file__).resolve().parents[2] / "config/host_config.json"
    config = load_host_config(config_path)
    validate_remote_access_config(config)

    assert config["schema_version"] == 1
    openvpn = config["gateway"]["remote_access"]["openvpn"]
    assert {
        "protocol",
        "port",
        "device",
        "topology",
        "client_to_client",
        "auth",
        "cipher",
        "push_domains",
        "endpoint",
    }.isdisjoint(openvpn)


def test_accepts_fully_configured_wireguard_only_when_explicitly_enabled() -> None:
    """Validate IPv4-only WireGuard values without reading the server key."""
    validate_remote_access_config(
        _config()
        | {
            "gateway": {
                "remote_access": {
                    "openvpn": OPENVPN_CONFIG.copy(),
                    "ssh_tun": {"enabled": False},
                    "wireguard": _wireguard_config(),
                }
            }
        }
    )


def test_accepts_server_address_inside_peer_pool_as_split_dns_resolver() -> None:
    """Reserve the server address in the peer pool and allow it as the resolver."""
    wireguard = _wireguard_config(
        address_pool="192.168.10.0/24",
        server_address="192.168.10.1",
        dns_server="192.168.10.1",
    )
    config = _config()
    config["gateway"]["remote_access"]["wireguard"] = wireguard

    validate_remote_access_config(config)


def test_rejects_pool_network_address_as_wireguard_server() -> None:
    """Reject a non-host network address for the server inside its peer pool."""
    wireguard = _wireguard_config(
        address_pool="192.168.10.0/24",
        server_address="192.168.10.0",
        dns_server="192.168.10.0",
    )
    config = _config()
    config["gateway"]["remote_access"]["wireguard"] = wireguard

    with pytest.raises(ValueError, match="usable host address"):
        validate_remote_access_config(config)


def test_rejects_wireguard_endpoint_in_host_config() -> None:
    """Keep client-reachable endpoints out of persistent host configuration."""
    wireguard = _wireguard_config(endpoint="vpn.example.test")
    config = _config()
    config["gateway"]["remote_access"]["wireguard"] = wireguard

    with pytest.raises(ValueError, match="missing or unsupported fields"):
        validate_remote_access_config(config)


def test_wireguard_disabled_can_retain_prior_pool_for_owned_route_cleanup() -> None:
    """Allow validated inactive settings so deployment can remove its old route."""
    wireguard = _wireguard_config(enabled=False)
    validate_remote_access_config(
        _config()
        | {
            "gateway": {
                "remote_access": {
                    "openvpn": OPENVPN_CONFIG.copy(),
                    "ssh_tun": {"enabled": False},
                    "wireguard": wireguard,
                }
            }
        }
    )


@pytest.mark.parametrize(
    "retired_field",
    [
        "protocol",
        "port",
        "device",
        "topology",
        "client_to_client",
        "auth",
        "cipher",
        "push_domains",
        "endpoint",
    ],
)
def test_rejects_retired_openvpn_fields(retired_field: str) -> None:
    """Reject retired OpenVPN fields in this schema-v1 setup."""
    openvpn = OPENVPN_CONFIG.copy()
    openvpn[retired_field] = "legacy"

    with pytest.raises(ValueError, match="unsupported fields"):
        validate_remote_access_config(_config(openvpn=openvpn))


def test_missing_openvpn_pool_warns_and_remains_optional() -> None:
    """Allow an unknown external allocation without inventing a client range."""
    openvpn = {"enabled": True, "profile_path": OPENVPN_CONFIG["profile_path"]}
    config = _config(openvpn=openvpn)
    config["networks"] = [{"name": "app", "subnet": "203.0.113.0/24"}]
    messages = []

    validate_remote_access_config(
        config,
        announce=messages.append,
    )

    assert len(messages) == 1
    assert "client_pool is not configured" in messages[0]
    assert "symmetric client reply routing is not guaranteed" in messages[0]


def test_host_preflight_warns_when_openvpn_pool_is_missing() -> None:
    """Report unavailable allocation and return-route checks during preflight."""
    config = _config(
        openvpn={
            "enabled": False,
            "profile_path": OPENVPN_CONFIG["profile_path"],
        }
    )
    messages = []

    def run_command(
        arguments: list[str], **kwargs: object
    ) -> subprocess.CompletedProcess:
        if arguments == ["podman", "network", "ls", "--format", "{{.Name}}"]:
            return subprocess.CompletedProcess(arguments, 0, "", "")
        if arguments == ["ip", "-j", "-4", "route", "show", "table", "all"]:
            return subprocess.CompletedProcess(
                arguments,
                0,
                '[{"dst":"172.24.0.0/16","dev":"eth0","table":"100"}]',
                "",
            )
        raise AssertionError(f"unexpected command: {arguments}")

    validate_gateway_networks(config, run_command=run_command, announce=messages.append)

    assert any(
        "client_pool is not configured" in message
        and "symmetric client reply routing is not guaranteed" in message
        for message in messages
    )


@pytest.mark.parametrize("unsupported", ["routes", "ccd", "route_pushes"])
def test_rejects_unapproved_openvpn_server_route_metadata(
    unsupported: str,
) -> None:
    """Reject route-push and CCD fields not present in the supplied topology."""
    openvpn = OPENVPN_CONFIG.copy()
    openvpn[unsupported] = []

    with pytest.raises(ValueError, match="unsupported fields"):
        validate_remote_access_config(_config(openvpn=openvpn))


def test_rejects_enabled_ssh_tun_without_explicit_activation_inputs() -> None:
    """Require operator-selected SSH account and address pool before enabling."""
    with pytest.raises(ValueError, match="explicit account"):
        validate_remote_access_config(_config(ssh_tun={"enabled": True}))


def test_accepts_test_only_ssh_inputs_when_disabled_or_explicit() -> None:
    """Validate an isolated test pool without assigning production values."""
    validate_remote_access_config(
        _config(
            ssh_tun={
                "enabled": True,
                "account": "gateway-tunnel",
                "address_pool": "198.18.0.0/24",
                "authorized_keys_path": "/etc/gateway/ssh_tun/authorized_keys",
                "max_sessions": 4,
            }
        )
    )


@pytest.mark.parametrize(
    ("pool", "message"),
    [
        ("192.168.9.0/24", "overlaps Podman network"),
        ("172.24.4.0/24", "overlaps OpenVPN client pool"),
    ],
)
def test_rejects_overlapping_remote_access_pools(pool: str, message: str) -> None:
    """Reject remote pool overlaps with Podman or another tunnel pool."""
    ssh_tun = {
        "enabled": True,
        "account": "gateway-tunnel",
        "address_pool": pool,
        "authorized_keys_path": "/etc/gateway/ssh_tun/authorized_keys",
        "max_sessions": 4,
    }

    with pytest.raises(ValueError, match=message):
        validate_remote_access_config(_config(ssh_tun=ssh_tun))


def test_host_preflight_ignores_default_route_and_rejects_pool_overlap() -> None:
    """Ignore default host route but reject a specific route overlapping pool."""
    config = _config()
    validate_remote_access_host_routes(
        config,
        [{"dst": "default", "gateway": "192.0.2.1", "dev": "eth0"}],
    )

    with pytest.raises(ValueError, match="overlaps host IPv4 route"):
        validate_remote_access_host_routes(
            config,
            [{"dst": "172.24.0.0/16", "dev": "eth0", "table": "100"}],
        )


def test_host_preflight_requires_exact_active_session_context() -> None:
    """Allow an exact pool route only for its explicit active owner."""
    config = _config()
    route = RouteSpec(
        ipaddress.ip_network("172.24.0.0/21"),
        "host",
        interface="tun0",
    )
    owned = OwnedRoute(route, RouteOwner("openvpn", "openvpn-client"))
    route_state = [{"dst": "172.24.0.0/21", "dev": "tun0", "table": "main"}]

    validate_remote_access_host_routes(
        config,
        route_state,
        active_routes=[owned],
        active_owners={"openvpn": [owned.owner]},
    )

    with pytest.raises(ValueError, match="overlaps host IPv4 route"):
        validate_remote_access_host_routes(
            config,
            route_state,
            active_routes=[owned],
            active_owners={"openvpn": [RouteOwner("openvpn", "different-session")]},
        )


@pytest.mark.parametrize("protocol", ["186", "bgp"])
def test_preflight_recognizes_only_exact_tagged_openvpn_host_return_route(
    protocol: str,
) -> None:
    """Allow the managed pool route but reject wrong gateway or route tag."""
    openvpn = OPENVPN_CONFIG.copy() | {
        "enabled": True,
    }
    config = _config(openvpn=openvpn)
    owned_route = {
        "dst": "172.24.0.0/21",
        "gateway": "192.168.8.2",
        "dev": "podman1",
        "protocol": protocol,
        "table": 254,
    }

    _validate_remote_access_routes(config, [owned_route])

    with pytest.raises(ValueError, match="overlaps host IPv4 route"):
        _validate_remote_access_routes(
            config,
            [owned_route | {"gateway": "192.168.8.3"}],
        )
    with pytest.raises(ValueError, match="overlaps host IPv4 route"):
        _validate_remote_access_routes(
            config,
            [owned_route | {"protocol": "static"}],
        )


@pytest.mark.parametrize("protocol", ["186", "bgp"])
def test_preflight_recognizes_only_exact_tagged_wireguard_return_route(
    protocol: str,
) -> None:
    """Allow only the exact WireGuard pool route through its configured gateway."""
    config = _config()
    config["gateway"]["remote_access"]["wireguard"] = _wireguard_config()
    owned_route = {
        "dst": "198.18.1.0/24",
        "gateway": "192.168.8.2",
        "dev": "podman1",
        "protocol": protocol,
        "table": 254,
    }

    _validate_remote_access_routes(config, [owned_route])

    with pytest.raises(ValueError, match="overlaps host IPv4 route"):
        _validate_remote_access_routes(
            config,
            [owned_route | {"gateway": "192.168.8.3"}],
        )


def test_gateway_preflight_rejects_invalid_pool_before_host_commands() -> None:
    """Reject a Podman-overlapping pool before issuing preflight commands."""
    config = _config()
    remote = config["gateway"]["remote_access"]
    remote["openvpn"]["client_pool"] = "192.168.9.0/24"
    commands: list[list[str]] = []

    def run_command(command: list[str], **kwargs: object):
        commands.append(command)
        raise AssertionError(f"unexpected command: {command}")

    with pytest.raises(ValueError, match="overlaps Podman network"):
        validate_gateway_networks(
            config,
            run_command=run_command,
            announce=lambda message: None,
        )

    assert commands == []


def test_gateway_preflight_rejects_missing_enabled_profile_without_commands() -> None:
    """Fail on profile metadata before Podman or route inspection."""
    openvpn = OPENVPN_CONFIG.copy() | {
        "enabled": True,
        "profile_path": "/etc/gateway/openvpn/missing-test-profile.ovpn",
    }
    config = _config(openvpn=openvpn)
    commands: list[list[str]] = []

    def run_command(command: list[str], **kwargs: object):
        commands.append(command)
        raise AssertionError(f"unexpected command: {command}")

    with pytest.raises(ValueError, match="profile is unavailable"):
        validate_gateway_networks(
            config,
            run_command=run_command,
            announce=lambda message: None,
        )

    assert commands == []


def test_gateway_preflight_rejects_missing_ssh_tun_public_key_file() -> None:
    """Fail before host inspection when the enabled key file is unavailable."""
    config = _config(
        ssh_tun={
            "enabled": True,
            "account": "gateway-tunnel",
            "address_pool": "198.18.0.0/24",
            "authorized_keys_path": "/etc/gateway/ssh_tun/authorized_keys",
            "max_sessions": 4,
        }
    )
    commands: list[list[str]] = []

    def run_command(command: list[str], **kwargs: object):
        commands.append(command)
        raise AssertionError(f"unexpected command: {command}")

    with pytest.raises(ValueError, match="public-key file is unavailable"):
        validate_gateway_networks(
            config,
            run_command=run_command,
            announce=lambda message: None,
        )

    assert commands == []


def test_gateway_preflight_checks_pool_against_read_only_host_routes() -> None:
    """Reject a configured remote pool overlapping a real-route candidate."""
    config = _config()
    config["networks"] = []
    commands: list[list[str]] = []

    def run_command(command: list[str], **kwargs: object):
        commands.append(command)
        if command == ["podman", "network", "ls", "--format", "{{.Name}}"]:
            return subprocess.CompletedProcess(command, 0, "", "")
        if command == ["ip", "-j", "-4", "route", "show", "table", "all"]:
            return subprocess.CompletedProcess(
                command,
                0,
                '[{"dst":"172.24.0.0/16","dev":"eth0","table":"100"}]',
                "",
            )
        raise AssertionError(f"unexpected command: {command}")

    with pytest.raises(ValueError, match="overlaps host IPv4 route"):
        validate_gateway_networks(
            config,
            run_command=run_command,
            announce=lambda message: None,
        )

    assert commands == [
        ["podman", "network", "ls", "--format", "{{.Name}}"],
        ["ip", "-j", "-4", "route", "show", "table", "all"],
    ]


def test_reconcile_rejects_addresses_before_mutation() -> None:
    """Reject candidate endpoint conflicts before invoking route callbacks."""
    mutations: list[RouteSpec] = []
    with pytest.raises(ValueError, match="endpoint 192.168.9.10 overlaps"):
        reconcile_remote_routes(
            owner=RouteOwner("openvpn", "openvpn-client"),
            assigned_addresses=["172.24.0.10"],
            endpoint_address="192.168.9.10",
            client_prefix="172.24.0.0/21",
            openvpn_pool="172.24.0.0/21",
            ssh_pool=None,
            tunnel_interface="tun0",
            pushed_routes=[],
            networks=_networks(),
            observed_routes=[],
            active_routes=[],
            host_routes=[],
            add_route=mutations.append,
            remove_route=mutations.append,
        )
    assert mutations == []


def test_reconcile_rejects_foreign_pool_route_before_mutation() -> None:
    """Do not mutate when a host route overlaps a configured remote pool."""
    mutations: list[RouteSpec] = []

    with pytest.raises(ValueError, match="overlaps host IPv4 route"):
        reconcile_remote_routes(
            owner=RouteOwner("openvpn", "openvpn-client"),
            assigned_addresses=["172.24.0.10"],
            endpoint_address="203.0.113.25",
            client_prefix="172.24.0.0/21",
            openvpn_pool="172.24.0.0/21",
            ssh_pool=None,
            tunnel_interface="tun0",
            pushed_routes=[],
            networks=_networks(),
            observed_routes=[],
            active_routes=[],
            host_routes=[{"dst": "172.24.0.0/16", "dev": "eth0", "table": "100"}],
            add_route=mutations.append,
            remove_route=mutations.append,
        )

    assert mutations == []


def test_activation_requires_two_ssh_tun_addresses_from_explicit_pool() -> None:
    """Accept a test-only TUN pair and reject a single-address SSH candidate."""
    arguments = {
        "transport": "ssh_tun",
        "assigned_addresses": ["198.18.0.1", "198.18.0.2"],
        "endpoint_address": "203.0.113.25",
        "client_prefix": "198.18.0.1/32",
        "openvpn_pool": "172.24.0.0/21",
        "ssh_pool": "198.18.0.0/24",
        "networks": _networks(),
        "host_routes": [],
    }

    validate_activation_addresses(**arguments)

    with pytest.raises(ValueError, match="requires 2 unique assigned"):
        validate_activation_addresses(
            **arguments | {"assigned_addresses": ["198.18.0.1"]}
        )


def test_reconcile_without_openvpn_pool_does_not_plan_host_return_route() -> None:
    """Keep unknown OpenVPN allocations from creating managed host routes."""
    plan = reconcile_remote_routes(
        owner=RouteOwner("openvpn", "openvpn-client"),
        assigned_addresses=["172.25.4.10"],
        endpoint_address="203.0.113.25",
        client_prefix="172.25.4.0/24",
        openvpn_pool=None,
        ssh_pool=None,
        tunnel_interface="tun0",
        pushed_routes=[],
        networks=_networks(),
        observed_routes=[],
        active_routes=[],
        host_routes=[],
        add_route=lambda route: None,
        remove_route=lambda route: None,
    )

    assert all(route.plane != "host" for route in plan.additions)


def test_reconcile_without_openvpn_pool_preserves_existing_host_return_route() -> None:
    """Leave existing OpenVPN host routes untouched when its pool is unknown."""
    owner = RouteOwner("openvpn", "openvpn-client")
    destination = ipaddress.ip_network("172.25.4.0/24")
    gateway_route = RouteSpec(destination, "gateway", interface="tun0")
    stale_gateway_route = RouteSpec(
        ipaddress.ip_network("172.25.3.0/24"),
        "gateway",
        interface="tun0",
    )
    host_return_route = RouteSpec(
        destination,
        "host",
        gateway=ipaddress.ip_address("192.168.8.2"),
    )
    added: list[RouteSpec] = []
    removed: list[RouteSpec] = []

    reconcile_remote_routes(
        owner=owner,
        assigned_addresses=["172.25.4.10"],
        endpoint_address="203.0.113.25",
        client_prefix="172.25.4.0/24",
        openvpn_pool=None,
        ssh_pool=None,
        tunnel_interface="tun0",
        pushed_routes=[],
        networks=_networks(),
        observed_routes=[gateway_route, stale_gateway_route, host_return_route],
        active_routes=[
            OwnedRoute(gateway_route, owner),
            OwnedRoute(stale_gateway_route, owner),
            OwnedRoute(host_return_route, owner),
        ],
        host_routes=[
            {
                "dst": "172.25.4.0/24",
                "gateway": "192.168.8.2",
                "table": "main",
            }
        ],
        add_route=added.append,
        remove_route=removed.append,
    )

    assert added == []
    assert removed == [stale_gateway_route]
    assert host_return_route not in removed


def test_rejects_default_pushed_route_before_mutation() -> None:
    """Reject pushed default routes and leave mutation adapters untouched."""
    owner = RouteOwner("openvpn", "openvpn-client")
    mutations: list[RouteSpec] = []
    stale_route = RouteSpec(
        ipaddress.ip_network("172.25.0.0/24"),
        "gateway",
        interface="tun0",
    )

    with pytest.raises(ValueError, match="non-default"):
        reconcile_remote_routes(
            owner=owner,
            assigned_addresses=["172.24.0.10"],
            endpoint_address="203.0.113.25",
            client_prefix="172.24.0.0/21",
            openvpn_pool="172.24.0.0/21",
            ssh_pool=None,
            tunnel_interface="tun0",
            pushed_routes=["0.0.0.0/0"],
            networks=_networks(),
            observed_routes=[stale_route],
            active_routes=[OwnedRoute(stale_route, owner)],
            host_routes=[],
            add_route=mutations.append,
            remove_route=mutations.append,
        )
    assert mutations == []


def test_plan_ignores_and_preserves_existing_host_default_route() -> None:
    """Keep an existing host default route outside candidate ownership."""
    default_route = RouteSpec(
        ipaddress.ip_network("0.0.0.0/0"),
        "host",
        gateway=ipaddress.ip_address("192.0.2.1"),
    )

    plan = plan_remote_routes(
        owner=RouteOwner("openvpn", "openvpn-client"),
        client_prefix="172.24.0.0/21",
        tunnel_interface="tun0",
        pushed_routes=[],
        networks=_networks(),
        observed_routes=[default_route],
        active_routes=[],
    )

    assert default_route not in plan.additions
    assert default_route not in plan.removals


def test_rejects_pushed_route_overlapping_podman_network() -> None:
    """Reject routes that would replace connected Podman paths."""
    with pytest.raises(ValueError, match="overlaps Podman network"):
        plan_remote_routes(
            owner=RouteOwner("openvpn", "openvpn-client"),
            client_prefix="172.24.0.0/21",
            tunnel_interface="tun0",
            pushed_routes=["192.168.8.0/29"],
            networks=_networks(),
            observed_routes=[],
            active_routes=[],
        )


def test_accepts_only_exact_owned_active_route_in_same_session() -> None:
    """Treat an exact same-session route as idempotent, not a foreign route."""
    owner = RouteOwner("openvpn", "openvpn-client")
    gateway_route = RouteSpec(
        ipaddress.ip_network("172.24.0.0/21"),
        "gateway",
        interface="tun0",
    )
    host_route = RouteSpec(
        ipaddress.ip_network("172.24.0.0/21"),
        "host",
        gateway=ipaddress.ip_address("192.168.8.2"),
    )
    active = [
        OwnedRoute(gateway_route, owner),
        OwnedRoute(host_route, owner),
    ]

    plan = plan_remote_routes(
        owner=owner,
        client_prefix="172.24.0.0/21",
        tunnel_interface="tun0",
        pushed_routes=[],
        networks=_networks(),
        observed_routes=[gateway_route, host_route],
        active_routes=active,
    )

    assert plan.additions == ()
    assert set(plan.unchanged) == {gateway_route, host_route}

    foreign_owner = RouteOwner("openvpn", "another-session")
    with pytest.raises(ValueError, match="conflicts"):
        plan_remote_routes(
            owner=owner,
            client_prefix="172.24.0.0/21",
            tunnel_interface="tun0",
            pushed_routes=[],
            networks=_networks(),
            observed_routes=[gateway_route, host_route],
            active_routes=[
                OwnedRoute(gateway_route, foreign_owner),
                OwnedRoute(host_route, foreign_owner),
            ],
        )


def test_rejects_foreign_same_prefix_and_preserves_other_session_cleanup() -> None:
    """Reject foreign same-prefix routes and plan cleanup for this owner only."""
    owner = RouteOwner("ssh_tun", "session-1")
    other_owner = RouteOwner("ssh_tun", "session-2")
    candidate = RouteSpec(
        ipaddress.ip_network("198.18.0.0/24"),
        "gateway",
        interface="tun1",
    )
    with pytest.raises(ValueError, match="conflicts"):
        plan_remote_routes(
            owner=owner,
            client_prefix="198.18.0.0/24",
            tunnel_interface="tun1",
            pushed_routes=[],
            networks=_networks(),
            observed_routes=[candidate],
            active_routes=[OwnedRoute(candidate, other_owner)],
        )

    stale_gateway = RouteSpec(
        ipaddress.ip_network("198.18.1.0/24"),
        "gateway",
        interface="tun1",
    )
    stale_host = RouteSpec(
        ipaddress.ip_network("198.18.1.0/24"),
        "host",
        gateway=ipaddress.ip_address("192.168.8.2"),
    )
    foreign = RouteSpec(
        ipaddress.ip_network("198.18.2.0/24"),
        "gateway",
        interface="tun2",
    )
    plan = plan_remote_routes(
        owner=owner,
        client_prefix="198.18.0.0/24",
        tunnel_interface="tun1",
        pushed_routes=[],
        networks=_networks(),
        observed_routes=[stale_gateway, stale_host, foreign],
        active_routes=[
            OwnedRoute(stale_gateway, owner),
            OwnedRoute(stale_host, owner),
            OwnedRoute(foreign, other_owner),
        ],
    )

    assert {owned.route for owned in plan.removals} == {stale_gateway, stale_host}
    assert all(owned.route != foreign for owned in plan.removals)


def test_host_return_next_hop_is_deterministic() -> None:
    """Select the configured Gateway address on the lowest sorted subnet."""
    plan = plan_remote_routes(
        owner=RouteOwner("openvpn", "openvpn-client"),
        client_prefix="172.24.0.0/21",
        tunnel_interface="tun0",
        pushed_routes=[],
        networks=list(reversed(_networks())),
        observed_routes=[],
        active_routes=[],
    )

    host_route = next(route for route in plan.additions if route.plane == "host")
    assert host_route.gateway == ipaddress.ip_address("192.168.8.2")


def test_route_apply_rolls_back_only_confirmed_changes_after_failed_cleanup() -> None:
    """Restore successful changes but preserve routes after atomic failure."""
    owner = RouteOwner("ssh_tun", "session-1")
    old_gateway = RouteSpec(
        ipaddress.ip_network("198.18.1.0/24"),
        "gateway",
        interface="tun1",
    )
    old_host = RouteSpec(
        ipaddress.ip_network("198.18.1.0/24"),
        "host",
        gateway=ipaddress.ip_address("192.168.8.2"),
    )
    foreign = RouteSpec(
        ipaddress.ip_network("198.18.2.0/24"),
        "gateway",
        interface="tun2",
    )
    plan = plan_remote_routes(
        owner=owner,
        client_prefix="198.18.0.0/24",
        tunnel_interface="tun1",
        pushed_routes=[],
        networks=_networks(),
        observed_routes=[old_gateway, old_host, foreign],
        active_routes=[
            OwnedRoute(old_gateway, owner),
            OwnedRoute(old_host, owner),
            OwnedRoute(foreign, RouteOwner("ssh_tun", "session-2")),
        ],
    )
    routes = {
        old_gateway: owner,
        old_host: owner,
        foreign: RouteOwner("ssh_tun", "session-2"),
    }
    added: list[RouteSpec] = []
    removed: list[RouteSpec] = []

    def add_route(route: RouteSpec) -> None:
        added.append(route)
        routes[route] = owner

    def remove_route(route: RouteSpec) -> None:
        removed.append(route)
        if route == old_host:
            raise OSError("test failure")
        routes.pop(route)

    with pytest.raises(OSError, match="test failure"):
        apply_route_plan(plan, add_route=add_route, remove_route=remove_route)

    candidate_routes = set(plan.additions)
    assert set(routes) == {old_gateway, old_host, foreign}
    assert old_gateway in added
    assert old_host not in added
    assert candidate_routes.issubset(set(removed))
    assert foreign not in added and foreign not in removed


def test_route_apply_does_not_remove_route_after_failed_add() -> None:
    """Keep a foreign route when an atomic add callback reports a collision."""
    owner = RouteOwner("ssh_tun", "session-1")
    other_owner = RouteOwner("ssh_tun", "session-2")
    foreign_route = RouteSpec(
        ipaddress.ip_network("198.18.0.0/24"),
        "gateway",
        interface="tun2",
    )
    plan = RoutePlan(owner, (foreign_route,), (), ())
    routes = {foreign_route: other_owner}
    removed: list[RouteSpec] = []

    def add_route(route: RouteSpec) -> None:
        if route in routes:
            raise FileExistsError("route already exists")
        routes[route] = owner

    def remove_route(route: RouteSpec) -> None:
        removed.append(route)
        routes.pop(route)

    with pytest.raises(FileExistsError, match="route already exists"):
        apply_route_plan(plan, add_route=add_route, remove_route=remove_route)

    assert routes == {foreign_route: other_owner}
    assert removed == []


def test_route_apply_is_idempotent_for_unchanged_active_routes() -> None:
    """Applying an unchanged active plan repeatedly performs no mutations."""
    owner = RouteOwner("openvpn", "openvpn-client")
    gateway_route = RouteSpec(
        ipaddress.ip_network("172.24.0.0/21"),
        "gateway",
        interface="tun0",
    )
    host_route = RouteSpec(
        ipaddress.ip_network("172.24.0.0/21"),
        "host",
        gateway=ipaddress.ip_address("192.168.8.2"),
    )
    active_routes = [
        OwnedRoute(gateway_route, owner),
        OwnedRoute(host_route, owner),
    ]
    plan = plan_remote_routes(
        owner=owner,
        client_prefix="172.24.0.0/21",
        tunnel_interface="tun0",
        pushed_routes=[],
        networks=_networks(),
        observed_routes=[gateway_route, host_route],
        active_routes=active_routes,
    )
    mutations: list[RouteSpec] = []

    assert plan.additions == ()
    apply_route_plan(plan, add_route=mutations.append, remove_route=mutations.append)
    apply_route_plan(plan, add_route=mutations.append, remove_route=mutations.append)

    assert mutations == []


def test_route_apply_refuses_foreign_owned_cleanup_plan() -> None:
    """Refuse malformed cleanup plans before calling mutation adapters."""
    owner = RouteOwner("ssh_tun", "session-1")
    foreign_route = RouteSpec(
        ipaddress.ip_network("198.18.2.0/24"),
        "gateway",
        interface="tun2",
    )
    mutations: list[RouteSpec] = []
    plan = RoutePlan(
        owner,
        (),
        (),
        (OwnedRoute(foreign_route, RouteOwner("ssh_tun", "session-2")),),
    )

    with pytest.raises(ValueError, match="owned by another session"):
        apply_route_plan(
            plan,
            add_route=mutations.append,
            remove_route=mutations.append,
        )

    assert mutations == []
