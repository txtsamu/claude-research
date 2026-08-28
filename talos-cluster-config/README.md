---
type: how-to
tags: [kubernetes, talos, proxmox, terraform, machine-config]
created: 2026-08-28
last_verified: 2026-08-28
status: current
---

# Talos cluster config artifacts

Real config files behind [[talos-kubernetes-cluster-buildout]] — that doc explains the *why* and the step-by-step; this directory is the actual *what*, so the exact shape/syntax is copy-pasteable rather than just described in prose.

This is the one intentional exception to the repo's flat/no-folders convention (see main [README.md](../README.md)) — these are working config artifacts, not knowledge-base docs, so a directory fits the content better than a markdown file would.

**Every real secret and every real internal IP has been replaced.** Two different kinds of substitution were used, both applied to the actual files pulled from the live cluster's bastion host — nothing here was written from scratch:

- **IPs** → placeholder tokens like `<CP1_STATIC_IP>`, `<CONTROLPLANE_VIP>`, `<DNS_SERVER_IP>`, `<LAN_GATEWAY_IP>` — consistent across every file, so the relationships between files (e.g. which patch targets which node) are still clear.
- **Secrets** (cluster CA cert/key, join token, `talosconfig`'s client cert/key) → **freshly-generated fake ED25519 keypairs and a fake token**, not derived from the real ones in any way, substituted in so the files stay structurally complete/parseable rather than showing broken placeholder text. Each file that got this treatment has a loud header comment saying so. The real, live versions exist only on the cluster's actual bastion host.

## Layout

- **`terraform/`** — the `bpg/proxmox` Terraform that clones the 6 node VMs from a pre-built template and feeds each one its finished machine config via cloud-init (`nodes.tf`, `providers.tf`, `variables.tf`). No secrets ever lived in these files directly — the real Proxmox API token stays in a separate, gitignored `terraform.tfvars`, referenced here only as a variable.
- **`machine-configs/`** — the Talos node configs themselves:
  - `controlplane.yaml` / `worker.yaml` — the base output of `talosctl gen config`, before any per-node identity is patched in.
  - `patch-cp1.yaml`..`patch-worker3.yaml` — the small per-node patches (static IP, hostname, install disk, and — control-plane only — the VIP declaration) merged onto the base files above via `talosctl machineconfig patch` (an offline, local operation — no live node contact).
  - `cp1.yaml` — one representative *fully-merged* result (base + patch), i.e. the actual file that gets fed to a real node's cloud-init. The other 5 nodes' merged files follow the identical pattern, just with the corresponding per-node patch swapped in.
  - `talosconfig` — the client credentials file `talosctl` needs to talk to the cluster (not to be confused with `kubeconfig`, which is `kubectl`'s, pulled separately after bootstrap and not included here since it's pure secret material with no structural teaching value).
- **`patches/`** — the "patch history": real config changes applied to the *already-running* cluster over its lifetime (as opposed to the initial-boot configs above), roughly chronological:
  - `disable-flannel.yaml` — switching the CNI from Flannel to none (Kube-OVN installs its own), applied via `talosctl patch mc`.
  - `fix-node-ip.yaml` — pinning kubelet's node IP to the real LAN subnet (Talos was picking a different interface's address by default).
  - `dns-patch.yaml` — an early attempt at fixing a stale-DNS-resolver regression (see the buildout doc's "DNS regression" section for why this *specific* patch shape doesn't actually work as a live patch, and what the real fix ended up being).
  - `metallb-pool.yaml` — the MetalLB `IPAddressPool` + `L2Advertisement`, applied via plain `kubectl apply` (Kubernetes-level, not Talos-level).
  - `registry-mirror.yaml` — a local pull-through registry mirror (Docker Hub + GHCR) to cut down on repeated image pulls over a slow WAN link.
  - `wave1-storage.yaml` — early app namespace + PVC scaffolding from the first migration wave.
  - `node-debug-daemonset.yaml` — a privileged per-node DaemonSet that bind-mounts each node's real root filesystem at `/host`, the standard workaround for Talos having no SSH/shell of its own.
