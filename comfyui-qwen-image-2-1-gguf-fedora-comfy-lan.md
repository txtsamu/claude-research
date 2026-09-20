---
type: how-to
tags: [comfyui, qwen-image, gguf, rocm, gfx1101, fedora, caddy, technitium, nixos, openwebui, image-generation]
created: 2026-09-21
last_verified: 2026-09-21
status: current
---

# ComfyUI + Qwen-Image 2.1 GGUF on fedora (RX 7800 XT), exposed at comfy.lan, wired for Open WebUI

**Goal:** replace the `llama-server` Bonsai-27B instance on fedora with an image model
([abenzerps/Qwen-Image-2.1-Uncensored-GGUF](https://huggingface.co/abenzerps/Qwen-Image-2.1-Uncensored-GGUF)),
reachable from the LAN at `https://comfy.lan` and usable from Open WebUI.

**Status at end of session:** ComfyUI, firewall, Caddy and DNS are done and verified end to end.
Open WebUI's *settings* are **not** written yet - a manual Admin UI step remains (see the last section). The
integration code path itself was verified from inside the Open WebUI pod.

## Decisions that shaped this

- The model is text-to-image (ComfyUI-GGUF), **not** an LLM, so it can't run in llama.cpp. First idea was
  `stable-diffusion.cpp`'s `sd-server` (OpenAI-compatible `/v1/images/generations`, so Open WebUI could use it
  without a workflow) - built nothing, dropped when the user asked for ComfyUI instead.
- **Where to run it:** `home` (192.168.50.200, the NixOS k3s/Caddy/DNS VM) has no GPU (8 vCPU, ~8 GB free RAM,
  no `/dev/kfd`) and a 20B-class image model on CPU would be unusable. The GPU is on fedora
  (192.168.50.20, RX 7800 XT 16 GB). Chosen: **ComfyUI runs on fedora**, `home`'s Caddy just proxies to it.
- Quant: **Q4_K_M** (4.6 GiB, the model card's recommendation). The text encoder alone is 8.7 GiB and the whole thing
  only just fits in 16 GB (see the OOM below), so a bigger quant means offloading.

## 1. Stop the old server

```bash
kill <llama-server pid>          # was PID 3029697 on :8083, Bonsai-2-27B-CRACK
ss -ltnp | grep 8083 || echo free
```

## 2. Download the model (verify checksums)

```bash
mkdir -p ~/archive/models/qwen-image-2.1 && cd ~/archive/models/qwen-image-2.1
hf download abenzerps/Qwen-Image-2.1-Uncensored-GGUF qwen-image-2.1-Q4_K_M.gguf \
  vae/qwen_image_2.1_vae_bf16.safetensors SHA256SUMS --local-dir .
hf download abenzerps/Qwen-Image-2.1-Uncensored-GGUF \
  text_encoders/qwen3vl_8b_int8_convrot.safetensors --local-dir .
grep -E 'Q4_K_M|int8_convrot|vae_bf16' SHA256SUMS | sha256sum -c -     # all OK
```

Text encoder: `int8_convrot` (8.7 GiB) - the card recommends it over the 16 GiB bf16.

Gotcha: `pkill -f 'hf download ...'` from inside a Bash tool call also matches (and kills) the calling shell
because the pattern is in its own command line. Use `pgrep -af` + `kill <pid>` instead.

## 3. Install ComfyUI (Python 3.13 venv, PyTorch ROCm 7.2)

Fedora's system Python is 3.14; the ComfyUI README recommends 3.13, so `uv` fetches its own.

```bash
cd ~/archive && git clone --depth 1 https://github.com/comfyanonymous/ComfyUI.git && cd ComfyUI
uv venv --python 3.13 .venv && source .venv/bin/activate
uv pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/rocm7.2
uv pip install -r requirements.txt
git clone --depth 1 https://github.com/city96/ComfyUI-GGUF custom_nodes/ComfyUI-GGUF
uv pip install -r custom_nodes/ComfyUI-GGUF/requirements.txt
python -c "import torch; print(torch.__version__, torch.version.hip, torch.cuda.is_available())"
# 2.14.0+rocm7.2 7.2.x True  -> AMD Radeon Graphics 15.98 GiB
```

No `HSA_OVERRIDE_GFX_VERSION` was needed for gfx1101.

Model placement (symlinks into the archive dir):

```bash
M=~/archive/models/qwen-image-2.1; C=~/archive/ComfyUI/models
ln -sf $M/qwen-image-2.1-Q4_K_M.gguf                      $C/diffusion_models/
ln -sf $M/text_encoders/qwen3vl_8b_int8_convrot.safetensors $C/text_encoders/
ln -sf $M/vae/qwen_image_2.1_vae_bf16.safetensors           $C/vae/
```

## 4. systemd user service

`~/.config/systemd/user/comfyui.service` (linger is already enabled for `moo`, so it survives logout/reboot):

```ini
[Unit]
Description=ComfyUI (Qwen-Image 2.1 GGUF, ROCm)
After=network-online.target

[Service]
WorkingDirectory=%h/archive/ComfyUI
Environment=PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True
ExecStart=%h/archive/ComfyUI/.venv/bin/python main.py --listen 0.0.0.0 --port 8188 --reserve-vram 2
Restart=on-failure
RestartSec=10

[Install]
WantedBy=default.target
```

```bash
systemctl --user daemon-reload && systemctl --user enable --now comfyui.service
```

Native venv + systemd rather than a Podman quadlet: ROCm GPU passthrough into a container was more moving parts than
this needed, and the other llama-server instances on this box run the same way.

## 5. Three real problems (in the order hit)

### 5a. `UnetLoaderGGUF`: "This model is not currently supported - (Unknown model architecture!)"

The GGUF has **no `general.architecture` key** (it was converted with stable-diffusion.cpp; header fields are only
`GGUF.version/tensor_count/kv_count`). ComfyUI-GGUF then falls into "sd.cpp compatibility mode" and guesses the
architecture from tensor names via `tools/convert.py:detect_arch()`, whose `arch_list` has **no Qwen-Image entry**
(city96's own Qwen-Image files carry the metadata so they never hit this path). Qwen-Image 2.1 tensors are
`img_in.weight`, `txt_in.text_norm.weight`, `transformer_blocks.N.img_mlp.{gate_layer,proj,out}.weight`, ...

Fix - **local patch** in `custom_nodes/ComfyUI-GGUF/tools/convert.py` (`arch_str` is only used for the
`IMG_ARCH_LIST` check afterwards; ComfyUI itself then detects the model from the state dict):

```python
class ModelQwenImage(ModelTemplate):
    arch = "qwen_image"
    keys_detect = [
        ("img_in.weight", "txt_in.text_norm.weight", "transformer_blocks.0.img_mlp.gate_layer.weight")
    ]
# ...and append ModelQwenImage to arch_list
```

### 5b. `CUDA out of memory` in `VAEDecode` (14 GiB already allocated)

Nothing else held VRAM (`rocm-smi --showmeminfo vram` idle ~0.6 GB). Text encoder 8.7 GB + UNet 4.6 GB + VAE decode is
too tight for 16 GB. Fix: `--reserve-vram 2` (make the memory manager keep 2 GB free, so it offloads the encoder
earlier) plus `PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True` - both are in the unit above.

### 5c. Second generation fails: `Boolean value of Tensor with more than one value is ambiguous` (KSampler)

First job after a restart succeeded; the next one died in
`comfy/ldm/qwen_image21/model.py:select_prefix_cache` -> `comfy/ldm/wan/model_animate2.py:select()` at
`self.slots.remove(s)`. Cause: the Qwen-Image 2.1 prefix cache keeps several slots (positive + negative prefix);
`list.remove()` compares slot **dicts** with `==`, which compares the `"key"` tensors, and that is ambiguous as soon as
the matching slot isn't the first one. ComfyUI 0.37.0 (commit `c194dd0`, 2026-09-20) had no upstream fix yet
(`git fetch origin master` showed nothing newer). Local patch, identity-based removal:

```python
# comfy/ldm/wan/model_animate2.py, in select()
self.slots[:] = [x for x in self.slots if x is not s]
self.slots.append(s)
```

Verified with three back-to-back jobs with different prompts (all `success`, ~45 s each at 768x768, 20 steps).

> **Both patches are uncommitted local edits.** `git pull` in `~/archive/ComfyUI` or `ComfyUI-GGUF` will conflict or
> silently drop them - re-check whether upstream fixed each one before discarding the patch (`git stash` / diff first).

## 6. Workflow (API format)

Built from the official Comfy-Org template `image_qwen_image_2_1_t2i.json`. That template hides everything inside a
**subgraph** (the top-level JSON has just 5 nodes), so the real nodes were read from
`definitions.subgraphs[0]`: `UNETLoader` -> `KSampler`, `CLIPLoader` (type `qwen_image`), `TextEncodeQwenImage21`,
`EmptyLatentImage`, `VAEDecode`. cfg is **1** (negative prompt is unused at cfg 1), ~25 steps euler/simple. The only
change for GGUF is `UNETLoader` -> `UnetLoaderGGUF`. Saved as `~/archive/comfyui-workflows/qwen-image-2.1-t2i-api.json`.

Input names come from `curl -s http://127.0.0.1:8188/object_info/<NodeClass>` (the `TextEncodeQwenImage21` node
takes `clip, prompt, negative_prompt, resolution`, plus an optional autogrow `images` for editing).

Test: POST it to `/prompt`, poll `/history/<id>`. Result at 768x768/20 steps: ~45 s/image; the sign text in the test
image rendered correctly.

## 7. Firewall (fedora)

Existing pattern on this box is opening ports zone-wide (8081, 8083 already are). ComfyUI has **no authentication**,
so it's restricted to the LAN subnet instead (first tried `home` only, widened to the subnet on request):

```bash
sudo firewall-cmd --permanent --zone=FedoraWorkstation \
  --add-rich-rule='rule family="ipv4" source address="192.168.50.0/24" port port="8188" protocol="tcp" accept'
sudo firewall-cmd --reload
```

Anyone on the LAN can therefore use (and see the history of) this uncensored generator; add `basicauth` in the Caddy
block if that becomes a concern.

## 8. comfy.lan: Caddy + Technitium (both live on `home`, NixOS)

`home` is NixOS now, not the old podman Caddy on warp-vm - see [[warp-vm-nixos-migration-plan]]. Source of truth is the
git checkout `~/archive/home-nixos` on fedora (remote `txtsamu/home-nixos`); `~/home-nixos` on `home` is a plain rsync
target, so edit the local checkout, never the copy on `home`.

`hosts/home/proxy.nix`:

```nix
virtualHosts."comfy.lan".extraConfig = ''
  tls internal
  reverse_proxy 192.168.50.20:8188
'';
```

Deploy - **preview first** (a bare `nixos-rebuild switch` against the production host was rejected by the tool
permission layer as a blind apply, which is fair):

```bash
rsync -az --delete --exclude='.git' ~/archive/home-nixos/ moo@home:/home/moo/home-nixos-preview/
ssh moo@home 'cd /home/moo/home-nixos-preview && sudo nixos-rebuild dry-activate --flake .#home'
#   -> "would reload the following units: caddy.service"   (nothing else)
rsync -az --delete --exclude='.git' ~/archive/home-nixos/ moo@home:/home/moo/home-nixos/
ssh moo@home 'cd /home/moo/home-nixos && sudo nixos-rebuild switch --flake .#home'
```

Side effect to know about: the local checkout already had an *undeployed* commit (`c565997`, `programs.nix-ld.enable`
for `hermes update`), so this rebuild activated that too. Also `git status` in `~/archive/home-nixos` still shows the
`proxy.nix` change **uncommitted/unpushed**.

DNS: the `.lan` zone is explicit A records (no wildcard). Added via the Technitium API on `home`, taking the password
from the agenix secret so it never appears on a command line or in output (see
[[agenix-technitium-admin-password-fix]]):

```bash
ssh moo@home 'sudo bash -s' <<'EOF'
PW=$(sed -n "s/^DNS_SERVER_ADMIN_PASSWORD=//p" /run/agenix/technitium-admin-password)
TOKEN=$(curl -s -G http://127.0.0.1:5380/api/user/login --data-urlencode user=admin \
  --data-urlencode "pass=$PW" --data-urlencode includeInfo=false | python3 -c 'import sys,json;print(json.load(sys.stdin)["token"])')
curl -s -G http://127.0.0.1:5380/api/zones/records/add --data-urlencode "token=$TOKEN" \
  --data-urlencode domain=comfy.lan --data-urlencode zone=lan --data-urlencode type=A \
  --data-urlencode ipAddress=192.168.50.200 --data-urlencode ttl=3600
curl -s -G http://127.0.0.1:5380/api/user/logout --data-urlencode "token=$TOKEN"
EOF
getent hosts comfy.lan        # 192.168.50.200  comfy.lan
```

Observation, not fixed: the `lan` zone shows `notifyFailed: true` for `100.68.54.91` (a zone-transfer notify to a
secondary). The record was only added on `home`'s Technitium, same as `perses.lan` before it.

Verification:

```bash
curl -sk https://comfy.lan/system_stats                       # 0.37.0, cuda:0 AMD Radeon Graphics : native
ssh moo@home 'curl -s http://192.168.50.20:8188/system_stats'  # 200 (a LAN host other than fedora)
```

`-k` because `tls internal` uses Caddy's own CA; see [[caddy-internal-ca-cert-mismatch-after-host-migration]].

## 9. Open WebUI (k3s deployment `openwebui`, ns `homelab`, v0.11.3)

Findings:

- Open WebUI's pod already reaches fedora directly by IP (`OPENAI_API_BASE_URLS=http://192.168.50.20:8081/v1`,
  `NO_PROXY` includes `192.168.50.20`), so use `http://192.168.50.20:8188` as the ComfyUI base URL, **not**
  `https://comfy.lan` (the pod wouldn't trust Caddy's internal CA).
- **Env vars won't work.** The `config` table (key/value) already persists every `image_generation.*` key with defaults
  (`enable=false`, `engine="openai"`), and persisted values win over `ENABLE_IMAGE_GENERATION` / `COMFYUI_*` env vars -
  same trap as in [[hermes-openwebui-integration]]. (Upstream also has an open report that
  `COMFYUI_WORKFLOW_NODES` env is ignored.) Deployment strategy is `Recreate`, 1 replica, so a restart is a short outage.
- No manifest for this deployment exists in any repo/dir found (`kubectl apply`'d directly).
- The code path was verified **without changing any config** by running Open WebUI's own client from inside the pod:

```bash
# copy workflow + node mapping + a tiny script into the pod's /tmp, then:
kubectl -n homelab exec <pod> -- python3 /tmp/owui-test.py
# imports open_webui.utils.images.comfyui.comfyui_create_image and calls it against http://192.168.50.20:8188
# -> {'data': [{'url': 'http://192.168.50.20:8188/view?filename=qwen_image_2.1_00005_.png&subfolder=&type=output'}]}
```

  That test is what exposed problem 5c (first run of it failed in KSampler).

- Writing the settings straight into the pod's sqlite `config` table (with a backup first) was attempted and **blocked**
  by the tool permission layer as an unreviewed remote write to a production database; not retried another way.

### Remaining manual step (Admin UI)

Admin Panel -> Settings -> Images (Image Generation):

| Field | Value |
|---|---|
| Image Generation | on |
| Engine | ComfyUI |
| ComfyUI Base URL | `http://192.168.50.20:8188` |
| ComfyUI Workflow | paste `~/archive/comfyui-workflows/qwen-image-2.1-t2i-api.json` (API format) |
| Map nodes | `~/archive/comfyui-workflows/openwebui-comfyui-nodes.json`: model->node 1 `unet_name`, prompt->4 `prompt`, width/height/n->5, steps/seed->6 |
| Model | `qwen-image-2.1-Q4_K_M.gguf` |
| Image size | `1024x1024` |
| Steps | `25` |

Do **not** map `negative_prompt` - Open WebUI would write `null` into a string input and ComfyUI would reject the graph
(cfg is 1 anyway).

## Notes / not done

- Time per image is ~45 s at 768x768/20 steps (not measured at 1024x1024/25 - expect roughly 2x).
- The old `8083/tcp` firewall opening from the killed Bonsai llama-server is still there.
- `~/archive/home-nixos` change is uncommitted/unpushed.
- Leftover test files in the Open WebUI pod's `/tmp` (`wf.json`, `nodes.json`, `owui-test.py`) vanish on the next restart.

## References

- [ComfyUI README - AMD/ROCm install (torch rocm7.2, Python 3.13, HSA override note)](https://github.com/comfyanonymous/ComfyUI)
- [abenzerps/Qwen-Image-2.1-Uncensored-GGUF model card](https://huggingface.co/abenzerps/Qwen-Image-2.1-Uncensored-GGUF)
- [Comfy-Org workflow template: image_qwen_image_2_1_t2i.json](https://github.com/Comfy-Org/workflow_templates/blob/main/templates/image_qwen_image_2_1_t2i.json)
- [stable-diffusion.cpp docs/qwen_image_2.1.md](https://github.com/leejet/stable-diffusion.cpp/blob/master/docs/qwen_image_2.1.md) (the abandoned sd-server route)
- [stable-diffusion.cpp server API (OpenAI-compatible endpoints)](https://github.com/leejet/stable-diffusion.cpp/blob/master/examples/server/api.md)
- [city96/ComfyUI-GGUF](https://github.com/city96/ComfyUI-GGUF) and [issue #256 "Unknown model architecture!"](https://github.com/city96/ComfyUI-GGUF/issues/256)
- [Comfy-Org/ComfyUI PR #16400 - Qwen-Image 2.1 support](https://github.com/Comfy-Org/ComfyUI/pull/16400)
- [Open WebUI docs - ComfyUI image generation](https://docs.openwebui.com/features/chat-conversations/image-generation-and-editing/comfyui/)
- [Open WebUI discussion #19886 - COMFYUI_WORKFLOW_NODES env ignored](https://github.com/open-webui/open-webui/discussions/19886)
