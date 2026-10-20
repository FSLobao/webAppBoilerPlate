# SSH TUN permission probe (2026-10-19)

## Result

Found the cause of the synthetic `ssh -w` failure. The client and root server
could each create TUN devices directly. OpenSSH authenticated a dedicated
non-root account, then its post-authentication `sshd-session` process dropped
to UID 1000. That process opened `/dev/net/tun`, but the kernel rejected
`TUNSETIFF` with `EPERM`: the process had neither `CAP_NET_ADMIN` nor ownership
of an existing persistent TUN device.

Precreating a persistent TUN device as root and assigning its owner to the
tunnel account allowed `sshd-session` to attach without retaining
`CAP_NET_ADMIN`. Two separate root-owned key slots with distinct
`tunnel="n"` IDs supported concurrent sessions and bidirectional TCP packets.
This proves the static local ownership mechanism, not the production session
allocator, route policy, teardown, or target-host acceptance.

## Isolated environment

- Host kernel: `5.14.0-687.56.1.el9_8.x86_64`.
- Rootful Podman: `5.8.2`, `crun`; containers used separate default-bridge
  network namespaces.
- Test image: local `localhost/gateway:1`, with Debian OpenSSH `10.0p2`.
- Client and server containers each received `--cap-add NET_ADMIN` and
  `--device /dev/net/tun`. In each namespace, `/dev/net/tun` was mode `0666`.
- Server account: image account `developer`, UID/GID 1000, used only for this
  probe. It was restricted to public-key authentication, with
  `PermitTunnel point-to-point` and forwarding disabled.
- Keys and host key were generated for this probe only. No production SSH key
  or OpenVPN profile was read or used.

## Failure and syscall evidence

Direct TUN creation passed as root in both container namespaces:

```text
ip tuntap add dev client-check mode tun
ip tuntap add dev server-check mode tun
```

The SSH key was accepted with the matching `tunnel="0"` option. Server logs
reported `sys_tun_open: failed to configure tunnel (mode 1): Operation not
permitted`. Host `strace -f` attached to the isolated sshd captured:

```text
setresuid(1000, 1000, 1000) = 0
openat(AT_FDCWD, "/dev/net/tun", O_RDWR) = 8
ioctl(8, TUNSETIFF, ...) = -1 EPERM (Operation not permitted)
```

This separates device-node access from tunnel creation permission. The root
server had `NET_ADMIN`; the post-authentication session process did not. A
world-readable TUN character device alone did not grant `TUNSETIFF`.

The root server used this command with a generated host key and relevant
settings:

```text
/usr/sbin/sshd -D -e -o LogLevel=DEBUG3 -o Port=2222 \
  -o PermitTunnel=point-to-point -o HostKey=<generated-host-key> \
  -o AuthorizedKeysFile=.ssh/authorized_keys -o UsePAM=no \
  -o PasswordAuthentication=no -o PubkeyAuthentication=yes \
  -o AllowUsers=developer -o StrictModes=yes \
  -o AllowTcpForwarding=no -o AllowAgentForwarding=no \
  -o ForceCommand=/usr/bin/id
```

The client ran this command with the matching synthetic key:

```text
ssh -vvv -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null \
  -o BatchMode=yes -w 0:0 -p 2222 -i <synthetic-private-key> \
  -N developer@<server-bridge-ip>
```

Its verbose output ended with `Remote: Failed to open the tunnel device.`,
`channel 0: open failed: connect failed: open failed`, and `Tunnel
forwarding failed`.

## Successful static ownership test

As root in the server namespace, precreate persistent devices and assign each
to the non-root tunnel account:

```text
ip tuntap add dev tun0 mode tun user developer
ip tuntap add dev tun1 mode tun user developer
```

The test's root-owned, non-writable `authorized_keys` file contained only
generated public keys, in this form:

```text
restrict,tunnel="0",command="/usr/bin/id" ssh-ed25519 <synthetic-public-key-0>
restrict,tunnel="1",command="/usr/bin/id" ssh-ed25519 <synthetic-public-key-1>
```

With `PermitTunnel point-to-point`, the two client requests succeeded:

