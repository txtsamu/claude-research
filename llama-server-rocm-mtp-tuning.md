# llama-server on ROCm: Fixing MTP Crash, Migrating from Vulkan, and Performance Tuning

**Hardware:** AMD Ryzen 9 7950X + RX 7800 XT (gfx1101, 16 GB VRAM)  
**OS:** Fedora 43  
**Model:** Gemma 4 12B QAT (HauhauCS) + MTP draft + mmproj  
**llama.cpp version:** b9844

---

## Problem: llama-server Crash Loop

The service was restarting every ~10 seconds with an abort from ggml's backend scheduler:

```
/root/llama.cpp/ggml/src/ggml-backend.cpp:898:
pre-allocated tensor (cache_k_l46) in a buffer (Vulkan0)
that cannot run the operation (NONE)
```

**Root cause:** Gemma 4's MTP (Multi-Token Prediction) architecture **shares KV cache tensors** between the main model and the draft model. Both must run on the **same device and same backend**. The original config put the draft model on `Vulkan1` (the iGPU) while the main model was on `Vulkan0` (RX 7800 XT). Cross-device KV sharing creates graph nodes with operation type `NONE` — no backend can schedule them.

A secondary compounding issue: the build had both Vulkan and HIP compiled in simultaneously. When a single `--device` flag is passed without `--spec-draft-device`, the auto-device selector can pick different backends for the two models even on the same physical GPU.

