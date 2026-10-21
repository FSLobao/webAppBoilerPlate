# Windows 11 access to Podman networks over SSH TUN

> **Future-use recipe only. Do not connect to this deployment yet.** The repository now contains an opt-in dynamic SSH TUN lifecycle, but checked-in config keeps it disabled. The disposable two-session source-preservation test passes on the local Debian image; target-host acceptance remains outstanding. No production key file, address pool, or maximum session count is supplied. Enable only after an operator reviews those values and target acceptance passes. `ssh -N` is unsupported: the client must request the fixed forced session.

This recipe supports IPv4 connections started by applications running inside a Linux VM used by a Windows 11 user. Examples include the VM's browser, terminal, and development tools. Windows-native applications, including the Windows browser, cannot use this tunnel. The Gateway runtime has no session-owned Windows `/32` return-route lifecycle, so Windows-host transit is unsupported until that lifecycle exists and passes target acceptance.

```text
Windows 11 user
  └─ application running inside Linux VM
       └─ Linux VM SSH TUN session
            └─ Gateway
                 └─ configured Podman networks
```

The VM needs an uplink that can reach the authorized Gateway SSH endpoint and Linux TUN device access. Do not configure Windows routes, Windows-to-VM forwarding, or NAT for Windows-originated traffic. The SSH connection and tunneled application connections originate inside the VM.

Gateway tunnel addresses, pools, routed destinations, host return routes, and generated DNS records use IPv4 and DNS A records only. This runtime does not disable IPv6 on the Gateway, VM, Windows host, or other host interfaces. `ssh -4` below selects IPv4 only for the outer SSH connection; it does not change the tunnel payload's address family.

Current configured Podman CIDRs are `192.168.9.0/24` (`shared`, Gateway `192.168.9.2`) and `192.168.8.0/29` (`webApp`). Review these against the VM, Gateway, host, and corporate routes before use. The selected `shared` range is not a host interface, tunnel pool, or proof that the range is free on a target host.

## Why use a Linux VM

Windows 11 includes Microsoft's Win32-OpenSSH client, but its documentation does not establish supported `ssh -w` TUN operation. Win32-OpenSSH lists unsupported features, and its maintainers discuss the limitation. Treat the bundled Windows client as unsupported and unverified for this use. Run OpenSSH `ssh -w` inside a Linux VM with TUN device access instead.

WSL2 may be investigated as an experimental, unverified alternative. This recipe does not promise that WSL2 can create or forward the required TUN device.

## Operator inputs

Obtain and approve these values before implementation testing:

- Gateway host and SSH port.
- The fixed dedicated account `gateway-tunnel`; do not use an ordinary Gateway administrator or login account.
- A root-owned, non-empty file containing only approved Ed25519 public keys for `gateway-tunnel`. Keep each private key on its authorized client.
- A non-overlapping SSH address pool, separate from Podman CIDRs and the OpenVPN pool, plus an explicit maximum session count. The Gateway assigns a `/31` point-to-point address pair and server TUN slot per connection.
- A unique client TUN ID per concurrent client process. The forced command reports the matching client-side local and peer addresses after authentication.
- All configured Podman CIDRs.
- DNS suffix and resolver address, if split DNS is required.
- Authorized route from the VM uplink to the Gateway/host network, including the Gateway SSH endpoint.
- Approved Gateway forwarding policy between the VM TUN and Podman CIDRs.
- Host, guest, and Gateway firewall rules required for those paths.

Check all route and address overlaps before enabling forwarding. Include Podman CIDRs, TUN pools and endpoints, VM subnets, and relevant host/corporate routes. Do not change a default route.

## Create and provision the client key

Generate one dedicated Ed25519 key pair inside the Linux VM for this tunnel identity. Do not reuse the ordinary Gateway-login key, an application-container destination key, or a Windows-host key. Replace `<LINUX_VM_USER>` with the VM account name; review both paths first. Never overwrite an existing key:

```bash
(
  set -Eeuo pipefail
  readonly KEY="/home/<LINUX_VM_USER>/.ssh/gateway_tunnel_ed25519"
  install -d -m 0700 "/home/<LINUX_VM_USER>/.ssh"
  if [[ -e "$KEY" || -e "$KEY.pub" ]]; then
    printf 'Refusing to overwrite an existing key: %s\n' "$KEY" >&2
    exit 1
  fi
  ssh-keygen -t ed25519 -a 64 \
    -C "gateway-tunnel-<CLIENT_LABEL>" \
    -f "$KEY"
  chmod 0600 "$KEY"
  chmod 0644 "$KEY.pub"
  ssh-keygen -lf "$KEY.pub"
)
```

