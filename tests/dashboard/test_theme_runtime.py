"""Smoke-level assertions on dashboard/theme.js.

We do not run the module in a browser here; we assert its public
contract (exports + inline pre-paint snippet) textually, which is
enough to catch accidental regressions like "someone deleted the
first-paint bootstrap and the page flashes dark on every load".
"""
from pathlib import Path

THEME_JS = Path(__file__).resolve().parents[2] / "dashboard" / "theme.js"


def test_theme_js_exists():
    assert THEME_JS.exists()


def test_exports_initThemeToggle():
    assert "export function initThemeToggle" in THEME_JS.read_text()


def test_exports_applyStoredTheme():
    """Called inline before first paint — must be side-effecting."""
    assert "export function applyStoredTheme" in THEME_JS.read_text()


def test_reads_prefers_color_scheme():
    """Fallback when localStorage has no value."""
    src = THEME_JS.read_text()
    assert "matchMedia" in src
    assert "prefers-color-scheme: light" in src


def test_persists_to_localstorage_under_known_key():
    src = THEME_JS.read_text()
    assert "localStorage.setItem('bo.theme'" in src or \
           'localStorage.setItem("bo.theme"' in src
