// Back Office — theme first-paint bootstrap.
//
// Loaded synchronously in <head> before theme.css so the data-theme
// attribute is set before CSS variables resolve. No flash for
// light-mode users.
//
// Classic script (not a module) on purpose — modules defer and would
// run after the stylesheet paints.
(function () {
  var KEY = 'bo.theme';
  var stored;
  try { stored = localStorage.getItem(KEY); } catch (_) { stored = null; }

  var theme;
  if (stored === 'light' || stored === 'dark') {
    theme = stored;
  } else if (window.matchMedia && window.matchMedia('(prefers-color-scheme: light)').matches) {
    theme = 'light';
  } else {
    theme = 'dark';
  }
  document.documentElement.setAttribute('data-theme', theme);
})();
