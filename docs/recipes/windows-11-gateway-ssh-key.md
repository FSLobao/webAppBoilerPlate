# Windows 11 Gateway SSH key

Use this for the preflight error that `/etc/gateway/authorized_keys` is missing or empty. This key grants Gateway login only; it is not an SSH TUN or application key.

1. In PowerShell, generate an Ed25519 key. Keep the private key on Windows:

   ```powershell
   New-Item -ItemType Directory -Force "$HOME\.ssh" | Out-Null
   ssh-keygen -t ed25519 -a 64 -f "$HOME\.ssh\gateway_ed25519" -C "gateway-login"
   Get-Content "$HOME\.ssh\gateway_ed25519.pub" | Set-Clipboard
   ```

2. On the Gateway host, using an existing administrator session, append the clipboard’s single public-key line. Preserve existing keys:

   ```bash
   sudo install -d -o root -g root -m 0700 /etc/gateway
   sudo touch /etc/gateway/authorized_keys
   sudo nano /etc/gateway/authorized_keys
   sudo chown root:root /etc/gateway/authorized_keys
   sudo chmod 0600 /etc/gateway/authorized_keys
   sudo ssh-keygen -lf /etc/gateway/authorized_keys
   ```

3. Run `sudo ./scripts/deploy-gateway.sh --check config/host_config.json`. Connect with:

   ```powershell
   ssh -i "$HOME\.ssh\gateway_ed25519" -p 2222 developer@<gateway-host>
   ```

Never copy or paste the private key. Use the configured SSH port if it differs from `2222`.