**References:**
- [Issue #24492 — Gemma 4 31B MTP crashes on Vulkan, pre-allocated tensor cannot run operation NONE](https://github.com/ggml-org/llama.cpp/issues/24492)
- [Issue #24366 — Gemma MTP: Tensor in buffer cannot run (NONE)](https://github.com/ggml-org/llama.cpp/issues/24366)

---

## Fix 1: Migrate from Vulkan to ROCm

### Why ROCm instead of just fixing the device flag

Vulkan on RDNA3 has known limitations with flash attention and quantized KV cache. Switching to ROCm (HIP backend) gives a cleaner, more stable path and is the backend llama.cpp developers primarily target for AMD hardware.

### Check ROCm is installed

```bash
hipcc --version
rocminfo | grep -E '(Name|gfx)'
ls /usr/lib64/cmake/hip/hip-config.cmake
```

On Fedora, ROCm installs to system paths — no `/opt/rocm`. The cmake prefix is `/usr`.

### Identify GPU device numbers

```bash
/root/llama.cpp/build/bin/llama-server --list-devices
```

On this system:
- `ROCm0` = AMD Radeon RX 7800 XT (16 GB) — dGPU
- `ROCm1` = AMD Ryzen 9 7950X iGPU — integrated

> **Note:** The vulkaninfo order may differ from llama-server's ROCm numbering. Always use `--list-devices` to confirm rather than relying on comments in scripts.

### Update llama.cpp to latest stable

```bash
cd /root/llama.cpp
git fetch origin
git tag --sort=-version:refname | grep '^b' | head -5
git checkout b9844   # latest stable at time of writing
```

### Build with ROCm (HIP) backend

```bash
rm -rf /root/llama.cpp/build

cmake -S /root/llama.cpp -B /root/llama.cpp/build \
  -DCMAKE_BUILD_TYPE=Release \
  -DCMAKE_PREFIX_PATH=/usr \
  -DGGML_HIP=ON \
  -DAMDGPU_TARGETS=gfx1101 \
  -DGGML_NATIVE=ON \
  -DLLAMA_BUILD_SERVER=ON

cmake --build /root/llama.cpp/build --config Release -j$(nproc)
```

**Key flags:**
- `-DGGML_HIP=ON` — enables the HIP/ROCm backend (do NOT combine with `-DGGML_VULKAN=ON`, that causes the cross-backend crash)
- `-DAMDGPU_TARGETS=gfx1101` — compile kernels only for the RX 7800 XT; add `gfx1036` if you also need the iGPU
- `-DCMAKE_PREFIX_PATH=/usr` — tells cmake where to find `hip-config.cmake` on Fedora

---

## Fix 2: MTP Requires Both Models on the Same Device

In `/usr/local/bin/llama-server-start.sh`, both `--device` and `--spec-draft-device` must point to the same ROCm device:

```bash
exec /root/llama.cpp/build/bin/llama-server \
  --device ROCm0 \
  --spec-draft-device ROCm0 \   # ← must match --device, not ROCm1
  --spec-type draft-mtp \
  ...
```

Gemma 4 MTP layers 0–3 of the draft model share KV cache with layers 46–47 of the main model. If the models are on different devices, the scheduler sees a pre-allocated GPU tensor with no operable backend → `NONE` crash.

---

## Fix 3: Model Alias for OpenWebUI

Without an alias, llama-server exposes the full file path as the model ID in `/v1/models`, which OpenWebUI displays verbatim:

```
/root/models/hauhau-gemma4-12b-qat/Gemma4-12B-QAT-Uncensored-HauhauCS-Balanced-Q4_K_M.gguf
```

Add `--alias` to the server command:

```bash
--alias Gemma4-12B-QAT-HauhauCS
```

Verify:
```bash
curl -s http://localhost:8081/v1/models | python3 -c \
  'import sys,json; [print(m["id"]) for m in json.load(sys.stdin)["data"]]'
# Gemma4-12B-QAT-HauhauCS
```

---

## Fix 4: GPU Clock Stability with DPM Profile

With ROCm in the default `auto` DPM mode, the amdgpu driver is conservative about boosting clocks. This causes fluctuating power draw and inconsistent performance compared to Vulkan (which uses Mesa RADV and boosts more aggressively).

### Available DPM modes

| Mode | Clocks | Use case |
|---|---|---|
| `auto` | Dynamic (default) | General desktop |
| `low` | Minimum always | Debugging |
| `high` / `profile_peak` | Maximum always | Maximum throughput |
| `profile_standard` | Moderate sustained boost | LLM inference — good balance |
| `manual` | User-controlled via sysfs | Fine-grained tuning |

### Apply at service start (persistent)

Add `ExecStartPre` to `/etc/systemd/system/llama-server.service`:

```ini
[Service]
ExecStartPre=/bin/sh -c "echo profile_standard > /sys/class/drm/card0/device/power_dpm_force_performance_level"
ExecStart=/usr/local/bin/llama-server-start.sh
```

```bash
systemctl daemon-reload
systemctl restart llama-server
# Verify:
cat /sys/class/drm/card0/device/power_dpm_force_performance_level
# profile_standard
```

---

## Performance Tuning

### ROCm vs Vulkan performance gap

ROCm token generation on RDNA3 is consistently ~20% slower than Vulkan due to less-optimized HIP kernels for consumer GPUs. This is a known upstream gap with no easy fix — ROCm's advantage is stability and correct MTP support.

**Reference:** [Issue #20934 — ROCm significantly lower token generation vs Vulkan on RX 7900 XTX](https://github.com/ggml-org/llama.cpp/issues/20934)

### Parameter tuning

**Before (baseline with Vulkan, broken MTP):** 17.7 tok/s  
**After all tuning below:** 45–47 tok/s

Key changes and why:

```bash
# spec-draft-n-max: 3 → 4
# Mean accepted tokens/round was 2.74 out of 3 — hitting the ceiling
--spec-draft-n-max 4

# spec-draft-p-min: (missing) → 0.6
# Filter low-confidence drafts before main model verification
# Slightly reduces mean accepted len but raises effective acceptance quality
--spec-draft-p-min 0.6

# cache-type-k: q4_0 (best VRAM) or q8_0 (best quality)
# q8_0+q8_0 reportedly causes 0% MTP acceptance in some builds — test both
# q4_0/q4_0 saves ~3.5 GB VRAM vs q8_0/q8_0 with minor acceptance drop
--cache-type-k q4_0
--cache-type-v q4_0   # requires -fa on for V quantization

# ubatch-size: 512 → 1024
# Larger physical batch improves GPU utilization during prefill
--ubatch-size 1024

# threads: 16 → 8, threads-batch: 32 → 16
# With ROCm offloading compute to GPU, excess CPU threads create dispatch contention
--threads 8
--threads-batch 16
```

**References:**
- [Gemma 4 MTP Tuning — Pushing Toward 120 tok/s](https://knightli.com/en/2026/06/12/gemma-4-mtp-assistant-llama-cli-speedup/)
- [How to Get 2x Speed on Gemma 4 with MTP in llama.cpp](https://dev.to/everylocalai/how-to-get-2x-speed-on-gemma-4-with-multi-token-prediction-in-llamacpp-1b8e)
- [Why MTP doesn't speed up your llama.cpp inference](https://dev.to/alanwest/why-mtp-doesnt-speed-up-your-llamacpp-inference-and-how-to-actually-fix-it-2m2m)

### MTP acceptance rate check

After each config change, run a test inference and check:

```bash
journalctl -u llama-server -n 10 --no-pager | grep "print_timing"
# Look for: draft acceptance = 0.54 (38 accepted / 70 generated), mean len = 2.36
```

Healthy acceptance rate: 50–65%. Below 40% means MTP is hurting rather than helping. Above 70% means you can try increasing `--spec-draft-n-max`.

---

## Build with rocWMMA (Flash Attention Acceleration)

rocWMMA provides matrix multiply acceleration for flash attention on RDNA3. Gains are most visible at long context (pp8192+). For short prompts (<512 tokens) the difference is within noise.

**Benchmark at pp8192/tg8192 (from llm-tracker.info):**
- Without rocWMMA: 600 t/s prompt, 56 t/s generation
- With rocWMMA: 2175 t/s prompt, 69 t/s generation (3.6× faster prefill)

### Install rocwmma-devel

```bash
dnf install rocwmma-devel
```

### Rebuild with WMMA flag

```bash
rm -rf /root/llama.cpp/build

cmake -S /root/llama.cpp -B /root/llama.cpp/build \
  -DCMAKE_BUILD_TYPE=Release \
  -DCMAKE_PREFIX_PATH=/usr \
  -DGGML_HIP=ON \
  -DAMDGPU_TARGETS=gfx1101 \
  -DGGML_HIP_ROCWMMA_FATTN=ON \
  -DGGML_NATIVE=ON \
  -DLLAMA_BUILD_SERVER=ON

cmake --build /root/llama.cpp/build --config Release -j$(nproc)

# Verify flag
grep 'ROCWMMA' /root/llama.cpp/build/CMakeCache.txt
# GGML_HIP_ROCWMMA_FATTN:BOOL=ON
```

> **Note for gfx1100 (RX 7900 XTX):** Some reports suggest rocWMMA may hurt performance on gfx1100. Test with and without. On gfx1101 (RX 7800 XT) results are positive for long-context workloads.

**Reference:** [AMD GPUs — llm-tracker.info](https://llm-tracker.info/howto/AMD-GPUs)

---

## VRAM Budget

With 262144 context, q4_0 K+V, on a 16 GB card:

| Component | VRAM |
|---|---|
| Main model (Q4_K_M 12B) | ~7.0 GB |
| KV cache (262144 ctx, q4_0/q4_0) | ~3.5 GB |
| MTP draft model (Q8_0) | ~242 MB |
| mmproj (BF16) | ~168 MB |
| **Total** | **~11 GB (~68%)** |

Switching to q8_0/q8_0 adds ~3.5 GB (→ 84%). Use q4_0/q4_0 if VRAM is tight, q8_0/q8_0 if you have headroom and want better draft acceptance.

---

## Final `/usr/local/bin/llama-server-start.sh`

```bash
#!/bin/bash
# HauhauCS Gemma4-12B QAT Uncensored Balanced Q4_K_M + MTP + mmproj
# ROCm backend on RDNA3 (ROCm0 = RX 7800 XT; ROCm1 = Raphael iGPU)

export GGML_AVX512=1
export OMP_NUM_THREADS=32
export OMP_PROC_BIND=close
export OMP_PLACES=threads

exec /root/llama.cpp/build/bin/llama-server \
  --device ROCm0 \
  -m /root/models/hauhau-gemma4-12b-qat/Gemma4-12B-QAT-Uncensored-HauhauCS-Balanced-Q4_K_M.gguf \
  --mmproj /root/models/hauhau-gemma4-12b-qat/mmproj-Gemma4-12B-QAT-Uncensored-HauhauCS-Balanced-BF16.gguf \
  --spec-type draft-mtp \
  --spec-draft-model /root/models/hauhau-gemma4-12b-qat/mtp-gemma-4-12B-it.gguf \
  --spec-draft-device ROCm0 \
  --spec-draft-n-max 4 \
  --spec-draft-p-min 0.6 \
  -ngl 99 \
  -fa on \
  -c 262144 \
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
  --dry-multiplier 0.8 \
  --dry-base 1.75 \
  --dry-allowed-length 2 \
  --dry-penalty-last-n -1 \
  --poll 50 \
  --prio 3 \
  --metrics \
  --host 0.0.0.0 \
  --alias Gemma4-12B-QAT-HauhauCS \
  --port 8081
```

---

## Final `/etc/systemd/system/llama-server.service`

```ini
[Unit]
Description=Gemma4-12B-QAT-Uncensored-HauhauCS-Balanced-Q4_K_M
After=network.target

[Service]
User=root
ExecStartPre=/bin/sh -c "echo profile_standard > /sys/class/drm/card0/device/power_dpm_force_performance_level"
ExecStart=/usr/local/bin/llama-server-start.sh
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

---

## Results Summary

| | Before | After |
|---|---|---|
| llama.cpp version | b9555 | b9844 |
| Backend | Vulkan (crashing) | ROCm/HIP + rocWMMA |
| MTP status | Crash loop | Working, 54% acceptance |
| Token gen speed | 17.7 tok/s | ~45 tok/s |
| VRAM usage | ~70% | ~68% (q4_0/q4_0) |
| Model alias in OpenWebUI | Full path | `Gemma4-12B-QAT-HauhauCS` |
| GPU clock management | `auto` (fluctuating) | `profile_standard` (stable) |

---

## References

- [Issue #24492 — Gemma 4 31B MTP crashes on Vulkan backend](https://github.com/ggml-org/llama.cpp/issues/24492)
- [Issue #24366 — Gemma MTP: Tensor in buffer cannot run (NONE)](https://github.com/ggml-org/llama.cpp/issues/24366)
- [Issue #20934 — ROCm significantly lower token generation vs Vulkan on RX 7900 XTX](https://github.com/ggml-org/llama.cpp/issues/20934)
- [Discussion #15021 — Performance of llama.cpp on AMD ROCm (HIP)](https://github.com/ggml-org/llama.cpp/discussions/15021)
- [Discussion #10611 — Recent changes to scheduler leading to pre-allocated tensor error](https://github.com/ggml-org/llama.cpp/discussions/10611)
- [Gemma 4 MTP Tuning: Pushing Toward 120 tok/s](https://knightli.com/en/2026/06/12/gemma-4-mtp-assistant-llama-cli-speedup/)
- [How to Get 2x Speed on Gemma 4 with MTP in llama.cpp](https://dev.to/everylocalai/how-to-get-2x-speed-on-gemma-4-with-multi-token-prediction-in-llamacpp-1b8e)
- [Why MTP doesn't speed up your llama.cpp inference](https://dev.to/alanwest/why-mtp-doesnt-speed-up-your-llamacpp-inference-and-how-to-actually-fix-it-2m2m)
- [AMD GPUs — llm-tracker.info (rocWMMA benchmarks)](https://llm-tracker.info/howto/AMD-GPUs)
- [ROCm docs — llama.cpp on ROCm installation](https://rocm.docs.amd.com/projects/llama-cpp/en/docs-26.02/install/llama-cpp-install.html)