`ssh-keygen` prompts for a passphrase. Do not put the passphrase in a command, script, or file. The client may load this key into its local `ssh-agent`; the server disables agent forwarding. If the Linux VM client must run as root to access TUN, do not assume `sudo` preserves `SSH_AUTH_SOCK`. Use the explicit `-F` and `-i` paths below and enter the key passphrase when prompted, or configure an approved local privilege model that lets the VM user create and configure TUN devices.

Transfer only `gateway_tunnel_ed25519.pub` through the approved provisioning channel. For an approved staging host that permits SCP, use a separate provisioning account and key—not `gateway-tunnel`:

```bash
scp -4 \
  -i "/home/<LINUX_VM_USER>/.ssh/<PROVISIONING_KEY>" \
  "/home/<LINUX_VM_USER>/.ssh/gateway_tunnel_ed25519.pub" \
  "<PROVISIONER>@<ADMIN_HOST>:/<APPROVED_STAGING_DIRECTORY>/"
```

Use this only if that administrator-controlled endpoint supports SCP. The restricted `gateway-tunnel` account has no shell, SCP, or SFTP access. Never transfer the private key. Compare the public-key fingerprint from the VM with the fingerprint received independently over a trusted channel before an administrator installs it.

The Gateway-login key file configured by `gateway.authorized_keys_path` (currently `/etc/gateway/authorized_keys`) is separate. The SSH TUN allow-list path is configured by `gateway.remote_access.ssh_tun.authorized_keys_path` and mounted inside the container as `/run/gateway/ssh_tun/authorized_keys`. Per-container destination-account keys are separate again; SSH TUN authentication does not replace destination authentication.

Use this schema-shaped example only as a template. `198.18.0.0/24` and `8` are illustrative test values, not deployment inputs. Keep `enabled` false until the pool, session count, key list, routes, and target acceptance are approved. Replace the example pool with a reviewed, non-overlapping IPv4 pool before enabling:

```json
{
  "ssh_tun": {
    "enabled": false,
    "account": "gateway-tunnel",
    "address_pool": "198.18.0.0/24",
    "authorized_keys_path": "/etc/gateway/ssh_tun/authorized_keys",
    "max_sessions": 8
  }
}
```

These are the complete `ssh_tun` fields accepted when enabled. The key path is an absolute host path outside the repository; it must match the public-key file provisioned on the Gateway host. The runtime accepts `max_sessions` from 1 through 32 and needs at least two IPv4 addresses per session. Confirm the pool also avoids the OpenVPN pool, all Podman networks, and relevant host routes.

On the Gateway host, have an authorized administrator install the verified public key without replacing other developers' keys:

```bash
(
  set -Eeuo pipefail
  readonly KEYS=/etc/gateway/ssh_tun/authorized_keys
  sudo install -d -o root -g root -m 0755 /etc/gateway/ssh_tun
  if sudo test -L "$KEYS"; then
    printf 'Refusing to use a symlink: %s\n' "$KEYS" >&2
    exit 1
  fi
  if ! sudo test -e "$KEYS"; then
    sudo install -o root -g root -m 0644 /dev/null "$KEYS"
  fi
  if sudo test -s "$KEYS"; then
    sudo ssh-keygen -lf "$KEYS"
  fi
  STAGED=$(sudo mktemp "${KEYS}.stage.XXXXXXXX")
  trap 'sudo rm -f -- "$STAGED"' EXIT
  sudo install -o root -g root -m 0644 -- "$KEYS" "$STAGED"
  sudoedit "$STAGED"
  sudo ssh-keygen -lf "$STAGED"
  sudo chown root:root "$STAGED"
  sudo chmod 0644 "$STAGED"
  sudo mv -f -- "$STAGED" "$KEYS"
  trap - EXIT
)
```

Serialize key-list updates so concurrent edits cannot overwrite one another. In the staged file, append the verified plain `ssh-ed25519` public-key line with its client label; keep every existing line. Confirm each earlier fingerprint remains in the staged file before the final same-directory `mv`, which atomically replaces only the managed file. Host preflight and the runtime require a root-owned regular file that is not group- or world-writable; the runtime also rejects an empty list, key options, and non-Ed25519 keys. Keep the directory and file outside Git. To revoke this client, use the same staged-copy, review, validation, and atomic-rename procedure; remove only its exact public-key line and verify all remaining fingerprints. Never truncate the live file or replace it with a single developer's key.

