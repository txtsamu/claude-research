---
type: how-to
tags: [proxmox, px1, windows, tiny11, iso, sourceforge, aria2, ovmf, tpm, nas-lvm-thin, rtk]
created: 2026-09-20
last_verified: 2026-09-20
status: current
---

# Tiny11Core Windows 11 VM on Proxmox (px1) — download, verify, create

Goal: get the `Tiny11Core-25H2-English-Pro-2026-07-05.iso` from SourceForge and run it as a VM (4 GB RAM, 8 vCPU). Started as a local KVM/libvirt install on the Fedora desktop, redirected mid-session to Proxmox `px1`. The ISO was downloaded once locally and uploaded to px1.

**End state:** VM `100` (`tiny11`) created on `px1`, **not started** (see "Next step"). Disk on `nas-lvm-thin`.

## 1. Preflight (local KVM — abandoned, kept for context)

Checked the desktop first, before the switch to Proxmox:

```bash
grep -Ec '(vmx|svm)' /proc/cpuinfo        # 32 -> AMD-V present
lsmod | grep -E '^kvm'                    # kvm_amd loaded
which virt-install virsh qemu-system-x86_64 swtpm
virsh -c qemu:///system net-list --all    # default network active
virt-install --osinfo list | grep win11   # osinfo id: win11
```

Everything needed for libvirt was already installed; only the ISO was missing. No `virtio-win` package was present, which is why the final VM uses SATA + e1000e (Windows has in-box drivers for both).

## 2. Downloading the ISO from SourceForge — four gotchas

### 2a. The URL given was stale
`.../files/tiny11core-25H2-2026-07-05/Tiny11Core-...iso/download` returned **HTTP 200 with the HTML file-browser page** (115 KB), not the ISO. The project has since been reorganised into per-edition folders. The same file still exists under:

```
https://sourceforge.net/projects/tiny-11-releases/files/Tiny11Core-Pro-25H2/Tiny11Core-25H2-English-Pro-2026-07-05.iso/download
```

How I found it: fetched the folder listing (`.../files/Tiny11Core-Pro-25H2/`) and read the embedded JSON (`"name"`, `"download_url"`, `"sha1"`, `"md5"`) for the exact filename. That JSON is also where the **published SHA-1** comes from (`f84855b450f469c5c8c002457fde542d5194f76d`; SourceForge had `sha256: null` for this file, so SHA-1/MD5 only).

Tip: always `file` the result — a `curl -L` "success" of 100–150 KB is an HTML page.

### 2b. `/download` returns an interstitial, not a redirect
Even the correct URL gives a 134 KB HTML page ("your download will start in 5 seconds"). A browser follows its `<meta http-equiv="refresh">`; `curl -L` does not. The real link is a signed URL on `downloads.sourceforge.net` (`?ts=...&use_mirror=...`). Extract and follow it:

```bash
page="https://sourceforge.net/projects/tiny-11-releases/files/Tiny11Core-Pro-25H2/Tiny11Core-25H2-English-Pro-2026-07-05.iso/download"
url=$(curl -sSL -A "Mozilla/5.0 (X11; Linux x86_64)" "$page" \
  | grep -aoE 'url=https://downloads\.sourceforge\.net[^"]*' | head -1 \
  | sed 's/^url=//; s/&amp;/\&/g')            # the &amp; -> & decode is required
curl -L --fail -A "Mozilla/5.0 (X11; Linux x86_64)" -o out.iso "$url"
```

`file out.iso` should now say `ISO 9660 CD-ROM filesystem data (bootable)`.

### 2c. Single stream was too slow (~400 KB/s → 2+ h for 3.18 GB)
- The default `master` mirror is throttled per connection.
- Switching mirror by editing `use_mirror=` in the signed URL gives **HTTP 403** — the `ts=` token is bound to the mirror. Get a fresh interstitial *per mirror* (`"$page?use_mirror=<name>"`) and extract each signed URL.
- Fix: `aria2c` with several mirror URLs for the same file. Mirrors used: `master netcologne versaweb phoenixnap cfhcable deac-fra altushost-swe`. Average came out ~2 MiB/s (≈25 min) vs ~2 h.

```bash
# f_<mirror>.txt = signed URL per mirror, fetched fresh (tokens expire)
{ printf '%s\n' "$(cat f_*.txt | grep '^https' | paste -sd'\t')"
  printf ' out=Tiny11Core-25H2-English-Pro-2026-07-05.iso\n dir=%s/Downloads\n checksum=sha-1=f84855b450f469c5c8c002457fde542d5194f76d\n split=16\n max-connection-per-server=4\n min-split-size=8M\n' "$HOME"
} > aria.txt
aria2c -i aria.txt --user-agent="Mozilla/5.0 (X11; Linux x86_64)" \
  --file-allocation=none --allow-overwrite=true --auto-file-renaming=false
```

One line of URIs separated by **tabs**, then indented per-download options. `checksum=sha-1=...` makes aria2c verify at the end (result table shows `OK`).

### 2d. Progress monitoring lies with sparse files
`--file-allocation=none` makes aria2c create a sparse file: `ls`/`stat -c %s` shows the *full* 3.18 GB almost immediately. Use `du -k` (real blocks) to measure progress.

