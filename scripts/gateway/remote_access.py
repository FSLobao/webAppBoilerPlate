"""Validate remote-access inputs and plan explicitly owned route changes.

The public functions are pure except ``apply_route_plan``, which calls
caller-supplied route operations. This module never reads a VPN profile or
launches host commands.
"""

from __future__ import annotations

import ipaddress
import logging
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

Transport = Literal["openvpn", "ssh_tun", "wireguard"]
"""Supported remote-access transport names."""
RoutePlane = Literal["gateway", "host"]
"""Routing namespace that contains a route."""
RouteOperation = Callable[["RouteSpec"], None]
"""Run one route operation atomically; a raised exception must not mutate it."""


@dataclass(frozen=True)
class GatewayNetwork:
    """Describe one configured Gateway address and Podman subnet.

    Public attributes are the network name, subnet, and optional Gateway address.
    """

    name: str
    subnet: ipaddress.IPv4Network
    address: ipaddress.IPv4Address | None


@dataclass(frozen=True)
class RouteSpec:
    """Describe one IPv4 route and its routing namespace.

    Public attributes are destination, plane, optional interface and gateway,
    and route table.
    """

    destination: ipaddress.IPv4Network
    plane: RoutePlane
    interface: str | None = None
    gateway: ipaddress.IPv4Address | None = None
    table: str | int = "main"


@dataclass(frozen=True)
class RouteOwner:
    """Identify one transport session that owns route state.

    Public attributes are transport and stable session ID.
    """

    transport: Transport
    session_id: str


@dataclass(frozen=True)
class OwnedRoute:
    """Associate one route with its exact transport-session owner.

    Public attributes are route and owner.
    """

    route: RouteSpec
    owner: RouteOwner


@dataclass(frozen=True)
class RoutePlan:
    """Hold route changes owned by one session.

    Public attributes are owner, additions, unchanged routes, and removals.
    """

    owner: RouteOwner
    additions: tuple[RouteSpec, ...]
    unchanged: tuple[RouteSpec, ...]
    removals: tuple[OwnedRoute, ...]


def _ipv4_network(
    value: object, label: str, *, pool: bool = True
) -> ipaddress.IPv4Network:
    """Parse one canonical IPv4 network or pool."""
    if not isinstance(value, str):
        raise TypeError(f"{label} must be an IPv4 CIDR string")
    network = ipaddress.ip_network(value, strict=True)
    if (
        network.version != 4
        or network.prefixlen == 0
        or (pool and network.num_addresses < 4)
    ):
        raise ValueError(f"{label} must be a usable, non-default IPv4 range")
    return network


def _validate_profile_path(value: object) -> None:
    """Validate the external profile path without opening it."""
    if (
        not isinstance(value, str)
        or not value.startswith("/")
        or "\0" in value
        or any(part in (".", "..") for part in value.split("/"))
        or not re.fullmatch(r"/[A-Za-z0-9/_.-]+", value)
    ):
        raise ValueError(
            "gateway.remote_access.openvpn.profile_path must be an absolute safe path"
        )


def _validate_authorized_keys_path(value: object) -> None:
    """Validate the root-managed SSH key path without opening it."""
    if (
        not isinstance(value, str)
        or not value.startswith("/")
        or "\0" in value
        or any(part in (".", "..") for part in value.split("/"))
        or not re.fullmatch(r"/[A-Za-z0-9/_.-]+", value)
    ):
        raise ValueError(
            "gateway.remote_access.ssh_tun.authorized_keys_path "
            "must be an absolute safe path"
        )


def _validate_private_key_path(value: object) -> None:
    """Validate an absolute path for a root-managed private key."""
    if (
        not isinstance(value, str)
        or not value.startswith("/")
        or "\0" in value
        or any(part in (".", "..") for part in value.split("/"))
        or not re.fullmatch(r"/[A-Za-z0-9/_.-]+", value)
    ):
        raise ValueError(
            "gateway.remote_access.wireguard.server_private_key_path "
            "must be an absolute safe path"
        )


