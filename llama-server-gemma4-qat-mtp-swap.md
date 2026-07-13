---
type: how-to
tags: [llama-server, gemma4, mtp, qat, hermes]
created: 2026-06-24
last_verified: 2026-06-24
status: current
---

# Swapping llama-server to Gemma 4 QAT + MTP + Tuning

**Date:** 2026-06-24  
**Host:** fedora (192.168.50.20, AMD RX 7800 XT, Vulkan backend)  
**Goal:** Replace existing Gemma 4 abliterated model with a QAT variant that includes MTP speculative decoding, tune it, and wire it into Hermes.

---

## 1. Audit the existing setup

SSH to fedora and check what is running:

```bash
ssh moo@fedora "ps aux | grep llama-server | grep -v grep"
```

Find the service file:

```bash
ssh moo@fedora "find /etc/systemd/system -name 'llama*'"
ssh moo@fedora "cat /etc/systemd/system/llama-server.service"
ssh moo@fedora "cat /usr/local/bin/llama-server-start.sh"
```

Note: the actual launch parameters live in the start script referenced by `ExecStart`.

---

## 2. Find a suitable model on HuggingFace

Search criteria: **Gemma 4 12B + QAT (Quantization-Aware Training) + MTP (Multi-Token Prediction) drafter**.

