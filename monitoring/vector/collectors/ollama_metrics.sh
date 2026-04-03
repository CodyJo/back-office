#!/bin/bash
# Collects Ollama model status from /api/ps and /api/tags.
# Computes vram_ratio for GPU offload detection.
# Outputs JSON array. Exits 0 with zero-values if Ollama is down.
# Uses Python for JSON generation to avoid subshell variable scoping issues.
set -euo pipefail

OLLAMA_HOST="${OLLAMA_HOST:-http://localhost:11434}"

# Check if Ollama is reachable and generate all metrics in Python
# to avoid bash subshell variable scoping bugs with pipes.
python3 << 'PYEOF'
import json, sys, urllib.request, datetime

host = "${OLLAMA_HOST}" if "${OLLAMA_HOST}" != "" else "http://localhost:11434"
# Re-read from env since heredoc doesn't expand
import os
host = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

def metric(name, labels, value):
    return {"time": now, "source": "ollama", "metric": name, "labels": labels, "value": value}

metrics = []

# Check if Ollama is reachable
try:
    tags_raw = urllib.request.urlopen(f"{host}/api/tags", timeout=5).read()
    tags = json.loads(tags_raw)
except Exception:
    print(json.dumps([metric("ollama_running", {}, 0)]))
    sys.exit(0)

metrics.append(metric("ollama_running", {}, 1))
metrics.append(metric("ollama_models_available", {}, len(tags.get("models", []))))

# Get running models
try:
    ps_raw = urllib.request.urlopen(f"{host}/api/ps", timeout=5).read()
    ps = json.loads(ps_raw)
except Exception:
    ps = {"models": []}

for m in ps.get("models", []):
    name = m.get("name", "unknown")
    size = m.get("size", 0)
    size_vram = m.get("size_vram", 0)
    vram_ratio = round(size_vram / size, 4) if size > 0 else 0.0
    expires_at = m.get("expires_at", "")
    labels = {"model": name}

    metrics.append(metric("ollama_model_loaded", labels, 1))
    metrics.append(metric("ollama_model_size_bytes", labels, size))
    metrics.append(metric("ollama_model_vram_bytes", labels, size_vram))
    metrics.append(metric("ollama_model_vram_ratio", labels, vram_ratio))

    if expires_at:
        metrics.append(metric("ollama_model_expires_at", {**labels, "expires_at": expires_at}, 1))

print(json.dumps(metrics, indent=2))
PYEOF