def _validate_client_profiles_path(value: object) -> None:
    """Validate the absolute host directory used for generated client profiles."""
    if (
        not isinstance(value, str)
        or not value.startswith("/")
        or value == "/"
        or "\0" in value
        or value.endswith("/")
        or any(part in ("", ".", "..") for part in value.split("/")[1:])
        or not re.fullmatch(r"/[A-Za-z0-9/_.-]+", value)
    ):
        raise ValueError(
            "gateway.remote_access.wireguard.client_profiles_path "
            "must be an absolute safe host directory path"
        )
    if value == "/var/lib/gateway/wireguard" or value.startswith(
        "/var/lib/gateway/wireguard/"
    ):
        raise ValueError(
            "gateway.remote_access.wireguard.client_profiles_path must be outside "
            "the Gateway peer-state mount"
        )


def _validate_endpoint(value: object, label: str) -> ipaddress.IPv4Address | None:
    """Validate an optional endpoint literal or DNS name."""
    if not isinstance(value, str) or not value:
        raise ValueError(f"{label} must be a non-empty IPv4 address or DNS name")
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        if len(value) > 253 or any(
            not re.fullmatch(
                r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?", label_part
            )
            for label_part in value.rstrip(".").split(".")
        ):
            raise ValueError(f"{label} must be an IPv4 address or DNS name") from None
        return None
    if address.version != 4:
        raise ValueError(f"{label} must be an IPv4 address")
    return address


def _configured_networks(config: Mapping[str, object]) -> list[GatewayNetwork]:
    """Parse configured Podman networks for remote-access checks."""
    networks = config.get("networks")
    if not isinstance(networks, list):
        raise TypeError("top-level networks must be an array")
    parsed = []
    for item in networks:
        if not isinstance(item, dict):
            raise TypeError("each top-level network must be an object")
        name = item.get("name")
        if not isinstance(name, str):
            raise TypeError("each top-level network must have a string name")
        subnet = _ipv4_network(
            item.get("subnet"), f"network '{name}' subnet", pool=False
        )
        raw_address = item.get("gateway_address")
        address = None
        if raw_address is not None:
            if not isinstance(raw_address, str):
                raise ValueError(
                    f"network '{name}' gateway_address must be an IPv4 address"
                )
            parsed_address = ipaddress.ip_address(raw_address)
            if parsed_address.version != 4 or parsed_address not in subnet:
                raise ValueError(
                    f"network '{name}' gateway_address must be inside its subnet"
                )
            address = parsed_address
        parsed.append(GatewayNetwork(name, subnet, address))
    return parsed


