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
| **Total** | **~18 min** |

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

exec "$BIN/llama-server" \
  -m "$MODEL" \
  --host 127.0.0.1 --port "$PORT" \
  -ngl 99 \
  -c "$CTX" \
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

Speculative decoding is worth **1.57x** on decode here and costs ~5% of prompt throughput. The model card claims ~1.65x on a 4090 with 66% acceptance; the speedup tracks acceptance, so a lower-capability machine sees a slightly smaller win. Assorted one-shot chats landed between 61 and 88 tok/s depending on how predictable the answer was (the 75% acceptance on a two-word arithmetic answer pushed it to 88 tok/s).

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

## References

- [kelsey1337/Ternary-Bonsai-2.5-27B-Uncensored-MTP-GGUF](https://huggingface.co/kelsey1337/Ternary-Bonsai-2.5-27B-Uncensored-MTP-GGUF)
- [AtomicChat/Ternary-Bonsai-2.5-27B-Uncensored-GGUF](https://huggingface.co/AtomicChat/Ternary-Bonsai-2.5-27B-Uncensored-GGUF) — source of the abliteration
- [prism-ml/Ternary-Bonsai-2.5-27B-GGUF](https://huggingface.co/prism-ml/Ternary-Bonsai-2.5-27B-GGUF) — stock packings the repack was built from
- [llama.cpp release b12774](https://github.com/ggml-org/llama.cpp/releases/tag/b12774) — prebuilt Vulkan binaries
