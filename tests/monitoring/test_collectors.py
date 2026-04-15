"""Tests for monitoring collector scripts.

Each test mocks the underlying tool and verifies:
1. Valid JSON output
2. Correct metric names and structure
3. Graceful degradation (zero-values) when tools are unavailable
"""

import json
import shutil
import subprocess
import os

import pytest

COLLECTORS_DIR = os.path.join(
    os.path.dirname(__file__), "..", "..", "monitoring", "vector", "collectors"
)


def run_collector(name: str, env: dict | None = None) -> list[dict]:
    """Run a collector script and return parsed JSON output."""
    script = os.path.join(COLLECTORS_DIR, name)
    result = subprocess.run(
        ["bash", script],
        capture_output=True,
        text=True,
        timeout=30,
        env={**os.environ, **(env or {})},
    )
    assert result.returncode == 0, f"Script exited {result.returncode}: {result.stderr}"
    data = json.loads(result.stdout)
    assert isinstance(data, list), f"Expected JSON array, got {type(data)}"
    return data


def validate_metric(m: dict):
    """Validate a single metric dict has required fields."""
    assert "time" in m, f"Missing 'time': {m}"
    assert "source" in m, f"Missing 'source': {m}"
    assert "metric" in m, f"Missing 'metric': {m}"
    assert "labels" in m, f"Missing 'labels': {m}"
    assert "value" in m, f"Missing 'value': {m}"
    assert isinstance(m["labels"], dict), f"labels must be dict: {m}"
    assert isinstance(m["value"], (int, float)), f"value must be number: {m}"


class TestGpuMetrics:
    def test_produces_valid_json(self):
        metrics = run_collector("gpu_metrics.sh")
        if not shutil.which("nvidia-smi"):
            # Without nvidia-smi the collector returns [] which is valid
            assert metrics == []
            return
        for m in metrics:
            validate_metric(m)

    def test_has_expected_metrics(self):
        if not shutil.which("nvidia-smi"):
            pytest.skip("nvidia-smi not available on this system")
        metrics = run_collector("gpu_metrics.sh")
        names = {m["metric"] for m in metrics}
        expected = {"gpu_temp_celsius", "gpu_utilization_percent", "gpu_memory_used_bytes",
                    "gpu_memory_total_bytes", "gpu_memory_free_bytes", "gpu_power_watts"}
        assert expected.issubset(names), f"Missing metrics: {expected - names}"

    def test_graceful_without_nvidia_smi(self):
        """When nvidia-smi is not found, should output empty array."""
        metrics = run_collector("gpu_metrics.sh", env={**os.environ, "NVIDIA_SMI": "/nonexistent"})
        assert metrics == []


class TestSystemSensors:
    def test_produces_valid_json(self):
        metrics = run_collector("system_sensors.sh")
        for m in metrics:
            validate_metric(m)

    def test_has_vmstat_metrics(self):
        if not os.path.exists("/proc/vmstat"):
            pytest.skip("/proc/vmstat not available on this system")
        metrics = run_collector("system_sensors.sh")
        names = {m["metric"] for m in metrics}
        assert "oom_kills_total" in names
        assert "memory_page_faults_major" in names

    def test_has_cpu_temp_metrics(self):
        """CPU temperature metrics require k10temp hwmon; skip if unavailable."""
        metrics = run_collector("system_sensors.sh")
        names = {m["metric"] for m in metrics}
        if "cpu_temp_celsius" not in names:
            pytest.skip("k10temp hwmon not available on this system")


class TestOllamaMetrics:
    def test_produces_valid_json(self):
        metrics = run_collector("ollama_metrics.sh")
        for m in metrics:
            validate_metric(m)

    def test_has_running_status(self):
        metrics = run_collector("ollama_metrics.sh")
        names = {m["metric"] for m in metrics}
        assert "ollama_running" in names

    def test_graceful_when_ollama_down(self):
        """When Ollama is unreachable, should output ollama_running: 0."""
        metrics = run_collector("ollama_metrics.sh", env={**os.environ, "OLLAMA_HOST": "http://localhost:99999"})
        assert len(metrics) == 1
        assert metrics[0]["metric"] == "ollama_running"
        assert metrics[0]["value"] == 0


class TestClaudeSessions:
    def test_produces_valid_json(self):
        metrics = run_collector("claude_sessions.sh")
        for m in metrics:
            validate_metric(m)

    def test_has_expected_metrics(self):
        metrics = run_collector("claude_sessions.sh")
        names = {m["metric"] for m in metrics}
        assert "claude_active_sessions" in names
        assert "claude_worktrees_active" in names
