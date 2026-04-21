// Back Office — theme runtime (module).
//
// The first-paint work lives in theme-bootstrap.js (classic script, loaded
// synchronously in <head>). This module handles the interactive toggle
// after DOM is ready.
//
// Exports `applyStoredTheme` and `initThemeToggle` so tests can assert
// the public contract; the module also auto-wires `#themeToggle` on load
// so pages don't need to import it explicitly.
//
// Storage key: 'bo.theme'. Values: 'light' | 'dark'.
// If nothing stored, falls back to prefers-color-scheme: light.

const KEY = 'bo.theme';

function preferred() {
  let stored = null;
  try { stored = localStorage.getItem(KEY); } catch (_) { /* quota, etc. */ }
  if (stored === 'light' || stored === 'dark') return stored;
  if (window.matchMedia && window.matchMedia('(prefers-color-scheme: light)').matches) return 'light';
  return 'dark';
}

export function applyStoredTheme() {
  document.documentElement.setAttribute('data-theme', preferred());
}

export function initThemeToggle(btn) {
  if (!btn) return;
  const paint = () => {
    const theme = document.documentElement.getAttribute('data-theme') || 'dark';
    btn.setAttribute('aria-label', `Switch to ${theme === 'dark' ? 'light' : 'dark'} theme`);
    btn.textContent = theme === 'dark' ? 'Light' : 'Dark';
  };
  paint();
  btn.addEventListener('click', () => {
    const next = document.documentElement.getAttribute('data-theme') === 'dark' ? 'light' : 'dark';
    document.documentElement.setAttribute('data-theme', next);
    try { localStorage.setItem('bo.theme', next); } catch (_) { /* quota */ }
    paint();
  });
}

function autoWire() {
  const btn = document.getElementById('themeToggle');
  if (btn) initThemeToggle(btn);
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', autoWire);
} else {
  autoWire();
}
