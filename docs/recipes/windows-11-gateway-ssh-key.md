# Windows 11 Gateway SSH key

Use this for the preflight error that `/etc/gateway/authorized_keys` is missing or empty. This key grants Gateway login only; it is not an SSH TUN or application key.

1. Generate an Ed25519 key on your client. Keep the private key on that client.

   Windows PowerShell:

   ```powershell
   New-Item -ItemType Directory -Force "$HOME\.ssh" | Out-Null
   ssh-keygen -t ed25519 -a 64 -f "$HOME\.ssh\gateway_ed25519" -C "gateway-login"
   Get-Content "$HOME\.ssh\gateway_ed25519.pub" | Set-Clipboard
   ```

   macOS Terminal:

   ```bash
   mkdir -p "$HOME/.ssh"
   chmod 700 "$HOME/.ssh"
   ssh-keygen -t ed25519 -a 64 -f "$HOME/.ssh/gateway_ed25519" -C "gateway-login"
   pbcopy < "$HOME/.ssh/gateway_ed25519.pub"
   ```

   Linux Terminal:

   ```bash
   mkdir -p "$HOME/.ssh"
   chmod 700 "$HOME/.ssh"
   ssh-keygen -t ed25519 -a 64 -f "$HOME/.ssh/gateway_ed25519" -C "gateway-login"
   ```

   On Linux, copy the public key with `wl-copy < "$HOME/.ssh/gateway_ed25519.pub"` on
   Wayland or `xclip -selection clipboard < "$HOME/.ssh/gateway_ed25519.pub"` on X11,
   if that clipboard tool is installed. Otherwise, display the public key with
   `cat "$HOME/.ssh/gateway_ed25519.pub"` and copy its single line.

2. On the Gateway host, use an existing administrator session to append the
   clipboard’s single public-key line. Preserve existing keys:

   ```bash
   sudo install -d -o root -g root -m 0700 /etc/gateway
   sudo touch /etc/gateway/authorized_keys
   sudo nano /etc/gateway/authorized_keys
   sudo chown root:root /etc/gateway/authorized_keys
   sudo chmod 0600 /etc/gateway/authorized_keys
   sudo ssh-keygen -lf /etc/gateway/authorized_keys
   ```

3. From the repository root on the Gateway host, run:

   ```bash
   sudo ./scripts/deploy-gateway.sh --check config/host_config.json
   ```

   Connect from Windows PowerShell:

   ```powershell
   ssh -i "$HOME\.ssh\gateway_ed25519" -p 2222 developer@<gateway-host>
   ```

   Connect from macOS Terminal or Linux:

   ```bash
   ssh -i "$HOME/.ssh/gateway_ed25519" -p 2222 developer@<gateway-host>
   ```

Never copy or paste the private key. Use the configured SSH port if it differs from `2222`.
