# WireGuard peer onboarding on macOS

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
   Identify the developer, Mac device, owner, purpose, and requested expiry. Do not send private
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
5. Receive the private key/profile only through the approved authenticated channel. Import it into
   the approved WireGuard client and protect it with macOS account access controls. Do not place it
   in email, chat, screenshots, clipboard history, a shared folder, source control, or an
   unapproved cloud-synced location. Do not assume deletion erases backups or storage snapshots.
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

1. Install the organization-approved WireGuard client from its approved software source. Verify
   its publisher and version according to local endpoint policy.
2. Import the service-generated profile. Do not create a profile from guessed values. Restrict
   profile access to the authorized macOS user and use the client's approved storage controls.
3. Keep the tunnel disconnected until the assigned peer, endpoint, UDP port, server public key,
   address, and `AllowedIPs` pass operator review.
4. Connect and confirm a recent handshake. A host-published UDP port is necessary, but does not
   guarantee endpoint reachability.
5. Confirm only configured Podman CIDRs and resolver reachability route through WireGuard. Check
   that the default route, public DNS, and unrelated routes remain unchanged.
6. Confirm the Gateway presents the current A record for an approved internal name. Confirm no
   AAAA is published. Verify service authentication independently.

## Split DNS with `/etc/resolver`

macOS does not receive split DNS settings from the WireGuard profile. A resolver file scoped to
`dev.anatel` sends queries for only that domain to the approved resolver. Do not change the global
DNS server or add a default domain. The resolver IPv4 address is unset; obtain it from the operator.

After confirming that no existing file or managed profile owns this domain, create the
`/etc/resolver` directory with approved administrator permissions if it does not exist. Create
`/etc/resolver/dev.anatel` with an approved editor such as `sudoedit`. Use only this content:

```text
nameserver <APPROVED_RESOLVER_IPV4>
```

If the file already exists, do not overwrite it. Ask the DNS/service owner to resolve ownership.
Inspect the active scoped resolvers:

```bash
scutil --dns
```

Replace `<APPROVED_INTERNAL_HOSTNAME>` with an approved hostname ending in `.dev.anatel`. Verify it
through the system resolver, and confirm the A record matches the current Gateway DNS record:

```bash
dscacheutil -q host -a name <APPROVED_INTERNAL_HOSTNAME>
dscacheutil -q host -a name <APPROVED_PUBLIC_HOSTNAME>
netstat -rn -f inet
route -n get default
```

Verify that public names still use the previous resolver and no global DNS setting changed. Query
the approved DNS server directly to confirm the zone returns an A record and no AAAA record:

```bash
dig @<APPROVED_RESOLVER_IPV4> <APPROVED_INTERNAL_HOSTNAME> A
dig @<APPROVED_RESOLVER_IPV4> <APPROVED_INTERNAL_HOSTNAME> AAAA
```

The AAAA query must return no record. Confirm the client routes only configured Podman CIDRs and
resolver reachability through WireGuard. Do not use `0.0.0.0/0` or `::/0`.

When the peer is disconnected or revoked, remove `/etc/resolver/dev.anatel` only if this recipe
created it and no other service now owns it. Use an approved privileged file-removal procedure.
Do not remove unrelated resolver files or global DNS settings.

## Rotation, revocation, and cleanup

- Request and approve a replacement through the same identity and audit process.
- Receive the replacement profile once. Confirm its public-key fingerprint and assigned address.
- Connect and verify split routes and DNS before the operator revokes the old peer.
- Ask the operator to remove the old public key from active server configuration and inventory.
  Confirm its existing tunnel loses access.
- Disconnect and remove only the obsolete profile and this recipe's resolver file. Do not delete
  unrelated macOS DNS configuration.
- Report a lost device promptly for revocation. Do not rely on profile deletion as revocation.