def validate_remote_access_config(
    config: Mapping[str, object],
    *,
    announce: Callable[[str], None] | None = None,
) -> None:
    """Validate the optional, strict ``gateway.remote_access`` configuration.

    Unknown keys are rejected. Disabled sections remain inert. OpenVPN client
    pools are optional; without one, allocation checks and a managed host return
    route are unavailable.

    Args:
        config: Parsed schema-version-1 host configuration.
        announce: Optional recipient for validation warnings.

    Raises:
        TypeError: A remote-access field has an unsupported type.
        ValueError: The schema, metadata, or pool relationships are invalid.
    """
    gateway = config.get("gateway")
    if not isinstance(gateway, dict) or "remote_access" not in gateway:
        return
    remote = gateway["remote_access"]
    if not isinstance(remote, dict) or set(remote) != {
        "openvpn",
        "ssh_tun",
        "wireguard",
    }:
        raise ValueError(
            "gateway.remote_access must contain openvpn, ssh_tun, and wireguard objects"
        )

    openvpn = remote["openvpn"]
    openvpn_keys = {
        "enabled",
        "profile_path",
    }
    optional_openvpn_keys = {"client_pool"}
    if (
        not isinstance(openvpn, dict)
        or set(openvpn) - openvpn_keys - optional_openvpn_keys
        or openvpn_keys - set(openvpn)
    ):
        raise ValueError(
            "gateway.remote_access.openvpn has missing or unsupported fields"
        )
    if not isinstance(openvpn["enabled"], bool):
        raise TypeError("gateway.remote_access.openvpn.enabled must be boolean")
    _validate_profile_path(openvpn["profile_path"])
    openvpn_pool = None
    if "client_pool" in openvpn:
        openvpn_pool = _ipv4_network(
            openvpn["client_pool"], "gateway.remote_access.openvpn.client_pool"
        )
    else:
        warning = (
            "OpenVPN client_pool is not configured; assigned prefix cannot be "
            "checked against the client allocation, no managed host return route "
            "will be installed or validated, and symmetric client reply routing "
            "is not guaranteed."
        )
        if announce is None:
            logging.getLogger(__name__).warning("%s", warning)
        else:
            announce(warning)

    ssh_tun = remote["ssh_tun"]
    if (
        not isinstance(ssh_tun, dict)
        or set(ssh_tun)
        - {
            "enabled",
            "account",
            "address_pool",
            "authorized_keys_path",
            "max_sessions",
        }
        or "enabled" not in ssh_tun
    ):
        raise ValueError(
            "gateway.remote_access.ssh_tun has missing or unsupported fields"
        )
    if not isinstance(ssh_tun["enabled"], bool):
        raise TypeError("gateway.remote_access.ssh_tun.enabled must be boolean")
    ssh_pool = None
    if "account" in ssh_tun:
        account = ssh_tun["account"]
        if not isinstance(account, str) or not re.fullmatch(
            r"[a-z_][a-z0-9_-]{0,31}\$?", account
        ):
            raise ValueError(
                "gateway.remote_access.ssh_tun.account must be a valid account name"
            )
        if account != "gateway-tunnel":
            raise ValueError(
                "gateway.remote_access.ssh_tun.account must be 'gateway-tunnel'"
            )
    if "address_pool" in ssh_tun:
        ssh_pool = _ipv4_network(
            ssh_tun["address_pool"], "gateway.remote_access.ssh_tun.address_pool"
        )
    if "authorized_keys_path" in ssh_tun:
        _validate_authorized_keys_path(ssh_tun["authorized_keys_path"])
    max_sessions = ssh_tun.get("max_sessions")
    if max_sessions is not None and (
        isinstance(max_sessions, bool)
        or not isinstance(max_sessions, int)
        or not 1 <= max_sessions <= 32
    ):
        raise ValueError(
            "gateway.remote_access.ssh_tun.max_sessions must be between 1 and 32"
        )
    if ssh_tun["enabled"] and (
        "account" not in ssh_tun
        or "address_pool" not in ssh_tun
        or "authorized_keys_path" not in ssh_tun
        or "max_sessions" not in ssh_tun
    ):
        raise ValueError(
            "enabled SSH TUN requires explicit account, address_pool, "
            "authorized_keys_path, and max_sessions inputs"
        )
    if (
        ssh_tun["enabled"]
        and ssh_pool is not None
        and isinstance(max_sessions, int)
        and ssh_pool.num_addresses < max_sessions * 2
    ):
        raise ValueError(
            "SSH TUN address_pool must contain two addresses per max_sessions slot"
        )

    networks = _configured_networks(config)
    if (
        openvpn["enabled"]
        and openvpn_pool is not None
        and not any(network.address is not None for network in networks)
    ):
        raise ValueError(
            "enabled OpenVPN requires a Gateway address for the host return route"
        )
    pools = [("OpenVPN client pool", openvpn_pool)] if openvpn_pool is not None else []
    if ssh_pool is not None:
        pools.append(("SSH TUN pool", ssh_pool))
    for name, pool in pools:
        for network in networks:
            if pool.overlaps(network.subnet):
                raise ValueError(
                    f"{name} {pool} overlaps Podman network '{network.name}' "
                    f"subnet {network.subnet}"
                )
    if (
        ssh_pool is not None
        and openvpn_pool is not None
        and openvpn_pool.overlaps(ssh_pool)
    ):
        raise ValueError(
            f"SSH TUN pool {ssh_pool} overlaps OpenVPN client pool {openvpn_pool}"
        )

    wireguard = remote["wireguard"]
    wireguard_keys = {
        "enabled",
        "host_bind_address",
        "listen_port",
        "address_pool",
        "server_address",
        "dns_server",
        "server_private_key_path",
    }
    onboarding_keys = {
        "client_profiles_path",
        "peer_purpose",
        "client_endpoint",
        "approval_reference",
        "expires_at",
    }
    if (
        not isinstance(wireguard, dict)
        or set(wireguard) - wireguard_keys - onboarding_keys
        or "enabled" not in wireguard
    ):
        raise ValueError(
            "gateway.remote_access.wireguard has missing or unsupported fields"
        )
    if not isinstance(wireguard["enabled"], bool):
        raise TypeError("gateway.remote_access.wireguard.enabled must be boolean")
    configured_onboarding_keys = set(wireguard) & onboarding_keys
    if configured_onboarding_keys and configured_onboarding_keys != onboarding_keys:
        raise ValueError(
            "gateway.remote_access.wireguard peer onboarding settings must be "
            "configured together"
        )
    if configured_onboarding_keys:
        _validate_client_profiles_path(wireguard["client_profiles_path"])
        purpose = wireguard["peer_purpose"]
        approval_reference = wireguard["approval_reference"]
        expires_at = wireguard["expires_at"]
        if (
            not isinstance(purpose, str)
            or not purpose.strip()
            or len(purpose) > 256
            or any(
                ord(character) < 32 or ord(character) == 127 for character in purpose
            )
        ):
            raise ValueError(
                "gateway.remote_access.wireguard.peer_purpose must be "
                "non-empty printable text up to 256 characters"
            )
        _validate_endpoint(
            wireguard["client_endpoint"],
            "gateway.remote_access.wireguard.client_endpoint",
        )
        if (
            not isinstance(approval_reference, str)
            or not approval_reference.strip()
            or len(approval_reference) > 128
            or any(
                ord(character) < 32 or ord(character) == 127
                for character in approval_reference
            )
        ):
            raise ValueError(
                "gateway.remote_access.wireguard.approval_reference must be "
                "non-empty printable text up to 128 characters"
            )
        if not isinstance(expires_at, str):
            raise TypeError(
                "gateway.remote_access.wireguard.expires_at must be an "
                "ISO-8601 timestamp with a UTC offset"
            )
        try:
            parsed_expiry = datetime.fromisoformat(expires_at)
        except ValueError as error:
            raise ValueError(
                "gateway.remote_access.wireguard.expires_at must be an "
                "ISO-8601 timestamp with a UTC offset"
            ) from error
        if parsed_expiry.tzinfo is None or parsed_expiry.utcoffset() is None:
            raise ValueError(
                "gateway.remote_access.wireguard.expires_at must include a UTC offset"
            )
    wg_pool = None
    if wireguard["enabled"] or set(wireguard) != {"enabled"}:
        if not wireguard_keys <= set(wireguard):
            raise ValueError(
                "enabled WireGuard requires explicit host bind, UDP port, address "
                "pool, server address, DNS resolver, and server key path"
            )
        bind_address = _validate_endpoint(
            wireguard["host_bind_address"],
            "gateway.remote_access.wireguard.host_bind_address",
        )
        if bind_address is None:
            raise ValueError(
                "gateway.remote_access.wireguard.host_bind_address must be an IPv4 address"
            )
        listen_port = wireguard["listen_port"]
        if (
            isinstance(listen_port, bool)
            or not isinstance(listen_port, int)
            or not 1 <= listen_port <= 65535
        ):
            raise ValueError(
                "gateway.remote_access.wireguard.listen_port must be between 1 and 65535"
            )
        wg_pool = _ipv4_network(
            wireguard["address_pool"], "gateway.remote_access.wireguard.address_pool"
        )
        server_address = wireguard["server_address"]
        resolver_address = wireguard["dns_server"]
        for value, label in (
            (server_address, "server_address"),
            (resolver_address, "dns_server"),
        ):
            if not isinstance(value, str):
                raise TypeError(
                    f"gateway.remote_access.wireguard.{label} must be an IPv4 address"
                )
            parsed = ipaddress.ip_address(value)
            if parsed.version != 4:
                raise ValueError(
                    f"gateway.remote_access.wireguard.{label} must be an IPv4 address"
                )
            if label == "server_address":
                server_address_ip = parsed
            else:
                resolver_address_ip = parsed
        if wg_pool.prefixlen <= 30 and server_address_ip in (
            wg_pool.network_address,
            wg_pool.broadcast_address,
        ):
            raise ValueError(
                "WireGuard server_address must be a usable host address in the peer pool"
            )
        _validate_private_key_path(wireguard["server_private_key_path"])
        if resolver_address_ip != server_address_ip and not any(
            network.address == resolver_address_ip for network in networks
        ):
            raise ValueError(
                "WireGuard dns_server must match a configured Gateway network "
                "address or server_address"
            )
        pools.append(("WireGuard peer pool", wg_pool))
        if wireguard["enabled"] and not any(
            network.address is not None for network in networks
        ):
            raise ValueError(
                "enabled WireGuard requires a Gateway address for the host return route"
            )

    for name, pool in pools:
        if (
            wg_pool is not None
            and name != "WireGuard peer pool"
            and pool.overlaps(wg_pool)
        ):
            raise ValueError(f"WireGuard peer pool {wg_pool} overlaps {name} {pool}")
    if wg_pool is not None:
        for network in networks:
            if wg_pool.overlaps(network.subnet):
                raise ValueError(
                    f"WireGuard peer pool {wg_pool} overlaps Podman network "
                    f"'{network.name}' subnet {network.subnet}"
                )
            if server_address_ip in network.subnet:
                raise ValueError(
                    f"WireGuard server_address {server_address_ip} overlaps "
                    f"Podman network '{network.name}' subnet {network.subnet}"
                )


