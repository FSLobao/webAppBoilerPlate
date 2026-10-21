# WireGuard peer onboarding on Windows 11

> WireGuard runtime and peer CLI are implemented, and checked-in config enables the server.
> Do not use peers until `--apply` completes after host preflight. It creates a missing server key
> and reuses an existing key to preserve issued profiles.
> Supply a reachable endpoint for each client profile; it is not stored in host config.
> Peer operations require Gateway root and a direct, non-recording terminal.

## Approved network contract

- WireGuard is an additive IPv4-only server in the Gateway. It does not replace the OpenVPN
  client or SSH TUN.
- Every approved peer must route every top-level Podman CIDR, including application and PostgreSQL
  networks. Current CIDRs are `192.168.9.0/24` (`shared`) and `192.168.8.0/29` (`webApp`).
  PostgreSQL is reachable through those configured networks. Include future network entries too.
- `dev.anatel` is the internal-only, non-public DNS suffix. DNS returns A records only.
- Keep the normal Windows default route, public DNS, and unrelated routes unchanged. Do not use
  `0.0.0.0/0`, `::/0`, or any all-traffic route.
- WireGuard does not push routes or DNS. The peer profile carries exactly the configured Podman
  CIDRs in `AllowedIPs`; the configured resolver is a Gateway address inside those CIDRs.
- The host must publish the selected Gateway UDP listener. Endpoint, UDP bind/port, server address,
  peer pool, and resolver remain deployment inputs.
- No external firewall/perimeter change is required by this plan. Host port publication does not
  prove endpoint reachability.

## Peer generation, approval, and key handling

1. A trusted Gateway administrator verifies Windows user/device identity and records owner,
   purpose, approval reference, and expiry. Do not send private keys or public endpoints in a
   public ticket.
2. Confirm the operator terminal is direct and is not recorded or multiplexed. Generate the peer
   with a foreground interactive TTY. WireGuard clients import a `.conf` profile; this CLI generates
   the client key and profile once, so no separate key-generation script is needed:

   ```bash
   podman exec --interactive --tty --user 0 gateway \
     gateway-wireguard peer generate \
     --id "windows-device-01" \
     --owner "approved-owner-id" \
     --purpose "development access" \
     --endpoint "<APPROVED_REACHABLE_HOST>"
   ```

   Gateway stores pending public metadata, then prints the profile once to `/dev/tty`. The private
   key exists transiently in Gateway memory. It is never stored in inventory or written to logs,
   command arguments, or environment.
3. If output fails or may have been recorded, do not retry or recover the key. Revoke that pending
   peer using its ID and public fingerprint, then obtain approval for a replacement.
4. Activate only after approval, with an approved reference and future timezone-aware expiry:

   ```bash
   podman exec --user 0 gateway gateway-wireguard peer approve \
     "windows-device-01" \
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
     "windows-device-01" --reason "device access ended"
   ```

8. Store the one-time profile in an approved protected Windows location. Keep it out of email, chat,
   clipboard history, cloud sync, screenshots, logs, shared folders, and source control. Deletion
   may not erase backups or snapshots. Service authentication remains required.

The CLI generates this client profile shape from the supplied endpoint and configured UDP port.
The endpoint is a public IPv4 address or DNS name, without a port. Placeholders below are not
deployment values:

```ini
[Interface]
PrivateKey = <ONE_TIME_PRIVATE_KEY_FROM_GATEWAY>
Address = <ASSIGNED_PEER_IPV4_PREFIX>
# Split DNS resolver; configure per OS: <GATEWAY_DNS_IPV4>

[Peer]
PublicKey = <GATEWAY_SERVER_PUBLIC_KEY>
Endpoint = <APPROVED_REACHABLE_HOST>:1194
AllowedIPs = <EVERY_TOP_LEVEL_PODMAN_CIDR>
```

Confirm the server public-key fingerprint through an independent trusted channel. `AllowedIPs` must
contain exactly every configured top-level Podman CIDR, including PostgreSQL networks. The Gateway
resolver address belongs to those CIDRs, so add no separate resolver route. Do not add default or
IPv6 routes. Do not infer DNS settings from a WireGuard profile.

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
create a default-suffix rule, or send public DNS through Gateway. Read the resolver IPv4 address
from the generated profile comment. The profile has no `DNS` directive, so it cannot replace global DNS.

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
- Revoke the old peer by exact ID:

  ```bash
  podman exec --user 0 gateway gateway-wireguard peer revoke \
    "windows-device-01" --reason "rotation"
  ```

- Confirm its existing tunnel loses access. Peer expiry also revokes server authorization.
- Disconnect and remove only the obsolete client profile and this recipe's NRPT rule. Do not remove
  unrelated Windows DNS policy.
- Report a lost device promptly for revocation. Do not rely on profile deletion as revocation.
