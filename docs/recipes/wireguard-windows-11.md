# WireGuard peer onboarding on Windows 11

> **Draft for a future service. Not executable today.** The Gateway has no WireGuard runtime, peer
> service, schema, or key-delivery channel. Do not connect or create a peer from this recipe. Service
> operation names, UI, and API are intentionally unspecified.

## Approved network contract

- WireGuard will be an additive IPv4-only server in the Gateway. It will not replace the OpenVPN
  client or SSH TUN.
- Every approved peer must route every top-level Podman CIDR, including application and PostgreSQL
  networks. Current CIDRs are `192.168.9.0/24` (`shared`) and `192.168.8.0/29` (`webApp`).
  PostgreSQL is reachable through those configured networks. Include future network entries too.
- `dev.anatel` is the internal-only, non-public DNS suffix. DNS returns A records only.
- Keep the normal Windows default route, public DNS, and unrelated routes unchanged. Do not use
  `0.0.0.0/0`, `::/0`, or any all-traffic route.
- WireGuard does not push routes or DNS. The peer profile must carry all Podman routes and resolver
  reachability in `AllowedIPs`.
- The host must publish the selected Gateway UDP listener. Endpoint, UDP port, server address,
  peer pool, and resolver are not selected. `51820/UDP` is only an unapproved suggestion.
- No external firewall/perimeter change is required by this plan. Host port publication does not
  prove endpoint reachability.

## Peer request, approval, and key handling

1. Request a peer through the approved internal administrative process when that process exists.
   Identify the developer, Windows device, owner, purpose, and requested expiry. Do not send a
   private key or public endpoint in a public ticket.
2. An authorized operator verifies the developer identity and obtains explicit approval. The
   operator records approval, peer identity, assigned IPv4 address, expiry, and audit reference.
   Exact identity checks, approval roles, and audit format remain pending design input.
3. The future peer service generates the peer private/public key pair **inside Gateway**. It adds
   only the peer public key and approved metadata to active server state. The client private key is
   plaintext transiently in Gateway memory, but must never be persisted or logged.
4. The service delivers the generated private key and client profile once through a yet-to-be
   designed authenticated channel. A person with Gateway-container administrative privilege can
   perform peer operations and can reach all configured networks, including PostgreSQL. Treat each
   such administrator as a trusted network administrator.
5. Verify the one-time delivery is for the approved Windows user/device. Do not copy it to email,
   chat, clipboard history, cloud sync, screenshots, logs, or a shared folder. Protect the profile
   with Windows account controls. Do not assume deletion can erase prior backups or storage
   snapshots.
6. If delivery fails, do not recover a saved private key. Revoke that peer and create a newly
   approved replacement. Rotation requires approving a replacement, delivering its key once, then
   revoking the old peer. Revocation must remove active server authorization.
7. Record the public-key fingerprint and operation result, never the private key or full profile.
   Service authentication remains required after tunnel connection; WireGuard does not grant
   application or PostgreSQL credentials.

The following fields describe the future client profile; placeholders are not deployment values.
The service must generate the actual configuration. Do not paste a made-up private key or address:

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
contain both current CIDRs and every configured Podman network added later. Add the resolver address
when it is not already covered by those routes. It must not contain a default route or IPv6 route.
Do not infer DNS settings from a WireGuard profile.

## Install and connect

1. Install the approved WireGuard client from the organization-approved Windows software source.
   Verify the publisher and version according to local endpoint policy.
2. Import the service-generated profile using the client. Do not create a profile from guessed
   values. Store it only in the approved protected location.
3. Keep the tunnel disconnected until the assigned peer, endpoint, UDP port, server public key,
   address, and `AllowedIPs` pass operator review.
4. Connect and confirm the tunnel reports an active handshake. A host-published UDP port is
   necessary; it does not guarantee the endpoint is reachable.
5. Confirm Windows routes only the configured Podman CIDRs and resolver address through WireGuard.
   Confirm the ordinary default route and unrelated routes remain unchanged.

```powershell
Get-NetRoute -AddressFamily IPv4
```

## Split DNS for `dev.anatel`

Use a Windows DNS Client NRPT rule for the exact suffix. Do not change the global adapter DNS server,
create a default-suffix rule, or send public DNS through Gateway. The resolver IPv4 address is still
unset; substitute only an operator-approved reachable address.

After confirming no conflicting policy or existing NRPT rule, an administrator can add a uniquely
named rule. These are Windows-native examples, not WireGuard service commands:

```powershell
$rule = Add-DnsClientNrptRule `
  -Namespace ".dev.anatel" `
  -NameServers "<APPROVED_RESOLVER_IPV4>" `
  -Comment "Gateway-WireGuard-dev-anatel" `
  -PassThru
```

Record the returned rule `Name` identifier. Inspect that exact rule and its scope before connecting:

```powershell
Get-DnsClientNrptRule |
  Where-Object { $_.Name -eq $rule.Name }
```

Verify an approved internal name returns its current IPv4 A record, with no AAAA record. Verify a
public name still uses existing Windows DNS and does not route through WireGuard:

```powershell
Resolve-DnsName <APPROVED_INTERNAL_HOSTNAME> -Type A
Resolve-DnsName <APPROVED_INTERNAL_HOSTNAME> -Type AAAA
Resolve-DnsName <APPROVED_PUBLIC_HOSTNAME>
```

Replace both hostname placeholders with approved names. A missing AAAA answer is expected.
After peer disconnect or revocation, remove only this uniquely named NRPT rule:

```powershell
Remove-DnsClientNrptRule -Name $rule.Name -Force
```

If policy owns the NRPT rule, do not overwrite or remove it; ask the policy owner to make the
suffix-scoped change.

## Rotation, revocation, and cleanup

- Request and approve a replacement through the same identity and audit process.
- Receive the replacement profile once. Confirm its public-key fingerprint and assigned address.
- Connect and verify split routes and DNS before the operator revokes the old peer.
- Ask the operator to remove the old public key from active server configuration and inventory.
  Confirm its existing tunnel loses access.
- Disconnect and remove only the obsolete client profile and this recipe's NRPT rule. Do not remove
  unrelated Windows DNS policy.
- Report a lost device promptly for revocation. Do not rely on profile deletion as revocation.