def validate_remote_access_host_routes(
    config: Mapping[str, object],
    routes: Sequence[Mapping[str, object]],
    *,
    active_routes: Sequence[OwnedRoute] = (),
    active_owners: Mapping[Transport, Sequence[RouteOwner]] | None = None,
) -> None:
    """Reject remote pools that conflict with existing non-default host routes.

    An exact pool route is allowed only when the caller supplies the matching
    active transport-session owner and the active inventory marks that exact
    host route as owned.

    Args:
        config: Parsed host configuration.
        routes: One read-only IPv4 route-table snapshot.
        active_routes: Routes with recorded session ownership.
        active_owners: Expected active session owners per transport.

    Raises:
        ValueError: A pool overlaps an unrelated host route.
    """
    gateway = config.get("gateway")
    remote = gateway.get("remote_access") if isinstance(gateway, dict) else None
    if not isinstance(remote, dict):
        return

    configured_pools: list[tuple[Transport, ipaddress.IPv4Network]] = []
    openvpn = remote.get("openvpn")
    if isinstance(openvpn, dict) and "client_pool" in openvpn:
        configured_pools.append(
            (
                "openvpn",
                _ipv4_network(
                    openvpn.get("client_pool"),
                    "gateway.remote_access.openvpn.client_pool",
                ),
            )
        )
    ssh_tun = remote.get("ssh_tun")
    if isinstance(ssh_tun, dict) and "address_pool" in ssh_tun:
        configured_pools.append(
            (
                "ssh_tun",
                _ipv4_network(
                    ssh_tun["address_pool"],
                    "gateway.remote_access.ssh_tun.address_pool",
                ),
            )
        )
    wireguard = remote.get("wireguard")
    if isinstance(wireguard, dict) and "address_pool" in wireguard:
        configured_pools.append(
            (
                "wireguard",
                _ipv4_network(
                    wireguard.get("address_pool"),
                    "gateway.remote_access.wireguard.address_pool",
                ),
            )
        )

    for route in routes:
        raw_destination = route.get("dst")
        if raw_destination == "default" or raw_destination is None:
            continue
        destination = ipaddress.ip_network(str(raw_destination), strict=False)
        if destination.version != 4 or destination.prefixlen == 0:
            continue
        for transport, pool in configured_pools:
            if not pool.overlaps(destination):
                continue
            exact_owned = any(
                active_owners is not None
                and owned.owner in active_owners.get(transport, ())
                and owned.route.plane == "host"
                and owned.route.destination == destination
                and owned.route.interface == route.get("dev")
                and str(owned.route.gateway or "") == str(route.get("gateway", ""))
                and owned.route.table == route.get("table", "main")
                for owned in active_routes
            )
            if not exact_owned:
                raise ValueError(
                    f"{transport} pool {pool} overlaps host IPv4 route "
                    f"{destination} (table={route.get('table', 'unspecified')}, "
                    f"dev={route.get('dev', 'unspecified')})"
                )


