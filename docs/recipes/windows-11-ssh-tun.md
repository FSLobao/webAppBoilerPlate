# Windows 11 access to Podman networks over SSH TUN

> **Future-use recipe only. Do not connect to this deployment yet.** SSH TUN, tunnel-account support, address allocation, routing, and teardown are not implemented. The current Gateway startup sets `PermitTunnel no`. Use only after implementation and disposable-host acceptance.

This recipe describes a routed Layer 3 path from Windows 11 to every configured Podman network. Windows uses a Linux VM as its SSH TUN endpoint:

```text
Windows 11
  └─ explicit routes for Podman CIDRs
       └─ VM host-only NIC
            └─ Linux VM forwarding
                 └─ SSH TUN session
                      └─ Gateway
                           └─ configured Podman networks
```

The VM needs two NICs: an uplink to the authorized network that can reach the Gateway SSH endpoint, and a host-only/internal NIC shared with Windows. The inner client-to-container packets must preserve the Windows source address; do not NAT them. The SSH connection itself is an outer connection from the VM.

Current configured Podman CIDRs are `192.168.9.0/24` (`shared`, Gateway `192.168.9.2`) and `192.168.8.0/29` (`webApp`). Review these against every relevant Windows, VM, Gateway, host, and corporate route before use. The selected `shared` range is not a host interface, tunnel pool, or proof that the range is free on a target host.

## Why use a Linux VM

Windows 11 includes Microsoft's Win32-OpenSSH client, but its documentation does not establish supported `ssh -w` TUN operation. Win32-OpenSSH lists unsupported features, and its maintainers discuss the limitation. Treat the bundled Windows client as unsupported and unverified for this use. Run OpenSSH `ssh -w` inside a Linux VM with TUN device access instead.

WSL2 may be investigated as an experimental, unverified alternative. This recipe does not promise that WSL2 can create or forward the required TUN device.

## Operator inputs

Obtain and approve these values before implementation testing:

- Gateway host and SSH port.
- A dedicated, restricted tunnel account. Do not use an ordinary Gateway administrator or login account.
- The developer's public key only. Keep its private key on the developer's authorized client.
- Unique client and Gateway TUN interface IDs, plus a non-overlapping point-to-point address pair for each session from a dedicated SSH TUN pool separate from Podman CIDRs and the OpenVPN pool.
- All configured Podman CIDRs.
- Host-only subnet, VM host-only address, Windows host-only interface index, and Windows host-only source address. For a single Windows host, use its source address as a `/32` return prefix. Use a wider prefix only if deliberately allocated to that one client and ownership is validated; never route other host-only clients through this session.
- DNS suffix and resolver address, if split DNS is required.
- Authorized route from the VM uplink to the Gateway/host network, including the Gateway SSH endpoint.
- Approved forwarding policy between the Windows host-only NIC, the VM TUN, and Podman CIDRs.
- Host, Windows, guest, and hypervisor firewall rules required for those paths.

Check all route and address overlaps before enabling forwarding. Include Podman CIDRs, TUN pools and endpoints, Windows and VM subnets, and relevant host/corporate routes. Do not change a default route.

## Future setup order

1. **Wait for implementation acceptance.** The Gateway must support a restricted SSH TUN account, `PermitTunnel`, per-session allocation, endpoint configuration, forwarding, return routes, and owned-state cleanup. Current deployment does not.
2. **Prepare an authorized disposable Linux VM.** Attach one uplink NIC and one host-only/internal NIC. Confirm the VM can reach the Gateway SSH endpoint on the approved host/port. Enable guest IP forwarding only under an approved policy. Ensure firewall and hypervisor policy permit the required forwarding without NAT on inner packets.
3. **Check routes and addresses.** Confirm no relevant overlap or pre-existing route would divert traffic. The VM must forward Windows-originated packets to the TUN and forward replies from the TUN back to the Windows host-only address.
4. **Start the allocated SSH TUN session from the VM.** Use only the dedicated account and assigned interface IDs/address pair. The allocator must configure both tunnel endpoints and the required routes. The SSH command alone does not establish a working routed path.
5. **Add Windows routes only for configured Podman CIDRs.** Use the temporary ActiveStore template below. Each route sends traffic through the VM's host-only address. Do not install a default route or routes for unrelated networks.
6. **Configure DNS only if needed.** Use split DNS for the approved development suffix and the Gateway resolver reachable over the tunnel. Do not replace Windows global DNS settings.
7. **Test an authorized destination.** Confirm the container sees the original Windows source address, destination authentication still applies, replies return through the owning session, and application networks do not forward to one another.
8. **Remove only state owned by this session.** Remove its Windows routes and split-DNS rule, stop its SSH session, and let session teardown remove only its assigned Gateway/VM interfaces, addresses, and routes.

## Future `ssh -w` template

Run this template **inside the Linux VM**, after the Gateway implementation supports SSH TUN and the operator assigns every placeholder. Replace all angle-bracket placeholders; the template is not a command verified against the current repository.

```sh
ssh -N \
  -w <CLIENT_TUN_ID>:<GATEWAY_TUN_ID> \
  -p <GATEWAY_SSH_PORT> \
  -i "<PATH_TO_CLIENT_PRIVATE_KEY>" \
  <RESTRICTED_TUNNEL_ACCOUNT>@<GATEWAY_HOST>
```

`-w` requests a point-to-point TUN device at each endpoint. The `ssh` process must have approved TUN permissions; do not run it with `sudo`, which may make the user-owned private key unreadable. Keep the private key accessible only to its owner or an approved `ssh-agent`. The client and Gateway must both have compatible OpenSSH configuration. The future allocator/session hooks must assign and configure both endpoints, install the Windows-source return route through this session, install routes to the Podman CIDRs, and tear down only this session's state. Do not distribute or copy private keys.

