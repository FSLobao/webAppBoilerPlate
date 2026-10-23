# WireGuard peer onboarding on Windows 11

> WireGuard runtime and peer CLI are implemented, and checked-in config enables the server.
> Do not use peers until `--apply` completes after host preflight. It creates a missing server key
> and reuses an existing key to preserve issued profiles.
> Automated onboarding reads endpoint and approval policy from host config. Direct manual
> `peer generate --endpoint` still requires Gateway root and a direct, non-recording terminal.

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

## Automated host onboarding

Set `client_profiles_path`, `peer_purpose`, `client_endpoint`, `approval_reference`, and
`expires_at` under `gateway.remote_access.wireguard` in `config/host_config.json`. The endpoint is
an IPv4 address or DNS name without a port. The script uses the configured UDP `listen_port`.
External reachability must be confirmed by the network administrator; preflight does not test it.

On the Gateway host, run the script as root with a unique device ID and owner label:

```bash
sudo ./scripts/gateway/onboard-wireguard-peer.sh \
  "win-platform-laptop-01" "platform-user-1042"
```

The script generates and approves the peer in one run. It saves the profile as
`<client_profiles_path>/peer-<DEVICE_ID>.conf`, with root-only directory mode `0700` and file mode
`0600`. It prints only the saved path or an error. Transfer the profile to the authorized Windows
device through an approved protected channel; do not expose it in chat, email, or shared storage.

## Manual CLI generation, approval, and key handling

1. A trusted Gateway administrator verifies Windows user/device identity and records owner,
   purpose, approval reference, and expiry. Do not send private keys or public endpoints in a
   public ticket.
2. Identify the endpoint with the Gateway or network administrator. It must be an IPv4 address or
   DNS name reachable from the Windows device's current network. For Internet access, use the
   approved public DNS name or public IPv4 address that routes to the host or firewall publishing
   the Gateway's UDP listener. If NAT is in use, the network administrator must confirm UDP
   forwarding to that listener. In the checked-in configuration, the listener uses UDP `1194`;
   verify the deployed port with the operator.

   A DNS lookup can confirm that a name resolves, but cannot confirm UDP reachability:

   ```powershell
   Resolve-DnsName vpn.example.org -Type A
   ```

   Do not use the WireGuard tunnel address `192.168.10.1` or a container-only address as an
   Internet endpoint. The endpoint is a host name or IPv4 address only: do not include a scheme,
   port, or path. The profile adds the configured UDP port. Host preflight does not test external
   reachability, so have the network administrator verify the UDP path.
3. Confirm the operator terminal is direct and is not recorded or multiplexed. Generate the peer
   with a foreground interactive TTY. WireGuard clients import a `.conf` profile; this CLI generates
   the client key and profile once, so no separate key-generation script is needed:

   ```bash
   podman exec --interactive --tty --user 0 gateway \
     gateway-wireguard peer generate \
     --id "win-platform-laptop-01" \
     --owner "platform-user-1042" \
     --purpose "development access" \
     --endpoint "vpn.example.org"
   ```

   The generation command requires these arguments:

   - `--id`: Unique peer ID used for approval, audit, and revocation. Use 1-64 ASCII letters,
     numbers, dots, underscores, or hyphens; start with a letter or number. Prefer lowercase IDs
     shaped like `<platform>-<team-or-owner>-<device>-<sequence>`, such as
     `win-platform-laptop-01`. Use one stable ID per device. Do not include passwords, email
     addresses, or other unnecessary personal data.
   - `--owner`: Non-empty owner label, up to 128 characters. Use an organization-approved user or
     device inventory ID, such as `platform-user-1042`; do not use a secret.
   - `--purpose`: Non-empty access reason, up to 256 characters, such as
     `development access to staging services`. Keep it concise and do not include secrets.
   - `--endpoint`: Reachable IPv4 address or DNS name, such as `vpn.example.org`. Prefer a stable,
     organization-managed DNS name. Do not use a URL or append the UDP port.

   `--endpoint` is not a Gateway server setting. It is supplied for each generated profile. The
   other three flags are peer metadata. The profile's private key and peer address are generated;
   its server key, UDP port, resolver, and `AllowedIPs` come from the deployed Gateway configuration.
   Do not hand-edit these profile values.

   Gateway stores pending public metadata, then prints the profile once to `/dev/tty`. The private
   key exists transiently in Gateway memory. It is never stored in inventory or written to logs,
   command arguments, or environment.
4. If output fails or may have been recorded, do not retry or recover the key. Revoke that pending
   peer using its ID and public fingerprint, then obtain approval for a replacement.
5. Activate only after approval, with an approved reference and future timezone-aware expiry:

   ```bash
   podman exec --user 0 gateway gateway-wireguard peer approve \
     "win-platform-laptop-01" \
     --approval-reference "CHG-12345" \
     --expires-at "2027-04-30T17:00:00+00:00"
   ```

   The approval command takes the peer ID created above, a non-empty `--approval-reference` of up
   to 128 characters, and an `--expires-at` timestamp. Use an approved change or access-request ID
   for the reference. Expiry must be a future ISO 8601 timestamp with a timezone offset; the sample
   timestamp only shows the format. Choose the actual expiry under organization policy.
6. Any Gateway-container administrator can operate peers and reach every configured network,
   including PostgreSQL. Treat each as a trusted network administrator. Service credentials remain
   required.
7. `peer list` takes no arguments and returns public metadata, fingerprints, and audit events only:

   ```bash
   podman exec --user 0 gateway gateway-wireguard peer list
   ```

8. Revoke only the named peer when access ends or output may have been recorded:

   ```bash
   podman exec --user 0 gateway gateway-wireguard peer revoke \
     "win-platform-laptop-01" --reason "device retired"
   ```

   The revoke command takes the exact peer ID and a non-empty `--reason`, such as
   `device retired` or `access request withdrawn`.
9. Store the one-time profile in an approved protected Windows location. Keep it out of email, chat,
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