def validate_activation_addresses(
    *,
    transport: Transport,
    assigned_addresses: Sequence[str],
    endpoint_address: str,
    client_prefix: str,
    openvpn_pool: str | None,
    ssh_pool: str | None,
    networks: Sequence[GatewayNetwork],
    host_routes: Sequence[Mapping[str, object]],
) -> None:
    """Validate runtime-assigned tunnel and endpoint addresses before mutation.

    Args:
        transport: OpenVPN or SSH TUN.
        assigned_addresses: One OpenVPN address or one SSH TUN point-to-point pair.
        endpoint_address: Remote tunnel endpoint IPv4 address.
        client_prefix: Remote client destination prefix, contained in its pool.
        openvpn_pool: External server's OpenVPN client pool, or None when unknown.
        ssh_pool: Explicit SSH TUN pool, or None while SSH TUN is disabled.
        networks: Configured Gateway Podman networks.
        host_routes: One read-only host route-table snapshot.

    Raises:
        ValueError: An address is invalid, outside its pool, or conflicts with
            configured networks or local host addresses.
    """
    if transport not in ("openvpn", "ssh_tun"):
        raise ValueError("remote-access transport is unsupported")
    assigned = [ipaddress.ip_address(value) for value in assigned_addresses]
    endpoint = ipaddress.ip_address(endpoint_address)
    if any(address.version != 4 for address in assigned) or endpoint.version != 4:
        raise ValueError("remote-access assigned address and endpoint must be IPv4")
    required_addresses = 1 if transport == "openvpn" else 2
    if len(assigned) != required_addresses or len(set(assigned)) != len(assigned):
        raise ValueError(
            f"{transport} activation requires {required_addresses} unique assigned address(es)"
        )
    vpn_pool = (
        _ipv4_network(openvpn_pool, "OpenVPN client pool")
        if openvpn_pool is not None
        else None
    )
    tunnel_pool = (
        _ipv4_network(ssh_pool, "SSH TUN pool") if ssh_pool is not None else None
    )
    pool = vpn_pool if transport == "openvpn" else tunnel_pool
    if transport == "ssh_tun" and pool is None:
        raise ValueError("SSH TUN activation requires an explicit SSH TUN pool")
    prefix = _ipv4_network(client_prefix, "remote client prefix", pool=False)
    if pool is not None and not prefix.subnet_of(pool):
        raise ValueError(
            f"remote client prefix {prefix} is outside {transport} pool {pool}"
        )
    for address in assigned:
        if pool is not None and address not in pool:
            raise ValueError(
                f"assigned address {address} is outside {transport} pool {pool}"
            )
    pools = [("OpenVPN client pool", vpn_pool)] if vpn_pool is not None else []
    if tunnel_pool is not None:
        pools.append(("SSH TUN pool", tunnel_pool))
    for name, other_pool in pools:
        if endpoint in other_pool:
            raise ValueError(f"endpoint {endpoint} overlaps {name} {other_pool}")
    if pool is not None and endpoint in pool:
        raise ValueError(f"endpoint {endpoint} overlaps {transport} client pool {pool}")
    other_pool = tunnel_pool if transport == "openvpn" else vpn_pool
    for address in assigned:
        if other_pool is not None and address in other_pool:
            raise ValueError(
                f"assigned address {address} overlaps another remote-access pool "
                f"{other_pool}"
            )
    for network in networks:
        for name, candidate_pool in (
            ("OpenVPN client pool", vpn_pool),
            ("SSH TUN pool", tunnel_pool),
        ):
            if candidate_pool is not None and candidate_pool.overlaps(network.subnet):
                raise ValueError(
                    f"{name} {candidate_pool} overlaps Podman network "
                    f"'{network.name}' subnet {network.subnet}"
                )
        for address in assigned:
            if address in network.subnet:
                raise ValueError(
                    f"assigned address {address} overlaps Podman network "
                    f"'{network.name}' subnet {network.subnet}"
                )
        if endpoint in network.subnet:
            raise ValueError(
                f"endpoint {endpoint} overlaps Podman network "
                f"'{network.name}' subnet {network.subnet}"
            )
    for route in host_routes:
        if route.get("type") != "local":
            continue
        destination = route.get("dst")
        if not isinstance(destination, str) or destination == "default":
            continue
        local_network = ipaddress.ip_network(destination, strict=False)
        if local_network.version == 4 and (
            any(address in local_network for address in assigned)
            or endpoint in local_network
        ):
            raise ValueError(
                f"remote-access address conflicts with local host route {destination}"
            )


