---
type: how-to
tags: [llama.cpp, llama-server, vulkan, rocm, gfx1101, rx-7800-xt, gguf, ternary, quantization, mtp, speculative-decoding, bonsai, qwen]
created: 2026-11-26
last_verified: 2026-11-26
status: current
---

# Ternary-Bonsai-2.5-27B-Uncensored MTP on an RX 7800 XT (stock llama.cpp, Vulkan)

Running `kelsey1337/Ternary-Bonsai-2.5-27B-Uncensored-MTP-GGUF` on Fedora 43 with an RX 7800 XT (`gfx1101`, 16 GiB). The short version: use the **Q2_0-mtp** file, use **stock llama.cpp b11556+** with the **Vulkan** backend, and enable `--spec-type draft-mtp`. Measured 71.5 tok/s generation and ~530 tok/s prompt processing at 32k context, with the model fully on the GPU and about 3 GiB of VRAM to spare.

Related: [[bonsai-27b-prismml-ternary-gguf-deploy]] covers the earlier PrismML-fork/ROCm deployment of a different Bonsai ternary quant on the same card.

## Time estimate

| Step | Wall clock |
|---|---|
| Download 37 MB Vulkan release tarball | ~10 s |
| Extract + verify the GPU is visible | ~10 s |
| Download 7.91 GB GGUF | ~2 min on this connection |
| sha256 verify (8 GB) | 3.5 s |
| First load + smoke test | ~1 min |
| Full benchmark set (MTP on, MTP off, KV sweep) | ~10 min |
| HIP comparison for the same file (~2 min of it is model load) | ~3 min |
| MTP n-max sweep, 6 restarts | ~6 min |
| 100k context, two KV types, one 96k-token prompt each | ~15 min |
| Batch/ubatch sweep, 5 restarts | ~4 min |
| vLLM install (ROCm 10.0 wheels) | ~8 min |
| vLLM small-model proof + GGUF attempts | ~10 min |
| **Total** | **~65 min** |

Download figures are measurements from this session (`stat`/timestamps); the benchmark block is measured, the rest is estimate.

## Why this packing

The repo ships six files. Only the `Q2_0` pair runs on stock llama.cpp; `PTQ1_0` and `PQ2_0` need the PrismML fork. Between the two Q2_0 files, take the one with the MTP head.

| File | Size | Engine | Notes |
|---|---|---|---|
| `...-PTQ1_0-mtp.gguf` | 6.23 GB | PrismML fork only | smallest, but fork-only |
| `...-PQ2_0-mtp.gguf` | 7.49 GB | PrismML fork only | fork-only |
| `...-Q2_0-mtp.gguf` | 7.91 GB | stock llama.cpp b11556+ | **chosen** |
| `...-Q2_0.gguf` | 7.67 GB | stock llama.cpp b11556+ | no speculative decoding |

All six store the same ternary weights with the same fp16 group-128 scales; only the bit layout differs, so quality is identical across packings. The MTP head is an extra draft layer (`blk.64.*`) that lives in the same file, which is why no separate draft model is needed.

On Vulkan there is no reason to chase the fork. The fork buys ~1.7 GB of file size and nothing else, and it has no prebuilt Vulkan binaries.

## Steps

### 1. Check the GPU is reachable from Vulkan

```bash
vulkaninfo --summary | grep -iE 'deviceName|driverName'
```

This host reports `AMD Radeon RX 7800 XT (RADV NAVI32)` with the RADV driver, Vulkan 1.4.328, Mesa 25.3.6. ROCm runtime 6.4.2 is present but the HIP toolchain is not needed for this path.

### 2. Grab the prebuilt Vulkan build

No compiling required. llama.cpp publishes a Linux Vulkan tarball per release:

```bash
cd ~/src && curl -L -o llama-b12774-vulkan.tar.gz \
  https://github.com/ggml-org/llama.cpp/releases/download/b12774/llama-b12774-bin-ubuntu-vulkan-x64.tar.gz
tar xzf llama-b12774-vulkan.tar.gz
cd llama-b12774 && ./llama-cli --list-devices
```

Expected output, and the check that matters:

