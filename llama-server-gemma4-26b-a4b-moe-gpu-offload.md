---
type: how-to
tags: [llama-server, gemma4, qwen, moe, dense, mtp, rocm, vision, hermes]
created: 2026-08-15
last_verified: 2026-08-16
status: current
---

# Gemma 4 26B-A4B (MoE) on fedora: GPU offload, vision, MTP tuning

**Date:** 2026-08-15, extended 2026-08-16
**Host:** fedora (192.168.50.20, AMD RX 7700/7800 XT — Navi 32/RDNA3, ROCm backend)
**Goal:** Replace the running Gemma 4 12B model with Gemma 4 26B-A4B (MoE: 30 layers × 128 experts, top-8 routed, ~3.8B active/25.2B total params), GPU-offload it properly given it's MoE, add vision, add MTP speculative decoding, and land on the best-performing model+config. Round 1 (08-15) compared three Gemma variants. Round 2 (08-16) added a dense-vs-MoE offload comparison against Qwen3.8-27B, then swapped to an abliterated QAT variant with its own MTP+vision that beat the original on every metric.

Supersedes the 12B setup documented in `llama-server-gemma4-qat-mtp-swap.md` (2026-06-24) — same host, same systemd unit, new model family.

---

## 1. Hardware / environment audit

```
fedora: Fedora 43, 61GB RAM, 475GB disk (343GB free at start)
GPU0: AMD RX 7700/7800 XT (Navi 32), 16GiB VRAM, ROCm0
GPU1: AMD Raphael iGPU, 512MB, ROCm1 (unused, display only)
llama.cpp: prebuilt at /root/llama.cpp/build/bin/llama-server (ROCm build)
Prior model: served via systemd unit llama-server.service on :8081
```

Existing systemd unit (`/etc/systemd/system/llama-server.service`) execs
`/usr/local/bin/llama-server-start.sh`, runs as root, sets GPU power profile
via `power_dpm_force_performance_level` before start.

## 2. MoE GPU offload — the actual technique

For MoE models, `-ngl 99` alone tries to put *everything* on GPU, including
all 128 experts per layer — way more VRAM than a 16GB card has for a
26B-param model. The fix, confirmed against Unsloth's own docs:

- **`-ngl 99`** — offload all non-MoE tensors to GPU (attention, embed,
  output, norms) — these are cheap and always want to be on GPU.
- **`-ncmoe N`** / **`--n-cpu-moe N`** — keep the MoE FFN expert weights of
  the *first* N transformer layers on CPU (system RAM), leaving `n_layers -
  N` layers' experts on GPU. This is llama.cpp's newer flag-based equivalent
  of the older `-ot ".ffn_.*_exps.=CPU"` regex override — same underlying
  mechanism (expert tensors pinned to CPU buffer type), just expressed as a
  layer count instead of a regex.
- Since only top-8-of-128 experts are active per token, the CPU-resident
  experts don't tank throughput much — CPU only computes the ~4B active
  params' worth of matmuls per step, not all 25B.