## 3. Tooling gotchas hit along the way (RTK hook environment)

- **`sudo curl ...` fails with `sudo: rtk: command not found`.** The RTK hook rewrites the command to `sudo rtk curl`, and root's PATH has no `rtk`. Avoid `sudo` around hooked commands: download as the normal user (I used `rtk proxy curl`, the unfiltered passthrough) and only `sudo mv` afterwards. (For the Proxmox route this never mattered — the file goes to px1 by `scp` as root.)
- **`pkill -f 'curl -L --fail.*Tiny11Core'` killed my own shell** (exit 144): the pattern also matches the bash command line that contains it. Use the PID from `pgrep`, or a pattern the wrapper command line can't match.

## 4. Upload to px1 and verify

px1 = `192.168.50.30` (`ssh px1`, root). px2 (`192.168.50.50`) is unreachable ("No route to host") — consistent with it being offline.

Read-only survey of px1 first:

```bash
ssh px1 'pveversion; free -h | head -2; nproc; pvesm status; qm list; pvesh get /cluster/nextid; grep -E "^(auto|iface) vmbr" /etc/network/interfaces; ip -br a show vmbr0'
```

Result: PVE 9.2.11, 62 GiB RAM / 16 threads, `local` (dir, ISO storage), `local-lvm`, `nas-lvm-thin` (lvmthin, ~930 GB free), `nas-vm` (NFS); next free VMID = `100`; `vmbr0` = the LAN bridge (`192.168.50.30/24`). Existing VMs 101 (`warp`, stopped), 102 (`home`, running 16 GB).

```bash
scp ~/Downloads/Tiny11Core-25H2-English-Pro-2026-07-05.iso px1:/var/lib/vz/template/iso/
ssh px1 'sha1sum /var/lib/vz/template/iso/Tiny11Core-25H2-English-Pro-2026-07-05.iso'
# -> f84855b450f469c5c8c002457fde542d5194f76d  (matches SourceForge; 3175157760 bytes)
```

## 5. Create the VM

```bash
ssh px1 'qm create 100 --name tiny11 --ostype win11 --machine q35 --bios ovmf \
  --cpu host --sockets 1 --cores 8 --memory 4096 --balloon 0 --numa 0 \
  --vga std --agent 0 --onboot 0 --scsihw virtio-scsi-single \
  --net0 e1000e,bridge=vmbr0,firewall=0 \
  --efidisk0 nas-lvm-thin:1,efitype=4m,pre-enrolled-keys=1 \
  --tpmstate0 nas-lvm-thin:1,version=v2.0 \
  --sata0 nas-lvm-thin:64,discard=on,ssd=1 \
  --ide2 local:iso/Tiny11Core-25H2-English-Pro-2026-07-05.iso,media=cdrom \
  --boot "order=ide2;sata0"'
```

Why these choices:
- **4096 MB / 8 cores, `cpu host`, balloon off** — as requested; ballooning is off because Windows guests handle it poorly without the balloon driver.
- **`ovmf` + `efidisk0` + `tpmstate0 v2.0` + `q35`** — the standard Windows 11 recipe (UEFI, Secure Boot keys pre-enrolled, emulated TPM 2.0). Tiny11 bypasses the TPM/Secure Boot checks anyway, so this is belt-and-braces and harmless.
- **`sata0` + `e1000e`, no virtio** — no `virtio-win` ISO available; SATA and e1000e have in-box Windows drivers. Switch to virtio later if a virtio-win ISO is attached (faster disk/NIC).
- **Disk on `nas-lvm-thin`** — explicit user choice (thin-provisioned, iSCSI-backed on the NAS). 64 GB is a thin allocation, not reserved. See [[nas-lvm-thin-proxmox-setup]].
- Proxmox pinned the machine type to `pc-q35-11.0+pve2` for the Windows guest OS automatically.

Verify: `ssh px1 'qm config 100'`.

## Next step (not done yet)

The VM is **not started** on purpose: the Windows installer shows *"Press any key to boot from CD or DVD…"* for only a few seconds, so it needs someone at the console. To install:

```bash
ssh px1 'qm start 100'      # then open the Proxmox web console for VM 100 and press a key immediately
```

If the prompt is missed the VM falls through to the UEFI shell — just `qm reset 100` and try again. After install, the ISO can be detached: `qm set 100 --ide2 none,media=cdrom`.

Caveats worth knowing: Tiny11Core is a stripped, non-serviceable image (no Windows Update/component servicing by design) and is a third-party modified Windows build — treat it as a disposable test/lab VM. Windows licensing/activation is separate and was not handled here.

## Cleanup left on the desktop

`~/Downloads/Tiny11Core-25H2-English-Pro-2026-07-05.iso` (3.0 GB) and its scratch files in the session scratchpad can be deleted; the copy that matters is on px1.

## References

- [tiny-11-releases — SourceForge, Tiny11Core-Pro-25H2 folder](https://sourceforge.net/projects/tiny-11-releases/files/Tiny11Core-Pro-25H2/) — file listing and the published SHA-1/MD5 for the 2026-07-05 ISO (read from the page's embedded JSON).
- [tiny-11-releases — SourceForge project files](https://sourceforge.net/projects/tiny-11-releases/files/) — showed the new per-edition folder layout that made the original link stale.