```
Available devices:
  Vulkan0: AMD Radeon RX 7800 XT (RADV NAVI32) (16368 MiB, 12461 MiB free)
  Vulkan1: AMD Ryzen 9 7950X 16-Core Processor (RADV RAPHAEL_MENDOCINO) (32204 MiB, 32169 MiB free)
```

Build 12774 is well past the b11556 floor the model card requires for the `qwen35` architecture.

### 3. Download and verify the model

```bash
mkdir -p ~/models/ternary-bonsai-27b && cd ~/models/ternary-bonsai-27b
curl -L --retry 5 -C - -o Ternary-Bonsai-2.5-27B-Uncensored-Q2_0-mtp.gguf \
  "https://huggingface.co/kelsey1337/Ternary-Bonsai-2.5-27B-Uncensored-MTP-GGUF/resolve/main/Ternary-Bonsai-2.5-27B-Uncensored-Q2_0-mtp.gguf"
sha256sum Ternary-Bonsai-2.5-27B-Uncensored-Q2_0-mtp.gguf
```

The hash must equal the one published in the repo's `evaluation.json`:

```
6b321b5604ad32bcffe45c220f5926d51a9f5367eeb512b15f19ce63eb8ca386
```

File size `7912178944` bytes, verified in this session.

`-C -` resumes a partial download, which matters: an interrupted shell killed the first attempt at 1.8 GB.

### 4. Launch the server

`~/models/ternary-bonsai-27b/run-server.sh`:

```bash
#!/usr/bin/env bash
set -u
BIN="$HOME/src/llama-b12774"
MODEL="$HOME/models/ternary-bonsai-27b/Ternary-Bonsai-2.5-27B-Uncensored-Q2_0-mtp.gguf"
CTX="${CTX:-32768}"
PORT="${PORT:-8080}"
SPEC="${SPEC:-draft-mtp}"
KV="${KV:-q8_0}"
NMAX="${NMAX:-3}"
BATCH="${BATCH:-2048}"
UBATCH="${UBATCH:-1024}"

exec "$BIN/llama-server" \
  -m "$MODEL" \
  --host 127.0.0.1 --port "$PORT" \
  -ngl 99 \
  -c "$CTX" \
  -b "$BATCH" -ub "$UBATCH" \
  -fa on \
  -ctk "$KV" -ctv "$KV" \
  --jinja \
  -np 1 \
  --spec-type "$SPEC" \
  --spec-draft-n-max "$NMAX" \
  --spec-draft-p-min 0 \
  --temp 0.7 --top-p 0.95 --top-k 20
```

```bash
cd ~/models/ternary-bonsai-27b && PORT=8090 ./run-server.sh
```

Load takes about 2.3 s from page cache. `--spec-type draft-mtp` logs `creating MTP draft context against the target model` and reuses the same GGUF; there is no second file to fetch.

Flag notes:
- `-fa on` is required to keep the KV cache small; the model is a hybrid attention/SSM stack, so KV is much cheaper than a pure transformer of this size.
- `-ctk q8_0 -ctv q8_0` saves ~1.2 GB over f16 and costs about 2 tok/s.
- `-np 1` keeps one slot so the whole context belongs to a single request.
- `--spec-draft-p-min 0` matches the settings the model card benchmarked.

## Results

RX 7800 XT, driver RADV, build b12774, 32k context, q8_0 KV, greedy decoding, 320-token generations:

| Config | Prompt (2401 tok) | Generation | Draft acceptance |
|---|---|---|---|
| MTP on (`draft-mtp`, n-max 3) | 529 tok/s | **71.5 tok/s** | 197/365 = 54% |
| MTP off (`--spec-type none`) | 557 tok/s | 45.5 tok/s | n/a |
| MTP on, 64k ctx, q8_0 KV | 531 tok/s | 70.8 tok/s | 54% |

That table is one prompt at a time. The 3-prompt averaged bench used for the tuning sweeps below gives **81.5 tok/s** mean at n-max 3, because a single prompt either matches the model's drafting rhythm or does not. Treat ~80 tok/s as the realistic chat figure and 71.5 as a pessimistic single-sample one.