def _parse_candidate_routes(
    client_prefix: str,
    tunnel_interface: str,
    pushed_routes: Sequence[str],
    networks: Sequence[GatewayNetwork],
) -> list[RouteSpec]:
    """Build tunnel routes and reject pushed defaults or Podman overlaps."""
    if not re.fullmatch(r"[A-Za-z0-9_.:-]{1,64}", tunnel_interface):
        raise ValueError("tunnel interface name is invalid")
    prefix = _ipv4_network(client_prefix, "remote client prefix", pool=False)
    destinations = [("remote client prefix", prefix)]
    for value in pushed_routes:
        route = _ipv4_network(value, "pushed route", pool=False)
        destinations.append(("pushed route", route))
    routes = []
    for label, destination in destinations:
        for network in networks:
            if destination.overlaps(network.subnet):
                raise ValueError(
                    f"{label} {destination} overlaps Podman network "
                    f"'{network.name}' subnet {network.subnet}"
                )
        routes.append(RouteSpec(destination, "gateway", interface=tunnel_interface))
    return routes


def plan_remote_routes(
    *,
    owner: RouteOwner,
    client_prefix: str,
    tunnel_interface: str,
    pushed_routes: Sequence[str],
    networks: Sequence[GatewayNetwork],
    observed_routes: Sequence[RouteSpec],
    active_routes: Sequence[OwnedRoute],
    install_host_return: bool = True,
) -> RoutePlan:
    """Plan candidate tunnel routes and an optional deterministic host route.

    Only exact observed routes owned by this same transport session are
    idempotent. Foreign, ambiguous, default, and Podman-overlapping routes
    fail before any route operation is called.

    Args:
        owner: Exact transport-session owner.
        client_prefix: Remote client prefix.
        tunnel_interface: Active tunnel device name.
        pushed_routes: Candidate routes supplied by the remote endpoint.
        networks: Configured Gateway Podman networks.
        observed_routes: Current routes from the relevant routing namespaces.
        active_routes: Routes with exact ownership records.
        install_host_return: Whether to manage the host return route.

    Returns:
        A plan of candidate additions, exact owned routes, and stale owned routes.

    Raises:
        ValueError: A candidate conflicts with configured or observed routes.
    """
    if owner.transport not in ("openvpn", "ssh_tun") or not re.fullmatch(
        r"[A-Za-z0-9_.-]{1,128}", owner.session_id
    ):
        raise ValueError(
            "route owner must have a supported transport and stable session ID"
        )
    gateway_routes = _parse_candidate_routes(
        client_prefix, tunnel_interface, pushed_routes, networks
    )
    host_return_routes: list[RouteSpec] = []
    if install_host_return:
        gateway_addresses = [
            network for network in networks if network.address is not None
        ]
        if not gateway_addresses:
            raise ValueError("host return route requires a configured Gateway address")
        gateway_addresses.sort(
            key=lambda network: (
                int(network.subnet.network_address),
                network.subnet.prefixlen,
                network.name,
            )
        )
        host_return_routes.append(
            RouteSpec(
                ipaddress.ip_network(client_prefix, strict=True),
                "host",
                gateway=gateway_addresses[0].address,
            )
        )
    candidates = list(dict.fromkeys([*gateway_routes, *host_return_routes]))

    unchanged = []
    additions = []
    for candidate in candidates:
        conflict = False
        for observed in observed_routes:
            if observed.plane != candidate.plane:
                continue
            if observed.destination.prefixlen == 0:
                continue
            if not candidate.destination.overlaps(observed.destination):
                continue
            exact_owner = observed == candidate and any(
                owned.owner == owner and owned.route == observed
                for owned in active_routes
            )
            if not exact_owner:
                raise ValueError(
                    f"candidate route {candidate.destination} conflicts with "
                    f"{observed.destination} on {observed.plane} plane"
                )
            conflict = True
        if conflict:
            unchanged.append(candidate)
        else:
            additions.append(candidate)

    desired = set(candidates)
    removals = tuple(
        owned
        for owned in active_routes
        if owned.owner == owner
        and owned.route not in desired
        and owned.route in observed_routes
        and (install_host_return or owned.route.plane != "host")
    )
    return RoutePlan(owner, tuple(additions), tuple(unchanged), removals)


