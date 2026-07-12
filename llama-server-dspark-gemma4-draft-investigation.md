# Investigating a DSpark Draft Model Swap for llama-server (Gemma4)

**Date:** 2026-07-04
**Host:** fedora (192.168.50.20, AMD RX 7800 XT, ROCm backend)
**Goal:** Swap the MTP speculative-decoding draft model currently used by `llama-server` for a newer "DSpark" draft model, after benchmarking the current setup as a baseline.
**Outcome:** Not possible yet — the only public runtime implementation for DSpark drafts doesn't support Gemma4 (Qwen3-only so far). Production server restored to its original MTP configuration, no downtime beyond the test window.

---

## 1. Audit the existing setup

```bash
ssh moo@fedora "systemctl status llama-server --no-pager -l"
```

Server was running `llama-server` from `/root/llama.cpp` (stock `master`, commit `6c5de1cc8`, 2026-06-30) with:

```
--device ROCm0 -m /root/models/hauhau-gemma4-12b-qat/Gemma4-12B-QAT-Uncensored-HauhauCS-Balanced-Q4_K_M.gguf
--mmproj /root/models/hauhau-gemma4-12b-qat/mmproj-Gemma4-12B-QAT-Uncensored-HauhauCS-Balanced-BF16.gguf
--spec-type draft-mtp
--spec-draft-model /root/models/hauhau-gemma4-12b-qat/mtp-gemma-4-12B-it.gguf
--spec-draft-device ROCm0 --spec-draft-n-max 4 --spec-draft-p-min 0.6
-ngl 99 -fa on -c 262144 --parallel 1 --cache-type-k q4_0 --cache-type-v q4_0
--batch-size 2048 --ubatch-size 1024 --threads 8 --threads-batch 16
--no-mmap --cont-batching --jinja --port 8081
```

This is the MTP (multi-token-prediction) drafter setup documented in an earlier session ([llama-server-gemma4-qat-mtp-swap.md](./llama-server-gemma4-qat-mtp-swap.md)).

---

## 2. Identify what the linked model actually is

The user linked `ankk98/dspark-gemma4-12b-block7-Q4_0-GGUF` on HuggingFace. Checked the HF API:

```bash
curl -s https://huggingface.co/api/models/ankk98/dspark-gemma4-12b-block7-Q4_0-GGUF
```

Key facts from the metadata:
- `architecture: dspark`, `causal: false`
- `base_model: [deepseek-ai/dspark_gemma4_12b_block7, google/gemma-4-12B-it]`
- Single file: `dspark_gemma4_12b_q4pure.gguf` (~1.9 GB)

**This is not a replacement main model** — it's a **draft model** for a different speculative-decoding scheme called **DSpark**, meant to pair with the existing Gemma4-12B target model, same role as the current `mtp-gemma-4-12B-it.gguf`.

The repo's README confirmed usage:

```sh
llama-cli -m gemma-4-12B-it-Q4_0.gguf -md dspark_gemma4_12b_q4pure.gguf \
  --spec-type draft-dspark --spec-draft-n-max 4 -c 512 -ngl 99 -ngld 99
```

and stated it requires **llama.cpp built from `ft-dspark`** (a branch not found anywhere public — see §6).

---

## 3. Baseline benchmark of the current MTP setup

Before touching anything, benchmarked the live production server via its native `/completion` endpoint with deterministic sampling (`temperature: 0, seed: 42`), 300 tokens per run, 3 runs per prompt type. Draft-acceptance stats pulled from the systemd journal (`slot print_timing` log lines).

```bash
curl -s -X POST http://localhost:8081/completion -H 'Content-Type: application/json' \
  -d '{"prompt": "...", "n_predict": 300, "temperature": 0, "seed": 42, "cache_prompt": false, "stream": false}'

sudo journalctl -u llama-server --since '2 minutes ago' --no-pager | grep -iE 'draft|accept'
```

**Results — current MTP draft (`mtp-gemma-4-12B-it.gguf`):**

| Prompt type | Runs (tok/s) | Avg tok/s | Draft accept rate | Mean draft len |
|---|---|---|---|---|
| Prose (BST explanation) | 46.0, 50.2, 53.9 | ~50.0 | 44–58% | 2.7–3.2 |
| Code (fibonacci docstring) | 69.3, 63.3, 72.9 | ~68.5 | 73–89% | 3.8–4.3 |

