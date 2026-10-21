# Gateway Cockpit TLS: generation and developer trust

Use this recipe to supply the external Cockpit certificate and private key required
by Gateway preflight. It follows the architecture contract's
[Cockpit control-plane boundary](../contracts/WEB_APP_BOILERPLATE_ARCHITECTURE.md#52-cockpit).
It does not configure application HTTPS, SSH login keys, or client certificates.

## Summary

- Generate the server private key on the Gateway **host**. Keep it there.
- Prefer a certificate issued by your organization's approved CA.
- If no organizational CA is available, use the dedicated development CA below.
- Install the server certificate at `/etc/gateway/tls/gateway.cert` and its
  unencrypted private key at `/etc/gateway/tls/gateway.key`.
- Share only the **public CA certificate** and a separately verified SHA-256
  fingerprint with developers. Never share either private key.
- Developers trust the CA on Windows, macOS, or Linux, then access Cockpit through
  an authorized connection. Certificate trust does not grant login permission.
- Keep Cockpit bound to `127.0.0.1`. The example uses an SSH tunnel through a
  **host administrator account**, not the Gateway container's `developer` account.

## Understand the two private keys

The host and signing workstation generate **different keys for different roles**.
They do not generate copies of the same key.

- **Gateway host:** `gateway.key` is the server's private key. Cockpit uses it
  to prove possession of the identity in `gateway.cert` during TLS connections.
  Generate it on the host; the container receives it through a read-only mount.
- **Administrator's signing workstation:** `gateway-dev-ca.key` is the CA's
  private signing key. It signs the Gateway's public certificate from the CSR.
  This is a controlled administrator machine, not every developer's workstation.
  The CA key must not be installed on the host or inside the container.
- **Developer computers:** import only `gateway-dev-ca.crt`, the CA's public
  certificate. They do not generate or receive a TLS private key for this recipe.
  SSH login keys are separate and are not covered here.

The CSR carries the server's public key to the signer. The signed certificate
returns to the host. Neither exchange requires transferring a private key.
Separating the CA from the host prevents a stolen server key from being used to
issue additional CA-trusted certificates.

Two machines are a security recommendation, not a TLS protocol requirement.
An organizational CA replaces the local signing workstation and CA key.
A self-signed server certificate could use only the server key, but developers
would need to redistribute trust when that certificate is replaced. Keeping the
same CA allows server keys and certificates to be replaced without changing
developer trust, while the CA remains valid and trusted.

## 1. Choose the URL and issuer

The commands require OpenSSL on the host and a controlled Bash/OpenSSL signing
workstation. Do not run key-generation commands inside the repository.

This example uses `https://localhost:9443/` or `https://127.0.0.1:9443/` through a
local SSH tunnel. Its certificate therefore includes `DNS:localhost` and
`IP:127.0.0.1` subject alternative names (SANs). Ports are not part of a SAN.
Do not use this certificate for unrelated services.

For an approved direct-access URL, add its actual DNS name or IP address to the
CSR and signing extensions below **before signing**. Developers must resolve that
name and have an authorized network route. Do not expose Cockpit publicly just
to make certificate validation work.

If an organizational CA is available, submit the CSR from step 3 to that CA.
Request a TLS server certificate with the required SANs and `serverAuth` usage.
Obtain its root and intermediate certificates through the organization's approved
channel. Skip steps 2 and 4; do not introduce another CA unnecessarily.

## 2. Create a dedicated development CA

Only use this fallback with infrastructure approval. Trusting a CA permits it to
authenticate servers on the trusting machine. Keep its use limited to development.
Never distribute `gateway-dev-ca.key`, put it in Git, or copy it to the Gateway.
Keep the encrypted CA key and its passphrase in separate approved secure storage;
keep the key offline when it is not being used for signing.

On the signing workstation, run this once from a private directory outside Git:

```bash
(
  set -Eeuo pipefail
  umask 077
  mkdir -m 0700 gateway-cockpit-ca
  cd gateway-cockpit-ca
  openssl genpkey -algorithm RSA -aes-256-cbc \
    -pkeyopt rsa_keygen_bits:3072 -out gateway-dev-ca.key
  openssl req -new -x509 -sha256 -days 1825 \
    -key gateway-dev-ca.key -out gateway-dev-ca.crt \
    -subj "/CN=Gateway Cockpit Development CA" \
    -addext "basicConstraints=critical,CA:TRUE,pathlen:0" \
    -addext "keyUsage=critical,keyCertSign,cRLSign" \
    -addext "subjectKeyIdentifier=hash"
  openssl x509 -in gateway-dev-ca.crt -noout -sha256 -fingerprint
)
```

OpenSSL prompts for the CA key passphrase. Do not put that passphrase in a command,
environment variable, or shared terminal transcript. An existing directory causes
this block to stop rather than replace an existing CA.

## 3. Generate the Gateway key and CSR

On the Gateway host, open an administrator session and run:

```bash
sudo bash <<'BASH'
set -Eeuo pipefail
umask 077
install -d -o root -g root -m 0700 /etc/gateway/tls
for path in /etc/gateway/tls/gateway.key /etc/gateway/tls/gateway.csr /etc/gateway/tls/gateway.cert; do
  if [[ -e "${path}" || -L "${path}" ]]; then
    printf 'Refusing to replace existing TLS input: %s\n' "${path}" >&2
    exit 1
  fi
done
openssl req -new -newkey rsa:3072 -nodes -sha256 \
  -keyout /etc/gateway/tls/gateway.key \
  -out /etc/gateway/tls/gateway.csr \
  -subj "/CN=localhost" \
  -addext "subjectAltName=DNS:localhost,IP:127.0.0.1"
chmod 0600 /etc/gateway/tls/gateway.key
openssl req -in /etc/gateway/tls/gateway.csr -noout -verify -text
BASH
```

The server key is deliberately unencrypted: Cockpit must start unattended.
Root ownership, mode `0600`, and the restricted parent directory protect it.
If generation fails, inspect any partial files before retrying; do not delete an
existing working certificate or key.

Transfer only `gateway.csr` to the signing workstation through an authenticated
administrator channel. For example, an administrator can display it using
`sudo cat /etc/gateway/tls/gateway.csr` and save the complete PEM block as
`gateway.csr` inside `gateway-cockpit-ca`. The CSR is public; the key stays on the
host. Verify the CSR subject and SANs with the signing administrator.

## 4. Sign the server certificate

On the signing workstation, inside `gateway-cockpit-ca`, run:

```bash
(
  set -Eeuo pipefail
  umask 077
  if [[ -e gateway.cert || -L gateway.cert || -e gateway-server.ext || -L gateway-server.ext ]]; then
    printf 'Existing signing output found; use a fresh signing directory.\n' >&2
    exit 1
  fi
  cat > gateway-server.ext <<'EOF'
basicConstraints=critical,CA:FALSE
keyUsage=critical,digitalSignature,keyEncipherment
extendedKeyUsage=serverAuth
subjectAltName=DNS:localhost,IP:127.0.0.1
subjectKeyIdentifier=hash
authorityKeyIdentifier=keyid,issuer
EOF
  openssl x509 -req -in gateway.csr \
    -CA gateway-dev-ca.crt -CAkey gateway-dev-ca.key \
    -set_serial "0x$(openssl rand -hex 16)" \
    -out gateway.cert -days 365 -sha256 -extfile gateway-server.ext
  openssl verify -CAfile gateway-dev-ca.crt -purpose sslserver \
    -verify_hostname localhost gateway.cert
  openssl verify -CAfile gateway-dev-ca.crt \
    -verify_ip 127.0.0.1 gateway.cert
  openssl x509 -in gateway.cert -noout -dates -ext subjectAltName
)
```

Ensure the CA remains valid for the entire server-certificate lifetime.
The signing extensions explicitly define the issued SANs; the CSR alone does not
guarantee they will appear in the certificate.

## 5. Install and activate on the host

Transfer the signed `gateway.cert` and public `gateway-dev-ca.crt` to the host
administrator's home directory through a verified SSH connection. From that
directory, verify them before installation:

```bash
openssl verify -CAfile gateway-dev-ca.crt -purpose sslserver \
  -verify_hostname localhost gateway.cert
openssl x509 -in gateway.cert -pubkey -noout
sudo openssl pkey -in /etc/gateway/tls/gateway.key -pubout
```

The two complete `PUBLIC KEY` blocks must match. Stop if validation fails or the
keys differ. For an organizational issuer, use its root CA for verification and
`-untrusted intermediates.pem` when needed.

After successful verification, install the certificate:

```bash
sudo install -o root -g root -m 0644 gateway.cert /etc/gateway/tls/gateway.cert
sudo stat -c '%U:%G %a %n' /etc/gateway/tls/gateway.cert /etc/gateway/tls/gateway.key
```

Expected ownership is `root:root`; modes are `644` for the certificate and `600`
for the key. For an organizational chain, `gateway.cert` must contain PEM
certificates in order: server certificate first, then intermediate certificates.
Do not include a private key or require the server to send the root certificate.

From the repository root, follow the existing
[preflight and deployment procedure](../../README.md#preflight-e-deployment):

```bash
sudo ./scripts/deploy-gateway.sh --check config/host_config.json
sudo ./scripts/deploy-gateway.sh --apply config/host_config.json
```

Run deployment only on an authorized RHEL 9.8 target with rootful Podman 5.8.2
and SELinux already disabled. Other external inputs must also be ready.
Deployment mounts the certificate and key read-only into
`/etc/cockpit/ws-certs.d/` in the container. It does not generate these inputs.

## 6. Share public trust material

Distribute `gateway-dev-ca.crt`, the approved URL, expiry dates, and these client
instructions through an authenticated internal channel. For an organizational CA,
use its approved trust-distribution process instead.

Publish the CA certificate's SHA-256 fingerprint through a **separate verified
channel**, such as a known administrator's voice call or managed IT notice.
Developers must compare it before importing. A hash shipped beside an unverified
download does not authenticate that download.

Share neither `gateway.key` nor `gateway-dev-ca.key`. A browser needs the CA's
public certificate, not the server private key. Do not share the Cockpit password
in the certificate bundle; follow the team's separate credential policy.

### Windows 11

Save the PEM CA certificate as `$HOME\Downloads\gateway-dev-ca.crt`.
Inspect its SHA-256 **certificate fingerprint** in PowerShell:

```powershell
$path = "$HOME\Downloads\gateway-dev-ca.crt"
$cert = [System.Security.Cryptography.X509Certificates.X509Certificate2]::new($path)
$cert.GetCertHashString([System.Security.Cryptography.HashAlgorithmName]::SHA256)
```

Compare with the administrator's fingerprint, ignoring colon separators and
letter case. Do not compare a file hash with a certificate fingerprint.
After verification, import for the current Windows user:

```powershell
Import-Certificate -FilePath $path -CertStoreLocation Cert:\CurrentUser\Root
```

This trusts the CA for applications honoring that user's Windows root store.
Accept the import only if local IT policy permits it. Restart the browser.

### macOS

Save the certificate in `~/Downloads`. In Terminal:

```bash
openssl x509 -in "$HOME/Downloads/gateway-dev-ca.crt" -noout -sha256 -fingerprint
```

After comparing the fingerprint, use the system trust store only with IT approval:

```bash
sudo security add-trusted-cert -d -r trustRoot \
  -k /Library/Keychains/System.keychain "$HOME/Downloads/gateway-dev-ca.crt"
```

This changes system-wide trust. Alternatively, use Keychain Access to import into
the login keychain and approve SSL trust for the current user, subject to policy.
Restart the browser.

### Linux

First compare the certificate fingerprint:

```bash
openssl x509 -in "$HOME/Downloads/gateway-dev-ca.crt" -noout -sha256 -fingerprint
```

Then use **only** the commands for your distribution. These change system-wide trust.

Debian / Ubuntu:

```bash
sudo install -m 0644 "$HOME/Downloads/gateway-dev-ca.crt" \
  /usr/local/share/ca-certificates/gateway-dev-ca.crt
sudo update-ca-certificates
```

RHEL / Fedora:

```bash
sudo install -m 0644 "$HOME/Downloads/gateway-dev-ca.crt" \
  /etc/pki/ca-trust/source/anchors/gateway-dev-ca.crt
sudo update-ca-trust extract
```

Restart the browser. Browser, container, Java, Python, and other application trust
stores can differ from OS trust. If Firefox or another browser does not honor the
OS store, follow its managed policy or import the verified CA under its
certificate **Authorities** settings for website identification. Do not bypass
certificate warnings or disable verification.

## 7. Connect and verify

On Windows PowerShell, macOS Terminal, or Linux, use the installed OpenSSH client:

```text
ssh -N -T -o ExitOnForwardFailure=yes -L 127.0.0.1:9443:127.0.0.1:9090 -p 22 host-admin@gateway-host
```

Replace `host-admin`, `gateway-host`, and port `22` with the approved **host SSH**
account, hostname, and port. Verify the SSH host-key fingerprint separately.
This requires host-level SSH access and permitted local forwarding. It does not
use the container's published SSH port `2222`: its `developer` account restricts
forwarding destinations. If developers lack host access, infrastructure must
provide an approved access path; do not relax those restrictions for this recipe.
The tunnel destination `9090` is the host's configured Cockpit port; adjust it if
deployment uses another port.

Leave SSH running and open `https://localhost:9443/`. The certificate must be
valid, issued by the expected CA, and contain the URL's hostname in its SANs.
Sign in as `gateway-admin` only if authorized, using separately supplied
credentials. This account controls rootful Podman; certificate trust is not an
authorization boundary.

With a curl build supporting `--cacert`, test without disabling TLS verification:

```bash
curl --cacert gateway-dev-ca.crt --fail --show-error https://localhost:9443/ -o /dev/null
```

On Windows, use `curl.exe` and replace `/dev/null` with `NUL`.
Explicit `--cacert` verifies the CA file independently of OS/browser import.
Also check the browser without a warning to confirm its trust setup.
If local port `9443` is occupied, choose another unused local port in both the
tunnel command and URL; no certificate change is needed.

## Renewal and removal

Track the server and CA expiry dates. Renew before expiry, keeping the same SAN
contract. Stage and verify replacement files before an approved maintenance
window; never overwrite a live key while generating its replacement.
Back up the existing pair in root-only storage for rollback. Install a matching
pair and rerun preflight/apply so read-only file mounts use the new inputs.
Verify the certificate served over the developer connection after activation.

For CA rotation, verify and distribute the new public CA before switching the
server certificate. Remove the old CA after all dependent certificates are retired.
If a private key is exposed, stop using it and follow infrastructure incident
response; issuing another certificate alone does not invalidate the old one.

To remove trust, remove the specific CA from Windows Current User Trusted Root
Certification Authorities, macOS Keychain Access, or the Linux anchor installed
above. On Linux, rerun the corresponding trust-update command. Remove separate
browser imports too. Identify the CA by its fingerprint, not only its display name.

## Back up signing material in approved secure storage

Here, "safe repository" means approved, access-controlled secret storage or an
encrypted backup, **not this source-code Git repository**. Storage-system setup
is outside this recipe's scope. Never commit private keys to source control,
even when the CA key is passphrase-encrypted.

Preserve these items for the dedicated development CA:

- **`gateway-dev-ca.key` — required, secret:** the original encrypted CA signing
  key. Without it, you cannot issue another certificate under the existing CA.
- **CA key passphrase — required, secret:** keep it in separate approved secure
  storage, not alongside the key or in the signing configuration. A key backup
  without a recoverable passphrase is unusable.
- **`gateway-dev-ca.crt` — required, public:** the original CA certificate already
  trusted by developers. Restore this exact certificate rather than generating
  another CA certificate with the same name.
- **`gateway-server.ext` — reproducible signing configuration:** preserve the
  approved SANs, constraints, and server usage. Review it for each new request;
  do not blindly reuse a previous host's identity.
- **Issued `gateway.cert` files and their `gateway.csr` files — public records:**
  retain them with issuance dates, serial numbers, expiry dates, and intended
  hostnames. They support audit and recovery, but are not needed to generate a
  new server key.
- **CA fingerprint and recovery metadata:** retain the independently verified
  SHA-256 certificate fingerprint, responsible administrator, approved SANs,
  and this issuance procedure.

Step 4 generates a random serial for each certificate using `-set_serial`; it
does not create a `.srl` file or an OpenSSL CA database. There is no serial-counter
file to restore for this procedure. If your organization uses a different CA
tool, preserve its database, serial state, and revocation records according to
that tool's recovery procedure.

An optional **separate server-recovery backup** may contain the matching
`/etc/gateway/tls/gateway.key` and `/etc/gateway/tls/gateway.cert` pair. The server
key is unencrypted on disk, so its backup requires encryption and restricted
access. This is the exception to keeping the key only on the host: it is an
administrator recovery copy, never a developer distribution artifact.
The server pair is not needed to sign a newly generated server key.

## Restore signing material for a new server key

Use this procedure when replacing a server key or recovering the signing
workstation. It reuses the existing CA; it does not create another one.

1. On a controlled signing workstation, create a fresh private directory outside
   Git. Restrict the directory to its owner (`0700`). Restore the original
   `gateway-dev-ca.key` and `gateway-dev-ca.crt` there. Restrict the private key
   to its owner (`0600`), and retrieve its passphrase through the separate
   approved recovery process.
2. Compare the restored CA certificate's SHA-256 fingerprint with the
   independently verified record, using the command in step 2. Inspect its
   validity dates. Confirm that it remains valid for the planned server
   certificate lifetime; otherwise follow the CA rotation procedure.
3. Check the restored CA key with
   `openssl pkey -in gateway-dev-ca.key -check -noout`. OpenSSL prompts for its
   passphrase. Compare the complete public-key output of
   `openssl pkey -in gateway-dev-ca.key -pubout` with
   `openssl x509 -in gateway-dev-ca.crt -pubkey -noout`. Stop if they differ or
   any validation fails. These commands do not display the private key.
4. On the Gateway host, generate a **new server key and CSR** using step 3.
   For an existing deployment, use a fresh root-only staging directory and
   adjust the output paths; step 3 deliberately refuses to overwrite live
   inputs. Keep the working pair in place until its replacement is ready.
5. Transfer only the new CSR to the restored signing directory. Review its
   public key, subject, and SANs. Restore the saved signing configuration for
   reference, then use step 4 to create a reviewed `gateway-server.ext` and
   issue a new certificate. Leave those output filenames absent before running
   step 4; its guard refuses to overwrite existing files.
6. Verify and install the new matching server pair during an approved
   maintenance window, following step 5 and the renewal procedure. For a staged
   replacement key, install it as `root:root`, mode `0600`, at
   `/etc/gateway/tls/gateway.key` as well as installing the signed certificate.
   Rerun preflight/apply and verify the certificate served to developers.
7. Update the secure backup's issuance records and any server-recovery copy.
   Remove temporary CA private-key copies from the signing workstation under
   your organization's secure cleanup policy once signing is complete.
   Keep the recoverable encrypted CA backup.

Developers do not reimport the CA when only the server key and certificate
change under the same trusted CA and the URL still matches the SANs.

If restoring the existing server instead of generating a new key, recover its
matching backed-up key and certificate, verify their match and certificate
validity, restore the ownership and modes from step 5, and rerun preflight/apply.
Do not restore a compromised key or an expired certificate.

If the CA key or passphrase is lost, the public CA certificate cannot recover
the signing key. Create a new CA through an approved rotation and redistribute
its public certificate and verified fingerprint. A compromised CA also requires
incident response and removal of the old trust; restoring its backup does not
make it safe.