def reconcile_remote_routes(
    *,
    owner: RouteOwner,
    assigned_addresses: Sequence[str],
    endpoint_address: str,
    client_prefix: str,
    openvpn_pool: str | None,
    ssh_pool: str | None,
    tunnel_interface: str,
    pushed_routes: Sequence[str],
    networks: Sequence[GatewayNetwork],
    observed_routes: Sequence[RouteSpec],
    active_routes: Sequence[OwnedRoute],
    host_routes: Sequence[Mapping[str, object]],
    add_route: RouteOperation,
    remove_route: RouteOperation,
) -> RoutePlan:
    """Validate a complete route candidate before applying any route change.

    Callbacks must leave routes unchanged when they raise. Successful operations
    are rolled back if a later callback fails; partial callback mutations cannot
    be detected safely. Callback exceptions propagate unless rollback also fails.

    Args:
        owner: Exact transport-session owner.
        assigned_addresses: One OpenVPN address or one SSH TUN point-to-point pair.
        endpoint_address: Remote tunnel endpoint IPv4 address.
        client_prefix: Remote client destination prefix.
        openvpn_pool: External server's OpenVPN client pool, or None when unknown.
        ssh_pool: Explicit SSH TUN pool, or None while SSH TUN is disabled.
        tunnel_interface: Active tunnel device name.
        pushed_routes: Candidate routes supplied by the remote endpoint.
        networks: Configured Gateway Podman networks.
        observed_routes: Current routes from the relevant routing namespaces.
        active_routes: Routes with exact ownership records.
        host_routes: One read-only host route-table snapshot.
        add_route: Caller-supplied operation for adding one planned route.
        remove_route: Caller-supplied operation for removing one owned route.

    Returns:
        The applied route plan.

    Raises:
        ValueError: Candidate routes conflict before mutation.
        RuntimeError: A callback fails and one or more rollback operations fail.
    """
    if owner.transport not in ("openvpn", "ssh_tun"):
        raise ValueError("route owner has an unsupported transport")
    route_config = {
        "gateway": {
            "remote_access": {
                "openvpn": (
                    {"client_pool": openvpn_pool} if openvpn_pool is not None else {}
                ),
                "ssh_tun": ({"address_pool": ssh_pool} if ssh_pool is not None else {}),
            }
        }
    }
    active_owners: dict[Transport, list[RouteOwner]] = {}
    for owned in active_routes:
        active_owners.setdefault(owned.owner.transport, []).append(owned.owner)
    active_owners.setdefault(owner.transport, []).append(owner)
    validate_remote_access_host_routes(
        route_config,
        host_routes,
        active_routes=active_routes,
        active_owners=active_owners,
    )
    validate_activation_addresses(
        transport=owner.transport,
        assigned_addresses=assigned_addresses,
        endpoint_address=endpoint_address,
        client_prefix=client_prefix,
        openvpn_pool=openvpn_pool,
        ssh_pool=ssh_pool,
        networks=networks,
        host_routes=host_routes,
    )
    plan = plan_remote_routes(
        owner=owner,
        client_prefix=client_prefix,
        tunnel_interface=tunnel_interface,
        pushed_routes=pushed_routes,
        networks=networks,
        observed_routes=observed_routes,
        active_routes=active_routes,
        install_host_return=(owner.transport != "openvpn" or openvpn_pool is not None),
    )
    apply_route_plan(plan, add_route=add_route, remove_route=remove_route)
    return plan