Code-heavy prompts see much higher draft-acceptance (more predictable token sequences) than free-form prose, as expected for small-drafter speculative decoding.

---

## 4. Build llama.cpp with DSpark support, in an isolated directory

`draft-dspark` isn't in the stock build's `--spec-type` list:

```
--spec-type none,draft-simple,draft-eagle3,draft-mtp,draft-dflash,ngram-simple,...
```

Found the feature via GitHub search — open PR [ggml-org/llama.cpp#25173](https://github.com/ggml-org/llama.cpp/pull/25173) "spec: add DSpark speculative decoding" by `wjinxu`, branch `dspark-upstream` on `wjinxu/llama.cpp`, **not yet merged**.

To avoid touching the working production build, cloned and built the PR branch into a **separate directory**:

```bash
sudo git clone --branch dspark-upstream --single-branch \
  https://github.com/wjinxu/llama.cpp.git /root/llama.cpp-dspark

cd /root/llama.cpp-dspark
sudo cmake -B build -DCMAKE_BUILD_TYPE=Release -DGGML_HIP=ON \
  -DAMDGPU_TARGETS=gfx1101 -DGGML_HIP_ROCWMMA_FATTN=ON \
  -DCMAKE_HIP_COMPILER=/usr/lib64/rocm/llvm/bin/clang++
sudo cmake --build build --config Release -j$(nproc) \
  --target llama-server llama-cli llama-bench
```

(Matched the ROCm/HIP flags — `gfx1101` target — from the existing build's `CMakeCache.txt` to keep it comparable.)

Build succeeded; confirmed `draft-dspark` now appears in `--help`:

```
--spec-type none,draft-simple,draft-eagle3,draft-mtp,draft-dflash,draft-dspark,ngram-simple,...
```

Downloaded the draft model in parallel:

```bash
sudo mkdir -p /root/models/dspark-gemma4-12b
sudo curl -L -o /root/models/dspark-gemma4-12b/dspark_gemma4_12b_q4pure.gguf \
  'https://huggingface.co/ankk98/dspark-gemma4-12b-block7-Q4_0-GGUF/resolve/main/dspark_gemma4_12b_q4pure.gguf'
```

---

## 5. Test load — fails immediately

Only one GPU with enough VRAM (17 GB total, ~13.7 GB already used by the running server, ~3.45 GB free) — not enough to run a second full 12B model alongside it. Stopped the production service for the test window:

```bash
ssh moo@fedora "sudo systemctl stop llama-server"
```

Launched the new build manually on an alternate port, same flags as production but `--spec-type draft-dspark` / `--spec-draft-model dspark_gemma4_12b_q4pure.gguf`:

```
0.10.743.329 I srv    load_model: loading model '...Gemma4-12B-QAT...Q4_K_M.gguf'
0.11.299.993 E llama_model_load: error loading model: missing tensor 'blk.0.attn_v.weight'
0.11.299.999 E llama_model_load_from_file_impl: failed to load model
0.11.300.052 W srv    load_model: [spec] failed to measure draft model memory: failed to load model
...
0.13.266.070 E srv    load_model: failed to load draft model, '/root/models/dspark-gemma4-12b/dspark_gemma4_12b_q4pure.gguf'
```

### Isolating the failure

Ruled out a corrupted download or a broken build:

- `md5sum` on the target model file completed cleanly (no I/O errors, file intact).
- `diff`'d every loader-relevant source file (`llama-model.cpp`, `llama-model-loader.{cpp,h}`, `llama-arch.{cpp,h}`, `ggml.c`, `gguf.cpp`) between `/root/llama.cpp` (master) and `/root/llama.cpp-dspark` — differences were **purely additive** (new `LLM_ARCH_DSPARK` enum/switch cases), nothing touching existing Gemma4 tensor mapping.
- Loaded the **target** Gemma4 model standalone (CPU-only, no `-md`, no `--spec-type`) on the new build — succeeded (ran past the point where it previously failed in <1s, kept running for 4+ minutes of CPU inference with no error).
- Loaded the **draft** file standalone (CPU-only, no target model at all):

```bash
sudo /root/llama.cpp-dspark/build/bin/llama-cli \
  -m /root/models/dspark-gemma4-12b/dspark_gemma4_12b_q4pure.gguf -p 'hi' -n 1 -ngl 0
```

```
0.11.071.588 E llama_model_load: error loading model: missing tensor 'blk.0.attn_v.weight'
...
Failed to load the model
```

**Confirmed: the draft GGUF itself fails to load, independent of speculative decoding or the target model.** The build's `dspark` architecture loader can't parse this file's tensor layout at all.

---

## 6. Root cause (found via GitHub PR discussion + web search)

Read through the comment thread on [PR #25173](https://github.com/ggml-org/llama.cpp/pull/25173):

> **wjinxu** (PR author), 2026-07-01, replying to a request to also cover DeepSeek-V4:
> "DeepSeek hasn't open-sourced the DSpark weights for DeepSeek-V4 though — only the Qwen3 and Gemma4 drafts are released. So **this PR covers Qwen3 for now, and I'll add Gemma4 as a small follow-up.**"

As of the last activity on the PR (2026-07-02), that Gemma4 follow-up had not landed. The PR's converter code only adds a `Qwen3DSparkModel` converter (`conversion/qwen.py`) — no Gemma4-specific tensor mapping exists anywhere in this branch.

The HF model card for `ankk98/dspark-gemma4-12b-block7-Q4_0-GGUF` claims it was "Converted with llama.cpp `ft-dspark`" — a branch name that doesn't match `dspark-upstream` and isn't findable in any public fork (checked `ankk98`'s own GitHub repos — no `llama.cpp` fork present). It was very likely converted with a private/local branch the uploader never published.

**Bottom line: no publicly available llama.cpp build today can load this specific file.** The only implementation of DSpark decoding that exists in the open supports Qwen3 drafts only.

---

## 7. Cleanup / restore production

```bash
ssh moo@fedora "sudo pkill -f 'llama.cpp-dspark/build/bin/llama-server'"
ssh moo@fedora "sudo systemctl start llama-server"
```

Confirmed healthy and back on MTP speculative decoding:

```bash
curl -s http://localhost:8081/health          # {"status":"ok"}
curl -s http://localhost:8081/slots | jq '.[0].speculative'   # true
```

Left in place for when Gemma4 DSpark support lands upstream:
- `/root/llama.cpp-dspark` — built binaries (`llama-server`, `llama-cli`, `llama-bench`) with working `draft-dspark` support (Qwen3 drafts only, currently).
- `/root/models/dspark-gemma4-12b/dspark_gemma4_12b_q4pure.gguf` — the (currently unusable) Gemma4 draft file, in case a future build can load it without re-downloading.

---

## 8. Follow-up: watching PR #25173

Set up a recurring check on [ggml-org/llama.cpp#25173](https://github.com/ggml-org/llama.cpp/pull/25173) for Gemma4 DSpark support landing (either merged upstream, or a comment/commit adding Gemma4 conversion support). When it lands: re-clone/rebuild `/root/llama.cpp-dspark` from the updated branch (or `master` if merged), reconvert or re-download the Gemma4 draft GGUF if the tensor format changed, and re-run the same standalone-load test from §5 before attempting the swap again.

**Baseline to beat**, from §3 (current MTP draft): ~50 tok/s prose / ~68.5 tok/s code, 44–89% draft acceptance depending on prompt type.

---

## 9. Update (2026-07-12): removed the leftover build and model files

Decided the files noted as "left in place" in §7 weren't worth keeping around — the build directory is quick to reproduce, and the daily [PR watch](#8-follow-up-watching-pr-25173) routine is still active and will flag it if Gemma4 support ever lands, at which point everything below gets re-fetched anyway.

```bash
ssh moo@fedora "sudo rm -rf /root/llama.cpp-dspark"                      # 1.4G, cloned repo + build
ssh moo@fedora "sudo rm -rf /root/models/dspark-gemma4-12b"              # 1.9G, the unusable draft GGUF
```

Both removed. `/root/models/` on fedora now only has the active model directories (`hauhau-gemma4-12b-qat`, `huihui-gemma-4-12b-abliterated`, `mia-gemmable-4-12b-mtp`). Production `llama-server` was untouched by this cleanup — it was already back on its original MTP setup since §7.

**If/when the PR watch fires:** re-clone `wjinxu/llama.cpp` (branch `dspark-upstream`, or `master` if merged) into `/root/llama.cpp-dspark`, rebuild with the same ROCm/HIP flags as §4, and re-download the Gemma4 draft GGUF from `ankk98/dspark-gemma4-12b-block7-Q4_0-GGUF` (or whatever repo the landed support actually targets) before repeating the standalone-load test in §5.