Speculative decoding is worth **1.57x to 1.8x** on decode here and costs ~5% of prompt throughput. The model card claims ~1.65x on a 4090 with 66% acceptance; the speedup tracks acceptance, so a lower-capability machine sees a slightly smaller win.

### Vulkan (stock b12774) vs HIP (old PrismML fork), same file

| Backend | Prompt (2401 tok) | Generation | MTP |
|---|---|---|---|
| Vulkan, stock b12774 | 557 tok/s | 45.5 tok/s | off |
| Vulkan, stock b12774 | 529 tok/s | 71.5 tok/s | on |
| HIP, PrismML fork `1a07bfa` | 268 tok/s | 43.1 tok/s | not possible (see below) |

Vulkan is roughly **2x faster on prompt processing** and marginally faster on decode than the ROCm path on this card. The caveat is real: the fork checkout is from September and the stock build is from today, so part of that gap is engine age, not backend quality. Still, there is no reason to fight the HIP toolchain on Fedora for this model when a prebuilt Vulkan binary already beats it.

VRAM (GPU total, desktop idle baseline is 4.06 GB):

| Config | Used | Headroom |
|---|---|---|
| 32k ctx, f16 KV | 14.43 GB | 1.6 GB |
| 32k ctx, q8_0 KV | 13.40 GB | 3.0 GB |
| 64k ctx, q8_0 KV | 14.73 GB | 1.3 GB |

64k context fits but leaves little room if something else grabs VRAM (a browser playing video, a game). 32k with q8_0 is the sane default on a 16 GB card; `CTX=65536` works when nothing else is running.

Long prompt check: an 11,926-token prompt processed at 526 tok/s (22.7 s) at 64k context with no OOM.

The sweep over `--spec-draft-n-max` 2/4/6 moved generation between 71.5 and 72.4 tok/s, inside noise. Leaving it at the default 3 is fine.

Sanity checks that the model actually works, beyond token counts:

- `/v1/chat/completions` returns a clean answer with `chat_template_kwargs: {"enable_thinking": false}`.
- With thinking left on, the reasoning lands in `reasoning_content` and the final answer in `content`.
- `84 * 3 / 2` answered `126`.

## Gotchas

- **`pkill -f llama-server` kills the shell running it.** The pattern matches the invoking `bash -c` command line, which contains the binary path. Use `pkill -x llama-server` or `pgrep -x`.
- **The old PrismML fork cannot run the MTP head on this file.** Build `1a07bfa` (Sep 2026) loads the main model fine but dies when creating the draft context:

  ```
  W llama_verify_hadamard_graph: latent lookup 'mtp_tok_embd-64' consumed by op=RMS_NORM name='norm-64' src0 hint=0
  E llama_init_from_model: failed to initialize the context: Hadamard-latent table 'token_embd.weight' is read without the inverse transform
  E common_speculative_init_result: failed to create MTP context
  ```

  The ternary `qwen35` format gained a Hadamard-rotated latent path that the fork predates. Drop `--spec-type draft-mtp` on the fork and it runs (that is how the HIP numbers below were taken), but then you give up the whole reason to pick this file.
- **Port 8080 is taken on this host** (a rootless container via pasta). Use 8090.
- **Extra CLI flags appended after `run-server.sh` do not override the script's own flags** reliably. Drive variants through the env vars (`SPEC=none`, `CTX=65536`, `KV=f16`) instead of appending `--flags`.
- **Download is 7.9 GB.** 245 GB free here, no concern, but the first attempt died at 1.8 GB when the parent shell was interrupted; `setsid` plus `-C -` fixed it.
- The blog-style "runs on stock llama.cpp b11556+" claim was true: build 12774 loads the `qwen35` architecture and the MTP head without complaint.

## What this does not cover

- Quality regression from the abliteration. The card claims +3.1% perplexity and 0/12 refusals; that was not re-measured here, only functional output was checked.
- Long-run stability past a few thousand tokens of generation.
- Why the Hadamard-latent MTP path fails on the old fork in more depth; only the error was captured.
- Perplexity or refusal claims. The card's numbers were not reproduced, only functional output and speed.
- vLLM throughput for a 27B model on this card. The GGUF cannot load, and no supported-quant checkpoint of this model exists, so there is nothing to measure. A smaller model at 4-bit would fit and could be benchmarked separately if that comparison is ever wanted.