Model chosen: [HauhauCS/Gemma4-12B-QAT-Uncensored-HauhauCS-Balanced](https://huggingface.co/HauhauCS/Gemma4-12B-QAT-Uncensored-HauhauCS-Balanced)

Files in the repo:

| File | Size | Purpose |
|------|------|---------|
| `Gemma4-12B-QAT-Uncensored-HauhauCS-Balanced-Q4_K_M.gguf` | 6.9 GB | Main model |
| `mmproj-Gemma4-12B-QAT-Uncensored-HauhauCS-Balanced-BF16.gguf` | 168 MB | Vision multimodal projector |
| `mtp-gemma-4-12B-it.gguf` | 242 MB | MTP speculative decoding drafter |

**What QAT means:** The model weights were quantized during training, not after — preserving near-BF16 quality at Q4 size (~3× less VRAM than BF16).

**What MTP means:** A small draft head predicts several tokens ahead; the main model verifies them in parallel. Accepted drafts are free tokens — output is mathematically identical to non-MTP inference.

---

## 3. Download the model

Use the `hf` CLI (newer replacement for `huggingface-cli`) on the target machine. Download all `.gguf` files:

```bash
ssh moo@fedora "sudo mkdir -p /root/models/hauhau-gemma4-12b-qat && \
  sudo hf download HauhauCS/Gemma4-12B-QAT-Uncensored-HauhauCS-Balanced \
    --local-dir /root/models/hauhau-gemma4-12b-qat \
    --include '*.gguf'"
```

Verify:

```bash
ssh moo@fedora "ls -lh /root/models/hauhau-gemma4-12b-qat/"
```

Expected output:

```
6.9G  Gemma4-12B-QAT-Uncensored-HauhauCS-Balanced-Q4_K_M.gguf
168M  mmproj-Gemma4-12B-QAT-Uncensored-HauhauCS-Balanced-BF16.gguf
242M  mtp-gemma-4-12B-it.gguf
```

> **Note:** If your machine doesn't have `hf` installed: `pip install -U huggingface_hub[hf_transfer]`

---

## 4. Update the start script

Edit `/usr/local/bin/llama-server-start.sh` (or wherever your ExecStart script lives):

```bash
sudo tee /usr/local/bin/llama-server-start.sh > /dev/null << 'EOF'
#!/bin/bash
# Gemma4-12B-QAT-Uncensored-HauhauCS-Balanced Q4_K_M + mmproj BF16 + MTP
# Vulkan backend on RDNA3 (RX 7800 XT = Vulkan1; Vulkan0 is the Raphael iGPU)

export GGML_AVX512=1
export OMP_NUM_THREADS=32
export OMP_PROC_BIND=close
export OMP_PLACES=threads

exec /root/llama.cpp/build/bin/llama-server \
  --device Vulkan1 \
  -m /root/models/hauhau-gemma4-12b-qat/Gemma4-12B-QAT-Uncensored-HauhauCS-Balanced-Q4_K_M.gguf \
  --mmproj /root/models/hauhau-gemma4-12b-qat/mmproj-Gemma4-12B-QAT-Uncensored-HauhauCS-Balanced-BF16.gguf \
  --spec-type draft-mtp \
  --spec-draft-model /root/models/hauhau-gemma4-12b-qat/mtp-gemma-4-12B-it.gguf \
  --spec-draft-device Vulkan1 \
  --spec-draft-n-max 3 \
  -ngl 99 \
  -fa on \
  -c 262144 \
  --parallel 1 \
  --cache-type-k q4_0 \
  --cache-type-v q8_0 \
  --batch-size 2048 \
  --ubatch-size 512 \
  --threads 16 \
  --threads-batch 32 \
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
  --port 8081
EOF
sudo chmod +x /usr/local/bin/llama-server-start.sh
```

Update the service unit description to match the model name:

```bash
sudo sed -i 's/Description=.*/Description=Gemma4-12B-QAT-Uncensored-HauhauCS-Balanced-Q4_K_M/' \
  /etc/systemd/system/llama-server.service
sudo systemctl daemon-reload
sudo systemctl restart llama-server
```

Confirm it is running:

```bash
sudo journalctl -u llama-server -n 10 --no-pager
```

Look for: `server is listening on http://0.0.0.0:8081`

---

## 5. Benchmark and tune MTP `spec-draft-n-max`

The guide at https://unsloth.ai/docs/models/mtp recommends trying values 1–6 and picking whichever is fastest for your hardware.

### Benchmark script

Save as `/tmp/mtp_bench.sh` on the target machine:

```bash
#!/bin/bash
PROMPT='{"messages":[{"role":"user","content":"Write a detailed explanation of how neural networks work, covering backpropagation, gradient descent, and activation functions."}],"max_tokens":300,"stream":false}'
SCRIPT=/usr/local/bin/llama-server-start.sh

bench_run() {
  local n=$1
  sudo sed -i "s/--spec-draft-n-max [0-9]*/--spec-draft-n-max $n/" $SCRIPT
  sudo systemctl restart llama-server
  # wait for server ready
  for i in $(seq 1 30); do
    sleep 2
    curl -sf http://localhost:8081/health | grep -q '"status":"ok"' && break
  done
  # warm-up
  curl -s -X POST http://localhost:8081/v1/chat/completions \
    -H "Content-Type: application/json" -d "$PROMPT" > /dev/null
  # 3 timed runs, average
  total=0
  for i in 1 2 3; do
    tps=$(curl -s -X POST http://localhost:8081/v1/chat/completions \
      -H "Content-Type: application/json" -d "$PROMPT" \
      | python3 -c "import json,sys; d=json.load(sys.stdin); u=d.get('usage',{}); t=d.get('timings',{}); print(u.get('completion_tokens',0)/max(t.get('predicted_ms',1)/1000,0.001))")
    total=$(python3 -c "print($total + $tps)")
  done
  avg=$(python3 -c "print(f'{$total/3:.1f}')")
  echo "n-max=$n  avg tok/s: $avg"
}

for n in 1 2 3 4 5 6; do
  bench_run $n
done
```

Run it:

```bash
sudo bash /tmp/mtp_bench.sh
```

### Results (RX 7800 XT, Vulkan, Gemma 4 12B QAT)

| n-max | avg tok/s |
|-------|-----------|
| 1 | 80.6 |
| 2 | 86.5 |
| **3** | **93.8 ← winner** |
| 4 | 86.2 |
| 5 | 88.5 |
| 6 | 85.3 |

**Optimal value: `--spec-draft-n-max 3`**

Set it and restart:

```bash
sudo sed -i 's/--spec-draft-n-max [0-9]*/--spec-draft-n-max 3/' /usr/local/bin/llama-server-start.sh
sudo systemctl restart llama-server
```

---

## 6. Check MTP acceptance rates by task type

The completions response includes `draft_n` and `draft_n_accepted` in the `timings` field, giving the acceptance rate per request.

Quick check:

```bash
curl -s -X POST http://localhost:8081/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"messages":[{"role":"user","content":"Write a Python quicksort."}],"max_tokens":200,"stream":false,"seed":42}' \
  | python3 -c "
import json, sys
d = json.load(sys.stdin)
t = d.get('timings', {})
dn = t.get('draft_n', 0)
da = t.get('draft_n_accepted', 0)
rate = da/dn*100 if dn else 0
print(f'draft accept: {da}/{dn} ({rate:.0f}%)')
print(f'tok/s: {d[\"usage\"][\"completion_tokens\"] / max(t.get(\"predicted_ms\",1)/1000, 0.001):.1f}')
"
```

### Acceptance rates observed (n-max=3, RX 7800 XT)

| task | tok/s | acceptance |
|------|-------|------------|
| code (Python) | 121.5 | 93% |
| general text | 102.2 | 73% |
| translation | 87.0 | 55% |
| math | 71.2 | 38% |
| bash scripts | 69.9 | 36% |

**Key point:** Low acceptance does NOT affect output quality — speculative decoding only uses verified tokens. Low acceptance just means less speedup for those task types.

The MTP drafter is the stock base-IT drafter from Unsloth. Acceptance rates on structured output (bash, math) are lower because the HauhauCS fine-tune shifted token probabilities away from the base model the drafter was trained on.

---

## 7. Check for repetition loops

A common failure mode with fine-tuned models. Test using n-gram duplicate scoring across prompt types:

```python
#!/usr/bin/env python3
# Save as reptest.py, run on the target machine
import json, urllib.request
from collections import Counter

def rep_score(text, n=8):
    """Fraction of duplicate n-grams. >0.3 = looping, >0.1 = warn."""
    words = text.split()
    if len(words) < n * 2:
        return 0.0
    ngrams = [tuple(words[i:i+n]) for i in range(len(words) - n)]
    c = Counter(ngrams)
    dupes = sum(v - 1 for v in c.values() if v > 1)
    return dupes / max(len(ngrams), 1)

def check(label, prompt, n_predict=500):
    body = json.dumps({
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": n_predict, "stream": False
    }).encode()
    req = urllib.request.Request(
        "http://localhost:8081/v1/chat/completions",
        data=body, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=120) as r:
        d = json.loads(r.read())
    text = d["choices"][0]["message"]["content"]
    score = rep_score(text)
    status = "LOOP" if score > 0.3 else ("WARN" if score > 0.1 else "OK  ")
    print(f"[{status}] {label:<22} rep={score:.3f}  tokens={len(text.split())}")
    if score > 0.1:
        print(f"       tail: ...{text[-300:]!r}")

check("long story",      "Write a long detailed story about a dragon who discovers a hidden library in a mountain cave.", 600)
check("python scraper",  "Write a complete Python web scraper using requests and BeautifulSoup.", 500)
check("50 lang list",    "List 50 different programming languages with a one-sentence description of each.", 700)
check("sequence cont",   "Continue: A=1, B=2, C=3, D=4, E=5, F=6, G=7, H=8, I=9, J=10,", 400)
check("bash sysmon",     "Write a bash script for system monitoring: CPU, memory, disk, network, processes.", 500)
check("math proof",      "Solve step by step: snail climbs 3m/day, slides 2m/night. Days to escape a 20m well?", 300)
check("JSON schema",     "Generate a complete JSON schema for a library REST API with books, authors, members, loans.", 500)
```

```bash
python3 reptest.py
```

### Results (HauhauCS Gemma4 QAT)

```
[OK  ] long story             rep=0.000  tokens=461
[OK  ] python scraper         rep=0.000  tokens=233
[OK  ] 50 lang list           rep=0.000  tokens=449
[OK  ] sequence cont          rep=0.000  tokens=141
[OK  ] bash sysmon            rep=0.005  tokens=217
[OK  ] math proof             rep=0.000  tokens=192
[OK  ] JSON schema            rep=0.032  tokens=196
```

All clean. JSON schema 0.032 is expected structural repetition in schema boilerplate, not a loop.

The `--dry-multiplier` + `--repeat-penalty` + `--repeat-last-n -1` flags in the start script prevent loops from forming.

---

## 8. Update Hermes auxiliary config

Hermes uses the local llama-server for auxiliary tasks (vision, web extract, compression, session search, title generation). Update the model name in `~/.hermes/config.yaml`:

```bash
sed -i 's/gemma-4-12B-it-qat-q4_0-unquantized-heretic-Q4_0\.gguf/Gemma4-12B-QAT-Uncensored-HauhauCS-Balanced-Q4_K_M.gguf/g' \
  ~/.hermes/config.yaml
```

Or if updating from a different previous model name, replace `gemma-4-12B-it-qat-q4_0-unquantized-heretic-Q4_0\.gguf` with your old model filename.

Verify the 5 affected sections:

```bash
grep -n "model:" ~/.hermes/config.yaml | grep -i "hauhau\|gguf"
```

Restart hermes-gateway:

```bash
systemctl restart hermes-gateway.service
systemctl is-active hermes-gateway.service
```

---

## 9. Enable reasoning mode

Gemma 4 supports chain-of-thought reasoning via `<|channel>thought` tags. The start script ships with `--reasoning off` — flip it to `on`:

```bash
sudo sed -i 's/--reasoning off/--reasoning on/' /usr/local/bin/llama-server-start.sh
sudo systemctl restart llama-server
sleep 6 && systemctl is-active llama-server
```

Verify reasoning is working — the response should have a `reasoning_content` field separate from `content`:

```bash
curl -s -X POST http://localhost:8081/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"messages":[{"role":"user","content":"What is 17 * 23? Think step by step."}],"max_tokens":300,"stream":false}' \
  | python3 -c "
import json,sys
d=json.load(sys.stdin)
m=d['choices'][0]['message']
print('reasoning_content:', m.get('reasoning_content','')[:200])
print('content:', m.get('content','')[:200])
"
```

Available flags for reference:

| flag | values | effect |
|------|--------|--------|
| `--reasoning` | `on / off / auto` | force enable/disable or detect from template |
| `--reasoning-format` | `none / deepseek / deepseek-legacy` | where thought tags land in the response |
| `--reasoning-budget` | `-1 / 0 / N` | token budget for thinking (`-1` = unlimited) |

---

## 10. Strip mmproj to recover VRAM

If you loaded the model with `--mmproj` but don't need vision on that instance (e.g. you have a dedicated vision model elsewhere), removing it frees the projector weight from VRAM.

**Do NOT use `sed -i` to remove a single line from a multi-line `exec` block** — the backslash continuations will break the entire command and the service will silently fail.

Instead, rewrite the script in full without the `--mmproj` lines:

```bash
sudo tee /usr/local/bin/llama-server-start.sh > /dev/null << 'EOF'
#!/bin/bash
# HauhauCS Gemma4-12B QAT Uncensored Balanced Q4_K_M + MTP (no mmproj)
export GGML_AVX512=1
export OMP_NUM_THREADS=32
export OMP_PROC_BIND=close
export OMP_PLACES=threads

exec /root/llama.cpp/build/bin/llama-server \
  --device Vulkan1 \
  -m /root/models/hauhau-gemma4-12b-qat/Gemma4-12B-QAT-Uncensored-HauhauCS-Balanced-Q4_K_M.gguf \
  --spec-type draft-mtp \
  --spec-draft-model /root/models/hauhau-gemma4-12b-qat/mtp-gemma-4-12B-it.gguf \
  --spec-draft-device Vulkan1 \
  --spec-draft-n-max 3 \
  -ngl 99 -fa on -c 262144 --parallel 1 \
  --cache-type-k q4_0 --cache-type-v q8_0 \
  --batch-size 2048 --ubatch-size 512 \
  --threads 16 --threads-batch 32 \
  --no-mmap --cont-batching --jinja \
  --reasoning on \
  --temp 0.4 --top-k 64 --top-p 0.95 --min-p 0.01 \
  --repeat-penalty 1.05 --repeat-last-n -1 \
  --dry-multiplier 0.8 --dry-base 1.75 --dry-allowed-length 2 --dry-penalty-last-n -1 \
  --poll 50 --prio 3 --metrics --host 0.0.0.0 --port 8081
EOF
sudo chmod +x /usr/local/bin/llama-server-start.sh
sudo systemctl restart llama-server
```

VRAM impact on RX 7800 XT (16 GB):

| state | VRAM used |
|-------|-----------|
| Gemma4 + mmproj | 10.18 GB |
| Gemma4 without mmproj | ~9.84 GB |

---

## 11. Running a second llama-server alongside the main one

You can load a second model on a different port as long as VRAM headroom allows.

### Check available VRAM

```bash
rocm-smi --showmeminfo vram
```

Calculate: `total_free = vram_total - vram_used`. New model needs: `model_size + mmproj_size + ~500 MB KV cache headroom`.

### Download the second model

```bash
sudo mkdir -p /root/models/<model-dir>
sudo hf download <repo/model> --local-dir /root/models/<model-dir> --include '*.gguf'
```

### Write a second start script

```bash
sudo tee /usr/local/bin/llama-<name>-start.sh > /dev/null << 'EOF'
#!/bin/bash
exec /root/llama.cpp/build/bin/llama-server \
  --device Vulkan1 \
  -m /root/models/<model-dir>/<model>.gguf \
  --mmproj /root/models/<model-dir>/<mmproj>.gguf \
  -ngl 99 -fa on -c 8192 --parallel 1 \
  --cache-type-k q8_0 --cache-type-v q8_0 \
  --batch-size 512 --ubatch-size 512 \
  --threads 8 --threads-batch 16 \
  --no-mmap --cont-batching --jinja \
  --metrics --host 0.0.0.0 --port 8082
EOF
sudo chmod +x /usr/local/bin/llama-<name>-start.sh
```

### Create a second systemd service

```bash
sudo tee /etc/systemd/system/llama-<name>.service > /dev/null << 'EOF'
[Unit]
Description=<ModelName>
After=network.target llama-server.service

[Service]
User=root
ExecStart=/usr/local/bin/llama-<name>-start.sh
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
sudo systemctl daemon-reload
sudo systemctl enable --now llama-<name>.service
```

### Open the firewall port

```bash
sudo firewall-cmd --add-port=8082/tcp --permanent
sudo firewall-cmd --reload
```

> **This step is easy to forget.** Even if the service is running, containers and remote hosts cannot reach the port until it is opened in `firewalld`.

---

## 12. Add a second model to OpenWebUI

OpenWebUI stores its OpenAI-compatible connections as JSON in a SQLite database at `/app/backend/data/webui.db` (mounted from the host volume).

### Enable API key auth in the container

By default API keys are disabled. Add this to the container definition and restart:

```ini
# /etc/containers/systemd/openwebui-app.container
Environment=ENABLE_API_KEYS=true
```

```bash
systemctl daemon-reload && podman restart openwebui-app
```

### Create an admin API key

```bash
ADMIN_ID=$(sqlite3 /var/lib/containers/storage/volumes/systemd-openwebui-data/_data/webui.db \
  "SELECT id FROM user WHERE role='admin' LIMIT 1")
API_KEY="sk-owui-$(openssl rand -hex 16)"
KEY_ID=$(python3 -c "import uuid; print(str(uuid.uuid4()))")
NOW=$(date +%s)
sqlite3 /var/lib/containers/storage/volumes/systemd-openwebui-data/_data/webui.db \
  "INSERT INTO api_key (id, user_id, key, created_at, updated_at) VALUES ('$KEY_ID', '$ADMIN_ID', '$API_KEY', $NOW, $NOW)"
echo "KEY: $API_KEY"
```

### Add the connection via the admin API

```bash
TOKEN="<your-api-key>"

# Get current config
curl -s http://localhost:8080/openai/config -H "Authorization: Bearer $TOKEN"

# Add new connection (append to existing arrays)
python3 << 'EOF'
import json, sqlite3

db_path = '/var/lib/containers/storage/volumes/systemd-openwebui-data/_data/webui.db'
db = sqlite3.connect(db_path)
raw = db.execute('SELECT data FROM config WHERE id=1').fetchone()[0]
d = json.loads(raw)
conn = d['openai']

conn['api_base_urls'].append('http://192.168.50.20:8082/v1')
conn['api_keys'].append('sk-no-key')
idx = str(len(conn['api_configs']))
conn['api_configs'][idx] = {
    'enable': True, 'tags': [], 'prefix_id': 'mymodel',
    'model_ids': [], 'connection_type': 'local', 'auth_type': 'bearer'
}
d['openai'] = conn
db.execute('UPDATE config SET data=? WHERE id=1', (json.dumps(d),))
db.commit()
db.close()
print('Added index', idx, '→', conn['api_base_urls'])
EOF

podman restart openwebui-app
```

The `prefix_id` value becomes a prefix on the model name in the picker (e.g. `mymodel.ModelName.gguf`).

### Verify the model appears

```bash
TOKEN="<your-api-key>"
curl -s http://localhost:8080/api/models -H "Authorization: Bearer $TOKEN" \
  | python3 -c "import json,sys; print([m['id'] for m in json.load(sys.stdin).get('data',[])])"
```

---

## 13. Remove a model / full cleanup

```bash
# 1. Stop and remove the service
sudo systemctl disable --now llama-<name>.service
sudo rm /etc/systemd/system/llama-<name>.service /usr/local/bin/llama-<name>-start.sh
sudo systemctl daemon-reload

# 2. Delete model files
sudo rm -rf /root/models/<model-dir>

# 3. Close the firewall port
sudo firewall-cmd --remove-port=8082/tcp --permanent
sudo firewall-cmd --reload

# 4. Remove from OpenWebUI DB (adjust index to match which entry to remove)
python3 << 'EOF'
import json, sqlite3

db_path = '/var/lib/containers/storage/volumes/systemd-openwebui-data/_data/webui.db'
db = sqlite3.connect(db_path)
raw = db.execute('SELECT data FROM config WHERE id=1').fetchone()[0]
d = json.loads(raw)
conn = d['openai']

idx_to_remove = 3  # change to the index of the connection you want to remove
conn['api_base_urls'].pop(idx_to_remove)
conn['api_keys'].pop(idx_to_remove)
del conn['api_configs'][str(idx_to_remove)]
d['openai'] = conn

db.execute('UPDATE config SET data=? WHERE id=1', (json.dumps(d),))
db.commit()
db.close()
print('Remaining URLs:', conn['api_base_urls'])
EOF

podman restart openwebui-app
```

---

## Summary

| step | what changed |
|------|-------------|
| Model downloaded | `/root/models/hauhau-gemma4-12b-qat/` (3 files, ~7.3 GB) |
| Start script | New model + MTP drafter paths |
| MTP tuning | `--spec-draft-n-max 3` confirmed optimal (93.8 tok/s) |
| Repetition test | All 7 prompt types clean (max rep score 0.032) |
| Hermes config | 5 auxiliary model references updated |
| Service description | Matches filename: `Gemma4-12B-QAT-Uncensored-HauhauCS-Balanced-Q4_K_M` |
| Reasoning mode | `--reasoning on` enabled; `reasoning_content` field populated in responses |
| mmproj stripped | Removed from Gemma4 service; rewrote script in full (sed pitfall documented) |
| VRAM after cleanup | ~9.84 GB / 16 GB |
| OpenWebUI multi-model | Steps for adding/removing second server documented; firewall + API key auth pitfalls noted |
