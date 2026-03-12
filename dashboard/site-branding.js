/**
 * Site Branding — Shared header injection for admin.* subdomains
 *
 * When served from admin.codyjo.com, admin.thenewbeautifulme.com, etc.,
 * this script injects the parent site's header navigation at the top of
 * the page and applies site-specific branding to the dashboard.
 *
 * Include via <script src="site-branding.js"></script> in <head>.
 */

(function () {
  'use strict';

  window.showCommandToast = function (command) {
    var container = document.getElementById('toastContainer');
    if (!container) return;

    var toast = document.createElement('div');
    toast.className = 'toast';
    toast.innerHTML =
      '<strong>Run this locally:</strong><br>' +
      '<code style="display:block;margin-top:0.4rem;white-space:pre-wrap;">' +
      escapeHtml(command) +
      '</code>';

    container.appendChild(toast);
    setTimeout(function () {
      toast.style.opacity = '0';
      setTimeout(function () { toast.remove(); }, 300);
    }, 7000);
  };

  function escapeHtml(str) {
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  // ── Site Configurations ──────────────────────────────────────────────────
  var SITE_CONFIGS = {
    'codyjo.com': {
      name: 'Cody Jo Method',
      logoMark: 'CJ',
      logoFont: "'Playfair Display', Georgia, serif",
      fontUrl: 'https://fonts.googleapis.com/css2?family=Playfair+Display:ital,wght@0,400;0,500;0,600;1,400;1,500;1,600&display=swap',
      accent: '#c4944a',
      accentWarm: '#d4a055',
      accentDim: 'rgba(196, 148, 74, 0.12)',
      bgDeep: '#050505',
      bgNav: 'rgba(5, 5, 5, 0.92)',
      textPrimary: '#e8e0d4',
      textSecondary: '#9a8e80',
      textBright: '#f5f0e8',
      borderWarm: '#2a2318',
      siteUrl: 'https://codyjo.com',
      navLinks: [
        { text: 'Story', href: '/#story' },
        { text: 'Analogify', href: '/#analogify' },
        { text: 'ChromaHaus', href: '/#chromahaus' },
        { text: 'Features', href: '/features' },
        { text: 'Gallery', href: '/#gallery' },
        { text: 'Journal', href: '/blog' },
        { text: 'Contact', href: '/#contact' },
        { text: 'GitHub', href: 'https://github.com/CodyJo/analogify', external: true },
      ],
      cta: { text: 'Try Demo', href: '/demo.html' },
    },
  };

  // ── Detect admin subdomain ───────────────────────────────────────────────
  var host = window.location.hostname;
  var match = host.match(/^admin\.(.+)$/);
  if (!match) return;

  var parentDomain = match[1];
  var config = SITE_CONFIGS[parentDomain];
  if (!config) {
    // Fallback: still apply basic branding (logo initials + title)
    applyBasicBranding(parentDomain);
    return;
  }

  // ── Load custom font if needed ───────────────────────────────────────────
  if (config.fontUrl) {
    var link = document.createElement('link');
    link.rel = 'stylesheet';
    link.href = config.fontUrl;
    document.head.appendChild(link);
  }

  // ── Inject CSS ───────────────────────────────────────────────────────────
  var css = document.createElement('style');
  css.textContent = '\n' +
    '/* Site header from ' + parentDomain + ' */\n' +
    '.site-header {\n' +
    '  position: fixed; top: 0; left: 0; right: 0; z-index: 200;\n' +
    '  background: ' + config.bgNav + ';\n' +
    '  backdrop-filter: blur(24px); -webkit-backdrop-filter: blur(24px);\n' +
    '  border-bottom: 1px solid ' + config.borderWarm + ';\n' +
    '  font-family: "Inter", -apple-system, sans-serif;\n' +
    '}\n' +
    '.site-header-inner {\n' +
    '  max-width: 1280px; margin: 0 auto; padding: 0 1.5rem;\n' +
    '  display: flex; align-items: center; justify-content: space-between;\n' +
    '  height: 64px;\n' +
    '}\n' +
    '.site-header-logo {\n' +
    '  display: flex; align-items: center; gap: 0.75rem;\n' +
    '  color: ' + config.textBright + '; text-decoration: none;\n' +
    '  transition: color 0.3s;\n' +
    '}\n' +
    '.site-header-logo:hover { color: ' + config.accent + '; }\n' +
    '.site-logo-mark {\n' +
    '  font-family: ' + config.logoFont + ';\n' +
    '  font-size: 1.35rem; font-weight: 600; font-style: italic;\n' +
    '  width: 34px; height: 34px;\n' +
    '  display: flex; align-items: center; justify-content: center;\n' +
    '  border: 1.5px solid ' + config.accent + ';\n' +
    '  color: ' + config.accent + ';\n' +
    '}\n' +
    '.site-logo-text {\n' +
    '  font-family: ' + config.logoFont + ';\n' +
    '  font-size: 1.1rem; font-weight: 500; letter-spacing: 0.02em;\n' +
    '}\n' +
    '.site-header-nav {\n' +
    '  display: flex; align-items: center; gap: 1.5rem;\n' +
    '}\n' +
    '.site-header-link {\n' +
    '  font-size: 0.7rem; font-weight: 400; letter-spacing: 0.1em;\n' +
    '  text-transform: uppercase; text-decoration: none;\n' +
    '  color: ' + config.textSecondary + '; transition: color 0.3s;\n' +
    '}\n' +
    '.site-header-link:hover {\n' +
    '  color: ' + config.accent + ';\n' +
    '  text-decoration: underline; text-underline-offset: 4px;\n' +
    '}\n' +
    '.site-header-link.active {\n' +
    '  color: ' + config.accent + ';\n' +
    '  text-decoration: underline; text-underline-offset: 4px;\n' +
    '}\n' +
    '.site-header-cta {\n' +
    '  border: 1px solid ' + config.accent + ';\n' +
    '  color: ' + config.accent + ' !important;\n' +
    '  padding: 0.4rem 1rem; font-weight: 500;\n' +
    '  transition: all 0.3s;\n' +
    '}\n' +
    '.site-header-cta:hover {\n' +
    '  background: ' + config.accent + ';\n' +
    '  color: ' + config.bgDeep + ' !important;\n' +
    '}\n' +
    '.site-header-divider {\n' +
    '  width: 1px; height: 20px;\n' +
    '  background: ' + config.borderWarm + ';\n' +
    '  margin: 0 0.25rem;\n' +
    '}\n' +
    '.site-header-badge {\n' +
    '  font-size: 0.6rem; font-weight: 600; letter-spacing: 0.08em;\n' +
    '  text-transform: uppercase; padding: 0.25rem 0.6rem;\n' +
    '  border-radius: 4px; text-decoration: none;\n' +
    '  background: ' + config.accentDim + ';\n' +
    '  color: ' + config.accent + ';\n' +
    '}\n' +
    '.site-header-toggle {\n' +
    '  display: none; flex-direction: column; gap: 5px;\n' +
    '  background: none; border: none; cursor: pointer;\n' +
    '  padding: 8px; min-width: 44px; min-height: 44px; z-index: 201;\n' +
    '}\n' +
    '.site-header-toggle span {\n' +
    '  display: block; width: 22px; height: 1.5px;\n' +
    '  background: ' + config.textPrimary + ';\n' +
    '  transition: all 0.3s;\n' +
    '}\n' +
    '/* Push dashboard content below fixed header */\n' +
    'body { padding-top: 64px !important; }\n' +
    '@media (max-width: 960px) {\n' +
    '  .site-header-toggle { display: flex; }\n' +
    '  .site-header-nav {\n' +
    '    position: fixed; top: 0; left: 0; right: 0; bottom: 0;\n' +
    '    background: ' + config.bgDeep + '; flex-direction: column;\n' +
    '    justify-content: center; gap: 2rem;\n' +
    '    opacity: 0; pointer-events: none;\n' +
    '    transition: opacity 0.4s; z-index: 200;\n' +
    '  }\n' +
    '  .site-header-nav.open { opacity: 1; pointer-events: auto; }\n' +
    '  .site-header-link { font-size: 0.9rem; letter-spacing: 0.15em; }\n' +
    '  .site-header-toggle.open span:first-child { transform: rotate(45deg) translate(2px, 2px); }\n' +
    '  .site-header-toggle.open span:last-child { transform: rotate(-45deg) translate(2px, -2px); }\n' +
    '}\n';
  document.head.appendChild(css);

  // ── Build and inject the header ──────────────────────────────────────────
  document.addEventListener('DOMContentLoaded', function () {
    var siteUrl = config.siteUrl;
    var header = document.createElement('div');
    header.className = 'site-header';
    header.setAttribute('role', 'banner');

    var inner = '<div class="site-header-inner">';

    // Logo
    inner += '<a href="' + siteUrl + '" class="site-header-logo">';
    inner += '<span class="site-logo-mark">' + config.logoMark + '</span>';
    inner += '<span class="site-logo-text">' + config.name + '</span>';
    inner += '</a>';

    // Nav links
    inner += '<nav class="site-header-nav" role="navigation" aria-label="Main site navigation">';
    config.navLinks.forEach(function (link) {
      var href = link.external ? link.href : siteUrl + link.href;
      var extra = link.external ? ' target="_blank" rel="noopener"' : '';
      inner += '<a href="' + href + '" class="site-header-link"' + extra + '>' + link.text + '</a>';
    });

    // CTA
    if (config.cta) {
      var ctaHref = config.cta.href.startsWith('http') ? config.cta.href : siteUrl + config.cta.href;
      inner += '<a href="' + ctaHref + '" class="site-header-link site-header-cta">' + config.cta.text + '</a>';
    }

    // Separator + Back Office badge
    inner += '<span class="site-header-divider"></span>';
    inner += '<span class="site-header-badge">Back Office</span>';

    inner += '</nav>';

    // Mobile toggle
    inner += '<button class="site-header-toggle" aria-label="Toggle menu" aria-expanded="false">';
    inner += '<span></span><span></span>';
    inner += '</button>';

    inner += '</div>';
    header.innerHTML = inner;

    document.body.insertBefore(header, document.body.firstChild);

    // Mobile toggle behavior
    var toggle = header.querySelector('.site-header-toggle');
    var nav = header.querySelector('.site-header-nav');
    if (toggle && nav) {
      toggle.addEventListener('click', function () {
        var isOpen = nav.classList.toggle('open');
        toggle.classList.toggle('open');
        toggle.setAttribute('aria-expanded', String(isOpen));
      });
      document.addEventListener('keydown', function (e) {
        if (e.key === 'Escape' && nav.classList.contains('open')) {
          nav.classList.remove('open');
          toggle.classList.remove('open');
          toggle.setAttribute('aria-expanded', 'false');
          toggle.focus();
        }
      });
    }

    injectReportingContext();

    // Apply branding to dashboard elements
    applyDashboardBranding(parentDomain, config);
  });

  function injectReportingContext() {
    if (document.getElementById('productSelect') || document.getElementById('sharedReportingSelect')) return;

    originalFetch('org-data.json')
      .then(function (resp) { return resp.ok ? resp.json() : null; })
      .then(function (orgData) {
        if (!orgData || !Array.isArray(orgData.products) || !orgData.products.length) return;

        var current = new URL(window.location.href);
        var currentProduct = current.searchParams.get('product') || 'all';
        var container = document.createElement('section');
        container.className = 'shared-reporting-shell';
        container.innerHTML =
          '<div class="shared-reporting-card">' +
            '<div class="shared-reporting-label">Reporting On</div>' +
            '<select id="sharedReportingSelect" aria-label="Reporting on product">' +
              orgData.products.map(function (product) {
                var selected = product.key === currentProduct ? ' selected' : '';
                return '<option value="' + escapeHtml(product.key) + '"' + selected + '>' + escapeHtml(product.name) + '</option>';
              }).join('') +
            '</select>' +
          '</div>';

        var main = document.querySelector('main');
        if (main) {
          main.insertBefore(container, main.firstChild);
        } else {
          document.body.insertBefore(container, document.body.children[1] || null);
        }

        var style = document.createElement('style');
        style.textContent =
          '.shared-reporting-shell{max-width:1400px;margin:0 auto;padding:1rem 1.5rem 0;}' +
          '.shared-reporting-card{background:#12121a;border:1px solid #2a2a3a;border-radius:14px;padding:1rem;display:grid;gap:0.45rem;}' +
          '.shared-reporting-label{font-size:0.72rem;text-transform:uppercase;letter-spacing:0.08em;color:#8888a0;}' +
          '#sharedReportingSelect{width:100%;background:#1a1a26;color:#e4e4ef;border:1px solid #2a2a3a;border-radius:10px;padding:0.8rem 0.9rem;font-family:\"Inter\",-apple-system,sans-serif;font-size:0.92rem;}';
        document.head.appendChild(style);

        document.getElementById('sharedReportingSelect').addEventListener('change', function (event) {
          var url = new URL(window.location.href);
          if (event.target.value === 'all') {
            url.searchParams.delete('product');
          } else {
            url.searchParams.set('product', event.target.value);
          }
          window.location.href = url.toString();
        });
      })
      .catch(function () {});
  }

  function applyDashboardBranding(domain, cfg) {
    // Update logo/title in the dashboard's own header
    var iconEl = document.getElementById('logo-icon');
    var titleEl = document.getElementById('logo-title');
    var footerEl = document.getElementById('footer-brand');

    var name = domain.replace(/\.(com|org|net|io|dev|co)$/i, '');
    var words = name.replace(/([a-z])([A-Z])/g, '$1 $2')
                    .replace(/[-_]/g, ' ')
                    .split(/\s+/)
                    .filter(function (w) { return !['the','and','of','a'].includes(w.toLowerCase()); });
    var initials = words.length >= 2
      ? (words[0][0] + words[1][0]).toUpperCase()
      : name.slice(0, 2).toUpperCase();

    if (iconEl) iconEl.textContent = initials;
    if (titleEl) titleEl.textContent = domain;
    if (footerEl) footerEl.textContent = domain;
    document.title = rewriteTitle(document.title, domain);
  }

  function applyBasicBranding(domain) {
    document.addEventListener('DOMContentLoaded', function () {
      var iconEl = document.getElementById('logo-icon');
      var titleEl = document.getElementById('logo-title');
      var footerEl = document.getElementById('footer-brand');

      var name = domain.replace(/\.(com|org|net|io|dev|co)$/i, '');
      var words = name.replace(/([a-z])([A-Z])/g, '$1 $2')
                      .replace(/[-_]/g, ' ')
                      .split(/\s+/)
                      .filter(function (w) { return !['the','and','of','a'].includes(w.toLowerCase()); });
      var initials = words.length >= 2
        ? (words[0][0] + words[1][0]).toUpperCase()
        : name.slice(0, 2).toUpperCase();

      if (iconEl) iconEl.textContent = initials;
      if (titleEl) titleEl.textContent = domain;
      if (footerEl) footerEl.textContent = domain;
      document.title = rewriteTitle(document.title, domain);
    });
  }

  function rewriteTitle(title, domain) {
    if (!title) return domain + ' — Back Office';
    if (/^(BreakPoint Labs|Cody Jo Method)\b/.test(title)) {
      return title.replace(/^(BreakPoint Labs|Cody Jo Method)\b/, domain);
    }
    return title.indexOf(domain) === -1 ? domain + ' — ' + title : title;
  }
})();

/**
 * FAQ Hover Tooltips — Adds "?" icons next to elements with data-faq attributes
 * Usage: <span data-faq="qa-score">Health Score</span>
 * The value maps to an anchor ID on faq.html (e.g., faq.html#qa-score)
 */
(function () {
  'use strict';

  // Brief explanations shown in the hover tooltip
  var FAQ_TIPS = {
    'qa-score':       'Starts at 100. Deducts 15/critical, 8/high, 3/medium, 1/low for each open finding.',
    'qa-severity':    'Critical = security/blocking bugs. High = significant issues. Medium = moderate. Low = minor. Info = suggestions.',
    'seo-score':      'Weighted average: Technical (30%) + AI (20%) + Content (20%) + Performance (20%) + Social (10%).',
    'seo-categories': '5 categories, each scored 0\u2013100 with severity deductions, combined by weight.',
    'ada-score':      'Starts at 100. Deducts 15/critical, 8/high, 3/medium, 1/low. Info (AAA) items are free.',
    'ada-level':      'AAA = score\u226595 + no crit/high/med. AA = score\u226570 + no crit. A = score\u226540. Below = Non-Compliant.',
    'ada-pour':       'WCAG 2.1 principles: Perceivable, Operable, Understandable, Robust \u2014 each scored independently.',
    'compliance-score':    'Average of GDPR, ISO 27001, and Age Verification scores. Each uses heavier deductions for legal risk.',
    'compliance-status':   'Compliant \u2265 90. Partial = 60\u201389. Non-Compliant < 60.',
    'compliance-frameworks': 'Three frameworks: GDPR (data protection), ISO 27001 (info security), Age Verification (COPPA + state laws).',
    'monetization-score':  'Equal-weight average of 4 dimensions: Infrastructure, Audience, Features, Market Fit (25% each).',
    'monetization-value':  'High = $500+/mo. Medium = $100\u2013500/mo. Low = $10\u2013100/mo.',
    'product-score':       'Weighted: Features (30%) + UX (25%) + Technical (25%) + Growth (20%). Growth starts at 50 and adds points.',
    'product-priority':    'Must-Have \u2192 Should-Have \u2192 Nice-to-Have \u2192 Future \u2192 Idea.'
  };

  var tipStyle = document.createElement('style');
  tipStyle.textContent =
    '.faq-trigger {' +
    '  display: inline-flex; align-items: center; justify-content: center;' +
    '  width: 16px; height: 16px; border-radius: 50%;' +
    '  font-size: 0.55rem; font-weight: 700; font-family: "Inter", sans-serif;' +
    '  color: #5a5a70; background: rgba(90,90,112,0.15);' +
    '  cursor: help; margin-left: 0.35rem; vertical-align: middle;' +
    '  transition: all 0.15s; position: relative; text-decoration: none;' +
    '  line-height: 1; flex-shrink: 0;' +
    '}' +
    '.faq-trigger:hover {' +
    '  color: #c4944a; background: rgba(196,148,74,0.15);' +
    '}' +
    '.faq-tip {' +
    '  display: none; position: absolute; z-index: 500;' +
    '  bottom: calc(100% + 8px); left: 50%; transform: translateX(-50%);' +
    '  width: 280px; padding: 0.7rem 0.85rem;' +
    '  background: #1a1a26; border: 1px solid #3a3a5a;' +
    '  border-radius: 8px; box-shadow: 0 8px 32px rgba(0,0,0,0.4);' +
    '  font-size: 0.72rem; font-weight: 400; color: #c0c0d0;' +
    '  line-height: 1.55; text-align: left; pointer-events: none;' +
    '}' +
    '.faq-trigger:hover .faq-tip { display: block; pointer-events: auto; }' +
    '.faq-tip::after {' +
    '  content: ""; position: absolute; top: 100%; left: 50%;' +
    '  transform: translateX(-50%);' +
    '  border: 6px solid transparent; border-top-color: #3a3a5a;' +
    '}' +
    '.faq-tip-link {' +
    '  display: block; margin-top: 0.4rem; font-size: 0.65rem;' +
    '  color: #c4944a; text-decoration: none; font-weight: 500;' +
    '}' +
    '.faq-tip-link:hover { text-decoration: underline; }' +
    '@media (max-width: 600px) {' +
    '  .faq-tip { width: 220px; left: auto; right: -8px; transform: none; }' +
    '  .faq-tip::after { left: auto; right: 12px; transform: none; }' +
    '}';
  document.head.appendChild(tipStyle);

  // Auto-match labels by text content per page
  var PAGE_LABELS = {
    'qa.html': {
      'Health Score': 'qa-score',
      'Total Findings': 'qa-severity'
    },
    'seo.html': {
      'SEO Score': 'seo-score',
      'Overall Score': 'seo-score'
    },
    'ada.html': {
      'Current Compliance Level': 'ada-level',
      'Compliance Score': 'ada-score'
    },
    'compliance.html': {
      'Overall Score': 'compliance-score',
      'Compliance Score': 'compliance-score'
    },
    'monetization.html': {
      'Readiness Score': 'monetization-score',
      'Monetization Readiness': 'monetization-score'
    },
    'product.html': {
      'Product Readiness': 'product-score',
      'Readiness Score': 'product-score'
    }
  };

  function attachFaqTrigger(el, key) {
    if (el.querySelector('.faq-trigger')) return; // already attached
    var text = FAQ_TIPS[key] || '';
    if (!text) return;

    var trigger = document.createElement('a');
    trigger.className = 'faq-trigger';
    trigger.href = 'faq.html#' + key;
    trigger.setAttribute('aria-label', 'How is this calculated?');
    trigger.innerHTML = '?' +
      '<div class="faq-tip">' +
      text +
      '<span class="faq-tip-link">Learn more \u2192</span>' +
      '</div>';

    el.appendChild(trigger);
  }

  function scanAndAttach() {
    // 1. Explicit data-faq attributes
    var els = document.querySelectorAll('[data-faq]');
    els.forEach(function (el) {
      attachFaqTrigger(el, el.getAttribute('data-faq'));
    });

    // 2. Auto-match by page + label text
    var page = window.location.pathname.split('/').pop() || 'index.html';
    var labels = PAGE_LABELS[page];
    if (!labels) return;

    // Search stat-label, section-title, compliance-level-label, and similar elements
    var candidates = document.querySelectorAll('.stat-label, .section-title, .compliance-level-label, .score-label, .metric-label, .card-label, .stat-card .stat-label');
    candidates.forEach(function (el) {
      var txt = el.textContent.trim();
      if (labels[txt]) {
        attachFaqTrigger(el, labels[txt]);
      }
    });
  }

  document.addEventListener('DOMContentLoaded', function () {
    // Initial scan
    setTimeout(scanAndAttach, 500);
    // Re-scan after data loads and re-renders (covers JS-generated labels)
    setTimeout(scanAndAttach, 2000);
    setTimeout(scanAndAttach, 5000);
  });
})();

/**
 * Command Toast — Shows a persistent copyable command box
 * Available globally: window.showCommandToast(command)
 */
(function () {
  'use strict';

  // Inject CSS once
  var style = document.createElement('style');
  style.textContent =
    '.cmd-toast-overlay {' +
    '  position: fixed; inset: 0; z-index: 10000;' +
    '  background: rgba(0,0,0,0.5); backdrop-filter: blur(4px);' +
    '  display: flex; align-items: center; justify-content: center;' +
    '  animation: cmdFadeIn 0.2s ease;' +
    '}' +
    '.cmd-toast-box {' +
    '  background: #12121a; border: 1px solid #2a2a3a;' +
    '  border-radius: 12px; padding: 1.5rem 1.75rem;' +
    '  max-width: 560px; width: 90%; box-shadow: 0 16px 64px rgba(0,0,0,0.5);' +
    '  animation: cmdSlideIn 0.25s ease;' +
    '}' +
    '.cmd-toast-label {' +
    '  font-family: "Inter", -apple-system, sans-serif;' +
    '  font-size: 0.78rem; color: #8888a0; margin-bottom: 0.75rem;' +
    '}' +
    '.cmd-toast-cmd {' +
    '  display: flex; align-items: center; gap: 0.5rem;' +
    '  background: #0a0a0f; border: 1px solid #3a3a5a;' +
    '  border-radius: 8px; padding: 0.75rem 1rem; cursor: pointer;' +
    '  transition: border-color 0.15s;' +
    '}' +
    '.cmd-toast-cmd:hover { border-color: #c4944a; }' +
    '.cmd-toast-text {' +
    '  font-family: "JetBrains Mono", monospace; font-size: 0.82rem;' +
    '  color: #e4e4ef; flex: 1; user-select: all; word-break: break-all;' +
    '}' +
    '.cmd-toast-copy {' +
    '  font-family: "Inter", -apple-system, sans-serif;' +
    '  font-size: 0.68rem; font-weight: 500; text-transform: uppercase;' +
    '  letter-spacing: 0.06em; padding: 0.3rem 0.7rem;' +
    '  border-radius: 6px; border: 1px solid #c4944a;' +
    '  background: rgba(196,148,74,0.1); color: #c4944a;' +
    '  cursor: pointer; white-space: nowrap; transition: all 0.15s;' +
    '}' +
    '.cmd-toast-copy:hover { background: #c4944a; color: white; }' +
    '.cmd-toast-copy.copied { background: #2ed573; border-color: #2ed573; color: white; }' +
    '.cmd-toast-hint {' +
    '  font-family: "Inter", -apple-system, sans-serif;' +
    '  font-size: 0.68rem; color: #5a5a70; margin-top: 0.6rem;' +
    '  text-align: right;' +
    '}' +
    '@keyframes cmdFadeIn { from { opacity: 0; } to { opacity: 1; } }' +
    '@keyframes cmdSlideIn { from { opacity: 0; transform: translateY(12px); } to { opacity: 1; transform: translateY(0); } }';
  document.head.appendChild(style);

  window.showCommandToast = function (command) {
    // Remove existing
    var existing = document.querySelector('.cmd-toast-overlay');
    if (existing) existing.remove();

    var overlay = document.createElement('div');
    overlay.className = 'cmd-toast-overlay';
    overlay.innerHTML =
      '<div class="cmd-toast-box">' +
      '  <div class="cmd-toast-label">Run this command in your terminal:</div>' +
      '  <div class="cmd-toast-cmd" id="cmdToastCmd">' +
      '    <span class="cmd-toast-text">' + command.replace(/</g, '&lt;') + '</span>' +
      '    <button class="cmd-toast-copy" id="cmdToastCopy">Copy</button>' +
      '  </div>' +
      '  <div class="cmd-toast-hint">Click anywhere outside to close</div>' +
      '</div>';

    document.body.appendChild(overlay);

    // Copy on button click
    var copyBtn = document.getElementById('cmdToastCopy');
    var cmdBox = document.getElementById('cmdToastCmd');

    function doCopy() {
      navigator.clipboard.writeText(command).then(function () {
        copyBtn.textContent = 'Copied!';
        copyBtn.classList.add('copied');
        setTimeout(function () {
          copyBtn.textContent = 'Copy';
          copyBtn.classList.remove('copied');
        }, 2000);
      }).catch(function () {
        // Fallback: select the text
        var range = document.createRange();
        range.selectNodeContents(cmdBox.querySelector('.cmd-toast-text'));
        var sel = window.getSelection();
        sel.removeAllRanges();
        sel.addRange(range);
      });
    }

    copyBtn.addEventListener('click', function (e) {
      e.stopPropagation();
      doCopy();
    });

    cmdBox.addEventListener('click', function () { doCopy(); });

    // Close on overlay click or Escape
    overlay.addEventListener('click', function (e) {
      if (e.target === overlay) overlay.remove();
    });
    document.addEventListener('keydown', function handler(e) {
      if (e.key === 'Escape') {
        overlay.remove();
        document.removeEventListener('keydown', handler);
      }
    });
  };
})();