## Recommended config for this card

```bash
CTX=32768 KV=q8_0 NMAX=3 UBATCH=1024 ./run-server.sh
```

For long-document work, `CTX=102400 KV=q4_0` is the safe 100k setting; use `KV=q8_0` at that context only when nothing else is on the GPU.

## Tuning the MTP head

Unsloth's MTP guide says to start at `--spec-draft-n-max 2` but to sweep 1-6, because the best value is hardware dependent. Sweeping it here (3-prompt average, 300 tokens each, greedy, 32k ctx, q8_0 KV):

| `--spec-draft-n-max` | tg mean | Draft acceptance |
|---|---|---|
| 1 | 67.1 tok/s | 79% |
| 2 | 76.6 tok/s | 67% |
| 3 | **81.5 tok/s** | 60% |
| 4 | **81.6 tok/s** | 50% |
| 5 | 78.7 tok/s | 43% |
| 6 | 75.0 tok/s | 38% |

3 and 4 are tied; acceptance falls steadily while per-token verifier work rises, and past 4 the loss wins. The recommended default of 2 costs about 6% here. Keep 3.

The first attempt at this sweep looked like it did nothing (identical draft counts for every value) because extra flags appended after `run-server.sh` did not override the script's own `--spec-draft-n-max`. Driving it through an env var fixed it. Worth remembering before trusting any A/B of llama-server flags.

Sampling follows the same guide's Qwen-family presets: temp 1.0 / top_p 0.95 / top_k 20 / min_p 0 for thinking mode, and `chat_template_kwargs {"enable_thinking": false}` for a direct answer.

## 100k context

The model is a hybrid: 16 of the 64 layers are full attention (`full_attention_interval: 4`), the rest are linear-attention/SSM with constant state. So KV grows at 4 KB/token at f16, 2 KB/token at q8_0, 1 KB/token at q4_0, and only for those 16 layers.

`CTX=102400` loads fine with either quantized KV type. Load, then a 95,921-token prompt with a planted fact at ~85% depth:

| KV type | VRAM after load | VRAM peak | Prompt throughput | Recall |
|---|---|---|---|---|
| q8_0 | 15.52 GiB | 15.52 GiB | 300.7 tok/s | correct |
| q4_0 | 13.11 GiB | 13.59 GiB | 236.7 tok/s | correct |

Both answered the planted question (`73-19-04`, echoed as `731904` when asked for digits only), so quantized KV does not break deep recall at this depth. q4_0 buys 1.5 GiB of headroom but costs 21% of prompt throughput at full depth.

q8_0 at 100k leaves **0.46 GiB free** on a 16 GiB card with the desktop using 4 GiB. It works, and it worked twice, but one video decode in another window could send it over. Use q4_0 for a 100k default, q8_0 only when nothing else touches the GPU.

Shorter prompts are much faster: 73,361 tokens ran at 364.7 tok/s versus 300.7 at 95,921, so throughput decays with depth as expected.

## Batch tuning

`-ub` / `-b` sweep on a 11,901-token prompt:

| Batch / ubatch | Prompt throughput |
|---|---|
| 1024 / 256 | 511.4 tok/s |
| 2048 / 512 (default) | 523.3 tok/s |
| 2048 / 1024 | 533.0 tok/s |
| 2048 / 2048 | 537.4 tok/s |
| 4096 / 2048 | 537.5 tok/s |

About 5% from bottom to top, and the larger ubatch costs compute-buffer VRAM, which is exactly what is scarce at 100k context. `-ub 1024` is the sane middle; leave `-b` at 2048.

## vLLM: works on this card, cannot load this file

Tested properly rather than assumed. vLLM 0.34.0 does install and run on gfx1101 here, including prebuilt ROCm 10.0 wheels that bundle the GPU kernels for this architecture. No `HSA_OVERRIDE_GFX_VERSION` needed.

```bash
uv venv --python 3.12 --seed --managed-python ~/venvs/vllm312
source ~/venvs/vllm312/bin/activate
uv pip install vllm --extra-index-url https://wheels.vllm.ai/rocm/ \
    --index-strategy unsafe-best-match --upgrade
```