Do not add forwarding between application networks or change any default route. The intended path is between the client tunnel and each configured Podman network only.

## Windows route template

Run PowerShell as Administrator only after confirming the route table and receiving the assigned VM host-only address and interface index. These commands are future templates, not verified commands against the current repository. Replace placeholders first.

Inspect current adapters and IPv4 routes. Check exact, broader, and more-specific routes that could overlap each Podman CIDR. The template preflights exact prefixes; review broader and more-specific overlaps manually:

```powershell
Get-NetIPConfiguration
Get-NetRoute -AddressFamily IPv4
route print -4
```

Set the values from the approved deployment inputs. These example CIDR slots correspond to the current `shared` and `webApp` declarations; replace each with its current configured CIDR:

```powershell
$PodmanCidrs = @('<SHARED_PODMAN_CIDR>', '<WEBAPP_PODMAN_CIDR>')
$VmHostOnlyAddress = '<VM_HOST_ONLY_ADDRESS>'
$HostOnlyInterfaceIndex = <WINDOWS_HOST_ONLY_INTERFACE_INDEX>
```

Preflight every exact destination prefix before adding any route. This catches an existing route for that prefix regardless of interface or next hop. If any exact route exists, resolve it before proceeding. Then add only those CIDRs to the temporary ActiveStore:

```powershell
$SessionRoutes = @()
foreach ($Cidr in $PodmanCidrs) {
    $ExactRoute = Get-NetRoute `
        -DestinationPrefix $Cidr `
        -PolicyStore ActiveStore `
        -ErrorAction SilentlyContinue
    if ($ExactRoute) {
        throw "Exact destination route already exists; resolve conflict before adding routes: $Cidr"
    }
}

try {
    foreach ($Cidr in $PodmanCidrs) {
        $SessionRoutes += New-NetRoute `
            -DestinationPrefix $Cidr `
            -InterfaceIndex $HostOnlyInterfaceIndex `
            -NextHop $VmHostOnlyAddress `
            -PolicyStore ActiveStore `
            -PassThru `
            -ErrorAction Stop
    }
}
catch {
    $SessionRoutes | Remove-NetRoute -Confirm:$false -ErrorAction SilentlyContinue
    throw
}
```

ActiveStore routes do not persist across reboot. Keep this elevated PowerShell session open so `$SessionRoutes` retains the route objects created here. If a later add fails, the catch block removes only route objects created by this session, then reports the failure. During normal teardown, remove only those exact session-owned routes:

```powershell
$SessionRoutes | Remove-NetRoute -Confirm:$false
```

Verify route selection before testing. If the PowerShell session closes before teardown, inspect the route table and remove only entries confirmed to have been created by this session. Leave pre-existing routes untouched and ask the network owner to resolve conflicts.

## DNS, forwarding, and security boundaries

Configure split DNS only for the approved development suffix. Point that suffix to the reachable Gateway DNS resolver; leave all other Windows DNS resolution unchanged. ProxyJump or an SSH control connection alone does not route DNS queries.

The VM must forward packets between its host-only NIC and its active TUN interface. The Gateway must route replies for the Windows source prefix through the owning TUN session. The hypervisor, Windows firewall, guest firewall, and Gateway policy must allow the intended traffic. These requirements are not implemented by this repository today.

Every tunnel client can reach every configured Podman network and service, including PostgreSQL, under the architecture contract. The shared network also provides direct connectivity among its attached containers. Service authentication and the external security perimeter remain required. Do not add developer-to-container NAT; preserve the original Windows source. Ordinary container egress masquerading is a separate path and does not authorize client NAT.

## Host-originated Linux client tests

Testing from the same physical Linux host is feasible only on an authorized disposable host with network isolation. Use an isolated network namespace or disposable VM for the client. Keep direct Podman bridge routes out of that client network namespace, so its traffic must use the SSH TUN path. A client in the ordinary host namespace will usually reach Podman bridges directly and bypass the tunnel; that does not test routed tunnel access.

Before such a test, verify TUN device access and required permissions, an independently reachable Gateway SSH control path, no overlapping client/TUN/Podman/host routes, and no shared or live host state. Enable forwarding only under approved policy. Teardown must remove only resources owned by the test. Do not test on a live host.

The current implementation blocks this test too: Gateway startup sets `PermitTunnel no`, and SSH session allocation, forwarding, routes, and teardown are missing.

## OpenVPN profile handling

The planned configuration field is `gateway.remote_access.openvpn.profile_file`; the current configuration schema and runtime do not support it. SSH TUN testing does not need an OpenVPN profile. Do not place the profile in this repository or Git.

The externally provided path is `/etc/gateway/openvpn/ERMXDF02.ovpn`. Treat the profile as a secret because it may embed credentials. Keep the root-owned directory at mode `0700` and the root-owned file at mode `0600`, outside Git. Do not copy, read, stat, log, or distribute it as part of SSH TUN setup.

## References

- Microsoft, [Get started with OpenSSH](https://learn.microsoft.com/en-us/windows-server/administration/openssh/openssh_install_firstuse)
- Win32-OpenSSH, [Unsupported `sshd_config` features](https://github.com/PowerShell/Win32-OpenSSH/wiki/sshd_config#not-supported)
- Win32-OpenSSH, [TUN support discussion](https://github.com/PowerShell/Win32-OpenSSH/discussions/2197)
- OpenBSD, [`ssh(1)`](https://man.openbsd.org/ssh)
- OpenBSD, [`sshd_config(5)`](https://man.openbsd.org/sshd_config)