The config's `authorized_keys_path` must name the same host file. Host preflight validates it before apply, and Quadlet mounts it read-only. Do not copy private keys to the Gateway, into the repository, or into a container.

## Verify the Gateway host key

Obtain the Gateway's Ed25519 host public key and fingerprint from an authorized administrator over a trusted channel independent of the first SSH connection. Verify the key fingerprint against that separately delivered fingerprint, then install the exact host-key entry for the approved Gateway name and port in the Linux VM user's `/home/<LINUX_VM_USER>/.ssh/known_hosts`. Do not trust an unverified `ssh-keyscan` result, disable `StrictHostKeyChecking`, or accept a changed host key without administrator verification.

Create `/home/<LINUX_VM_USER>/.ssh/config` without replacing an existing file. Set both files to mode `0600`. Use absolute paths so the same config works when `sudo` changes the SSH process's home directory:

```sshconfig
Host gateway-tun
    HostName <GATEWAY_HOST>
    User gateway-tunnel
    Port <GATEWAY_SSH_PORT>
    IdentityFile /home/<LINUX_VM_USER>/.ssh/gateway_tunnel_ed25519
    IdentitiesOnly yes
    UserKnownHostsFile /home/<LINUX_VM_USER>/.ssh/known_hosts
    StrictHostKeyChecking yes
    Tunnel point-to-point
```

If configuration or host-key provisioning needs editing, preserve existing `known_hosts` entries. When using `sudo`, pass the explicit config path with `-F`; the absolute `IdentityFile` and `UserKnownHostsFile` paths prevent accidental use of root's unrelated keys or trust database.

## Future setup order

1. **Wait for deployment acceptance.** Confirm reviewed SSH keys, non-overlapping pool, maximum sessions, host routes, target kernel/OpenSSH behavior, and isolated source-preservation tests. Checked-in config stays disabled.
2. **Prepare an authorized disposable Linux VM.** Confirm the VM can reach the Gateway SSH endpoint on the approved host/port and can access TUN devices. Ensure the guest firewall permits VM-originated connections through the TUN and Gateway firewall policy permits forwarding to configured Podman networks without NAT.
3. **Check VM routes and addresses.** Inspect the VM route table and interfaces. Resolve all overlaps and existing conflicting routes before adding addresses or routes. Do not change a default route.
4. **Start the SSH TUN session from the VM.** Use one client TUN ID per process and `any` as the server ID. Force IPv4 for the outer SSH connection with `-4`. Omit `-N`; the fixed forced command reports the assigned pair and then holds the session. The Gateway PAM hook provisions only its reserved TUN before OpenSSH attaches.
5. **Configure the client TUN from a second VM terminal.** Use the exact client-local and peer addresses printed by the forced command. Add only the configured Podman routes through the client TUN. Follow the preflight, setup, and teardown steps below.
6. **Configure DNS only if needed.** Use per-link split DNS for the approved development suffix and a resolver reachable through the tunnel. Do not replace global DNS settings.
7. **Test an authorized destination from a VM application.** Confirm the container sees the VM TUN source address, destination authentication still applies, replies return through the owning session, and application networks do not forward to one another.
8. **Remove only state owned by this session.** Remove only the routes, address, and per-link DNS settings added for this session. Then stop its SSH process and let PAM cleanup remove only its allocated Gateway interface, address, and shared-forwarding lease. The host route stays owned by the Gateway Quadlet unit until SSH TUN is disabled or that unit stops.

## Future `ssh -w` template

Run this template **inside the Linux VM**, only after operator and target acceptance. Replace all angle-bracket placeholders; no production values are checked in.

```sh
ssh -4 \
  -F "/home/<LINUX_VM_USER>/.ssh/config" \
  -w "<CLIENT_TUN_ID>:any" \
  gateway-tun
```

`-w` requests a point-to-point TUN device. OpenSSH's key command assigns the Gateway's device number by connection, independent of the client-side ID. Do not add `-N`; it prevents the forced session command from running. The fixed command rejects non-empty client commands, prints `SSH TUN ready: <interface>; configure client local <IPv4> peer <IPv4>.`, and remains active until disconnect. Keep this terminal open. In another VM terminal, configure the client endpoint using the reported local and peer addresses and add only the approved IPv4 Podman routes through that client TUN. Remove only routes created for this session before stopping SSH.