Two gotchas in that command. Python 3.14 is advertised but the ROCm wheel index only carries `cp312` ABI wheels, so 3.12 it is. And the rocm index needs `--index-strategy unsafe-best-match`, otherwise resolution refuses to look across indexes.

Verification that the stack is real on this GPU:

```
vllm 0.34.0
torch 2.13.0+rocm10.0.0
devices 2  AMD Radeon RX 7800 XT
```

...and a chat completion from `Qwen/Qwen3-0.6B` returning a sane sentence ("A tensor is a mathematical object that generalizes the concept of a vector and a matrix..."). Note `llm.chat()` takes `chat_template_kwargs` as its own argument, not inside `SamplingParams`, which raises `TypeError: Unexpected keyword argument` if you try the obvious thing.

Then the actual model:

```bash
uv pip install vllm-gguf-plugin
vllm serve ./Ternary-Bonsai-2.5-27B-Uncensored-Q2_0-mtp.gguf \
  --quantization gguf --max-model-len 4096 \
  --gpu-memory-utilization 0.90 --tokenizer Qwen/Qwen3.5-27B
```

Fails during engine init, before any weight transfer:

```
File ".../vllm_gguf_plugin/gguf_utils.py", line 290, in extract_vocab_size_from_gguf
    reader = gguf.GGUFReader(str(model_path))
File ".../gguf/gguf_reader.py", line 328, in _build_tensors
    raise ve_exc
ValueError: np.uint32(42) is not a valid GGMLQuantizationType
```

Type 42 is the ternary `Q2_0` packing. vLLM cannot even parse the header, so this is not a fixable flag or a kernel-coverage question. Confirming from the source, the plugin's supported types are `Q4_0, Q4_1, Q5_0, Q5_1, Q8_0, Q8_1, Q2_K, Q3_K, Q4_K, Q5_K, Q6_K, Q1_M, Q1_S, Q2_XXS, Q2_XS, Q2_S, Q3_XXS, Q3_S, Q4_XS, Q4_NL`; no ternary type of any spelling appears, and its custom kernels are CUDA sources (`csrc/gguf/*.cuh`) with no HIP build.

Two further blockers would appear even if the type were supported: the plugin has no MTP/speculative path, and the same model in a supported format is bf16 (~54 GB) or a 4-bit derivative (~16 GB) that leaves no room for KV cache on a 16 GB card.

Verdict: vLLM is the wrong engine for this checkpoint. It is not the wrong engine for the GPU.

## References

- [kelsey1337/Ternary-Bonsai-2.5-27B-Uncensored-MTP-GGUF](https://huggingface.co/kelsey1337/Ternary-Bonsai-2.5-27B-Uncensored-MTP-GGUF)
- [AtomicChat/Ternary-Bonsai-2.5-27B-Uncensored-GGUF](https://huggingface.co/AtomicChat/Ternary-Bonsai-2.5-27B-Uncensored-GGUF) — source of the abliteration
- [prism-ml/Ternary-Bonsai-2.5-27B-GGUF](https://huggingface.co/prism-ml/Ternary-Bonsai-2.5-27B-GGUF) — stock packings the repack was built from
- [llama.cpp release b12774](https://github.com/ggml-org/llama.cpp/releases/tag/b12774) — prebuilt Vulkan binaries
- [Unsloth: How to Run MTP Models](https://unsloth.ai/docs/models/mtp) — `--spec-draft-n-max` tuning range, sampling presets for Qwen3.x
- [vLLM GPU installation](https://docs.vllm.ai/en/latest/getting_started/installation/gpu.html) — ROCm wheel index and gfx1101 support
- [vLLM quantized KV cache](https://docs.vllm.ai/en/latest/features/quantization/quantized_kvcache/) and [GGUF support](https://docs.vllm.ai/en/latest/features/quantization/gguf/) — out-of-tree plugin
- [vllm-project/vllm-gguf-plugin](https://github.com/vllm-project/vllm-gguf-plugin) — supported tensor types, CUDA-only kernels
- [vLLM supported models](https://docs.vllm.ai/en/latest/models/supported_models.html) — `Qwen3_5ForConditionalGeneration` is supported, which is why the architecture was not the blocker
