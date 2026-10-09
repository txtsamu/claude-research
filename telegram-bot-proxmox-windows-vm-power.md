---
type: how-to
tags: [telegram, bot, proxmox, px1, windows, vm, effect-v4, k3s, home, api-token, pveum, tls-pinning]
created: 2026-10-09
last_verified: 2026-10-09
status: current
---

# Telegram bot to power the Windows VM (Proxmox VM 100) on and off

Goal: turn the Windows VM (`tiny11`, VMID 100 on `px1`, see [tiny11core-windows-vm-proxmox-px1.md](tiny11core-windows-vm-proxmox-px1.md)) on and off from Telegram. Built as `~/vm-bot` (Effect v4, TypeScript) and run as `Deployment/vm-bot` in namespace `homelab` on home's k3s. Outbound long polling only, no Service or port.

## Design

- **Commands:** `/status`, `/on`, `/off` (graceful ACPI shutdown), `/forceoff` (hard stop, only after an inline "Yes" confirmation), plus inline buttons.
- **Authorisation:** allowlist of numeric Telegram user IDs; everyone else is silently ignored, and the bot refuses to start with an empty list.
- **Proxmox access:** a dedicated user and API token that can only see and power VM 100.
- **TLS:** Proxmox's certificate is self-signed, so the SHA-256 fingerprint is pinned instead of disabling verification.

## Steps run

```bash
# 1. Check the VM and what else is on the host (VM 102 `home` runs the whole homelab: must stay untouchable)
ssh px1 'qm list; pvesh get /nodes --output-format json'
ssh px1 'openssl x509 -in /etc/pve/local/pve-ssl.pem -noout -fingerprint -sha256'   # fingerprint to pin

# 2. Proxmox: least-privilege role, user and token (secret printed only once, kept out of logs)
pveum role add VMPower --privs "VM.PowerMgmt VM.Audit"
pveum user add vmbot@pve --comment "Telegram VM power bot (VM 100 only)"
pveum user token add vmbot@pve telegram --privsep 1 --output-format json      # -> .value is the secret
pveum acl modify /vms/100 --tokens 'vmbot@pve!telegram' --roles VMPower
pveum acl modify /vms/100 --users vmbot@pve --roles VMPower                    # see gotcha 1

# 3. Prove the isolation before wiring anything up
H="Authorization: PVEAPIToken=vmbot@pve!telegram=<secret>"; U=https://192.168.50.30:8006/api2/json/nodes/px1/qemu
curl -sk -H "$H" $U/100/status/current                  # 200, status: stopped
curl -sk -o /dev/null -w '%{http_code}' -H "$H" $U/102/status/current            # 403
curl -sk -o /dev/null -w '%{http_code}' -X POST -H "$H" $U/102/status/stop       # 403 (home keeps running)

# 4. Telegram: confirm the token and find the owner's numeric ID (they message the bot first)
curl -s https://api.telegram.org/bot<TOKEN>/getMe
curl -s "https://api.telegram.org/bot<TOKEN>/getUpdates?limit=10"   # message.from.id

# 5. Secret + image + deploy (no registry: import straight into k3s containerd)
printf '%s' "$SECRET" | ssh home 'sudo k3s kubectl -n homelab create secret generic vm-bot --from-file=PVE_TOKEN_SECRET=/dev/stdin'
# add TELEGRAM_TOKEN and ALLOWED_USER_IDS to the same Secret with a JSON patch piped on stdin
podman build -t localhost/vm-bot:0.1.0 . && podman save localhost/vm-bot:0.1.0 | ssh home 'sudo k3s ctr images import -'
cat k8s/vm-bot.yaml | ssh home 'sudo k3s kubectl apply -f -'
ssh home 'sudo k3s kubectl -n homelab logs deploy/vm-bot'
```

PVE endpoints used: `GET /nodes/px1/qemu/100/status/current`, `POST .../status/start`, `POST .../status/shutdown` (ACPI), `POST .../status/stop` (hard). Auth header: `Authorization: PVEAPIToken=vmbot@pve!telegram=<secret>`.

## Gotchas

1. **Privilege-separated tokens need the user to have the role too.** With `--privsep 1` the token's effective permissions are the *intersection* of the user's and the token's ACLs. Granting the role only to the token returned 403 even on VM 100; granting it to the user as well (both on `/vms/100`) fixed it, and the user still has nothing anywhere else.
2. **Pinning a self-signed cert in Node:** `rejectUnauthorized: false` plus `checkServerIdentity` does not work, because Node skips `checkServerIdentity` when verification already failed. Use a custom undici `connect` function that does `tls.connect`, then compares `socket.getPeerCertificate().fingerprint256` on `secureConnect` and destroys the socket on mismatch. Tested with the right and a wrong fingerprint. Do not set TLS `servername` to an IP (RFC 6066 deprecation warning).
3. **One `getUpdates` consumer per bot token.** A second poller on the same token gets HTTP 409 and breaks both. The token reused here was named "tt-dlp", the same name as the TikTok bot service on home; the owner confirmed that service uses a different token. Deployment strategy is `Recreate` so two pods never overlap.
4. **Never log the Telegram URL**, it contains the bot token; error messages from the Telegram client omit it.
5. The bot token was pasted into a chat to set this up, so it exists in that session's transcript. Revoke/regenerate it in @BotFather (`/revoke`) if that matters, then patch Secret `vm-bot` key `TELEGRAM_TOKEN` and restart the Deployment.
6. VM 100 has `onboot: 1`, so it also starts whenever px1 boots; the bot only reflects and controls current power state.

## Verification

- 12 unit tests (fake Telegram and Proxmox): strangers get no reply and no action; `/on` and `/off` are idempotent; `/off` never hard-stops; `/forceoff` needs the confirmation button; failures are reported to the user.
- Live: the pod started, processed the pending `/start` and replied, so egress to `api.telegram.org` works from the pod.
