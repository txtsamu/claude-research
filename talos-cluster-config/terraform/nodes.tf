# 3 control-plane + 3 worker nodes, cloned from the talos-1.13.9-template (VM 9000).
# Sizing is intentionally minimal (Talos's documented floor) -- this cluster exists to
# learn HA mechanics, not to run production workloads. See ../../../migration-talos/plan.md
# (on the machine that manages this repo) for the full rationale.

locals {
  nodes = {
    talos-cp1 = { vmid = 111, ip = "<CP1_STATIC_IP>", role = "controlplane" }
    talos-cp2 = { vmid = 112, ip = "<CP2_STATIC_IP>", role = "controlplane" }
    talos-cp3 = { vmid = 113, ip = "<CP3_STATIC_IP>", role = "controlplane" }

    talos-worker1 = { vmid = 114, ip = "<WORKER1_STATIC_IP>", role = "worker" }
    talos-worker2 = { vmid = 115, ip = "<WORKER2_STATIC_IP>", role = "worker" }
    talos-worker3 = { vmid = 116, ip = "<WORKER3_STATIC_IP>", role = "worker" }
  }
}

# The final per-node Talos machine configs (cp1.yaml..worker3.yaml) are generated
# ahead of time by `talosctl machineconfig patch` -- see ../talosconfig/. Terraform
# just uploads each one as a Proxmox snippet and wires it in as cloud-init user-data;
# Talos's nocloud platform reads it directly on first boot (no separate apply-config
# step, no DHCP race -- the node comes up already on its static IP).
resource "proxmox_virtual_environment_file" "machineconfig" {
  for_each = local.nodes

  content_type = "snippets"
  datastore_id = "local"
  node_name    = var.proxmox_node

  source_raw {
    data      = file("${path.module}/../talosconfig/${replace(each.key, "talos-", "")}.yaml")
    file_name = "${each.key}.yaml"
  }
}

# Proxmox's own auto-generated cloud-init meta-data includes a `local-hostname` field,
# which collides with the `machine.network.hostname` we set explicitly in each node's
# Talos config ("static hostname is already set in v1alpha1 config" -- Talos refuses to
# merge two hostname sources). Overriding meta-data here to just an instance-id sidesteps
# that: no local-hostname, so our own explicit hostname is the only source and applies cleanly.
resource "proxmox_virtual_environment_file" "metadata" {
  for_each = local.nodes

  content_type = "snippets"
  datastore_id = "local"
  node_name    = var.proxmox_node

  source_raw {
    data      = "instance-id: ${each.key}\n"
    file_name = "${each.key}-meta.yaml"
  }
}

resource "proxmox_virtual_environment_vm" "node" {
  for_each = local.nodes

  name      = each.key
  vm_id     = each.value.vmid
  node_name = var.proxmox_node

  clone {
    vm_id = var.template_vmid
    full  = true
  }

  cpu {
    cores = 2
    type  = "host"
  }
  memory {
    dedicated = 2048
  }

  disk {
    datastore_id = "local-lvm"
    interface    = "scsi0"
    size         = 20
    discard      = "on"
    ssd          = true
  }

  network_device {
    bridge = "vmbr0"
  }

  agent {
    enabled = true
  }

  initialization {
    datastore_id      = "local-lvm"
    user_data_file_id = proxmox_virtual_environment_file.machineconfig[each.key].id
    meta_data_file_id = proxmox_virtual_environment_file.metadata[each.key].id
  }

  # Talos manages its own boot/serial console; Terraform shouldn't fight it after
  # first apply (e.g. reboots via talosctl upgrades bump these).
  lifecycle {
    ignore_changes = [
      network_device,
    ]
  }

  started = true
}

output "node_ips" {
  value = { for k, v in local.nodes : k => v.ip }
}