def apply_route_plan(
    plan: RoutePlan,
    *,
    add_route: RouteOperation,
    remove_route: RouteOperation,
) -> None:
    """Apply a validated route plan and roll back confirmed completed changes.

    Callbacks must be atomic: a raised exception must leave the route unchanged.
    Successful operations are rolled back after a later callback fails. Partial
    callback mutations cannot be detected safely, so this contract is required
    to avoid removing routes that this plan did not create. Callback exceptions
    propagate unless rollback also fails.

    Args:
        plan: Fully validated candidate route plan.
        add_route: Caller-supplied operation for adding one planned route.
        remove_route: Caller-supplied operation for removing one owned route.

    Raises:
        RuntimeError: A callback fails and one or more rollback operations fail.
    """
    if any(owned.owner != plan.owner for owned in plan.removals):
        raise ValueError("route plan contains a removal owned by another session")
    added: list[RouteSpec] = []
    removed: list[OwnedRoute] = []
    try:
        for route in plan.additions:
            add_route(route)
            added.append(route)
        for owned in plan.removals:
            remove_route(owned.route)
            removed.append(owned)
    except Exception as error:
        rollback_errors = []
        for owned in reversed(removed):
            try:
                add_route(owned.route)
            except Exception as rollback_error:  # noqa: BLE001 -- rollback covers callback failures.
                rollback_errors.append(rollback_error)
        for route in reversed(added):
            try:
                remove_route(route)
            except Exception as rollback_error:  # noqa: BLE001 -- rollback covers callback failures.
                rollback_errors.append(rollback_error)
        if rollback_errors:
            raise RuntimeError(
                f"route plan failed and {len(rollback_errors)} rollback operation(s) failed"
            ) from error
        raise
