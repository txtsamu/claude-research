terraform {
  required_version = ">= 1.9"
  required_providers {
    proxmox = {
      source  = "bpg/proxmox"
      version = "~> 0.66"
    }
  }
}

provider "proxmox" {
  endpoint  = var.proxmox_endpoint
  api_token = var.proxmox_api_token
  insecure  = true # px1 uses its self-signed cert; fine on the trusted LAN

  ssh {
    agent       = false
    username    = "root"
    private_key = file("~/.ssh/talos_proxmox_tf")
  }
}
