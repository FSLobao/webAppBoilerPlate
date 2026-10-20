# WireGuard peer onboarding on macOS

> WireGuard runtime and peer CLI are implemented, but checked-in config keeps the server disabled.
> Do not activate it until deployment inputs, server key, kernel support, and route preflight pass.
> Peer operations require Gateway root and a direct, non-recording terminal.

## Approved network contract

- WireGuard is an additive IPv4-only server in Gateway. It does not replace the OpenVPN client
  or SSH TUN.
- Every approved peer must route every top-level Podman CIDR, including application and PostgreSQL
  networks. Current CIDRs are `192.168.9.0/24` (`shared`) and `192.168.8.0/29` (`webApp`).
  PostgreSQL is reachable through those configured networks. Include future network entries too.
- `dev.anatel` is the internal-only, non-public DNS suffix. DNS returns A records only.
- Preserve the ordinary default route, public DNS, and unrelated routes. Do not use `0.0.0.0/0`,
  `::/0`, or any all-traffic route.
- WireGuard does not push routes or DNS. The peer profile carries exactly the configured Podman
  CIDRs in `AllowedIPs`; the configured resolver is a Gateway address inside those CIDRs.
- The host must publish the selected Gateway UDP listener. Endpoint, UDP bind/port, server address,
  peer pool, and resolver remain deployment inputs.
- No external firewall/perimeter change is required by this plan. Host port publication does not
  prove endpoint reachability.

## Peer generation, approval, and key handling

1. A trusted Gateway administrator verifies developer/device identity and records owner, purpose,
   approval reference, and expiry. Do not send private keys or public endpoints in a public ticket.
2. Confirm the operator terminal is direct and is not recorded or multiplexed. Generate the peer
   with a foreground interactive TTY:

   ```bash
   podman exec --interactive --tty --user 0 gateway \
     gateway-wireguard peer generate \
     --id "mac-device-01" \
     --owner "approved-owner-id" \
     --purpose "development access"
   ```

   Gateway stores pending public metadata, then prints the profile once to `/dev/tty`. The private
   key exists transiently in Gateway memory. It is never stored in inventory or written to logs,
   command arguments, or environment.
3. If output fails or may have been recorded, do not retry or recover the key. Revoke that pending
   peer using its ID and public fingerprint, then obtain approval for a replacement.
4. Activate only after approval, with an approved reference and future timezone-aware expiry:

   ```bash
   podman exec --user 0 gateway gateway-wireguard peer approve \
     "mac-device-01" \
     --approval-reference "approved-change-reference" \
     --expires-at "YYYY-MM-DDTHH:MM:SS+00:00"
   ```

5. Any Gateway-container administrator can operate peers and reach every configured network,
   including PostgreSQL. Treat each as a trusted network administrator. Service credentials remain
   required.
6. `peer list` returns public metadata, fingerprints, and audit events only:

   ```bash
   podman exec --user 0 gateway gateway-wireguard peer list
   ```

7. Revoke only the named peer when access ends or output may have been recorded:

   ```bash
   podman exec --user 0 gateway gateway-wireguard peer revoke \
     "mac-device-01" --reason "device access ended"
   ```

8. Store the one-time profile in an approved protected macOS location. Keep it out of email, chat,
   screenshots, clipboard history, shared folders, source control, and unapproved sync storage.
   Deletion may not erase backups or snapshots. Service authentication remains required.

The CLI generates this client profile shape from explicit deployment inputs. Placeholders below
are not deployment values:

```ini
[Interface]
PrivateKey = <ONE_TIME_PRIVATE_KEY_FROM_GATEWAY>
Address = <ASSIGNED_PEER_IPV4_PREFIX>
# Split DNS resolver; configure per OS: <GATEWAY_DNS_IPV4>

[Peer]
PublicKey = <GATEWAY_SERVER_PUBLIC_KEY>
Endpoint = <APPROVED_PUBLIC_ENDPOINT>:<HOST_PUBLISHED_UDP_PORT>
AllowedIPs = <EVERY_TOP_LEVEL_PODMAN_CIDR>
```

Confirm the server public-key fingerprint through an independent trusted channel. `AllowedIPs` must
contain exactly every configured top-level Podman CIDR, including PostgreSQL networks. The Gateway
resolver address belongs to those CIDRs, so add no separate resolver route. Do not add default or
IPv6 routes. Do not infer DNS settings from a WireGuard profile.

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
DNS server or add a default domain. Read the resolver IPv4 address from the generated profile
comment. The profile has no `DNS` directive, so it cannot replace global DNS.

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
- Revoke the old peer by exact ID:

  ```bash
  podman exec --user 0 gateway gateway-wireguard peer revoke \
    "mac-device-01" --reason "rotation"
  ```

- Confirm its existing tunnel loses access. Peer expiry also revokes server authorization.
- Disconnect and remove only the obsolete profile and this recipe's resolver file. Do not delete
  unrelated macOS DNS configuration.
- Report a lost device promptly for revocation. Do not rely on profile deletion as revocation.