- **Tuning `-ncmoe`:** start high (most experts on CPU, safe), watch
  `rocm-smi --showmeminfo vram`, lower N until VRAM is ~80-85% full. Settled
  on **`-ncmoe 18`** (18 of 30 layers' experts on CPU, 12 on GPU) — leaves
  headroom for KV cache + vision scratch space without OOM.

```bash
rocm-smi --showmeminfo vram   # check GPU0 used/total live
```

## 3. Vision (multimodal)

Just needs `--mmproj <mmproj-*.gguf>` pointing at the matching vision
projector from the same repo. Verified end-to-end by generating a test PNG
(ImageMagick: dark blue bg, red triangle, white text) and sending it through
`/v1/chat/completions` with an `image_url` data URI — model correctly
described background color, shape, and exact text content.

```bash
convert -size 400x300 xc:'#1a3c8f' -fill white -gravity center \
  -pointsize 40 -annotate 0 'TEST' /tmp/test_img.png
# then POST to /v1/chat/completions with
# {"type":"image_url","image_url":{"url":"data:image/png;base64,<b64>"}}
```

## 4. MTP (multi-token prediction / speculative decoding)

Flags: `--spec-type draft-mtp --spec-draft-model <mtp-*.gguf>
--spec-draft-device ROCm0 --spec-draft-n-max N --spec-draft-p-min 0.6`.

A benign-looking error always appears at load and is **not fatal**:
```
E llama_init_from_model: failed to initialize the context: Gemma4Assistant
  requires ctx_other to be set (this warning is normal during memory fitting)
W srv load_model: [spec] failed to measure draft model memory: failed to
  create llama_context from model
```
This is llama.cpp's internal memory-fitting dry-run failing as expected; the
server loads and serves fine afterward. Confirm MTP is actually active by
checking for `draft acceptance = ...` in the per-request timing log, not
just absence of errors.

**`--spec-draft-n-max` must be tuned per model+hardware** — Unsloth's docs
explicitly warn not to assume 2 is optimal and to sweep 1-6 (we went to 8).
Method used: restart with each N, health-poll, fire one completion with a
long-enough prompt/n_predict to avoid early-EOS truncation skewing the
numbers, read `eval time` (tok/s) + `draft acceptance` from
`journalctl -u llama-server --since <mark>`.

**Critical finding: the MTP draft head must be trained against the exact
model it's drafting for.** A borrowed/mismatched head still "works"
(loads, runs, produces real acceptance >0%) but at a steep efficiency loss:

| Model variant                                   | MTP head source                    | Best n-max | tok/s | acceptance |
|--------------------------------------------------|-------------------------------------|-----------:|------:|-----------:|
| `gemma-4-26B-A4B-it` (base, UD-Q4_K_XL)          | matched (google, base)              | 7          | 80.6  | 84%        |
| `gemma-4-26B-A4B-it-Claude-Opus-Distill-v2` (Q4_K_M) | **borrowed** from base (no MTP shipped anywhere for this finetune — checked TeichAI source repo + all 3 GGUF requants) | 2 | 41.4 | 66% |
| `gemma-4-26B-A4B-it-qat` (UD-Q4_K_XL) **← final** | matched (unsloth QAT-specific MTP) | 2          | 64.9  | **93%**    |

Before trusting a finetuned/distilled model's speculative decoding, check
whether the repo (or its quantizers) actually ships an `mtp-*.gguf` — if not,
you're borrowing the base model's head and should expect materially lower
acceptance, and the optimal n-max shifts down.

## 5. Model comparison / decision trail

Tried three model variants in this session before settling:

1. **`unsloth/gemma-4-26B-A4B-it-GGUF:UD-Q4_K_XL`** (17GB) — the plain
   instruct model. Best MTP result of the three raw options (84% acceptance)
   but not QAT so slightly worse quantization fidelity.
2. **`TeichAI/gemma-4-26B-A4B-it-Claude-Opus-Distill-v2-GGUF:Q4_K_M`** (16.8GB)
   — reasoning-distilled from Claude Opus outputs. No MTP head anywhere for
   it; had to borrow the base model's, capping speculative decoding
   efficiency at 66% acceptance / 41 tok/s.
3. **`unsloth/gemma-4-26B-A4B-it-qat-GGUF:UD-Q4_K_XL`** (14.2GB) — QAT
   (quantization-aware training) variant **with its own matched MTP head**
   (`mtp-gemma-4-26B-A4B-it.gguf`, 252MB, "smart 4-bit recovery" derived per
   Unsloth docs). **Won on every axis**: smallest file, highest MTP
   acceptance (93%), highest sustained tok/s (64.9), most VRAM headroom.
   **→ this is what's running now.**

## 5b. Round 2 (08-16): dense-model reality check, then a better MoE variant

### Qwen3.8-27B — why dense models don't offload like MoE

Tried swapping to `unsloth/Qwen3.8-27B-GGUF` (UD-Q4_K_XL, 17.9GB) as a
performance/accuracy comparison. Confirmed via `config.json`: **dense**,
64 layers, hybrid linear/full attention, no MoE fields, native
`vision_config` + shipped `mmproj-BF16.gguf`. No `mtp-*` file in the repo.

GPU offload for a dense model is just `-ngl N` (no `-ncmoe` — there are no
experts to split out). Since the 17.9GB weight file doesn't fit in 16GB
VRAM, only partial layer offload is possible. Tuned by binary-search on
`rocm-smi` output same as the MoE case:

| `-ngl` | VRAM used | headroom |
|-------:|----------:|---------:|
| 32 | 13.3 GB | 3.9 GB |
| 36 | 14.3 GB | **2.8 GB (chosen)** |
| 40 | 15.4 GB | 1.7 GB |

Result at `-ngl 36` (36/64 layers GPU, 28 layers CPU): **5.5 tok/s** —
**~8x slower** than the MoE Gemma setup's 43-65 tok/s, on the same box,
same VRAM budget. This is not a tuning gap, it's architectural: MoE only
computes the ~4B *active* params per token even for CPU-resident experts;
dense means every one of the 28 CPU-resident layers pays full-width compute
for every single token. No `-ngl` value fixes this on a 16GB card short of
fitting the whole model in VRAM. Accuracy was equal (3/3 on the test
prompts below, Qwen just spends extra tokens on hidden chain-of-thought by
default — it's a "hybrid thinking" model, watch for empty responses if
`max_tokens` is too low to cover the reasoning content).

**Takeaway: on VRAM-constrained hardware, prefer MoE over dense at a given
total-param size.** A dense model needs to fully fit in VRAM to be fast; a
MoE model of similar size can partially offload with much less speed loss.

### Huihui abliterated QAT — a straight upgrade

Swapped again to `huihui-ai/Huihui-gemma-4-26B-A4B-it-qat-q4_0-unquantized-abliterated-GGUF`
(Q4_K, 16.8GB) — same 30-layer MoE architecture as the winning `gemma-4-26B-A4B-it-qat`
from round 1, but abliterated (refusals stripped), **with its own shipped
MTP head** (`mtp-ggml-model-bf16.gguf`, 855MB — bigger than the original's
252MB because it's BF16, not quantized) and its own `mmproj-model-bf16.gguf`.

Same `-ngl 99 -ncmoe 18` split applied cleanly (same layer count). Re-swept
`--spec-draft-n-max` fresh since a different MTP head can have a different
optimum:

| n-max | tok/s | acceptance |
|------:|------:|-----------:|
| 1 | 39.2 | 86% |
| 2 | 51.8 | 89% |
| 3 | 50.2 | 78% |
| 4 | 58.7 | 90% |
| **5** | **63.4 → 66.7 (confirm run)** | **95%** |
| 6 | 61.4 | 81% |
| 7 | 60.2 | 73% |

**`n-max=5` won** — different optimum from the original QAT model's `n-max=2`,
confirming (again) that the sweep has to be redone per model, not assumed
from a previous run even on the "same" architecture.

**Head-to-head vs the original `gemma-4-26B-A4B-it-qat`:**

| | Original QAT | Huihui abliterated QAT |
|---|---|---|
| Quant / size | UD-Q4_K_XL, 14.2GB | Q4_K, 16.8GB |
| VRAM used | 12.7GB | 14.5GB |
| MTP acceptance | 93% | **95%** |
| Throughput | 64.9 tok/s | **66.7 tok/s** |
| Accuracy (3 prompts) | 3/3 | 3/3 |
| Vision | working | working |

Marginally better on every measured axis despite the larger, unquantized
MTP head — the bigger draft model apparently drafts better tokens, not just
more of them. **This is what's running now.** No functional downside found;
the only real difference is the abliteration itself (content filtering
removed), which wasn't separately tested since it wasn't the point of this
comparison.

### Accuracy test prompts (used across all model comparisons)

```
1. "What is 17 times 24? Answer with just the number."          → 408
2. "What is the capital of Australia? Answer with just the      → Canberra
    city name."
3. "A farmer has 15 sheep. All but 8 die. How many sheep does   → 8
    the farmer have left? Answer with just the number and a
    one-sentence explanation."
```
All models tested (base, Opus-distill, QAT, Qwen3.8, huihui-abliterated)
scored 3/3. This is a sanity check, not a rigorous eval — it only catches
gross regressions, not quality differences between models that all get the
basics right.

## 6. Context length

KV cache is statically preallocated at `n_ctx` at model load time — VRAM
usage does **not** grow further as the context actually fills during use, so
picking a context length is a one-time load-time VRAM budget decision, not a
runtime risk (confirmed: VRAM was identical before/after a real generation
at 256K ctx).

| `-c` value | GPU0 VRAM used | headroom |
|-----------:|---------------:|---------:|
| 65536 (64K)   | 11.6 GB | 5.6 GB |
| 131072 (128K) | 12.7 GB | 4.4 GB |
| 262144 (256K, model max) | 15.1 GB | ~2.0 GB |

**Settled on 128K** (`-c 131072`) — doubling from the original 64K default
while keeping comfortable headroom for vision scratch space (large/multiple
images spike transient VRAM beyond the static KV cache budget). 256K works
and doesn't OOM under text-only load but leaves too thin a margin once
images are in the mix.

## 7. Final config (current, live)

`/usr/local/bin/llama-server-start.sh`:
```bash
#!/bin/bash
export GGML_AVX512=1
export OMP_NUM_THREADS=32
export OMP_PROC_BIND=close
export OMP_PLACES=threads

exec /root/llama.cpp/build/bin/llama-server \
  --device ROCm0 \
  -m /root/models/gemma-4-26B-A4B-it-qat-abliterated/Huihui-gemma-4-26B-A4B-it-qat-q4_0-unquantized-abliterated-Q4_K.gguf \
  --mmproj /root/models/gemma-4-26B-A4B-it-qat-abliterated/mmproj-model-bf16.gguf \
  -ngl 99 \
  -ncmoe 18 \
  --spec-type draft-mtp \
  --spec-draft-model /root/models/gemma-4-26B-A4B-it-qat-abliterated/mtp-ggml-model-bf16.gguf \
  --spec-draft-device ROCm0 \
  --spec-draft-n-max 5 \
  --spec-draft-p-min 0.6 \
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
  --reasoning off \
  --temp 0.4 \
  --top-k 64 \
  --top-p 0.95 \
  --min-p 0.01 \
  --repeat-penalty 1.05 \
  --repeat-last-n -1 \
  --poll 50 \
  --prio 3 \
  --metrics \
  --host 0.0.0.0 \
  --alias Gemma4-26B-A4B-it-QAT-Abliterated \
  --port 8081
```

`/etc/systemd/system/llama-server.service` — unchanged structure from the
12B setup, `Description=Gemma4-26B-A4B-it-QAT-Abliterated`,
`power_dpm_force_performance_level` set to `auto` (was `profile_standard`).
Service is `enabled` (starts on boot) and `active`.

**Result:** GPU0 VRAM 14.5/17.2GB used (~2.6GB headroom), 95% MTP draft
acceptance, ~67 tok/s decode, vision confirmed working, 128K context.

## 8. Files kept on disk (`/root/models/`)

Only the winning variant (huihui abliterated QAT) is kept; every other
comparison download from both rounds (~70GB total across base, Opus-distill,
original QAT, Qwen3.8-27B) was deleted after benchmarking to reclaim disk
space. If revisiting any of these comparisons, the download commands are:

```bash
# Base (17GB + 1.2GB mmproj + 462MB mtp)
hf download unsloth/gemma-4-26B-A4B-it-GGUF \
  gemma-4-26B-A4B-it-UD-Q4_K_XL.gguf mmproj-BF16.gguf mtp-gemma-4-26B-A4B-it.gguf \
  --local-dir /root/models/gemma-4-26B-A4B-it

# Opus-distill (16.8GB + 1.2GB mmproj, no mtp available anywhere)
hf download TeichAI/gemma-4-26B-A4B-it-Claude-Opus-Distill-v2-GGUF \
  gemma-4-26B-A4B-it-Claude-Opus-Distill.q4_k_m.gguf mmproj-BF16.gguf \
  --local-dir /root/models/gemma-4-26B-A4B-it-opus-distill

# Original QAT (14.2GB + 1.2GB mmproj + 252MB mtp)
hf download unsloth/gemma-4-26B-A4B-it-qat-GGUF \
  gemma-4-26B-A4B-it-qat-UD-Q4_K_XL.gguf mmproj-BF16.gguf mtp-gemma-4-26B-A4B-it.gguf \
  --local-dir /root/models/gemma-4-26B-A4B-it-qat

# Qwen3.8-27B dense, for reference only — 8x slower on this hardware, don't bother
hf download unsloth/Qwen3.8-27B-GGUF \
  Qwen3.8-27B-UD-Q4_K_XL.gguf mmproj-BF16.gguf \
  --local-dir /root/models/qwen3.8-27b

# Huihui abliterated QAT (kept, live — 16.8GB + 1.2GB mmproj + 855MB mtp)
hf download huihui-ai/Huihui-gemma-4-26B-A4B-it-qat-q4_0-unquantized-abliterated-GGUF \
  Huihui-gemma-4-26B-A4B-it-qat-q4_0-unquantized-abliterated-Q4_K.gguf \
  mmproj-model-bf16.gguf mtp-ggml-model-bf16.gguf \
  --local-dir /root/models/gemma-4-26B-A4B-it-qat-abliterated
```

## 9. Useful commands

```bash
# Restart after editing the start script
sudo systemctl restart llama-server

# Watch VRAM live
rocm-smi --showmeminfo vram

# Confirm MTP is actually contributing (not just loaded)
sudo journalctl -u llama-server --since '<time>' --no-pager | grep -E 'eval time =|draft acceptance'

# Boot persistence check
sudo systemctl is-enabled llama-server   # should print: enabled
```
