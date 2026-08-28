variable "proxmox_endpoint" {
  type        = string
  description = "Proxmox API endpoint"
  default     = "https://<PROXMOX_HOST_IP>:8006/"
}

variable "proxmox_api_token" {
  type        = string
  description = "Proxmox API token, format user@realm!tokenid=secret"
  sensitive   = true
}

variable "proxmox_node" {
  type        = string
  description = "Proxmox node name to provision on"
  default     = "pve-pc"
}

variable "template_vmid" {
  type        = number
  description = "VMID of the talos-1.13.9-template to clone"
  default     = 9000
}
