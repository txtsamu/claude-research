---
type: how-to
tags: [llama-server, qwen, moe, rocm, gguf, uncensored, systemd]
created: 2026-08-31
last_verified: 2026-08-31
status: current
---

# Swapping llama-server (fedora) to Qwen3.6-35B-A3B-Uncensored-HauhauCS-Aggressive

**Host:** fedora (AMD RX 7800 XT, ROCm backend)
**Goal:** Replace the running model (Ornith-1.5-35B-Uncensored) with Qwen3.6-35B-A3B, HauhauCS's uncensored "Aggressive" finetune, at Q4_K_M.

---

## Step 1: Find the right model

Checked evomem first (per standing convention — search before re-deriving). Two useful hits:
- The prior Gemma4 model-swap write-up ([[llama-server-gemma4-qat-mtp-swap]]) as a structural template for "how to swap this box's model."
- A session note from 2026-08-17 confirming a Qwen3.6-35B model had already been pulled down once before during unrelated `llama-bench` testing.

Confirmed the exact repo via web search: **`HauhauCS/Qwen3.6-35B-A3B-Uncensored-HauhauCS-Aggressive`** on Hugging Face — MoE architecture (35B total params, ~3B active per forward pass), several quant variants available (Q2_K_P through Q8_K_P, plus IQ2_M/IQ3_M/IQ4_NL/IQ4_XS). Picked **Q4_K_M (21.2GB)** per the request, plus the accompanying **f16 mmproj (899MB)** for vision support. Note HauhauCS also publishes 27B non-MoE variants of Qwen3.6 (Balanced/Aggressive) — the 35B-A3B MoE was the one already referenced in this session's history, and matches the outgoing model's architecture class.

## Step 2: Model was already on disk

```bash
sudo -E env "PATH=$PATH" ls -la /root/models/qwen3.6-35b-hauhau-aggressive/
```

Both files were already present, dated 2026-08-17, sizes matching HF's listing exactly (21,166,758,016 bytes / 899,283,072 bytes) — no download needed, just needed to be wired in.

## Step 3: Compare against the outgoing model

```bash
sudo -E env "PATH=$PATH" cat /etc/systemd/system/llama-server.service
sudo -E env "PATH=$PATH" cat /usr/local/bin/llama-server-start.sh
sudo -E env "PATH=$PATH" ls -la /root/models/ornith-1.5-35b-uncensored/
```

Outgoing model (Ornith-1.5-35B-Uncensored) is also a ~35B MoE at nearly identical file size (21.7GB main + 903MB mmproj). Given the close match, the existing ROCm/offload tuning was carried over unchanged rather than re-tuned from scratch:

```
-ngl 99 -ncmoe 25 -fa on -c 131072 --cache-type-k q4_0 --cache-type-v q4_0
```

## Step 4: Swap the start script

`/usr/local/bin/llama-server-start.sh` — model path, mmproj path, and `--alias` updated (everything else unchanged):

```bash
#!/bin/bash
# Qwen3.6-35B-A3B-Uncensored-HauhauCS-Aggressive
# MoE (35B total, ~3B active). ROCm backend on RDNA3 (ROCm0 = RX 7800 XT).

export GGML_AVX512=1
export OMP_NUM_THREADS=32
export OMP_PROC_BIND=close
export OMP_PLACES=threads

exec /root/llama.cpp/build/bin/llama-server \
  --device ROCm0 \
  -m /root/models/qwen3.6-35b-hauhau-aggressive/Qwen3.6-35B-A3B-Uncensored-HauhauCS-Aggressive-Q4_K_M.gguf \
  --mmproj /root/models/qwen3.6-35b-hauhau-aggressive/mmproj-Qwen3.6-35B-A3B-Uncensored-HauhauCS-Aggressive-f16.gguf \
  -ngl 99 \
  -ncmoe 25 \
  -fa on \
  -c 131072 \
  --parallel 1 \
  --cache-type-k q4_0 \
  --cache-type-v q4_0 \
  --batch-size 2048 \
  --ubatch-size 1024 \
  --threads 8 \
  --threads-batch 16 \
  --no-mmap \
  --cont-batching \
  --jinja \
  --reasoning-format deepseek \
  --temp 0.6 \
  --top-k 20 \
  --top-p 0.95 \
  --poll 50 \
  --prio 3 \
  --metrics \
  --host 0.0.0.0 \
  --alias Qwen3.6-35B-A3B-Uncensored-HauhauCS-Aggressive \
  --port 8081
```

Install commands:

```bash
sudo -E env "PATH=$PATH" cp llama-server-start.sh /usr/local/bin/llama-server-start.sh
sudo -E env "PATH=$PATH" chmod 755 /usr/local/bin/llama-server-start.sh
sudo -E env "PATH=$PATH" sed -i \
  's/Description=Ornith-1.5-35B-Uncensored/Description=Qwen3.6-35B-A3B-Uncensored-HauhauCS-Aggressive/' \
  /etc/systemd/system/llama-server.service
```

## Step 5: Reload and verify

```bash
sudo -E env "PATH=$PATH" systemctl daemon-reload
sudo -E env "PATH=$PATH" systemctl restart llama-server.service
sudo -E env "PATH=$PATH" systemctl status llama-server.service --no-pager -l | head -15

# poll until ready:
for i in $(seq 1 15); do
  curl -s -m 3 http://localhost:8081/health | grep -q ok && echo READY && break
  sleep 5
done
curl -s http://localhost:8081/health

sudo -E env "PATH=$PATH" systemctl is-active llama-server.service
sudo -E env "PATH=$PATH" systemctl show llama-server.service -p NRestarts
sudo -E env "PATH=$PATH" journalctl -u llama-server --no-pager -n 15
```

Loaded clean in ~25s: `{"status":"ok"}`, `NRestarts=0` (no OOM crash-loop, which was the main risk given the file-size match was only approximate — main model file ended up ~500MB smaller than the outgoing one). Journal confirmed clean load: multimodal projector loaded, `n_ctx_slot = 131072`, listening on `:8081`. See [[fedora-memory-audit-warp-svc-leak-daily-restart]] for the `sudo -E env "PATH=$PATH" ...` workaround this required.

## Outcome

`llama-server` now serves **Qwen3.6-35B-A3B-Uncensored-HauhauCS-Aggressive (Q4_K_M)** on `:8081`, same ROCm/MoE offload tuning as the previous model, healthy on first boot with zero restarts.

## If revisiting later

- Load-time warning surfaced in the journal: *"Qwen-VL models require at minimum 1024 image tokens to function correctly on grounding tasks... try adding `--image-min-tokens 1024`"*. Not currently set — only matters for vision/grounding-task accuracy; add the flag to the start script if that's used.
- Other quant variants live in the same HF repo (`Q2_K_P` up through `Q8_K_P`, plus `IQ2_M`/`IQ3_M`/`IQ4_NL`/`IQ4_XS`) if VRAM headroom ever changes and a different size/quality tradeoff is wanted.
