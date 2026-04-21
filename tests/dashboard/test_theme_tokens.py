"""Structural contract for the theme token file.

Pure text assertions so the test runs without a browser and still
catches the most common regression: someone re-adds a hard-coded
color where a token should live.
"""
from pathlib import Path

THEME_CSS = Path(__file__).resolve().parents[2] / "dashboard" / "theme.css"


REQUIRED_TOKENS = [
    "--bg", "--surface", "--surface-2", "--surface-3",
    "--border", "--text", "--text-dim",
    "--accent", "--accent-2",
    "--critical", "--high", "--medium", "--low", "--info", "--success",
    "--radius", "--sans", "--mono",
]


def test_theme_css_exists():
    assert THEME_CSS.exists(), f"missing {THEME_CSS}"


def test_dark_palette_defines_every_token():
    css = THEME_CSS.read_text()
    dark_block = _extract_block(css, selector=':root, [data-theme="dark"]')
    for token in REQUIRED_TOKENS:
        assert f"{token}:" in dark_block, f"dark theme missing {token}"


def test_light_palette_defines_every_surface_and_text_token():
    css = THEME_CSS.read_text()
    light_block = _extract_block(css, selector='[data-theme="light"]')
    must_override = [
        "--bg", "--surface", "--surface-2", "--surface-3",
        "--border", "--text", "--text-dim",
    ]
    for token in must_override:
        assert f"{token}:" in light_block, f"light theme missing {token}"


def _extract_block(css: str, selector: str) -> str:
    start = css.index(selector)
    open_brace = css.index("{", start)
    close_brace = css.index("}", open_brace)
    return css[open_brace:close_brace]
