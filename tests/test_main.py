"""Tests for backoffice.__main__ dispatch."""
import subprocess
import sys


def test_help_shows_available_commands():
    result = subprocess.run(
        [sys.executable, "-m", "backoffice", "--help"],
        capture_output=True, text=True,
    )
    assert result.returncode == 0
    assert "sync" in result.stdout
    assert "config" in result.stdout
    assert "audit" in result.stdout


def test_unknown_command_exits_nonzero():
    result = subprocess.run(
        [sys.executable, "-m", "backoffice", "nonexistent"],
        capture_output=True, text=True,
    )
    assert result.returncode != 0