If TUN access requires root, run the same client with the explicit user config:

```sh
sudo ssh -4 \
  -F "/home/<LINUX_VM_USER>/.ssh/config" \
  -i "/home/<LINUX_VM_USER>/.ssh/gateway_tunnel_ed25519" \
  -w "<CLIENT_TUN_ID>:any" \
  gateway-tun
```

The explicit config and identity paths keep the verified host-key database and client key in use. Root must be able to read the private key; its passphrase remains interactive. Do not forward the local agent or copy the private key. The Gateway provisions and cleans only its reserved interface through required PAM hooks. Configure only the VM client endpoint and its approved routes; do not change a default route or unrelated route.

## Configure the VM client TUN

Keep the SSH terminal open. In a separate terminal inside the same VM, inspect its interfaces, addresses, and every IPv4 route table before making changes:

```bash
ip -brief link
ip -4 address show
ip -4 route show table all
```

Set `<CLIENT_TUN_ID>` to the numeric client ID passed to `ssh -w`. The VM-side interface is `tun<CLIENT_TUN_ID>`; the interface number printed by the forced command belongs to the Gateway and may differ. Confirm the VM-side interface belongs to this SSH session, has no pre-existing IPv4 address, and has no existing route that overlaps either Podman CIDR. Resolve conflicts before continuing; never replace or flush routes.

The forced command prints this exact format, with the allocated interface and addresses:

```text
SSH TUN ready: <GATEWAY_TUN_IFACE>; configure client local <CLIENT_LOCAL_IPV4> peer <GATEWAY_TUN_PEER_IPV4>.
```

Manually copy the reported local and peer IPv4 addresses into the variables below. Treat the output as data; do not evaluate it or use it as shell input.

```bash
set -Eeuo pipefail
CLIENT_TUN_ID='<CLIENT_TUN_ID>'
CLIENT_TUN="tun${CLIENT_TUN_ID}"
CLIENT_LOCAL='<CLIENT_LOCAL_IPV4>'
CLIENT_PEER='<GATEWAY_TUN_PEER_IPV4>'
```

Replace every placeholder first. Recheck the VM's complete route table and the interface's address state before adding anything. Stop if either CIDR has a conflicting route or if the interface already has an address:

```bash
sudo ip -4 address show dev "$CLIENT_TUN"
sudo ip -4 route show table all
```

These routes come from the current `networks` entries in `config/host_config.json`; verify that file before use.

Add the point-to-point address, bring up the SSH-owned client interface, then add one route for each configured Podman network:

```bash
sudo ip -4 address add local "$CLIENT_LOCAL" peer "$CLIENT_PEER" dev "$CLIENT_TUN"
sudo ip link set dev "$CLIENT_TUN" up
sudo ip -4 route add 192.168.9.0/24 dev "$CLIENT_TUN"
sudo ip -4 route add 192.168.8.0/29 dev "$CLIENT_TUN"
```

Run commands in order and stop at the first failure. Record which route-add commands and the address-add command succeeded. If setup fails, remove only those successful additions using the teardown commands below. Do not delete the SSH-owned interface.

Verify route selection and reachability before using VM applications:

```bash
ip -4 address show dev "$CLIENT_TUN"
ip -4 route get 192.168.9.2
ip -4 route get 192.168.8.2
```

Use only the configured Podman routes. If the approved DNS resolver is outside both routed CIDRs, obtain approval for a specific resolver `/32` route. Inspect all route tables and verify no conflicting route would be replaced before adding it; do not add or change a default route. Add this route only after approval, and record whether the command succeeded:

```bash
sudo ip -4 route add "<DNS_RESOLVER_IPV4>/32" dev "$CLIENT_TUN"
```

If the resolver is inside a configured CIDR, its route is already covered.

If `systemd-resolved` is active and split DNS is required, first inspect `resolvectl status "$CLIENT_TUN"`. Apply per-link settings only when the SSH-created interface has no pre-existing DNS or domain settings:

```bash
sudo resolvectl dns "$CLIENT_TUN" "<DNS_RESOLVER_IPV4>"
sudo resolvectl domain "$CLIENT_TUN" "~<DEVELOPMENT_DNS_SUFFIX>"
```

Do not change global resolver configuration or use commands that overwrite `/etc/resolv.conf`. Before disconnecting, run the revert only if these commands added the settings and no other per-link DNS or domain settings were added afterward:

```bash
sudo resolvectl revert "$CLIENT_TUN"
```

