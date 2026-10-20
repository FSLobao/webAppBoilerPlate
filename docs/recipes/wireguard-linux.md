# WireGuard peer onboarding on Linux

> **Draft for a future service. Not executable today.** The Gateway has no WireGuard runtime, peer
> service, schema, or key-delivery channel. Do not connect or create a peer from this recipe. Service
> operation names, UI, and API are intentionally unspecified.

## Approved network contract

- WireGuard will be an additive IPv4-only server in Gateway. It will not replace the OpenVPN client
  or SSH TUN.
- Every approved peer must route every top-level Podman CIDR, including application and PostgreSQL
  networks. Current CIDRs are `192.168.9.0/24` (`shared`) and `192.168.8.0/29` (`webApp`).
  PostgreSQL is reachable through those configured networks. Include future network entries too.
- `dev.anatel` is the internal-only, non-public DNS suffix. DNS returns A records only.
- Preserve the ordinary default route, public DNS, and unrelated routes. Do not use `0.0.0.0/0`,
  `::/0`, or any all-traffic route.
- WireGuard does not push routes or DNS. The peer profile must carry every Podman route and resolver
  reachability in `AllowedIPs`.
- The host must publish the selected Gateway UDP listener. Endpoint, UDP port, server address,
  peer pool, and resolver are not selected. `51820/UDP` is only an unapproved suggestion.
- No external firewall/perimeter change is required by this plan. Host port publication does not
  prove endpoint reachability.

## Peer request, approval, and key handling

1. Request a peer through the approved internal administrative process when that process exists.
   Identify the developer, Linux device, owner, purpose, and requested expiry. Do not send private
   keys or public endpoints in a public ticket.
2. An authorized operator verifies the developer identity and obtains explicit approval. The
   operator records approval, peer identity, assigned IPv4 address, expiry, and audit reference.
   Exact identity checks, approval roles, and audit format remain pending design input.
3. The future peer service generates the peer private/public key pair **inside Gateway**. It adds
   only the peer public key and approved metadata to active server state. The private key exists as
   plaintext transiently in Gateway memory, but must never be persisted or logged.
4. The service delivers the generated private key and client profile once through a yet-to-be
   designed authenticated channel. A person with Gateway-container administrative privilege can
   perform peer operations and reach all configured networks, including PostgreSQL. Treat each
   such administrator as a trusted network administrator.
5. Receive the private key/profile only through the approved authenticated workstation channel.
   Store the profile with owner-only access, outside shared folders, shell history, source control,
   backups, synchronization folders, logs, and issue trackers. Use the desktop keyring or an
   approved encrypted secret store when available. Do not assume deletion erases backups or
   storage snapshots.
6. If delivery fails, do not recover a saved private key. Revoke that peer and create a newly
   approved replacement. Rotation requires approving a replacement, delivering its key once, then
   revoking the old peer. Revocation must remove active server authorization.
7. Record the public-key fingerprint and operation result, never the private key or full profile.
   Service authentication remains required after tunnel connection; WireGuard does not grant
   application or PostgreSQL credentials.

The following fields describe the future client profile; placeholders are not deployment values.
The service must generate the actual configuration:

```ini
[Interface]
PrivateKey = <ONE_TIME_PRIVATE_KEY_FROM_GATEWAY>
Address = <ASSIGNED_PEER_IPV4_PREFIX>

[Peer]
PublicKey = <GATEWAY_SERVER_PUBLIC_KEY>
Endpoint = <APPROVED_PUBLIC_ENDPOINT>:<HOST_PUBLISHED_UDP_PORT>
AllowedIPs = <EVERY_TOP_LEVEL_PODMAN_CIDR>, <RESOLVER_IPV4_PREFIX_IF_NEEDED>
```

Confirm the server public-key fingerprint through an independent trusted channel. `AllowedIPs` must
cover both current CIDRs and every future top-level Podman network. Add the resolver address when it
is not already covered by those routes. It must contain no default route or IPv6 route. Do not infer
DNS settings from a WireGuard profile.

## Install, connect, and validate

1. Install the organization-approved WireGuard client using the host distribution's approved
   package source. Verify its package signature and version according to local policy.
2. Import the service-generated profile with the approved network manager or WireGuard client. Do
   not create a profile from guessed values. Restrict profile access to the authorized user.
3. Keep the tunnel disconnected until the assigned peer, endpoint, UDP port, server public key,
   address, and `AllowedIPs` pass operator review.
4. Connect and confirm a recent handshake. A host-published UDP port is necessary, but does not
   guarantee endpoint reachability.
5. Confirm only configured Podman CIDRs and resolver reachability route through WireGuard. Check
   that default route, public DNS, and unrelated routes remain unchanged.
6. Confirm the Gateway presents the current A record for an approved internal name. Confirm no
   AAAA is published. Verify service authentication independently.

## Split DNS with systemd-resolved

Use a routing-only domain on the WireGuard link. Do not set a global resolver or a search domain
that sends unrelated names through Gateway. Replace `<WIREGUARD_LINK_NAME>` and
`<APPROVED_RESOLVER_IPV4>` only after the operator assigns them.

Check that systemd-resolved is active and identify the WireGuard link:

```bash
resolvectl status
```

If the WireGuard link is not managed by NetworkManager or another connection manager, apply the
per-link resolver and routing-only domain after the tunnel is up:

```bash
sudo resolvectl dns <WIREGUARD_LINK_NAME> <APPROVED_RESOLVER_IPV4>
sudo resolvectl domain <WIREGUARD_LINK_NAME> '~dev.anatel'
resolvectl status <WIREGUARD_LINK_NAME>
```

If NetworkManager or another connection manager owns the link, configure the same per-link DNS
server and routing-only domain in that connection profile instead. Do not mix transient
`resolvectl` changes with managed settings.

Replace `<APPROVED_INTERNAL_HOSTNAME>` with an approved hostname ending in `.dev.anatel`. Verify
that it uses the resolver and returns its current A record. Verify a public name continues through
the prior resolver. Confirm no default route changed:

```bash
resolvectl query --type=A <APPROVED_INTERNAL_HOSTNAME>
resolvectl query --type=AAAA <APPROVED_INTERNAL_HOSTNAME>
ip -4 route
```

The AAAA query must return no record. Remove only the per-link `dev.anatel` routing-domain and DNS
settings when disconnecting or revoking the peer. For a manually configured, dedicated WireGuard
link, `resolvectl revert <WIREGUARD_LINK_NAME>` resets all transient per-link settings; use it only
if that link has no unrelated DNS settings. For a managed link, remove only these two settings in
its connection profile and restore any prior values recorded before the change.

## Rotation, revocation, and cleanup

- Request and approve a replacement through the same identity and audit process.
- Receive the replacement profile once. Confirm its public-key fingerprint and assigned address.
- Connect and verify split routes and DNS before the operator revokes the old peer.
- Ask the operator to remove the old public key from active server configuration and inventory.
  Confirm its existing tunnel loses access.
- Disconnect and remove only the obsolete profile and this recipe's resolver setting. Do not
  delete unrelated connection settings or resolver files.
- Report a lost device promptly for revocation. Do not rely on profile deletion as revocation.