```text
ssh -vvv -w 0:0 -p 2222 -i <synthetic-key-0> -N developer@<server-bridge-ip>
ssh -vvv -w 1:1 -p 2222 -i <synthetic-key-1> -N developer@<server-bridge-ip>
```

OpenSSH logs confirmed `sys_tun_open: tun0 mode 1`, `sys_tun_open: tun1 mode
1`, and `Tunnel forwarding using interface tun0` / `tun1`. `strace` confirmed
the server-side `TUNSETIFF` returned `0` after the account owned those
persistent interfaces.

Both tunnels were configured with distinct point-to-point address pairs:

```text
slot 0: client 10.250.0.2, server 10.250.0.1
slot 1: client 10.251.0.2, server 10.251.0.1
```

Concurrent TCP requests traversed both SSH TUN channels. The server observed
the assigned client source addresses and returned the payload:

```text
slot0_peer=10.250.0.2 payload=b'slot0-test'
slot0-reply:slot0-test
slot1_peer=10.251.0.2 payload=b'slot1-test'
slot1-reply:slot1-test
```

The root-owned key file was readable by OpenSSH with `StrictModes yes`. A
third per-key fixed command (`/bin/sleep 300`) opened a tunnel and a session
when the client omitted `-N`; server logs identified the forced command and
confirmed the TUN channel. It was stopped with the test container.

## Dynamic per-session lifecycle probe

A second isolated probe used the same Debian OpenSSH 10.0p2 image and
rootful-Podman network namespace. It used one generated Ed25519 client key for
two simultaneous connections from the same non-root `developer` account.
`PermitRootLogin no`, `AllowUsers developer`, public-key-only authentication,
`PermitTunnel point-to-point`, and a restricted key option remained in force.
The client omitted `-N`; a key-specific forced command held each session.

The disposable `AuthorizedKeysCommand` keyed a two-slot allocation table by
the connection endpoints and returned a line containing
`restrict,tunnel="n",command="...session <id> <n>"`. Repeated key queries on
one connection returned the same slot. The initial public-key query and signed
request both invoked the command, as expected. Concurrent sessions using the
same key received different slots:

```text
timeout --signal=TERM 12 ssh -o StrictHostKeyChecking=no \
  -o UserKnownHostsFile=/dev/null -o BatchMode=yes -w 0:any -p 2222 \
  -i /tmp/probe_key developer@10.88.0.17
timeout --signal=TERM 12 ssh -o StrictHostKeyChecking=no \
  -o UserKnownHostsFile=/dev/null -o BatchMode=yes -w 1:any -p 2222 \
  -i /tmp/probe_key developer@10.88.0.17
```

```text
client source port 58804 -> slot 0 -> server tun0
client source port 58820 -> slot 1 -> server tun1
```

OpenSSH server logs confirmed `sys_tun_open: tun0 mode 1` and
`sys_tun_open: tun1 mode 1`. Both forced commands started as UID 1000 and
reported their own `SSH_TUNNEL` values (`tun0` and `tun1`). PAM
`open_session` hooks ran as UID 0 before either TUN request. Each hook created
only its allocated persistent TUN, assigned a distinct point-to-point address
pair (`10.249.0.1`/`10.249.0.2` and `10.249.1.1`/`10.249.1.2`), and recorded
the connection mapping. The non-root SSH session then attached without
`CAP_NET_ADMIN`.

On client disconnect, each PAM `close_session` hook received the same
connection tuple as its open hook, deleted only that session's TUN, and freed
its slot. Final checks found no `tun0` or `tun1`, no session routes, and no
allocation records. This verifies same-key concurrent slot binding, forced
session execution, and cleanup after a client-detected disconnect in the
disposable OpenSSH container.

One important normalization is required. On this Debian OpenSSH 10.0p2 image,
the raw `%C` value passed to `AuthorizedKeysCommand` logged server endpoint
first, while PAM `SSH_CONNECTION` logged client endpoint first. The probe
normalized the two endpoint pairs before matching them. Production code must
canonicalize endpoint pairs rather than compare these strings byte-for-byte.

OpenSSH source for the tested `V_10_0_P2` release supports this lifecycle:

- [`sshd_config.5`](https://github.com/openssh/openssh-portable/blob/V_10_0_P2/sshd_config.5#L2178-L2181)
  documents `%C` as a four-field endpoint identity.
- [`auth2-pubkey.c`](https://github.com/openssh/openssh-portable/blob/V_10_0_P2/auth2-pubkey.c#L290-L299)
  performs a key-allowance query before signature authentication;
  [`user_key_command_allowed2`](https://github.com/openssh/openssh-portable/blob/V_10_0_P2/auth2-pubkey.c#L713-L725)
  expands `%C` for `AuthorizedKeysCommand`.
- [`sshd-session.c`](https://github.com/openssh/openssh-portable/blob/V_10_0_P2/sshd-session.c#L1331-L1363)
  opens the PAM session before entering the authenticated channel loop and
  closes it after that loop ends.
- [`auth-pam.c`](https://github.com/openssh/openssh-portable/blob/V_10_0_P2/auth-pam.c#L748-L756)
  supplies `SSH_CONNECTION` to PAM; its cleanup calls `pam_close_session`.
- [`serverloop.c`](https://github.com/openssh/openssh-portable/blob/V_10_0_P2/serverloop.c#L483-L522)
  applies the authenticated key's forced TUN number before opening the
  interface.

The probe helper ran as root inside the disposable container. Production
design must run the key lookup/allocator under a dedicated restricted account,
keep root SSH login disabled, and limit the root PAM hook to the exact
connection-owned interface, addresses, routes, and cleanup. A pre-auth public
key query can reserve a slot without authenticating; the probe confirmed
repeated queries but did not test abandoned-query expiry. Production
allocation therefore still needs idempotent reservations, a bounded pending
lease, and bounded detection of abruptly lost TCP connections. No generic
watcher or process-table scraping is needed.

## Ownership implications and limits

The probes support this limited model for further design review:

- Use a dedicated restricted tunnel account, not a Gateway login or admin
  account.
- Allocate one reservation per canonicalized connection tuple and tunnel
  account, idempotently across key queries. Validate each key fingerprint
  against authorized-key policy. Emit the slot through a root-managed,
  non-writable `AuthorizedKeysCommand` program running as a dedicated
  restricted account, as `tunnel="n"` plus a fixed forced-session helper; do
  not infer slot identity from client-controlled environment variables.
- Use PAM `open_session` to validate the authenticated reservation and create
  only its assigned user-owned TUN and addresses before OpenSSH handles TUN
  channel requests. Use `close_session` to remove that exact session's
  interface, addresses, routes, and allocation.
- Keep `CAP_NET_ADMIN` out of the non-root SSH session. Keep pending auth
  reservations bounded, and configure bounded detection for abruptly lost
  SSH connections.
- Omit `-N` when the fixed lifecycle command needs a session channel. `-N`
  suppresses that command; it does not prevent `ssh -w` from opening a TUN
  channel when no forced session helper is required.

The synthetic allocator verified two simultaneous same-key sessions and
cleanup after client-detected disconnect, but not abandoned-query expiry,
abrupt TCP-loss timing, reconnect races, routes to Podman networks, host return
routing, packet forwarding policy, OpenVPN coexistence, or target-host
acceptance. The Gateway still has `PermitTunnel no`, `UsePAM no`, and no
production allocator or session hook.

## Cleanup and validation

Both probes used only explicitly named disposable containers and temporary
synthetic SSH keys. Containers, processes, host keys, and client keys were
removed. `podman ps -a` showed no probe containers; the default network had
zero attached containers; host `tun0` and `tun1` were absent. Podman-managed
bridge endpoints disappeared with the containers. No host route, default
route, sysctl, security setting, or service changed.

Relevant commands and outcomes:

- `podman info --format 'rootless={{.Host.Security.Rootless}} runtime={{.Host.OCIRuntime.Name}} podman={{.Version.Version}}'`:
  `rootless=false runtime=crun podman=5.8.2`.
- `ssh -V` and `sshd -V` inside the test image: Debian OpenSSH `10.0p2`.
- Host `strace` recorded the failing and succeeding server-side `TUNSETIFF`
  calls.
- Synthetic SSH TUN establishment, concurrent two-slot packet tests, and the
  dynamic same-key PAM lifecycle probe passed. No routed Podman-network or
  target-host acceptance claim is made.