## Remove the VM client configuration

Keep the SSH session open while removing client state. Run only route deletions for routes successfully added by this session. If setup stopped before a route was added, omit that deletion. If this session added the approved resolver `/32` route, remove it first:

```bash
sudo ip -4 route del "<DNS_RESOLVER_IPV4>/32" dev "$CLIENT_TUN"
```

Remove the Podman routes and address only if their add commands succeeded:

```bash
sudo ip -4 route del 192.168.8.0/29 dev "$CLIENT_TUN"
sudo ip -4 route del 192.168.9.0/24 dev "$CLIENT_TUN"
sudo ip -4 address del local "$CLIENT_LOCAL" peer "$CLIENT_PEER" dev "$CLIENT_TUN"
```

Do not use `ip route replace`, `ip route flush`, or `ip tuntap del`. After verifying the added client state is gone, stop the SSH process with Ctrl-C. PAM then cleans only the Gateway interface and forwarding lease owned by that session.

## Windows-native traffic remains unsupported

This lifecycle does not register or remove a Windows source `/32` return route for each SSH session. Do not configure Windows routes, Windows-to-VM forwarding, or Windows NAT to send native Windows traffic through the VM. Those settings cannot establish a supported return path and can disrupt unrelated host traffic. Windows users must run network clients inside the Linux VM until a session-owned Windows return-route lifecycle is implemented and accepted on the target host.

## DNS, forwarding, and security boundaries

Configure split DNS only for the approved development suffix on the Linux VM. Use per-link DNS on the client TUN when `systemd-resolved` is active; keep unrelated VM DNS resolution unchanged. ProxyJump or an SSH control connection alone does not route DNS queries.

VM applications route approved Podman CIDRs through the active TUN. Gateway forwarding policy must allow tunnel-to-Podman traffic and established replies, and the Gateway must route IPv4 replies through the owning TUN session. The guest firewall must permit VM-originated connections. Do not configure Windows transit or disable unrelated IPv6 configuration on Windows, the VM, or Gateway host.

Every tunnel client can reach every configured Podman network and service, including PostgreSQL, under the architecture contract. The shared network also provides direct connectivity among its attached containers. Service authentication and the external security perimeter remain required. Do not add client-to-container NAT. Ordinary container egress masquerading is a separate path and does not authorize client NAT.

## Host-originated Linux client tests

Testing from the same physical Linux host is feasible only on an authorized disposable host with network isolation. Use an isolated network namespace or disposable VM for the client. Keep direct Podman bridge routes out of that client network namespace, so its traffic must use the SSH TUN path. A client in the ordinary host namespace will usually reach Podman bridges directly and bypass the tunnel; that does not test routed tunnel access.

Before such a test, verify TUN device access and required permissions, an independently reachable Gateway SSH control path, no overlapping client/TUN/Podman/host routes, and no shared or live host state. Enable forwarding only under approved policy. Teardown must remove only resources owned by the test. Do not test on a live host.

This repository now contains the opt-in Gateway session allocator, IPv4 forwarding policy, and owned teardown, but checked-in configuration disables SSH TUN. This Linux-host test still requires an isolated disposable network namespace or VM, and it does not replace target-host acceptance.

## OpenVPN profile handling

The configuration field is `gateway.remote_access.openvpn.profile_path`; host preflight checks its path and file metadata without reading the profile. The runtime does not support OpenVPN local IPv6 directives. SSH TUN testing does not need an OpenVPN profile. Do not place the profile in this repository or Git.

The externally provided path is `/etc/gateway/openvpn/ERMXDF02.ovpn`. Treat the profile as a secret because it may embed credentials. Keep the root-owned directory at mode `0700` and the root-owned file at mode `0600`, outside Git. Do not copy, read, stat, log, or distribute it as part of SSH TUN setup.

## References

- Microsoft, [Get started with OpenSSH](https://learn.microsoft.com/en-us/windows-server/administration/openssh/openssh_install_firstuse)
- Win32-OpenSSH, [Unsupported `sshd_config` features](https://github.com/PowerShell/Win32-OpenSSH/wiki/sshd_config#not-supported)
- Win32-OpenSSH, [TUN support discussion](https://github.com/PowerShell/Win32-OpenSSH/discussions/2197)
- OpenBSD, [`ssh(1)`](https://man.openbsd.org/ssh)
- OpenBSD, [`sshd_config(5)`](https://man.openbsd.org/sshd_config)
