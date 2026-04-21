(function() {
  'use strict';

  /* ── Constants ── */
  var DEPT_KEYS = ['qa', 'seo', 'ada', 'compliance', 'monetization', 'product', 'cloud-ops'];
  var DEPT_LABELS = {
    qa: 'QA', seo: 'SEO', ada: 'ADA',
    compliance: 'Compliance', monetization: 'Monetization', product: 'Product',
    'cloud-ops': 'Cloud Ops'
  };
  var DEPT_SOURCES = {
    qa:           {url: 'qa-data.json',           scoreField: null},
    seo:          {url: 'seo-data.json',          scoreField: 'seo_score'},
    ada:          {url: 'ada-data.json',           scoreField: 'compliance_score'},
    compliance:   {url: 'compliance-data.json',    scoreField: 'compliance_score'},
    monetization: {url: 'monetization-data.json',  scoreField: 'monetization_readiness_score'},
    product:      {url: 'product-data.json',       scoreField: 'product_readiness_score'},
    'cloud-ops':  {url: 'cloud-ops-data.json',     scoreField: 'cloud_ops_score'}
  };
  var SEV_ORDER  = {critical: 0, high: 1, medium: 2, low: 3, info: 4};
  var EFFORT_ORDER = {easy: 0, moderate: 1, hard: 2};
  var STALE_MS = 24 * 60 * 60 * 1000;

  /* ── State ── */
  var orgData = null;
  var deptData = {};
  var deptErrors = {};
  var backlogData = null;
  var historyData = null;
  var taskQueueData = null;
  var selectedProduct = 'all';

  /* ── Helpers ── */

  function escapeHtml(s) {
    if (!s) return '';
    var d = document.createElement('div');
    d.appendChild(document.createTextNode(s));
    return d.innerHTML;
  }

  function scoreColor(s) {
    if (s == null) return 'gray';
    if (s >= 85) return 'green';
    if (s >= 65) return 'yellow';
    if (s >= 50) return 'orange';
    return 'red';
  }

  function scoreColorVar(s) {
    if (s == null) return 'var(--text-dim)';
    if (s >= 85) return 'var(--success)';
    if (s >= 65) return 'var(--medium)';
    if (s >= 50) return 'var(--high)';
    return 'var(--critical)';
  }

  function deriveQaScore(summary) {
    if (!summary) return null;
    var c = summary.critical || 0;
    var h = summary.high || 0;
    var m = summary.medium || 0;
    var l = summary.low || 0;
    return Math.max(0, Math.min(100, 100 - c * 15 - h * 8 - m * 3 - l));
  }

  function getRepoScore(dept, repoObj) {
    if (!repoObj || !repoObj.summary) return null;
    if (dept === 'qa') return deriveQaScore(repoObj.summary);
    var field = DEPT_SOURCES[dept].scoreField;
    if (!field) return null;
    var val = repoObj.summary[field];
    if (val == null) return null;
    if (typeof val !== 'number') return 'N/A';
    return val;
  }

  function timeAgo(dateStr) {
    if (!dateStr) return '--';
    var ms = Date.now() - new Date(dateStr).getTime();
    if (ms < 0) ms = 0;
    var min = Math.floor(ms / 60000);
    if (min < 1) return 'just now';
    if (min < 60) return min + ' min ago';
    var hrs = Math.floor(min / 60);
    if (hrs < 24) return hrs + 'h ago';
    return Math.floor(hrs / 24) + 'd ago';
  }

  function isStale(dateStr) {
    if (!dateStr) return true;
    return (Date.now() - new Date(dateStr).getTime()) > STALE_MS;
  }

  function getProductRepos(productKey) {
    if (!orgData || !orgData.products) return [];
    if (productKey === 'all') {
      var allRepos = {};
      DEPT_KEYS.forEach(function(dept) {
        if (deptData[dept] && deptData[dept].repos) {
          deptData[dept].repos.forEach(function(r) { allRepos[r.name] = true; });
        }
      });
      return Object.keys(allRepos).sort();
    }
    var prod = orgData.products.find(function(p) { return p.key === productKey; });
    return prod ? (prod.repos || []) : [];
  }

  function findRepo(dept, repoName) {
    if (!deptData[dept] || !deptData[dept].repos) return null;
    return deptData[dept].repos.find(function(r) { return r.name === repoName; }) || null;
  }

  function getAvgScore(dept) {
    var repos = getProductRepos(selectedProduct);
    if (repos.length === 0 && selectedProduct === 'all') {
      if (!deptData[dept] || !deptData[dept].repos) return null;
      repos = deptData[dept].repos.map(function(r) { return r.name; });
    }
    var scores = [];
    repos.forEach(function(repoName) {
      var s = getRepoScore(dept, findRepo(dept, repoName));
      if (typeof s === 'number') scores.push(s);
    });
    if (scores.length === 0) return null;
    return Math.round(scores.reduce(function(a, b) { return a + b; }, 0) / scores.length);
  }

  function getSparkline(dept) {
    if (!historyData || !historyData.snapshots) return [];
    var repos = getProductRepos(selectedProduct);
    return historyData.snapshots.slice(-5).map(function(snap) {
      if (!snap.scores) return null;
      var vals = [];
      if (repos.length === 0 && selectedProduct === 'all') {
        Object.keys(snap.scores).forEach(function(rk) {
          var v = snap.scores[rk][dept];
          if (typeof v === 'number') vals.push(v);
        });
      } else {
        repos.forEach(function(repoName) {
          var sk = Object.keys(snap.scores).find(function(k) {
            return k === repoName || k.replace(/-/g, '') === repoName.replace(/-/g, '');
          });
          if (sk && typeof snap.scores[sk][dept] === 'number') vals.push(snap.scores[sk][dept]);
        });
      }
      if (vals.length === 0) return null;
      return Math.round(vals.reduce(function(a, b) { return a + b; }, 0) / vals.length);
    });
  }

  function computeTrend(sparkVals, currentScore) {
    if (!sparkVals || sparkVals.length < 2 || currentScore == null) return {label: '', cls: ''};
    var prev = null;
    for (var i = sparkVals.length - 2; i >= 0; i--) {
      if (sparkVals[i] != null) { prev = sparkVals[i]; break; }
    }
    if (prev == null) return {label: '', cls: ''};
    var delta = currentScore - prev;
    if (delta > 0) return {label: '+' + delta + ' from last scan', cls: 'trend-up'};
    if (delta < 0) return {label: delta + ' from last scan', cls: 'trend-down'};
    return {label: 'no change', cls: ''};
  }

  function getLatestTimestamp() {
    var latest = null;
    DEPT_KEYS.forEach(function(dept) {
      if (deptData[dept] && deptData[dept].generated_at) {
        var t = new Date(deptData[dept].generated_at).getTime();
        if (!latest || t > latest) latest = t;
      }
    });
    return latest ? new Date(latest).toISOString() : null;
  }

  /* ── DOM builders (safe — no innerHTML with user data) ── */

  function clearChildren(el) {
    while (el.firstChild) el.removeChild(el.firstChild);
  }

  function el(tag, attrs, children) {
    var node = document.createElement(tag);
    if (attrs) {
      Object.keys(attrs).forEach(function(k) {
        if (k === 'className') node.className = attrs[k];
        else if (k === 'textContent') node.textContent = attrs[k];
        else if (k === 'style') node.setAttribute('style', attrs[k]);
        else if (k === 'hidden') { if (attrs[k]) node.hidden = true; }
        else node.setAttribute(k, attrs[k]);
      });
    }
    if (children) {
      children.forEach(function(c) {
        if (typeof c === 'string') node.appendChild(document.createTextNode(c));
        else if (c) node.appendChild(c);
      });
    }
    return node;
  }

  function buildSparkline(sparkVals) {
    var wrap = el('div', {className: 'sparkline'});
    if (!sparkVals || sparkVals.length === 0) return wrap;
    sparkVals.forEach(function(v) {
      var bar = document.createElement('span');
      if (v == null) {
        bar.setAttribute('style', 'height:2px;opacity:0.15;');
      } else {
        var h = Math.max(3, Math.round((v / 100) * 20));
        bar.setAttribute('style', 'height:' + h + 'px;');
      }
      wrap.appendChild(bar);
    });
    return wrap;
  }

  /* ── Render functions ── */

  function renderSkeletons() {
    var row = document.getElementById('scoreRow');
    clearChildren(row);
    DEPT_KEYS.forEach(function(dept) {
      var card = el('div', {className: 'score-card', 'data-dept': dept, role: 'button', tabindex: '0', 'aria-label': DEPT_LABELS[dept] + ' department details'}, [
        el('div', {className: 'score-card-header'}, [
          el('span', {className: 'score-card-name', textContent: DEPT_LABELS[dept]})
        ]),
        el('div', {className: 'skeleton skeleton-score'}),
        el('div', {className: 'skeleton skeleton-trend'})
      ]);
      row.appendChild(card);
    });

    var mb = document.getElementById('matrixBody');
    clearChildren(mb);
    for (var i = 0; i < 4; i++) {
      var tr = el('tr', null, [
        el('td', null, [el('div', {className: 'skeleton', style: 'width:80px;height:14px;'})])
      ]);
      DEPT_KEYS.forEach(function() {
        tr.appendChild(el('td', null, [el('div', {className: 'skeleton skeleton-cell'})]));
      });
      mb.appendChild(tr);
    }

    var na = document.getElementById('needsAttention');
    clearChildren(na);
    for (var j = 0; j < 5; j++) {
      na.appendChild(el('div', {className: 'skeleton skeleton-row'}));
    }
  }

  function renderScoreCards() {
    var row = document.getElementById('scoreRow');
    clearChildren(row);

    DEPT_KEYS.forEach(function(dept) {
      var card = el('div', {className: 'score-card', 'data-dept': dept, role: 'button', tabindex: '0', 'aria-label': DEPT_LABELS[dept] + ' department details'});

      if (deptErrors[dept]) {
        card.appendChild(
          el('div', {className: 'score-card-header'}, [
            el('span', {className: 'score-card-name', textContent: DEPT_LABELS[dept]})
          ])
        );
        card.appendChild(
          el('div', {className: 'score-card-error', textContent: 'Failed to load ' + DEPT_LABELS[dept] + ' data'})
        );
        row.appendChild(card);
        return;
      }

      var score = getAvgScore(dept);
      var sparkVals = getSparkline(dept);
      var trend = computeTrend(sparkVals, score);
      var colorStyle = score != null ? 'color:' + scoreColorVar(score) : 'color:var(--text-dim)';

      card.appendChild(
        el('div', {className: 'score-card-header'}, [
          el('span', {className: 'score-card-name', textContent: DEPT_LABELS[dept]}),
          buildSparkline(sparkVals)
        ])
      );
      card.appendChild(
        el('div', {className: 'score-card-value', style: colorStyle, textContent: score != null ? String(score) : '--'})
      );
      if (trend.label) {
        card.appendChild(
          el('div', {className: 'score-card-trend' + (trend.cls ? ' ' + trend.cls : ''), textContent: trend.label})
        );
      }
      row.appendChild(card);
    });

    var forgejo = (opsStatusCache && opsStatusCache.forgejo) || null;
    if (forgejo) {
      var forgejoCard = el('div', {className: 'score-card'});
      forgejoCard.appendChild(
        el('div', {className: 'score-card-header'}, [
          el('span', {className: 'score-card-name', textContent: 'Forgejo'}),
          el('span', {className: 'ops-badge ' + (forgejo.healthy ? 'ops-badge-healthy' : 'ops-badge-unavailable'), textContent: forgejo.healthy ? 'Healthy' : 'Offline'})
        ])
      );
      forgejoCard.appendChild(
        el('div', {
          className: 'score-card-value',
          style: 'color:' + (forgejo.healthy ? 'var(--success)' : 'var(--critical)'),
          textContent: forgejo.repo_count != null ? String(forgejo.repo_count) : '--'
        })
      );
      forgejoCard.appendChild(
        el('div', {
          className: 'score-card-trend',
          textContent: 'Repos mirrored locally' + (forgejo.runner_count != null ? ' · runners ' + forgejo.runner_count : '')
        })
      );
      if (forgejo.base_url) {
        forgejoCard.appendChild(
          el('a', {
            className: 'score-card-link',
            href: forgejo.base_url,
            target: '_blank',
            rel: 'noreferrer',
            textContent: 'Open Forgejo'
          })
        );
      }
      row.appendChild(forgejoCard);
    }
  }

  function renderMatrix() {
    var mb = document.getElementById('matrixBody');
    clearChildren(mb);

    var repoNames;
    if (selectedProduct === 'all') {
      // Gather all unique repo names across all dept data
      var allRepos = {};
      DEPT_KEYS.forEach(function(dept) {
        if (deptData[dept] && deptData[dept].repos) {
          deptData[dept].repos.forEach(function(r) { allRepos[r.name] = true; });
        }
      });
      repoNames = Object.keys(allRepos).sort();
    } else {
      repoNames = getProductRepos(selectedProduct);
    }

    if (repoNames.length === 0) {
      var tr = el('tr', null, [
        el('td', {colspan: '7', style: 'text-align:center;color:var(--text-dim);padding:1.5rem;', textContent: 'No repos found for this product'})
      ]);
      mb.appendChild(tr);
      return;
    }

    repoNames.forEach(function(repoName) {
      var tr = el('tr');
      tr.appendChild(el('td', {textContent: repoName}));

      DEPT_KEYS.forEach(function(dept) {
        var td = el('td');
        var repoObj = findRepo(dept, repoName);
        var score = getRepoScore(dept, repoObj);

        if (score == null) {
          var gray = el('span', {className: 'cell gray'});
          gray.appendChild(document.createTextNode('\u2014'));
          td.appendChild(gray);
        } else if (score === 'N/A') {
          var na = el('span', {className: 'cell gray', textContent: 'N/A'});
          td.appendChild(na);
        } else {
          var cls = 'cell ' + scoreColor(score);
          var cell = el('span', {className: cls, textContent: String(score), 'data-dept': dept, 'data-repo': repoName, role: 'button', tabindex: '0', 'aria-label': DEPT_LABELS[dept] + ' score ' + score + ' for ' + repoName});
          td.appendChild(cell);
        }
        tr.appendChild(td);
      });

      mb.appendChild(tr);
    });
  }

  function renderNeedsAttention() {
    var container = document.getElementById('needsAttention');
    clearChildren(container);

    var productRepos = getProductRepos(selectedProduct);

    // Collect findings across all depts
    var allFindings = [];
    DEPT_KEYS.forEach(function(dept) {
      if (!deptData[dept] || !deptData[dept].repos) return;
      deptData[dept].repos.forEach(function(repo) {
        if (selectedProduct !== 'all' && productRepos.indexOf(repo.name) === -1) return;
        if (!repo.findings) return;
        repo.findings.forEach(function(f) {
          // Lookup backlog audit_count
          var auditCount = 0;
          if (backlogData && backlogData.findings) {
            var keys = Object.keys(backlogData.findings);
            for (var bi = 0; bi < keys.length; bi++) {
              var bf = backlogData.findings[keys[bi]];
              if (bf.current_finding &&
                  bf.current_finding.department === (f.department || dept) &&
                  bf.current_finding.repo === (f.repo || repo.name) &&
                  bf.current_finding.title === f.title) {
                auditCount = bf.audit_count || 0;
                break;
              }
            }
          }

          allFindings.push({
            department: f.department || dept,
            severity: f.severity || 'info',
            title: f.title || '',
            repo: f.repo || repo.name,
            effort: f.effort || 'moderate',
            fixable_by_agent: f.fixable_by_agent || false,
            audit_count: auditCount,
            id: f.id || '',
            file: f.file || ''
          });
        });
      });
    });

    // Sort: severity asc, audit_count desc, effort asc
    allFindings.sort(function(a, b) {
      var sa = SEV_ORDER[a.severity] != null ? SEV_ORDER[a.severity] : 99;
      var sb = SEV_ORDER[b.severity] != null ? SEV_ORDER[b.severity] : 99;
      if (sa !== sb) return sa - sb;
      if (b.audit_count !== a.audit_count) return b.audit_count - a.audit_count;
      var ea = EFFORT_ORDER[a.effort] != null ? EFFORT_ORDER[a.effort] : 99;
      var eb = EFFORT_ORDER[b.effort] != null ? EFFORT_ORDER[b.effort] : 99;
      return ea - eb;
    });

    var top = allFindings.slice(0, 15);

    if (top.length === 0) {
      container.appendChild(el('div', {className: 'empty-state', textContent: 'No findings match current filters'}));
      return;
    }

    top.forEach(function(f) {
      var titleSpan = el('span', {className: 'finding-title'});
      titleSpan.appendChild(document.createTextNode(f.title));
      if (f.fixable_by_agent) {
        titleSpan.appendChild(el('span', {className: 'ai-badge', textContent: 'AI fixable'}));
      }

      var row = el('div', {
        className: 'finding-row',
        'data-finding': f.id,
        'data-dept': f.department,
        'data-repo': f.repo,
        role: 'button',
        tabindex: '0',
        'aria-label': f.severity + ' ' + f.title
      }, [
        el('span', {className: 'finding-dept', textContent: DEPT_LABELS[f.department] || f.department}),
        el('span', {className: 'sev ' + f.severity, textContent: f.severity}),
        titleSpan,
        el('span', {className: 'finding-repo', textContent: f.repo}),
        el('span', {className: 'finding-effort', textContent: f.effort})
      ]);

      container.appendChild(row);
    });
  }

  function updateTimestamp() {
    var ts = getLatestTimestamp();
    var scanEl = document.getElementById('lastScan');
    var staleEl = document.getElementById('staleWarning');
    if (ts) {
      scanEl.textContent = 'Last scan: ' + timeAgo(ts);
      staleEl.hidden = !isStale(ts);
    } else {
      scanEl.textContent = 'Last scan: --';
      staleEl.hidden = true;
    }
  }

  /* ── URL Deep Linking ── */

  function readProductFromUrl() {
    var params = new URLSearchParams(window.location.search);
    return params.get('product') || 'all';
  }

  function updateUrl() {
    var params = new URLSearchParams(window.location.search);
    if (selectedProduct === 'all') {
      params.delete('product');
    } else {
      params.set('product', selectedProduct);
    }
    var qs = params.toString();
    history.replaceState(null, '', window.location.pathname + (qs ? '?' + qs : ''));
  }

  function populateProductSelector() {
    var sel = document.getElementById('productSelect');
    clearChildren(sel);

    if (!orgData || !orgData.products) {
      sel.appendChild(el('option', {value: 'all', textContent: 'All Products'}));
      return;
    }

    orgData.products.forEach(function(p) {
      var opt = el('option', {value: p.key, textContent: p.name});
      if (p.key === selectedProduct) opt.selected = true;
      sel.appendChild(opt);
    });

    sel.addEventListener('change', function() {
      selectedProduct = sel.value;
      updateUrl();
      renderAll();
    });
  }

  function renderAll() {
    renderScoreCards();
    renderMatrix();
    renderNeedsAttention();
    updateTimestamp();
  }

  /* ── Data Loading ── */

  function fetchJson(url) {
    return fetch(url + '?t=' + Date.now()).then(function(r) {
      if (!r.ok) throw new Error('HTTP ' + r.status);
      return r.json();
    });
  }

  function loadAll() {
    renderSkeletons();

    var promises = [];

    promises.push(
      fetchJson('org-data.json').then(function(d) { orgData = d; }).catch(function() { orgData = null; })
    );
    promises.push(
      fetchJson('score-history.json').then(function(d) { historyData = d; }).catch(function() { historyData = null; })
    );
    promises.push(
      fetchJson('backlog.json').then(function(d) { backlogData = d; }).catch(function() { backlogData = null; })
    );
    promises.push(
      fetchJson('task-queue.json').then(function(d) { taskQueueData = d; }).catch(function() { taskQueueData = null; })
    );

    DEPT_KEYS.forEach(function(dept) {
      promises.push(
        fetchJson(DEPT_SOURCES[dept].url)
          .then(function(d) { deptData[dept] = d; deptErrors[dept] = false; })
          .catch(function() { deptData[dept] = null; deptErrors[dept] = true; })
      );
    });

    Promise.all(promises).then(function() {
      selectedProduct = readProductFromUrl();
      populateProductSelector();
      renderAll();
    });
  }

  /* ── Init ── */
  loadAll();

  /* ─────────────────────────────────────────────────────────
     SLIDE-OVER PANEL SYSTEM (Tasks 7-9)
     ───────────────────────────────────────────────────────── */

  /* ── Panel State ── */
  var panelDept = null;        // currently open department
  var panelRepoFilter = null;  // null = all repos for product
  var panelFindings = [];      // filtered findings for current panel
  var panelAllFindings = [];   // unfiltered findings for current panel
  var currentFinding = null;   // finding shown in detail panel

  var filterSeverity = 'all';
  var filterStatus   = 'all';
  var filterEffort   = 'all';
  var filterAiFixable = false;
  var filterSearch   = '';
  var filterPillar   = 'all';

  /* ── SHA-256 hash (matches Python: sha256 of dept:repo:title:file lowercase trimmed, first 16 hex) ── */
  function findingHash(dept, repo, title, filePath) {
    var key = [dept, repo, title, filePath].map(function(s) { return (s || '').trim().toLowerCase(); }).join(':');
    // Use SubtleCrypto if available, else fallback to simple hash
    // For sync use, implement a simple sha256
    return simplesha256(key).substring(0, 16);
  }

  // Minimal synchronous SHA-256 (matches Python hashlib.sha256)
  function simplesha256(msg) {
    function rotr(x, n) { return (x >>> n) | (x << (32 - n)); }
    function ch(x, y, z) { return (x & y) ^ (~x & z); }
    function maj(x, y, z) { return (x & y) ^ (x & z) ^ (y & z); }
    function sigma0(x) { return rotr(x, 2) ^ rotr(x, 13) ^ rotr(x, 22); }
    function sigma1(x) { return rotr(x, 6) ^ rotr(x, 11) ^ rotr(x, 25); }
    function gamma0(x) { return rotr(x, 7) ^ rotr(x, 18) ^ (x >>> 3); }
    function gamma1(x) { return rotr(x, 17) ^ rotr(x, 19) ^ (x >>> 10); }
    var K = [
      0x428a2f98,0x71374491,0xb5c0fbcf,0xe9b5dba5,0x3956c25b,0x59f111f1,0x923f82a4,0xab1c5ed5,
      0xd807aa98,0x12835b01,0x243185be,0x550c7dc3,0x72be5d74,0x80deb1fe,0x9bdc06a7,0xc19bf174,
      0xe49b69c1,0xefbe4786,0x0fc19dc6,0x240ca1cc,0x2de92c6f,0x4a7484aa,0x5cb0a9dc,0x76f988da,
      0x983e5152,0xa831c66d,0xb00327c8,0xbf597fc7,0xc6e00bf3,0xd5a79147,0x06ca6351,0x14292967,
      0x27b70a85,0x2e1b2138,0x4d2c6dfc,0x53380d13,0x650a7354,0x766a0abb,0x81c2c92e,0x92722c85,
      0xa2bfe8a1,0xa81a664b,0xc24b8b70,0xc76c51a3,0xd192e819,0xd6990624,0xf40e3585,0x106aa070,
      0x19a4c116,0x1e376c08,0x2748774c,0x34b0bcb5,0x391c0cb3,0x4ed8aa4a,0x5b9cca4f,0x682e6ff3,
      0x748f82ee,0x78a5636f,0x84c87814,0x8cc70208,0x90befffa,0xa4506ceb,0xbef9a3f7,0xc67178f2
    ];
    var bytes = [];
    for (var i = 0; i < msg.length; i++) {
      var c = msg.charCodeAt(i);
      if (c < 0x80) bytes.push(c);
      else if (c < 0x800) { bytes.push(0xc0 | (c >> 6)); bytes.push(0x80 | (c & 0x3f)); }
      else { bytes.push(0xe0 | (c >> 12)); bytes.push(0x80 | ((c >> 6) & 0x3f)); bytes.push(0x80 | (c & 0x3f)); }
    }
    var bitLen = bytes.length * 8;
    bytes.push(0x80);
    while (bytes.length % 64 !== 56) bytes.push(0);
    bytes.push(0, 0, 0, 0);
    bytes.push((bitLen >>> 24) & 0xff, (bitLen >>> 16) & 0xff, (bitLen >>> 8) & 0xff, bitLen & 0xff);
    var H0=0x6a09e667,H1=0xbb67ae85,H2=0x3c6ef372,H3=0xa54ff53a,H4=0x510e527f,H5=0x9b05688c,H6=0x1f83d9ab,H7=0x5be0cd19;
    for (var off = 0; off < bytes.length; off += 64) {
      var W = new Array(64);
      for (var t = 0; t < 16; t++) W[t] = (bytes[off+t*4]<<24)|(bytes[off+t*4+1]<<16)|(bytes[off+t*4+2]<<8)|bytes[off+t*4+3];
      for (var t = 16; t < 64; t++) W[t] = (gamma1(W[t-2]) + W[t-7] + gamma0(W[t-15]) + W[t-16]) | 0;
      var a=H0,b=H1,c=H2,d=H3,e=H4,f=H5,g=H6,h=H7;
      for (var t = 0; t < 64; t++) {
        var T1 = (h + sigma1(e) + ch(e,f,g) + K[t] + W[t]) | 0;
        var T2 = (sigma0(a) + maj(a,b,c)) | 0;
        h=g; g=f; f=e; e=(d+T1)|0; d=c; c=b; b=a; a=(T1+T2)|0;
      }
      H0=(H0+a)|0; H1=(H1+b)|0; H2=(H2+c)|0; H3=(H3+d)|0; H4=(H4+e)|0; H5=(H5+f)|0; H6=(H6+g)|0; H7=(H7+h)|0;
    }
    function hex32(v) { return ('00000000' + (v >>> 0).toString(16)).slice(-8); }
    return hex32(H0)+hex32(H1)+hex32(H2)+hex32(H3)+hex32(H4)+hex32(H5)+hex32(H6)+hex32(H7);
  }

  /* ── Dept-specific 4th stat ── */
  function getDeptSpecificStat(dept, repos) {
    var label, value, color;
    switch (dept) {
      case 'qa':
        // Fixed count
        var fixedCount = 0;
        repos.forEach(function(r) {
          if (r.findings) r.findings.forEach(function(f) {
            if ((f.status || '').toLowerCase() === 'fixed') fixedCount++;
          });
        });
        label = 'Fixed'; value = String(fixedCount); color = 'var(--success)';
        break;
      case 'seo':
        // Overall seo_score (avg) — exclude non-numeric (N/A) scores
        var seoScores = [];
        repos.forEach(function(r) {
          if (r.summary && typeof r.summary.seo_score === 'number') seoScores.push(r.summary.seo_score);
        });
        var avgSeo = seoScores.length > 0 ? Math.round(seoScores.reduce(function(a,b){return a+b;},0)/seoScores.length) : null;
        label = 'SEO Score'; value = avgSeo != null ? String(avgSeo) : '--'; color = avgSeo != null ? scoreColorVar(avgSeo) : 'var(--text-dim)';
        break;
      case 'ada':
        // WCAG level
        var adaScores = [];
        var hasCritHigh = false, hasMed = false;
        repos.forEach(function(r) {
          var s = getRepoScore('ada', r);
          if (s != null) adaScores.push(s);
          if (r.findings) r.findings.forEach(function(f) {
            var sev = (f.severity || '').toLowerCase();
            if (sev === 'critical' || sev === 'high') hasCritHigh = true;
            if (sev === 'medium') hasMed = true;
          });
        });
        var avgAda = adaScores.length > 0 ? Math.round(adaScores.reduce(function(a,b){return a+b;},0)/adaScores.length) : null;
        var wcagLevel = '--';
        if (avgAda != null) {
          if (avgAda >= 95 && !hasCritHigh && !hasMed) wcagLevel = 'AAA';
          else if (avgAda >= 70 && !hasCritHigh) wcagLevel = 'AA';
          else if (avgAda >= 40) wcagLevel = 'A';
          else wcagLevel = 'Below A';
        }
        label = 'WCAG Level'; value = wcagLevel; color = wcagLevel === 'AAA' ? 'var(--success)' : wcagLevel === 'AA' ? 'var(--medium)' : 'var(--high)';
        break;
      case 'compliance':
      case 'privacy':
        // Framework count
        var frameworks = {};
        repos.forEach(function(r) {
          if (r.findings) r.findings.forEach(function(f) {
            if (f.category) frameworks[f.category] = true;
            if (f.framework) frameworks[f.framework] = true;
          });
        });
        var fwCount = Object.keys(frameworks).length;
        label = 'Frameworks'; value = String(fwCount); color = 'var(--text)';
        break;
      case 'monetization':
        // Revenue estimate sum
        var revSum = 0;
        repos.forEach(function(r) {
          if (r.findings) r.findings.forEach(function(f) {
            if (f.revenue_estimate) {
              var num = parseFloat(String(f.revenue_estimate).replace(/[^0-9.]/g, ''));
              if (!isNaN(num)) revSum += num;
            }
          });
        });
        label = 'Revenue Est.'; value = revSum > 0 ? '$' + revSum.toLocaleString() : '$0'; color = 'var(--success)';
        break;
      case 'product':
        // Backlog items count
        var backlogCount = 0;
        repos.forEach(function(r) {
          if (r.findings) backlogCount += r.findings.length;
        });
        label = 'Backlog Items'; value = String(backlogCount); color = 'var(--text)';
        break;
      default:
        label = 'Items'; value = '--'; color = 'var(--text-dim)';
    }
    return {label: label, value: value, color: color};
  }

  /* ── Gather findings for a department ── */
  function gatherDeptFindings(dept, repoFilter) {
    var source = dept === 'privacy' ? deptData['privacy'] : deptData[dept];
    if (!source || !source.repos) return [];
    var productRepos = getProductRepos(selectedProduct);
    var findings = [];
    source.repos.forEach(function(repo) {
      if (repoFilter && repo.name !== repoFilter) return;
      if (!repoFilter && selectedProduct !== 'all' && productRepos.indexOf(repo.name) === -1) return;
      if (!repo.findings) return;
      repo.findings.forEach(function(f) {
        findings.push({
          department: f.department || dept,
          severity: (f.severity || 'info').toLowerCase(),
          title: f.title || '',
          repo: f.repo || repo.name,
          effort: (f.effort || 'unknown').toLowerCase(),
          fixable_by_agent: f.fixable_by_agent || false,
          id: f.id || '',
          file: f.file || '',
          line: f.line || null,
          description: f.description || '',
          evidence: f.evidence || '',
          impact: f.impact || '',
          fix_suggestion: f.fix_suggestion || '',
          category: f.category || '',
          status: (f.status || 'open').toLowerCase(),
          revenue_estimate: f.revenue_estimate || null,
          framework: f.framework || ''
        });
      });
    });
    // Sort by severity desc
    findings.sort(function(a, b) {
      var sa = SEV_ORDER[a.severity] != null ? SEV_ORDER[a.severity] : 99;
      var sb = SEV_ORDER[b.severity] != null ? SEV_ORDER[b.severity] : 99;
      return sa - sb;
    });
    return findings;
  }

  /* ── Apply client-side filters ── */
  function applyFilters() {
    var q = filterSearch.toLowerCase();
    panelFindings = panelAllFindings.filter(function(f) {
      if (filterSeverity !== 'all' && f.severity !== filterSeverity) return false;
      if (filterStatus !== 'all' && f.status !== filterStatus.toLowerCase().replace(/ /g, '_')) return false;
      if (filterEffort !== 'all' && f.effort !== filterEffort.toLowerCase()) return false;
      if (filterAiFixable && !f.fixable_by_agent) return false;
      if (filterPillar !== 'all' && f.pillar !== filterPillar) return false;
      if (q) {
        var haystack = [f.title, f.description, f.file, f.id, f.repo].join(' ').toLowerCase();
        if (haystack.indexOf(q) === -1) return false;
      }
      return true;
    });
    renderFindingsList();
  }

  /* ── Render the findings list inside slideover body ── */
  function renderFindingsList() {
    var listContainer = document.getElementById('slideoverFindings');
    if (!listContainer) return;
    clearChildren(listContainer);

    if (panelFindings.length === 0) {
      listContainer.appendChild(el('div', {className: 'empty-state', textContent: 'No findings match current filters'}));
      return;
    }

    panelFindings.forEach(function(f) {
      var titleSpan = el('span', {className: 'finding-title'});
      titleSpan.appendChild(document.createTextNode(f.title));
      if (f.fixable_by_agent) {
        titleSpan.appendChild(el('span', {className: 'ai-badge', textContent: 'AI fixable'}));
      }

      var row = el('div', {className: 'finding-row'}, [
        el('span', {className: 'sev ' + f.severity, textContent: f.severity}),
        el('span', {className: 'finding-repo', textContent: f.repo}),
        titleSpan,
        el('span', {className: 'finding-effort', textContent: f.effort})
      ]);

      row.addEventListener('click', function() { openFindingDetail(f); });
      listContainer.appendChild(row);
    });
  }

  /* ── Render Department Panel (Task 8) ── */
  function renderDeptPanel(dept, repoFilter) {
    var body = document.getElementById('slideoverBody');
    clearChildren(body);

    // Get filtered repos
    var source = dept === 'privacy' ? deptData['privacy'] : deptData[dept];
    var repos = [];
    if (source && source.repos) {
      var productRepos = getProductRepos(selectedProduct);
      source.repos.forEach(function(r) {
        if (repoFilter && r.name !== repoFilter) return;
        if (!repoFilter && selectedProduct !== 'all' && productRepos.indexOf(r.name) === -1) return;
        repos.push(r);
      });
    }

    // Compute stats — exclude non-numeric (N/A) scores
    var scores = [];
    repos.forEach(function(r) {
      var s = getRepoScore(dept === 'privacy' ? 'compliance' : dept, r);
      if (typeof s === 'number') scores.push(s);
    });
    var avgScore = scores.length > 0 ? Math.round(scores.reduce(function(a,b){return a+b;},0)/scores.length) : null;

    var totalFindings = 0;
    var aiFixableCount = 0;
    repos.forEach(function(r) {
      if (r.findings) {
        totalFindings += r.findings.length;
        r.findings.forEach(function(f) {
          if (f.fixable_by_agent) aiFixableCount++;
        });
      }
    });

    var deptStat = getDeptSpecificStat(dept, repos);

    // Stats row
    var statsRow = el('div', {className: 'slideover-score-row'}, [
      el('div', {className: 'slideover-stat'}, [
        el('div', {className: 'slideover-stat-label', textContent: 'Score'}),
        el('div', {className: 'slideover-stat-value', style: 'color:' + (avgScore != null ? scoreColorVar(avgScore) : 'var(--text-dim)'), textContent: avgScore != null ? String(avgScore) : '--'})
      ]),
      el('div', {className: 'slideover-stat'}, [
        el('div', {className: 'slideover-stat-label', textContent: 'Findings'}),
        el('div', {className: 'slideover-stat-value', textContent: String(totalFindings)})
      ]),
      el('div', {className: 'slideover-stat'}, [
        el('div', {className: 'slideover-stat-label', textContent: 'AI Fixable'}),
        el('div', {className: 'slideover-stat-value', style: 'color:#6c5ce7', textContent: String(aiFixableCount)})
      ]),
      el('div', {className: 'slideover-stat'}, [
        el('div', {className: 'slideover-stat-label', textContent: deptStat.label}),
        el('div', {className: 'slideover-stat-value', style: 'color:' + deptStat.color, textContent: deptStat.value})
      ])
    ]);
    body.appendChild(statsRow);

    // Pillar breakdown (Cloud Ops only)
    if (dept === 'cloud-ops' && repos.length > 0) {
      var pillars = [
        {key: 'cost_optimization', label: 'Cost', weight: '30%'},
        {key: 'security', label: 'Security', weight: '25%'},
        {key: 'reliability', label: 'Reliability', weight: '20%'},
        {key: 'performance_efficiency', label: 'Performance', weight: '10%'},
        {key: 'operational_excellence', label: 'Ops Excellence', weight: '10%'},
        {key: 'sustainability', label: 'Sustainability', weight: '5%'}
      ];
      var pillarContainer = el('div', {style: 'margin-bottom:1.25rem'});
      var pillarAvgs = {};
      pillars.forEach(function(p) {
        var vals = [];
        repos.forEach(function(r) {
          var ps = r.pillar_scores || (r.summary || {}).pillar_scores;
          if (ps && ps[p.key] != null) vals.push(ps[p.key]);
        });
        pillarAvgs[p.key] = vals.length > 0 ? Math.round(vals.reduce(function(a,b){return a+b;},0)/vals.length) : null;
      });
      pillars.forEach(function(p) {
        var score = pillarAvgs[p.key];
        var color = score != null ? scoreColorVar(score) : 'var(--text-dim)';
        var bar = el('div', {style: 'display:flex;align-items:center;gap:0.5rem;margin-bottom:0.4rem;font-size:0.8rem'}, [
          el('span', {style: 'width:100px;color:var(--text-dim)', textContent: p.label + ' (' + p.weight + ')'}),
          el('div', {style: 'flex:1;height:8px;background:var(--surface-2);border-radius:4px;overflow:hidden'}, [
            el('div', {style: 'height:100%;width:' + (score || 0) + '%;background:' + color + ';border-radius:4px;transition:width 0.3s'})
          ]),
          el('span', {style: 'width:32px;text-align:right;font-weight:600;color:' + color, textContent: score != null ? String(score) : '--'})
        ]);
        pillarContainer.appendChild(bar);
      });
      body.appendChild(pillarContainer);
    }

    // Findings list container
    var listContainer = el('div', {id: 'slideoverFindings'});
    body.appendChild(listContainer);

    // Gather + apply
    panelAllFindings = gatherDeptFindings(dept, repoFilter);
    applyFilters();
  }

  /* ── Render Finding Detail (Task 9) ── */
  function renderFindingDetail(finding) {
    var body = document.getElementById('detailBody');
    clearChildren(body);
    var findingTask = null;
    var findingKey = finding.hash || findingHash(finding.department, finding.repo, finding.title, finding.file);
    if (taskQueueData && taskQueueData.tasks) {
      findingTask = taskQueueData.tasks.find(function(task) {
        var source = task.source_finding || {};
        return task.repo === finding.repo && (
          source.hash === findingKey ||
          (source.department === finding.department &&
            ((source.id && finding.id && source.id === finding.id) ||
             (source.file === finding.file && task.title === finding.title)))
        );
      }) || null;
    }

    // AI Fix Banner
    if (finding.fixable_by_agent) {
      var cmdText = 'make fix TARGET=' + (finding.repo || 'repo');
      var cmdSpan = el('span', {className: 'ai-fix-cmd', title: 'Click to copy', textContent: cmdText});
      cmdSpan.addEventListener('click', function(e) {
        e.stopPropagation();
        if (navigator.clipboard) {
          navigator.clipboard.writeText(cmdText);
          cmdSpan.textContent = 'Copied!';
          setTimeout(function() { cmdSpan.textContent = cmdText; }, 1500);
        }
      });

      var bannerTextDiv = el('div', {className: 'ai-fix-banner-text'});
      var strong = el('strong', {textContent: 'AI can fix this.'});
      bannerTextDiv.appendChild(strong);
      bannerTextDiv.appendChild(document.createTextNode(' The Back Office fix agent can resolve this automatically. '));
      bannerTextDiv.appendChild(cmdSpan);

      body.appendChild(el('div', {className: 'ai-fix-banner'}, [
        el('span', {className: 'ai-fix-banner-icon', textContent: '\u26A1'}),
        bannerTextDiv
      ]));
    }

    var actionCard = el('div', {className: 'detail-section'});
    actionCard.appendChild(el('div', {className: 'detail-section-title', textContent: 'Approval Workflow'}));
    actionCard.appendChild(el('div', {className: 'detail-text', textContent: findingTask
      ? 'This finding is already in the human approval queue.'
      : 'Queue this finding for a human-reviewed fix decision. Nothing runs automatically.'}));
    var queueBtn = el('button', {
      className: 'ops-btn ops-btn-primary',
      textContent: findingTask ? 'Already Queued' : 'Queue for Approval',
      disabled: !!findingTask
    });
    queueBtn.addEventListener('click', function() { queueFindingForApproval(finding, queueBtn); });
    actionCard.appendChild(queueBtn);
    if (findingTask) {
      actionCard.appendChild(el('div', {
        className: 'detail-text',
        style: 'margin-top:0.65rem;color:var(--text-dim);',
        textContent: 'Queue status: ' + (findingTask.status || 'pending_approval')
      }));
    }
    body.appendChild(actionCard);

    // Description
    if (finding.description) {
      body.appendChild(el('div', {className: 'detail-section'}, [
        el('div', {className: 'detail-section-title', textContent: 'Description'}),
        el('div', {className: 'detail-text', textContent: finding.description})
      ]));
    }

    // Evidence
    if (finding.evidence) {
      body.appendChild(el('div', {className: 'detail-section'}, [
        el('div', {className: 'detail-section-title', textContent: 'Evidence'}),
        el('div', {className: 'detail-code', textContent: finding.evidence})
      ]));
    }

    // Impact
    if (finding.impact) {
      body.appendChild(el('div', {className: 'detail-section'}, [
        el('div', {className: 'detail-section-title', textContent: 'Impact'}),
        el('div', {className: 'detail-text', textContent: finding.impact})
      ]));
    }

    // File
    if (finding.file) {
      var fileText = finding.file;
      if (finding.line) fileText += ':' + finding.line;
      body.appendChild(el('div', {className: 'detail-section'}, [
        el('div', {className: 'detail-section-title', textContent: 'File'}),
        el('div', {className: 'detail-file'}, [
          el('span', {className: 'detail-file-icon', textContent: '\uD83D\uDCC4'}),
          document.createTextNode(fileText)
        ])
      ]));
    }

    // Recommended Fix
    if (finding.fix_suggestion) {
      body.appendChild(el('div', {className: 'detail-section'}, [
        el('div', {className: 'detail-fix-title', textContent: 'Recommended Fix'}),
        el('div', {className: 'detail-fix', textContent: finding.fix_suggestion})
      ]));
    }

    // Backlog Info
    if (backlogData && backlogData.findings) {
      var hash = findingHash(finding.department, finding.repo, finding.title, finding.file);
      var entry = backlogData.findings[hash];
      if (entry) {
        var firstSeen = entry.first_seen ? new Date(entry.first_seen).toLocaleDateString() : 'Unknown';
        var lastSeen = entry.last_seen ? new Date(entry.last_seen).toLocaleDateString() : 'Unknown';
        var auditCount = entry.audit_count || 1;
        var infoText = 'First seen: ' + firstSeen + '  \u00B7  Seen in ' + auditCount + ' audit' + (auditCount !== 1 ? 's' : '') + '  \u00B7  Last seen: ' + lastSeen;
        body.appendChild(el('div', {className: 'detail-section'}, [
          el('div', {className: 'detail-section-title', textContent: 'Backlog'}),
          el('div', {className: 'backlog-info', textContent: infoText})
        ]));
      }
    }
  }

  /* ── Panel open/close functions ── */
  function openDeptPanel(department, repo) {
    panelDept = department;
    panelRepoFilter = repo || null;

    // Reset filters
    filterSeverity = 'all';
    filterStatus   = 'all';
    filterEffort   = 'all';
    filterAiFixable = false;
    filterSearch   = '';

    // Reset filter UI
    var sevSel = document.getElementById('filterSeverity');
    var statusSel = document.getElementById('filterStatus');
    var effortSel = document.getElementById('filterEffort');
    var aiToggle = document.getElementById('filterAiFixable');
    var searchInput = document.getElementById('filterSearch');
    if (sevSel) sevSel.value = 'all';
    if (statusSel) statusSel.value = 'all';
    if (effortSel) effortSel.value = 'all';
    if (aiToggle) aiToggle.classList.remove('active');
    if (searchInput) searchInput.value = '';

    // Manage pillar filter dropdown (Cloud Ops only)
    filterPillar = 'all';
    var existingPillar = document.getElementById('filterPillar');
    if (existingPillar) existingPillar.remove();

    if (department === 'cloud-ops') {
      var pillarSelect = document.createElement('select');
      pillarSelect.className = 'filter-select';
      pillarSelect.id = 'filterPillar';
      pillarSelect.setAttribute('aria-label', 'Filter by pillar');
      [
        {value: 'all', label: 'All Pillars'},
        {value: 'cost_optimization', label: 'Cost'},
        {value: 'security', label: 'Security'},
        {value: 'reliability', label: 'Reliability'},
        {value: 'performance_efficiency', label: 'Performance'},
        {value: 'operational_excellence', label: 'Ops Excellence'},
        {value: 'sustainability', label: 'Sustainability'}
      ].forEach(function(opt) {
        var option = document.createElement('option');
        option.value = opt.value;
        option.textContent = opt.label;
        pillarSelect.appendChild(option);
      });
      pillarSelect.addEventListener('change', function() { filterPillar = this.value; applyFilters(); });
      var filterBar = document.querySelector('.filters-bar');
      var searchInput = document.getElementById('filterSearch');
      if (filterBar && searchInput) {
        filterBar.insertBefore(pillarSelect, searchInput);
      }
    }

    // Header
    var deptLabel = DEPT_LABELS[department] || department;
    document.getElementById('slideoverTitle').textContent = deptLabel;

    // Subtitle
    var source = department === 'privacy' ? deptData['privacy'] : deptData[department];
    if (repo) {
      var repoObj = source && source.repos ? source.repos.find(function(r) { return r.name === repo; }) : null;
      var fCount = repoObj && repoObj.findings ? repoObj.findings.length : 0;
      document.getElementById('slideoverSubtitle').textContent = repo + ' \u2014 ' + fCount + ' finding' + (fCount !== 1 ? 's' : '');
    } else {
      var productRepos = getProductRepos(selectedProduct);
      var repoCount = 0, findingCount = 0;
      if (source && source.repos) {
        source.repos.forEach(function(r) {
          if (selectedProduct !== 'all' && productRepos.indexOf(r.name) === -1) return;
          repoCount++;
          findingCount += (r.findings ? r.findings.length : 0);
        });
      }
      document.getElementById('slideoverSubtitle').textContent = repoCount + ' repo' + (repoCount !== 1 ? 's' : '') + ' \u00B7 ' + findingCount + ' finding' + (findingCount !== 1 ? 's' : '');
    }

    // Render content
    renderDeptPanel(department, repo);

    // Open panels
    document.getElementById('overlay').classList.add('open');
    document.getElementById('slideover').classList.add('open');
    closeFindingDetail();

    // Update URL
    var params = new URLSearchParams(window.location.search);
    if (selectedProduct !== 'all') params.set('product', selectedProduct);
    params.set('dept', department);
    if (repo) params.set('repo', repo);
    var qs = params.toString();
    history.replaceState(null, '', window.location.pathname + (qs ? '?' + qs : ''));
  }

  function closeDeptPanel() {
    document.getElementById('overlay').classList.remove('open');
    document.getElementById('slideover').classList.remove('open');
    document.getElementById('detailPanel').classList.remove('open');
    panelDept = null;
    panelRepoFilter = null;
    currentFinding = null;

    // Remove dept/repo from URL, keep product
    var params = new URLSearchParams(window.location.search);
    params.delete('dept');
    params.delete('repo');
    if (selectedProduct === 'all') params.delete('product');
    else params.set('product', selectedProduct);
    var qs = params.toString();
    history.replaceState(null, '', window.location.pathname + (qs ? '?' + qs : ''));
  }

  function openFindingDetail(finding) {
    currentFinding = finding;

    // Populate header
    var headerLeft = document.getElementById('detailHeaderLeft');
    clearChildren(headerLeft);

    // ID
    headerLeft.appendChild(el('div', {className: 'detail-id', textContent: finding.id || findingHash(finding.department, finding.repo, finding.title, finding.file)}));

    // Title
    headerLeft.appendChild(el('div', {className: 'detail-title', id: 'detailTitle', textContent: finding.title}));

    // Meta tags
    var meta = el('div', {className: 'detail-meta'});
    meta.appendChild(el('span', {className: 'sev ' + finding.severity, textContent: finding.severity}));
    if (finding.category) meta.appendChild(el('span', {className: 'detail-tag', textContent: finding.category}));
    if (finding.effort) meta.appendChild(el('span', {className: 'detail-tag', textContent: finding.effort}));
    if (finding.fixable_by_agent) {
      meta.appendChild(el('span', {className: 'detail-tag', style: 'background:rgba(108,92,231,0.1);color:#6c5ce7;border-color:rgba(108,92,231,0.2);', textContent: 'AI Fixable'}));
    }
    headerLeft.appendChild(meta);

    // Render body
    renderFindingDetail(finding);

    // Open
    document.getElementById('detailPanel').classList.add('open');
  }

  function closeFindingDetail() {
    document.getElementById('detailPanel').classList.remove('open');
    currentFinding = null;
  }

  /* ── Keyboard & overlay handlers ── */
  document.addEventListener('keydown', function(e) {
    if (e.key === 'Escape') {
      if (document.getElementById('detailPanel').classList.contains('open')) {
        closeFindingDetail();
      } else if (document.getElementById('slideover').classList.contains('open')) {
        closeDeptPanel();
      }
    }
  });

  document.getElementById('overlay').addEventListener('click', function() {
    closeDeptPanel();
  });

  document.getElementById('slideoverCloseBtn').addEventListener('click', function() {
    closeDeptPanel();
  });

  document.getElementById('detailCloseBtn').addEventListener('click', function() {
    closeFindingDetail();
  });

  /* ── Wire score card clicks + keyboard ── */
  function handleScoreCardActivate(e) {
    var card = e.target.closest('.score-card');
    if (!card) return;
    var dept = card.getAttribute('data-dept');
    if (dept) openDeptPanel(dept, null);
  }
  document.getElementById('scoreRow').addEventListener('click', handleScoreCardActivate);
  document.getElementById('scoreRow').addEventListener('keydown', function(e) {
    if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); handleScoreCardActivate(e); }
  });

  /* ── Wire matrix cell clicks + keyboard ── */
  function handleCellActivate(e) {
    var cell = e.target.closest('.cell');
    if (!cell || cell.classList.contains('gray')) return;
    var dept = cell.getAttribute('data-dept');
    var repo = cell.getAttribute('data-repo');
    if (dept) openDeptPanel(dept, repo);
  }
  document.getElementById('matrixTable').addEventListener('click', handleCellActivate);
  document.getElementById('matrixTable').addEventListener('keydown', function(e) {
    if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); handleCellActivate(e); }
  });

  /* ── Wire needs attention finding clicks + keyboard ── */
  function handleFindingActivate(e) {
    var row = e.target.closest('.finding-row');
    if (!row) return;
    var dept = row.getAttribute('data-dept');
    var repo = row.getAttribute('data-repo');
    var findingId = row.getAttribute('data-finding');

    // Try to find the actual finding object
    if (dept && deptData[dept] && deptData[dept].repos) {
      var found = null;
      deptData[dept].repos.forEach(function(r) {
        if (found) return;
        if (repo && r.name !== repo) return;
        if (r.findings) r.findings.forEach(function(f) {
          if (found) return;
          if (findingId && (f.id === findingId)) { found = f; found.repo = found.repo || r.name; found.department = found.department || dept; }
        });
      });

      // If not found by id, try by title from the row
      if (!found) {
        var titleEl = row.querySelector('.finding-title');
        var titleText = titleEl ? titleEl.textContent.replace('AI fixable', '').trim() : '';
        deptData[dept].repos.forEach(function(r) {
          if (found) return;
          if (repo && r.name !== repo) return;
          if (r.findings) r.findings.forEach(function(f) {
            if (found) return;
            if (f.title === titleText) {
              found = {
                department: f.department || dept,
                severity: (f.severity || 'info').toLowerCase(),
                title: f.title || '',
                repo: f.repo || r.name,
                effort: (f.effort || 'unknown').toLowerCase(),
                fixable_by_agent: f.fixable_by_agent || false,
                id: f.id || '',
                file: f.file || '',
                line: f.line || null,
                description: f.description || '',
                evidence: f.evidence || '',
                impact: f.impact || '',
                fix_suggestion: f.fix_suggestion || '',
                category: f.category || '',
                status: (f.status || 'open').toLowerCase()
              };
            }
          });
        });
      }

      if (found) {
        // Open the dept panel first, then detail
        openDeptPanel(dept, repo || found.repo);
        openFindingDetail(found);
        return;
      }
    }

    // Fallback: just open dept panel
    if (dept) openDeptPanel(dept, repo);
  }
  document.getElementById('needsAttention').addEventListener('click', handleFindingActivate);
  document.getElementById('needsAttention').addEventListener('keydown', function(e) {
    if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); handleFindingActivate(e); }
  });

  /* ── Wire filter controls ── */
  document.getElementById('filterSeverity').addEventListener('change', function() {
    filterSeverity = this.value;
    applyFilters();
  });
  document.getElementById('filterStatus').addEventListener('change', function() {
    filterStatus = this.value;
    applyFilters();
  });
  document.getElementById('filterEffort').addEventListener('change', function() {
    filterEffort = this.value;
    applyFilters();
  });
  document.getElementById('filterAiFixable').addEventListener('click', function() {
    this.classList.toggle('active');
    filterAiFixable = this.classList.contains('active');
    applyFilters();
  });
  document.getElementById('filterSearch').addEventListener('input', function() {
    filterSearch = this.value;
    applyFilters();
  });

  /* ── Deep link: open panel from URL on load ── */
  function checkDeepLink() {
    var params = new URLSearchParams(window.location.search);
    var dept = params.get('dept');
    var repo = params.get('repo');
    if (dept && DEPT_KEYS.indexOf(dept) !== -1) {
      openDeptPanel(dept, repo || null);
    }
  }

  // Hook into renderAll to check deep links after first data load
  var _origRenderAll = renderAll;
  var _deepLinkChecked = false;
  renderAll = function() {
    _origRenderAll();
    if (!_deepLinkChecked) {
      _deepLinkChecked = true;
      checkDeepLink();
    }
  };

  /* ── Load privacy data source ── */
  fetchJson('privacy-data.json')
    .then(function(d) { deptData['privacy'] = d; })
    .catch(function() { deptData['privacy'] = null; });

  /* ─────────────────────────────────────────────────────────
     SUPPORT PANELS — Jobs, FAQ, Docs  (Task 10)
     ───────────────────────────────────────────────────────── */

  /* ── Support panel mode tracking ── */
  var supportPanelMode = null; // 'jobs' | 'faq' | 'docs'

  /* ── Show/hide the filters bar and swap body padding ── */
  function setFilterBarVisible(visible) {
    var fb = document.querySelector('.filters-bar');
    if (fb) fb.style.display = visible ? '' : 'none';
    var body = document.getElementById('slideoverBody');
    if (body) {
      if (!visible) {
        body.style.padding = '0';
        body.classList.add('support-panel-body');
      } else {
        body.style.padding = '';
        body.classList.remove('support-panel-body');
      }
    }
  }

  /* ── Close helper that also resets support mode ── */
  function closePanel() {
    supportPanelMode = null;
    setFilterBarVisible(true);
    closeDeptPanel();
  }

  /* ────────────────────────────────────────────────
     JOBS PANEL
  ──────────────────────────────────────────────── */

  function formatElapsed(sec) {
    if (!sec) return '--';
    if (sec < 60) return sec + 's';
    return Math.floor(sec / 60) + 'm ' + (sec % 60) + 's';
  }

  function buildJobsRunEl(run) {
    var status = (run.status || 'unknown').toLowerCase();
    var repoName = run.repo_name || run.target || 'unknown';

    var startedAt = run.started_at ? new Date(run.started_at) : null;
    var finishedAt = run.finished_at ? new Date(run.finished_at) : null;
    var dateStr = startedAt ? startedAt.toLocaleString() : '--';
    var elapsed = '';
    if (startedAt && finishedAt) {
      var diffSec = Math.round((finishedAt - startedAt) / 1000);
      elapsed = ' \u00B7 ' + formatElapsed(diffSec);
    }

    var wrap = document.createElement('div');
    wrap.className = 'jobs-run';

    // Header
    var header = document.createElement('div');
    header.className = 'jobs-run-header';

    var left = document.createElement('div');
    var title = document.createElement('div');
    title.className = 'jobs-run-title';
    title.textContent = repoName;
    var meta = document.createElement('div');
    meta.className = 'jobs-run-meta';
    meta.textContent = dateStr + elapsed;
    left.appendChild(title);
    left.appendChild(meta);

    var badge = document.createElement('span');
    badge.className = 'jobs-run-status ' + status;
    badge.textContent = status;

    header.appendChild(left);
    header.appendChild(badge);
    wrap.appendChild(header);

    // Department rows
    if (run.jobs && typeof run.jobs === 'object') {
      var deptList = document.createElement('div');
      deptList.className = 'jobs-dept-list';

      Object.keys(run.jobs).forEach(function(deptKey) {
        var job = run.jobs[deptKey];
        var row = document.createElement('div');
        row.className = 'jobs-dept-row';

        var dname = document.createElement('span');
        dname.className = 'jobs-dept-name';
        dname.textContent = DEPT_LABELS[deptKey] || deptKey;

        var dstatus = document.createElement('span');
        dstatus.className = 'jobs-dept-status ' + (job.status || 'unknown').toLowerCase();
        dstatus.textContent = job.status || 'unknown';

        var dscore = document.createElement('span');
        dscore.className = 'jobs-dept-score';
        dscore.style.color = job.score != null ? scoreColorVar(job.score) : 'var(--text-dim)';
        dscore.textContent = job.score != null ? String(job.score) : '--';

        var dfindings = document.createElement('span');
        dfindings.className = 'jobs-dept-findings';
        dfindings.textContent = job.findings_count != null ? job.findings_count + ' findings' : '';

        var delapsed = document.createElement('span');
        delapsed.className = 'jobs-dept-elapsed';
        delapsed.textContent = job.elapsed_seconds != null ? formatElapsed(job.elapsed_seconds) : '';

        row.appendChild(dname);
        row.appendChild(dstatus);
        row.appendChild(dscore);
        row.appendChild(dfindings);
        row.appendChild(delapsed);
        deptList.appendChild(row);
      });

      wrap.appendChild(deptList);
    }

    return wrap;
  }

  function renderJobsPanel() {
    var body = document.getElementById('slideoverBody');
    clearChildren(body);

    var wrap = document.createElement('div');
    wrap.className = 'support-content-wrap';
    wrap.style.padding = '1.25rem 1.5rem';

    // Load current job + history
    var currentP = fetch('.jobs.json?t=' + Date.now())
      .then(function(r) { return r.ok ? r.json() : null; })
      .catch(function() { return null; });

    var historyP = fetch('.jobs-history.json?t=' + Date.now())
      .then(function(r) { return r.ok ? r.json() : null; })
      .catch(function() { return null; });

    var loading = document.createElement('div');
    loading.className = 'support-loading';
    loading.textContent = 'Loading jobs\u2026';
    wrap.appendChild(loading);
    body.appendChild(wrap);

    Promise.all([currentP, historyP]).then(function(results) {
      var current = results[0];
      var history = results[1] || [];

      clearChildren(wrap);

      // Combine: current run at top, then history (deduplicated by run_id)
      var runs = [];
      var seenIds = {};

      if (current && current.run_id) {
        runs.push(current);
        seenIds[current.run_id] = true;
      }

      if (Array.isArray(history)) {
        history.slice().reverse().forEach(function(r) {
          if (!seenIds[r.run_id]) {
            runs.push(r);
            seenIds[r.run_id] = true;
          }
        });
      }

      if (runs.length === 0) {
        var empty = document.createElement('div');
        empty.className = 'empty-state';
        empty.textContent = 'No jobs found. Run an audit to see job history here.';
        wrap.appendChild(empty);
        return;
      }

      // Section label
      var label = document.createElement('div');
      label.className = 'section-label';
      label.style.marginBottom = '0.75rem';
      label.textContent = runs.length + ' run' + (runs.length !== 1 ? 's' : '');
      wrap.appendChild(label);

      runs.forEach(function(run) {
        wrap.appendChild(buildJobsRunEl(run));
      });
    });
  }

  function openJobsPanel() {
    supportPanelMode = 'jobs';

    document.getElementById('slideoverTitle').textContent = 'Jobs';
    document.getElementById('slideoverSubtitle').textContent = 'Recent audit runs';

    setFilterBarVisible(false);
    renderJobsPanel();

    document.getElementById('overlay').classList.add('open');
    document.getElementById('slideover').classList.add('open');
    closeFindingDetail();
  }

  /* ────────────────────────────────────────────────
     FAQ PANEL
  ──────────────────────────────────────────────── */

  var _faqHtml = null;

  function renderFaqPanel() {
    var body = document.getElementById('slideoverBody');
    clearChildren(body);

    var wrap = document.createElement('div');
    wrap.className = 'support-content-wrap';
    wrap.style.padding = '1.25rem 1.5rem';

    if (_faqHtml) {
      wrap.innerHTML = _faqHtml;
      body.appendChild(wrap);
      return;
    }

    var loading = document.createElement('div');
    loading.className = 'support-loading';
    loading.textContent = 'Loading FAQ\u2026';
    wrap.appendChild(loading);
    body.appendChild(wrap);

    fetch('faq-content.html?t=' + Date.now())
      .then(function(r) { return r.ok ? r.text() : Promise.reject('HTTP ' + r.status); })
      .then(function(html) {
        _faqHtml = html;
        clearChildren(wrap);
        wrap.innerHTML = html;
      })
      .catch(function(err) {
        clearChildren(wrap);
        var errEl = document.createElement('div');
        errEl.className = 'empty-state';
        errEl.textContent = 'Could not load FAQ content: ' + err;
        wrap.appendChild(errEl);
      });
  }

  function openFaqPanel() {
    supportPanelMode = 'faq';

    document.getElementById('slideoverTitle').textContent = 'FAQ';
    document.getElementById('slideoverSubtitle').textContent = 'How scores are calculated';

    setFilterBarVisible(false);
    renderFaqPanel();

    document.getElementById('overlay').classList.add('open');
    document.getElementById('slideover').classList.add('open');
    closeFindingDetail();
  }

  /* ────────────────────────────────────────────────
     DOCS PANEL
  ──────────────────────────────────────────────── */

  var _docsHtml = null;

  function renderDocsPanel() {
    var body = document.getElementById('slideoverBody');
    clearChildren(body);

    var wrap = document.createElement('div');
    wrap.className = 'support-content-wrap';
    wrap.style.padding = '1.25rem 1.5rem';

    if (_docsHtml) {
      wrap.innerHTML = _docsHtml;
      body.appendChild(wrap);
      // Re-run the docs tab script if needed
      var scripts = wrap.querySelectorAll('script');
      scripts.forEach(function(s) {
        var ns = document.createElement('script');
        ns.textContent = s.textContent;
        document.body.appendChild(ns);
        document.body.removeChild(ns);
      });
      return;
    }

    var loading = document.createElement('div');
    loading.className = 'support-loading';
    loading.textContent = 'Loading documentation\u2026';
    wrap.appendChild(loading);
    body.appendChild(wrap);

    fetch('docs-content.html?t=' + Date.now())
      .then(function(r) { return r.ok ? r.text() : Promise.reject('HTTP ' + r.status); })
      .then(function(html) {
        _docsHtml = html;
        clearChildren(wrap);
        wrap.innerHTML = html;
        // Execute inline scripts
        var scripts = wrap.querySelectorAll('script');
        scripts.forEach(function(s) {
          var ns = document.createElement('script');
          ns.textContent = s.textContent;
          document.body.appendChild(ns);
          document.body.removeChild(ns);
        });
      })
      .catch(function(err) {
        clearChildren(wrap);
        var errEl = document.createElement('div');
        errEl.className = 'empty-state';
        errEl.textContent = 'Could not load documentation: ' + err;
        wrap.appendChild(errEl);
      });
  }

  function openDocsPanel() {
    supportPanelMode = 'docs';

    document.getElementById('slideoverTitle').textContent = 'Documentation';
    document.getElementById('slideoverSubtitle').textContent = 'CLI, CI/CD, GitHub reference';

    setFilterBarVisible(false);
    renderDocsPanel();

    document.getElementById('overlay').classList.add('open');
    document.getElementById('slideover').classList.add('open');
    closeFindingDetail();
  }

  /* ── Wire top-bar support buttons ── */
  document.getElementById('jobsBtn').addEventListener('click', openJobsPanel);
  document.getElementById('faqBtn').addEventListener('click', openFaqPanel);
  document.getElementById('docsBtn').addEventListener('click', openDocsPanel);

  /* ── Override closeDeptPanel to restore filter bar when closing support panels ── */
  var _origCloseDeptPanel = closeDeptPanel;
  closeDeptPanel = function() {
    supportPanelMode = null;
    opsStopPolling();
    setFilterBarVisible(true);
    _origCloseDeptPanel();
  };

  /* ─────────────────────────────────────────────────────────
     OPERATIONS PANEL
     ───────────────────────────────────────────────────────── */

  var opsActiveTab = 'jobs';
  var opsPollingTimer = null;
  var opsStatusCache = null;
  var migrationPlanData = null;
  var remediationPlanData = null;

  /* ── Helpers ── */

  function opsCopyToClipboard(text, btnEl) {
    if (navigator.clipboard) {
      navigator.clipboard.writeText(text).then(function() {
        var orig = btnEl.textContent;
        btnEl.textContent = 'Copied!';
        setTimeout(function() { btnEl.textContent = orig; }, 1500);
      });
    }
  }

  function opsBadgeClass(status) {
    var s = (status || '').toLowerCase();
    if (s === 'running') return 'ops-badge ops-badge-running';
    if (s === 'complete' || s === 'done') return 'ops-badge ops-badge-complete';
    if (s === 'failed') return 'ops-badge ops-badge-failed';
    if (s === 'healthy') return 'ops-badge ops-badge-healthy';
    if (s === 'unavailable' || s === 'not configured') return 'ops-badge ops-badge-unavailable';
    return 'ops-badge ops-badge-idle';
  }

  function opsFeedback(container, msg, isError) {
    var fb = container.querySelector('.ops-feedback');
    if (!fb) {
      fb = el('div', {className: 'ops-feedback', 'aria-live': 'polite', role: 'status'});
      container.appendChild(fb);
    }
    fb.className = 'ops-feedback ' + (isError ? 'error' : 'success');
    fb.textContent = msg;
    fb.style.display = 'block';
    setTimeout(function() { fb.style.display = 'none'; }, 5000);
  }

  function opsFormatElapsed(seconds) {
    if (!seconds && seconds !== 0) return '\u2014';
    var m = Math.floor(seconds / 60);
    var s = seconds % 60;
    if (m === 0) return s + 's';
    return m + 'm ' + (s < 10 ? '0' : '') + s + 's';
  }

  /* ── Stop polling ── */
  function opsStopPolling() {
    if (opsPollingTimer) {
      clearInterval(opsPollingTimer);
      opsPollingTimer = null;
    }
  }

  /* ── Tab switching ── */
  function opsShowTab(name) {
    opsActiveTab = name;
    var wrap = document.getElementById('opsTabsWrap');
    if (!wrap) return;
    wrap.querySelectorAll('.ops-tab').forEach(function(t) {
      var isActive = t.getAttribute('data-tab') === name;
      t.classList.toggle('active', isActive);
      t.setAttribute('aria-selected', isActive ? 'true' : 'false');
    });
    wrap.parentElement.querySelectorAll('.ops-section').forEach(function(s) {
      s.classList.toggle('active', s.id === 'ops-sec-' + name);
    });

    // Start/stop polling based on tab
    opsStopPolling();
    if (name === 'jobs') {
      opsRefreshLiveJobs();
      opsPollingTimer = setInterval(opsRefreshLiveJobs, 5000);
    } else if (name === 'remediation') {
      opsRenderRemediationTab();
    } else if (name === 'migration') {
      opsRenderMigrationTab();
    }
  }

  /* ── Build command string ── */
  function opsBuildAuditCmd(target, depts, mode) {
    var base = 'cd /home/merm/projects/back-office && ';
    if (mode === 'full') return base + 'make full-scan TARGET=' + target;
    if (mode === 'sequential') return base + 'make audit-all TARGET=' + target;
    return base + 'make audit-all-parallel TARGET=' + target;
  }

  function refreshTaskQueueCache() {
    return fetch('/api/tasks?t=' + Date.now())
      .then(function(r) { return r.ok ? r.json() : Promise.reject('HTTP ' + r.status); })
      .then(function(data) {
        taskQueueData = data;
        if (opsStatusCache) opsStatusCache.task_queue = data;
        return data;
      });
  }

  function refreshMigrationPlanCache() {
    return fetch('/api/migration-plan?t=' + Date.now())
      .then(function(r) { return r.ok ? r.json() : Promise.reject('HTTP ' + r.status); })
      .then(function(data) {
        migrationPlanData = data;
        return data;
      });
  }

  function refreshRemediationPlanCache() {
    return fetch('/api/remediation-plan?t=' + Date.now())
      .then(function(r) { return r.ok ? r.json() : Promise.reject('HTTP ' + r.status); })
      .then(function(data) {
        remediationPlanData = data;
        return data;
      });
  }

  function queueFindingForApproval(finding, btn) {
    if (!finding || !finding.title || !finding.repo) return;
    var findingPayload = Object.assign({}, finding, {
      hash: finding.hash || findingHash(finding.department, finding.repo, finding.title, finding.file)
    });
    if (btn) {
      btn.disabled = true;
      btn.textContent = 'Queueing…';
    }
    fetch('/api/tasks/queue-finding', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({finding: findingPayload, by: 'dashboard'})
    })
    .then(function(r) { return r.json().then(function(d) { return {ok: r.ok, data: d}; }); })
    .then(function(res) {
      return refreshTaskQueueCache()
        .catch(function() { return null; })
        .then(function() {
          if (currentFinding && currentFinding.repo === finding.repo && currentFinding.title === finding.title && currentFinding.file === finding.file) {
            currentFinding = findingPayload;
            renderFindingDetail(currentFinding);
          }
          if (btn) {
            btn.disabled = res.ok || res.data.created === false;
            btn.textContent = res.ok ? 'Queued' : (res.data.created === false ? 'Already Queued' : 'Queue for Approval');
          }
        });
    })
    .catch(function(err) {
      if (btn) {
        btn.disabled = false;
        btn.textContent = 'Queue for Approval';
      }
      if (currentFinding && currentFinding.repo === finding.repo && currentFinding.title === finding.title && currentFinding.file === finding.file) {
        var body = document.getElementById('detailBody');
        if (body) {
          body.insertBefore(el('div', {className: 'detail-text', style: 'color:var(--critical);margin-bottom:0.75rem;', textContent: 'Failed to queue for approval: ' + err}), body.firstChild);
        }
      }
    });
  }

  /* ════════════════════════════════════════════════
     TAB 1: LIVE JOBS
  ════════════════════════════════════════════════ */

  function opsRefreshLiveJobs() {
    fetch('/api/ops/status?t=' + Date.now())
      .then(function(r) { return r.ok ? r.json() : Promise.reject('HTTP ' + r.status); })
      .then(function(data) {
        opsStatusCache = data;
        opsRenderLiveJobs(data);
      })
      .catch(function() {
        // Silently fail — keep previous data
      });
  }

  function opsRenderLiveJobs(data) {
    var container = document.getElementById('ops-live-jobs');
    if (!container) return;
    clearChildren(container);

    // Transform API shape: data.jobs is a single run with .jobs dict, data.jobs_history is list of completed runs
    var currentRun = data.jobs || null;
    var history = data.jobs_history || [];

    // Build active jobs list from current run
    var active = [];
    if (currentRun && currentRun.jobs && (currentRun.status || '').toLowerCase() !== 'complete') {
      var repoName = currentRun.repo_name || currentRun.target || 'unknown';
      Object.keys(currentRun.jobs).forEach(function(deptKey) {
        var j = currentRun.jobs[deptKey];
        var elapsed = j.elapsed_seconds;
        if (!elapsed && j.started_at && !j.finished_at) {
          elapsed = Math.round((Date.now() - new Date(j.started_at).getTime()) / 1000);
        }
        active.push({
          department: DEPT_LABELS[deptKey] || deptKey,
          target: repoName,
          status: j.status || 'unknown',
          elapsed: elapsed || null,
          findings_count: j.findings_count,
          score: j.score
        });
      });
    }

    // Active jobs card
    var activeCard = el('div', {className: 'ops-card'});
    var runningCount = active.filter(function(j) { return (j.status || '').toLowerCase() === 'running'; }).length;
    var queuedCount = active.filter(function(j) { return (j.status || '').toLowerCase() === 'queued'; }).length;

    var headerDiv = el('div', {className: 'ops-card-header'}, [
      el('div', null, [
        el('div', {className: 'ops-card-title', textContent: 'Active Jobs'}),
        el('div', {className: 'ops-card-subtitle', textContent: runningCount + ' running, ' + queuedCount + ' queued'})
      ])
    ]);
    var refreshBtn = el('button', {className: 'ops-btn ops-btn-ghost ops-btn-sm', textContent: 'Refresh'});
    refreshBtn.addEventListener('click', opsRefreshLiveJobs);
    headerDiv.appendChild(refreshBtn);
    activeCard.appendChild(headerDiv);

    if (active.length === 0) {
      activeCard.appendChild(el('div', {style: 'padding:1rem;text-align:center;color:var(--text-dim);font-size:0.82rem;', textContent: 'No active jobs'}));
    } else {
      // Header row
      var headerRow = el('div', {className: 'ops-job-row', style: 'font-weight:600;color:var(--text-dim);font-size:0.68rem;text-transform:uppercase;letter-spacing:0.06em;'}, [
        el('span', {textContent: 'Department'}),
        el('span', {textContent: 'Target'}),
        el('span', {textContent: 'Status'}),
        el('span', {textContent: 'Elapsed'}),
        el('span')
      ]);
      activeCard.appendChild(headerRow);

      active.forEach(function(job) {
        var statusBadge = el('span', {className: opsBadgeClass(job.status), textContent: job.status || 'Unknown'});
        var progressEl = el('span');
        if ((job.status || '').toLowerCase() === 'running') {
          var bar = el('div', {className: 'ops-progress-bar'});
          // Estimate progress from elapsed time (rough: assume 5 min per dept audit)
          var pct = job.elapsed ? Math.min(95, Math.round((job.elapsed / 300) * 100)) : 10;
          var fill = el('div', {className: 'ops-progress-fill', style: 'width:' + pct + '%'});
          bar.appendChild(fill);
          progressEl.appendChild(bar);
        }

        var row = el('div', {className: 'ops-job-row'}, [
          el('span', {className: 'ops-job-dept', textContent: job.department || 'Unknown'}),
          el('span', {className: 'ops-job-target', textContent: job.target || 'Unknown'}),
          el('span', null, [statusBadge]),
          el('span', {className: 'ops-job-time', textContent: job.elapsed ? opsFormatElapsed(job.elapsed) : '\u2014'}),
          progressEl
        ]);
        activeCard.appendChild(row);
      });
    }
    container.appendChild(activeCard);

    // Recent completions from history
    var completedRuns = history.filter(function(r) {
      return (r.status || '').toLowerCase() === 'complete' || (r.status || '').toLowerCase() === 'failed';
    }).slice(0, 5);

    if (completedRuns.length > 0) {
      var recentCard = el('div', {className: 'ops-card'});
      recentCard.appendChild(el('div', {className: 'ops-card-header'}, [
        el('div', {className: 'ops-card-title', textContent: 'Recent Completions'})
      ]));

      completedRuns.forEach(function(run) {
        var repoName = run.repo_name || run.target || 'unknown';
        var statusBadge = el('span', {className: opsBadgeClass(run.status), textContent: run.status || 'Done'});

        // Compute total findings and elapsed
        var totalFindings = 0;
        var totalElapsed = 0;
        if (run.jobs) {
          Object.keys(run.jobs).forEach(function(dk) {
            var j = run.jobs[dk];
            if (j.findings_count) totalFindings += j.findings_count;
            if (j.elapsed_seconds) totalElapsed += j.elapsed_seconds;
          });
        }
        if (!totalElapsed && run.started_at && run.finished_at) {
          totalElapsed = Math.round((new Date(run.finished_at) - new Date(run.started_at)) / 1000);
        }

        var resultSpan = el('span', {style: 'font-size:0.72rem;color:' + ((run.status || '').toLowerCase() === 'failed' ? 'var(--critical)' : 'var(--success)') + ';'});
        resultSpan.textContent = totalFindings + ' findings';

        var deptCount = run.jobs ? Object.keys(run.jobs).length : 0;

        var row = el('div', {className: 'ops-job-row'}, [
          el('span', {className: 'ops-job-dept', textContent: deptCount + ' depts'}),
          el('span', {className: 'ops-job-target', textContent: repoName}),
          el('span', null, [statusBadge]),
          el('span', {className: 'ops-job-time', textContent: totalElapsed ? opsFormatElapsed(totalElapsed) : '\u2014'}),
          resultSpan
        ]);
        recentCard.appendChild(row);
      });
      container.appendChild(recentCard);
    }
  }

  /* ════════════════════════════════════════════════
     TAB 2: RUN AUDIT
  ════════════════════════════════════════════════ */

  function opsRenderAuditTab() {
    var container = document.getElementById('ops-run-audit');
    if (!container) return;
    clearChildren(container);

    var card = el('div', {className: 'ops-card'});
    card.appendChild(el('div', {className: 'ops-card-title', style: 'margin-bottom:1rem;', textContent: 'Run Audit'}));

    // Target selector
    var targetGroup = el('div', {className: 'ops-form-group'});
    targetGroup.appendChild(el('label', {className: 'ops-form-label', textContent: 'Target'}));
    var targetSelect = el('select', {className: 'ops-form-select', id: 'opsAuditTarget'});
    targetSelect.appendChild(el('option', {value: 'all', textContent: 'All targets'}));

    // Populate from cached status if available
    var targets = (opsStatusCache && opsStatusCache.targets) || [];
    if (targets.length === 0 && orgData && orgData.products) {
      orgData.products.forEach(function(p) {
        if (p.repos) p.repos.forEach(function(r) { if (targets.indexOf(r) === -1) targets.push(r); });
      });
    }
    targets.forEach(function(t) {
      var name = typeof t === 'string' ? t : (t.name || t.key || '');
      var path = typeof t === 'string' ? '/home/merm/projects/' + t : (t.path || '/home/merm/projects/' + name);
      if (name) {
        targetSelect.appendChild(el('option', {value: path, textContent: name}));
      }
    });
    targetGroup.appendChild(targetSelect);
    card.appendChild(targetGroup);

    // Department checkboxes
    var deptGroup = el('div', {className: 'ops-form-group'});
    deptGroup.appendChild(el('label', {className: 'ops-form-label', textContent: 'Departments'}));
    var deptWrap = el('div', {style: 'display:flex;gap:1rem;flex-wrap:wrap;'});
    var deptNames = ['QA', 'SEO', 'ADA', 'Compliance', 'Monetization', 'Product'];
    var deptKeysAudit = ['qa', 'seo', 'ada', 'compliance', 'monetization', 'product'];
    deptKeysAudit.forEach(function(dk, i) {
      var cb = el('input', {type: 'checkbox', 'data-dept': dk});
      cb.checked = true;
      var lbl = el('label', {className: 'ops-form-check'});
      lbl.appendChild(cb);
      lbl.appendChild(document.createTextNode(' ' + deptNames[i]));
      deptWrap.appendChild(lbl);
    });
    deptGroup.appendChild(deptWrap);
    card.appendChild(deptGroup);

    // Mode radio buttons
    var modeGroup = el('div', {className: 'ops-form-group'});
    modeGroup.appendChild(el('label', {className: 'ops-form-label', textContent: 'Mode'}));
    var modeWrap = el('div', {style: 'display:flex;gap:0.75rem;'});
    var modes = [
      {value: 'parallel', label: 'Parallel (2 waves)', checked: true},
      {value: 'sequential', label: 'Sequential'},
      {value: 'full', label: 'Full scan + fix'}
    ];
    modes.forEach(function(m) {
      var radio = el('input', {type: 'radio', name: 'opsAuditMode', value: m.value});
      if (m.checked) radio.checked = true;
      var lbl = el('label', {className: 'ops-form-check'});
      lbl.appendChild(radio);
      lbl.appendChild(document.createTextNode(' ' + m.label));
      modeWrap.appendChild(lbl);
    });
    modeGroup.appendChild(modeWrap);
    card.appendChild(modeGroup);

    // Start button + hint
    var actionRow = el('div', {style: 'display:flex;gap:0.75rem;align-items:center;margin-top:1.25rem;'});
    var startBtn = el('button', {className: 'ops-btn ops-btn-primary', textContent: 'Start Audit'});
    actionRow.appendChild(startBtn);
    actionRow.appendChild(el('span', {style: 'font-size:0.72rem;color:var(--text-dim);', textContent: 'or paste in terminal:'}));
    card.appendChild(actionRow);

    // Command box
    var cmdBox = el('div', {className: 'ops-cmd-box', id: 'opsAuditCmd'});
    var cmdText = el('span', {id: 'opsAuditCmdText', textContent: 'make audit-all-parallel TARGET=/home/merm/projects/...'});
    var copyBtn = el('button', {className: 'ops-cmd-copy', textContent: 'Copy'});
    cmdBox.appendChild(cmdText);
    cmdBox.appendChild(copyBtn);
    card.appendChild(cmdBox);

    container.appendChild(card);

    // Update command on form change
    function updateCmd() {
      var target = targetSelect.value;
      if (target === 'all') target = '/home/merm/projects';
      var modeRadio = card.querySelector('input[name="opsAuditMode"]:checked');
      var mode = modeRadio ? modeRadio.value : 'parallel';
      var cmd = opsBuildAuditCmd(target, [], mode);
      cmdText.textContent = cmd;
    }

    targetSelect.addEventListener('change', updateCmd);
    card.querySelectorAll('input[name="opsAuditMode"]').forEach(function(r) {
      r.addEventListener('change', updateCmd);
    });
    updateCmd();

    copyBtn.addEventListener('click', function() {
      opsCopyToClipboard(cmdText.textContent, copyBtn);
    });

    // Start audit handler
    startBtn.addEventListener('click', function() {
      startBtn.disabled = true;
      startBtn.textContent = 'Starting\u2026';

      var target = targetSelect.value;
      if (target === 'all') target = null;
      var checkedDepts = [];
      card.querySelectorAll('input[data-dept]:checked').forEach(function(cb) {
        checkedDepts.push(cb.getAttribute('data-dept'));
      });
      var modeRadio = card.querySelector('input[name="opsAuditMode"]:checked');
      var mode = modeRadio ? modeRadio.value : 'parallel';

      var payload = {departments: checkedDepts, mode: mode};
      if (target) payload.target = target;

      fetch('/api/ops/audit', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(payload)
      })
      .then(function(r) { return r.json().then(function(d) { return {ok: r.ok, data: d}; }); })
      .then(function(res) {
        startBtn.disabled = false;
        startBtn.textContent = 'Start Audit';
        if (res.ok) {
          opsFeedback(container, 'Audit started successfully. Switch to Live Jobs to monitor.', false);
        } else {
          opsFeedback(container, 'Error: ' + (res.data.error || 'Unknown error'), true);
        }
      })
      .catch(function(err) {
        startBtn.disabled = false;
        startBtn.textContent = 'Start Audit';
        opsFeedback(container, 'Network error: ' + err, true);
      });
    });
  }

  /* ════════════════════════════════════════════════
     TAB 3: APPROVAL QUEUE
  ════════════════════════════════════════════════ */

  function opsRenderApprovalTab() {
    var container = document.getElementById('ops-approval');
    if (!container) return;
    clearChildren(container);

    var queue = (opsStatusCache && opsStatusCache.task_queue) || taskQueueData || {summary: {}, tasks: []};
    var summary = queue.summary || {};
    var tasks = queue.tasks || [];
    var productSummary = summary.by_product || {};

    var statusGrid = el('div', {className: 'ops-overnight-status'});
    statusGrid.appendChild(el('div', {className: 'ops-overnight-stat'}, [
      el('div', {className: 'ops-overnight-stat-label', textContent: 'Pending Approval'}),
      el('div', {className: 'ops-overnight-stat-value', textContent: String(summary.pending_approval || 0)})
    ]));
    statusGrid.appendChild(el('div', {className: 'ops-overnight-stat'}, [
      el('div', {className: 'ops-overnight-stat-label', textContent: 'Ready Queue'}),
      el('div', {className: 'ops-overnight-stat-value', textContent: String((summary.by_status || {}).ready || 0)})
    ]));
    statusGrid.appendChild(el('div', {className: 'ops-overnight-stat'}, [
      el('div', {className: 'ops-overnight-stat-label', textContent: 'Ready For Review'}),
      el('div', {className: 'ops-overnight-stat-value', textContent: String(summary.ready_for_review || 0)})
    ]));
    statusGrid.appendChild(el('div', {className: 'ops-overnight-stat'}, [
      el('div', {className: 'ops-overnight-stat-label', textContent: 'Open Draft PRs'}),
      el('div', {className: 'ops-overnight-stat-value', textContent: String(summary.pr_open || 0)})
    ]));
    container.appendChild(statusGrid);

    var intro = el('div', {className: 'ops-card'});
    intro.appendChild(el('div', {className: 'ops-card-title', textContent: 'Human-Centered Approval'}));
    intro.appendChild(el('div', {className: 'ops-card-subtitle', textContent: 'Nothing runs unattended. Findings, fixes, product suggestions, mentorship plans, and PRs move only after explicit approval.'}));
    container.appendChild(intro);

    var productKeys = Object.keys(productSummary);
    if (productKeys.length > 0) {
      var productCard = el('div', {className: 'ops-card'});
      productCard.appendChild(el('div', {className: 'ops-card-title', style: 'margin-bottom:0.75rem;', textContent: 'Per-Product Backlog Visibility'}));
      productKeys.sort().forEach(function(productKey) {
        var stats = productSummary[productKey] || {};
        productCard.appendChild(el('div', {className: 'ops-cycle-row'}, [
          el('span', {className: 'ops-cycle-id', textContent: productKey}),
          el('span', {textContent: 'total ' + (stats.total || 0)}),
          el('span', {textContent: 'open ' + (stats.open || 0)}),
          el('span', {textContent: 'pending approval ' + (stats.pending_approval || 0)}),
          el('span', {textContent: 'done ' + (stats.done || 0)}),
          el('span', null, [el('span', {className: 'ops-badge ops-badge-idle', textContent: 'isolated'})])
        ]));
      });
      container.appendChild(productCard);
    }

    if (tasks.length === 0) {
      container.appendChild(el('div', {className: 'empty-state', textContent: 'No queued work yet. Use a finding detail or the product/mentor operator tools to create approval items.'}));
      return;
    }

    var queueCard = el('div', {className: 'ops-card'});
    queueCard.appendChild(el('div', {className: 'ops-card-title', style: 'margin-bottom:0.75rem;', textContent: 'Approval Queue'}));
    tasks.slice(0, 24).forEach(function(task) {
      var row = el('div', {className: 'ops-job-row', style: 'grid-template-columns: 1.1fr 1fr 0.8fr auto;align-items:start;'});
      var left = el('div');
      left.appendChild(el('div', {className: 'ops-job-target', textContent: task.title || task.id}));
      left.appendChild(el('div', {style: 'font-size:0.72rem;color:var(--text-dim);margin-top:0.25rem;', textContent: (task.repo || 'unknown repo') + ' · ' + (task.product_key || 'no product')}));
      row.appendChild(left);
      row.appendChild(el('span', {className: 'ops-job-dept', textContent: task.task_type || task.category || 'task'}));
      row.appendChild(el('span', null, [el('span', {className: opsBadgeClass(task.status), textContent: task.status || 'pending'})]));

      var actions = el('div', {style: 'display:flex;gap:0.5rem;flex-wrap:wrap;justify-content:flex-end;'});
      if (task.status === 'pending_approval') {
        var approveBtn = el('button', {className: 'ops-btn ops-btn-primary', textContent: task.task_type === 'product_suggestion' ? 'Approve & Add' : 'Approve'});
        approveBtn.addEventListener('click', function() {
          var endpoint = task.task_type === 'product_suggestion' ? '/api/ops/product/approve' : '/api/tasks/approve';
          fetch(endpoint, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({id: task.id, by: 'dashboard'})
          })
          .then(function(r) { return r.json().then(function(d) { return {ok: r.ok, data: d}; }); })
          .then(function(res) {
            opsFeedback(container, res.ok ? 'Approval recorded.' : ('Error: ' + (res.data.error || 'Unknown error')), !res.ok);
            if (res.ok) refreshTaskQueueCache().then(function() { opsRenderApprovalTab(); });
          });
        });
        actions.appendChild(approveBtn);
      }
      if (task.status === 'ready_for_review') {
        var prBtn = el('button', {className: 'ops-btn', textContent: 'Create Draft PR'});
        prBtn.addEventListener('click', function() {
          fetch('/api/tasks/request-pr', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({id: task.id, by: 'dashboard'})
          })
          .then(function(r) { return r.json().then(function(d) { return {ok: r.ok, data: d}; }); })
          .then(function(res) {
            opsFeedback(container, res.ok ? 'Draft PR created.' : ('Error: ' + (res.data.error || 'Unknown error')), !res.ok);
            if (res.ok) refreshTaskQueueCache().then(function() { opsRenderApprovalTab(); });
          });
        });
        actions.appendChild(prBtn);
      }
      if (task.status !== 'done' && task.status !== 'cancelled') {
        var cancelBtn = el('button', {className: 'ops-btn ops-btn-danger', textContent: 'Cancel'});
        cancelBtn.addEventListener('click', function() {
          fetch('/api/tasks/cancel', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({id: task.id, by: 'dashboard'})
          })
          .then(function(r) { return r.json().then(function(d) { return {ok: r.ok, data: d}; }); })
          .then(function(res) {
            opsFeedback(container, res.ok ? 'Task cancelled.' : ('Error: ' + (res.data.error || 'Unknown error')), !res.ok);
            if (res.ok) refreshTaskQueueCache().then(function() { opsRenderApprovalTab(); });
          });
        });
        actions.appendChild(cancelBtn);
      }
      row.appendChild(actions);
      queueCard.appendChild(row);
    });
    container.appendChild(queueCard);
  }

  /* ════════════════════════════════════════════════
     TAB 4: MIGRATION PLAN
  ════════════════════════════════════════════════ */

  function opsTargetLabel(value) {
    return {
      'gcp': 'GCP',
      'aws-new': 'AWS 404166437757',
      'hybrid': 'Hybrid',
      'defer': 'Defer'
    }[value] || value || 'Unset';
  }

  function opsRenderMigrationSummary(container, summary) {
    var grid = el('div', {className: 'ops-overnight-status'});
    grid.appendChild(el('div', {className: 'ops-overnight-stat'}, [
      el('div', {className: 'ops-overnight-stat-label', textContent: 'Completion'}),
      el('div', {className: 'ops-overnight-stat-value', textContent: String(summary.completion_pct || 0) + '%'})
    ]));
    grid.appendChild(el('div', {className: 'ops-overnight-stat'}, [
      el('div', {className: 'ops-overnight-stat-label', textContent: 'GCP Targets'}),
      el('div', {className: 'ops-overnight-stat-value', textContent: String(summary.gcp_targets || 0)})
    ]));
    grid.appendChild(el('div', {className: 'ops-overnight-stat'}, [
      el('div', {className: 'ops-overnight-stat-label', textContent: 'AWS Targets'}),
      el('div', {className: 'ops-overnight-stat-value', textContent: String(summary.aws_targets || 0)})
    ]));
    grid.appendChild(el('div', {className: 'ops-overnight-stat'}, [
      el('div', {className: 'ops-overnight-stat-label', textContent: 'Updated'}),
      el('div', {className: 'ops-overnight-stat-value', textContent: timeAgo(summary.updated_at)})
    ]));
    container.appendChild(grid);
  }

  function opsMigrationSaveItem(collection, item, statusSelect, targetSelect, notesInput, nextInput, saveBtn, container) {
    saveBtn.disabled = true;
    saveBtn.textContent = 'Saving…';
    fetch('/api/migration-plan/item/update', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        collection: collection,
        id: item.id,
        status: statusSelect ? statusSelect.value : item.status,
        target: targetSelect ? targetSelect.value : item.target,
        notes: notesInput ? notesInput.value : item.notes,
        next_step: nextInput ? nextInput.value : item.next_step
      })
    })
    .then(function(r) { return r.json().then(function(d) { return {ok: r.ok, data: d}; }); })
    .then(function(res) {
      saveBtn.disabled = false;
      saveBtn.textContent = 'Save';
      if (res.ok) {
        migrationPlanData = res.data.plan;
        opsFeedback(container, 'Migration plan updated.', false);
        opsRenderMigrationTab();
      } else {
        opsFeedback(container, 'Error: ' + (res.data.error || 'Unknown error'), true);
      }
    })
    .catch(function(err) {
      saveBtn.disabled = false;
      saveBtn.textContent = 'Save';
      opsFeedback(container, 'Network error: ' + err, true);
    });
  }

  function opsRenderMigrationCollection(container, title, collection, items, options) {
    var card = el('div', {className: 'ops-card'});
    card.appendChild(el('div', {className: 'ops-card-title', style: 'margin-bottom:0.75rem;', textContent: title}));
    if (!items || items.length === 0) {
      card.appendChild(el('div', {className: 'empty-state', textContent: 'No items yet.'}));
      container.appendChild(card);
      return;
    }

    items.forEach(function(item) {
      var row = el('div', {className: 'ops-job-row', style: 'grid-template-columns: 1.2fr 0.7fr 0.8fr auto; align-items:start;'});
      var left = el('div');
      left.appendChild(el('div', {className: 'ops-job-target', textContent: item.label || item.title || item.id}));
      var metaBits = [];
      if (item.phase) metaBits.push('phase ' + item.phase);
      if (item.priority) metaBits.push('priority ' + item.priority);
      if (item.domain) metaBits.push(item.domain);
      if (item.dns_target) metaBits.push('DNS → ' + opsTargetLabel(item.dns_target));
      if (item.registration_target) metaBits.push('Registrar → ' + opsTargetLabel(item.registration_target));
      if (metaBits.length > 0) {
        left.appendChild(el('div', {style: 'font-size:0.72rem;color:var(--text-dim);margin-top:0.25rem;', textContent: metaBits.join(' · ')}));
      }
      if (item.summary) {
        left.appendChild(el('div', {style: 'font-size:0.76rem;color:var(--text);margin-top:0.35rem;', textContent: item.summary}));
      }
      if (item.blockers && item.blockers.length > 0) {
        left.appendChild(el('div', {style: 'font-size:0.72rem;color:var(--high);margin-top:0.35rem;', textContent: 'Blockers: ' + item.blockers.join(' | ')}));
      }
      row.appendChild(left);

      var statusSelect = el('select', {className: 'ops-form-select', style: 'min-width:125px;'});
      ['planned', 'in_progress', 'blocked', 'complete'].forEach(function(status) {
        var opt = el('option', {value: status, textContent: status.replace(/_/g, ' ')});
        if (item.status === status) opt.selected = true;
        statusSelect.appendChild(opt);
      });
      row.appendChild(statusSelect);

      var targetNode;
      if (options.showTarget) {
        targetNode = el('select', {className: 'ops-form-select', style: 'min-width:140px;'});
        var targets = options.domainTargets ? ['gcp', 'aws-new'] : ['gcp', 'aws-new', 'hybrid', 'defer'];
        targets.forEach(function(target) {
          var opt = el('option', {value: target, textContent: opsTargetLabel(target)});
          var selectedValue = options.domainTargets ? item[options.domainTargetKey] : item.target;
          if (selectedValue === target) opt.selected = true;
          targetNode.appendChild(opt);
        });
      } else {
        targetNode = el('span', null, [el('span', {className: opsBadgeClass(item.status), textContent: item.status.replace(/_/g, ' ')})]);
      }
      row.appendChild(targetNode);

      var saveBtn = el('button', {className: 'ops-btn ops-btn-primary', textContent: 'Save'});
      row.appendChild(saveBtn);
      card.appendChild(row);

      var notesRow = el('div', {style: 'display:grid;grid-template-columns:1fr 1fr;gap:0.75rem;margin:0 0 1rem 0;'});
      var notesInput = el('input', {className: 'ops-form-input', value: item.notes || '', placeholder: 'Notes'});
      var nextInput = el('input', {className: 'ops-form-input', value: item.next_step || '', placeholder: 'Next step'});
      notesRow.appendChild(notesInput);
      notesRow.appendChild(nextInput);
      card.appendChild(notesRow);

      saveBtn.addEventListener('click', function() {
        if (options.domainTargets) {
          var planAfterFirst = {
            collection: collection,
            id: item.id,
            status: statusSelect.value,
            notes: notesInput.value,
            next_step: nextInput.value
          };
          saveBtn.disabled = true;
          saveBtn.textContent = 'Saving…';
          fetch('/api/migration-plan/item/update', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(planAfterFirst)
          })
          .then(function(r) { return r.json().then(function(d) { return {ok: r.ok, data: d}; }); })
          .then(function(res) {
            if (!res.ok) throw new Error(res.data.error || 'Unknown error');
            migrationPlanData = res.data.plan;
            var patch = {};
            patch[options.domainTargetKey] = targetNode.value;
            var found = migrationPlanData.domains.find(function(domain) { return domain.id === item.id; });
            if (found) {
              found[options.domainTargetKey] = targetNode.value;
            }
            return fetch('/api/migration-plan/item/update', {
              method: 'POST',
              headers: {'Content-Type': 'application/json'},
              body: JSON.stringify({
                collection: collection,
                id: item.id,
                status: statusSelect.value,
                notes: notesInput.value,
                next_step: nextInput.value
              })
            });
          })
          .then(function(r) { return r.json().then(function(d) { return {ok: r.ok, data: d}; }); })
          .then(function() {
            saveBtn.disabled = false;
            saveBtn.textContent = 'Save';
            opsFeedback(container, 'Migration plan updated.', false);
            opsRenderMigrationTab();
          })
          .catch(function(err) {
            saveBtn.disabled = false;
            saveBtn.textContent = 'Save';
            opsFeedback(container, 'Error: ' + err.message, true);
          });
          return;
        }
        opsMigrationSaveItem(collection, item, statusSelect, options.showTarget ? targetNode : null, notesInput, nextInput, saveBtn, container);
      });
    });
    container.appendChild(card);
  }

  function opsRenderMigrationDomains(container, domains) {
    var card = el('div', {className: 'ops-card'});
    card.appendChild(el('div', {className: 'ops-card-title', style: 'margin-bottom:0.75rem;', textContent: 'Domains'}));
    if (!domains || domains.length === 0) {
      card.appendChild(el('div', {className: 'empty-state', textContent: 'No domains yet.'}));
      container.appendChild(card);
      return;
    }
    domains.forEach(function(item) {
      var row = el('div', {className: 'ops-job-row', style: 'grid-template-columns: 1.1fr 0.8fr 0.8fr 0.7fr auto; align-items:start;'});
      var left = el('div');
      left.appendChild(el('div', {className: 'ops-job-target', textContent: item.label}));
      if (item.notes) left.appendChild(el('div', {style: 'font-size:0.72rem;color:var(--text-dim);margin-top:0.25rem;', textContent: item.notes}));
      row.appendChild(left);

      var dnsSelect = el('select', {className: 'ops-form-select', style: 'min-width:125px;'});
      ['gcp', 'aws-new'].forEach(function(target) {
        var opt = el('option', {value: target, textContent: target === 'gcp' ? 'DNS → GCP' : 'DNS → AWS'});
        if (item.dns_target === target) opt.selected = true;
        dnsSelect.appendChild(opt);
      });
      row.appendChild(dnsSelect);

      var regSelect = el('select', {className: 'ops-form-select', style: 'min-width:150px;'});
      ['gcp', 'aws-new'].forEach(function(target) {
        var opt = el('option', {value: target, textContent: target === 'gcp' ? 'Registrar → GCP' : 'Registrar → AWS'});
        if (item.registration_target === target) opt.selected = true;
        regSelect.appendChild(opt);
      });
      row.appendChild(regSelect);

      var statusSelect = el('select', {className: 'ops-form-select', style: 'min-width:120px;'});
      ['planned', 'in_progress', 'blocked', 'complete'].forEach(function(status) {
        var opt = el('option', {value: status, textContent: status.replace(/_/g, ' ')});
        if (item.status === status) opt.selected = true;
        statusSelect.appendChild(opt);
      });
      row.appendChild(statusSelect);

      var saveBtn = el('button', {className: 'ops-btn ops-btn-primary', textContent: 'Save'});
      row.appendChild(saveBtn);
      card.appendChild(row);

      var notesRow = el('div', {style: 'display:grid;grid-template-columns:1fr 1fr;gap:0.75rem;margin:0 0 1rem 0;'});
      var notesInput = el('input', {className: 'ops-form-input', value: item.notes || '', placeholder: 'Notes'});
      var nextInput = el('input', {className: 'ops-form-input', value: item.next_step || '', placeholder: 'Next step'});
      notesRow.appendChild(notesInput);
      notesRow.appendChild(nextInput);
      card.appendChild(notesRow);

      saveBtn.addEventListener('click', function() {
        saveBtn.disabled = true;
        saveBtn.textContent = 'Saving…';
        fetch('/api/migration-plan/item/update', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({
            collection: 'domains',
            id: item.id,
            status: statusSelect.value,
            dns_target: dnsSelect.value,
            registration_target: regSelect.value,
            notes: notesInput.value,
            next_step: nextInput.value
          })
        })
          .then(function(r) { return r.json().then(function(d) { return {ok: r.ok, data: d}; }); })
          .then(function(res) {
            if (!res.ok) throw new Error(res.data.error || 'Unknown error');
            migrationPlanData = res.data.plan;
            saveBtn.disabled = false;
            saveBtn.textContent = 'Save';
            opsFeedback(container, 'Domain plan updated locally.', false);
            opsRenderMigrationTab();
          })
          .catch(function(err) {
            saveBtn.disabled = false;
            saveBtn.textContent = 'Save';
            opsFeedback(container, 'Error: ' + err, true);
          });
      });
    });
    container.appendChild(card);
  }

  function opsRenderMigrationUpdates(container, plan) {
    var card = el('div', {className: 'ops-card'});
    card.appendChild(el('div', {className: 'ops-card-title', style: 'margin-bottom:0.75rem;', textContent: 'Update Log'}));

    var actionRow = el('div', {style: 'display:grid;grid-template-columns:1fr auto;gap:0.75rem;margin-bottom:1rem;'});
    var updateInput = el('input', {className: 'ops-form-input', placeholder: 'Add a migration update that should appear in the dashboard'});
    var addBtn = el('button', {className: 'ops-btn ops-btn-primary', textContent: 'Add Update'});
    actionRow.appendChild(updateInput);
    actionRow.appendChild(addBtn);
    card.appendChild(actionRow);

    addBtn.addEventListener('click', function() {
      if (!updateInput.value.trim()) {
        opsFeedback(container, 'Update message is required.', true);
        return;
      }
      addBtn.disabled = true;
      addBtn.textContent = 'Adding…';
      fetch('/api/migration-plan/updates/add', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({actor: 'dashboard', kind: 'note', message: updateInput.value.trim()})
      })
      .then(function(r) { return r.json().then(function(d) { return {ok: r.ok, data: d}; }); })
      .then(function(res) {
        addBtn.disabled = false;
        addBtn.textContent = 'Add Update';
        if (res.ok) {
          migrationPlanData = res.data.plan;
          updateInput.value = '';
          opsFeedback(container, 'Migration update added.', false);
          opsRenderMigrationTab();
        } else {
          opsFeedback(container, 'Error: ' + (res.data.error || 'Unknown error'), true);
        }
      })
      .catch(function(err) {
        addBtn.disabled = false;
        addBtn.textContent = 'Add Update';
        opsFeedback(container, 'Network error: ' + err, true);
      });
    });

    var updates = (plan.updates || []).slice(0, 12);
    if (updates.length === 0) {
      card.appendChild(el('div', {className: 'empty-state', textContent: 'No updates yet.'}));
    } else {
      updates.forEach(function(update) {
        card.appendChild(el('div', {className: 'ops-cycle-row'}, [
          el('span', {className: 'ops-cycle-id', textContent: timeAgo(update.at)}),
          el('span', {textContent: update.actor || 'operator'}),
          el('span', {textContent: update.kind || 'note'}),
          el('span', {style: 'grid-column: span 2;', textContent: update.message || ''})
        ]));
      });
    }
    container.appendChild(card);
  }

  function opsRenderMigrationTab() {
    var container = document.getElementById('ops-migration');
    if (!container) return;
    clearChildren(container);
    if (!migrationPlanData) {
      container.appendChild(el('div', {style: 'padding:2rem;text-align:center;color:var(--text-dim);font-size:0.85rem;', textContent: 'Loading migration plan…'}));
      refreshMigrationPlanCache()
        .then(function() { opsRenderMigrationTab(); })
        .catch(function(err) {
          clearChildren(container);
          container.appendChild(el('div', {className: 'empty-state', textContent: 'Could not load migration plan: ' + err}));
        });
      return;
    }

    var intro = el('div', {className: 'ops-card'});
    intro.appendChild(el('div', {className: 'ops-card-title', textContent: 'Cloud Exit Control Plane'}));
    intro.appendChild(el('div', {className: 'ops-card-subtitle', textContent: migrationPlanData.goal || ''}));
    if ((migrationPlanData.principles || []).length > 0) {
      var principleList = el('div', {style: 'margin-top:0.75rem;font-size:0.78rem;color:var(--text-dim);'});
      migrationPlanData.principles.forEach(function(line) {
        principleList.appendChild(el('div', {textContent: '• ' + line}));
      });
      intro.appendChild(principleList);
    }
    container.appendChild(intro);

    opsRenderMigrationSummary(container, migrationPlanData.summary || {});
    opsRenderMigrationCollection(container, 'Phases', 'phases', migrationPlanData.phases || [], {showTarget: true});
    opsRenderMigrationCollection(container, 'Repositories', 'repositories', migrationPlanData.repositories || [], {showTarget: true});
    opsRenderMigrationDomains(container, migrationPlanData.domains || []);
    opsRenderMigrationUpdates(container, migrationPlanData);
  }

  /* ════════════════════════════════════════════════
     TAB 5: REMEDIATION PLAN
  ════════════════════════════════════════════════ */

  function opsRenderRemediationSummary(container, summary) {
    var grid = el('div', {className: 'ops-overnight-status'});
    grid.appendChild(el('div', {className: 'ops-overnight-stat'}, [
      el('div', {className: 'ops-overnight-stat-label', textContent: 'Waves'}),
      el('div', {className: 'ops-overnight-stat-value', textContent: String(summary.wave_count || 0)})
    ]));
    grid.appendChild(el('div', {className: 'ops-overnight-stat'}, [
      el('div', {className: 'ops-overnight-stat-label', textContent: 'Repos In Plan'}),
      el('div', {className: 'ops-overnight-stat-value', textContent: String(summary.repository_count || 0)})
    ]));
    grid.appendChild(el('div', {className: 'ops-overnight-stat'}, [
      el('div', {className: 'ops-overnight-stat-label', textContent: 'Must Fix Now'}),
      el('div', {className: 'ops-overnight-stat-value', textContent: String((summary.by_disposition || {}).must_fix_now || 0)})
    ]));
    grid.appendChild(el('div', {className: 'ops-overnight-stat'}, [
      el('div', {className: 'ops-overnight-stat-label', textContent: 'Deferred Findings'}),
      el('div', {className: 'ops-overnight-stat-value', textContent: String(summary.deferred_findings || 0)})
    ]));
    container.appendChild(grid);
  }

  function opsRemediationSaveItem(collection, itemId, statusValue, notesValue, button, container) {
    button.disabled = true;
    button.textContent = 'Saving…';
    fetch('/api/remediation-plan/item/update', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        collection: collection,
        id: itemId,
        status: statusValue,
        notes: notesValue
      })
    })
    .then(function(r) { return r.json().then(function(d) { return {ok: r.ok, data: d}; }); })
    .then(function(res) {
      button.disabled = false;
      button.textContent = 'Save';
      if (res.ok) {
        remediationPlanData = res.data.plan;
        opsFeedback(container, 'Remediation plan updated.', false);
        opsRenderRemediationTab();
      } else {
        opsFeedback(container, 'Error: ' + (res.data.error || 'Unknown error'), true);
      }
    })
    .catch(function(err) {
      button.disabled = false;
      button.textContent = 'Save';
      opsFeedback(container, 'Network error: ' + err, true);
    });
  }

  function opsRenderRemediationWave(container, wave) {
    var card = el('div', {className: 'ops-card'});
    var header = el('div', {className: 'ops-card-header'}, [
      el('div', null, [
        el('div', {className: 'ops-card-title', textContent: wave.title || wave.id}),
        el('div', {className: 'ops-card-subtitle', textContent: (wave.summary || '') + (wave.approval_checkpoint ? (' · ' + wave.approval_checkpoint) : '')})
      ])
    ]);
    var waveControls = el('div', {style: 'display:flex;gap:0.5rem;align-items:center;'});
    var waveStatus = el('select', {className: 'ops-form-select', style: 'min-width:130px;'});
    ['planned', 'in_progress', 'blocked', 'complete'].forEach(function(status) {
      var opt = el('option', {value: status, textContent: status.replace(/_/g, ' ')});
      if ((wave.status || 'planned') === status) opt.selected = true;
      waveStatus.appendChild(opt);
    });
    var waveSave = el('button', {className: 'ops-btn ops-btn-primary', textContent: 'Save'});
    waveControls.appendChild(waveStatus);
    waveControls.appendChild(waveSave);
    header.appendChild(waveControls);
    card.appendChild(header);

    var waveNotes = el('input', {className: 'ops-form-input', value: wave.notes || '', placeholder: 'Wave notes', style: 'margin-bottom:0.85rem;'});
    card.appendChild(waveNotes);
    waveSave.addEventListener('click', function() {
      opsRemediationSaveItem('waves', wave.id, waveStatus.value, waveNotes.value, waveSave, container);
    });

    (wave.repositories || []).forEach(function(repoPlan) {
      var row = el('div', {className: 'ops-job-row', style: 'grid-template-columns: 1.1fr 0.8fr 1.2fr auto;align-items:start;'});
      var left = el('div');
      left.appendChild(el('div', {className: 'ops-job-target', textContent: repoPlan.repo || 'unknown repo'}));
      left.appendChild(el('div', {style: 'font-size:0.72rem;color:var(--text-dim);margin-top:0.25rem;', textContent: repoPlan.summary || ''}));
      row.appendChild(left);
      var repoStatusWrap = el('div');
      repoStatusWrap.appendChild(el('div', {style: 'font-size:0.7rem;color:var(--text-dim);margin-bottom:0.25rem;', textContent: (repoPlan.disposition || 'fix_this_wave').replace(/_/g, ' ')}));
      var repoStatus = el('select', {className: 'ops-form-select', style: 'min-width:130px;'});
      ['planned', 'in_progress', 'blocked', 'complete'].forEach(function(status) {
        var opt = el('option', {value: status, textContent: status.replace(/_/g, ' ')});
        if ((repoPlan.status || 'planned') === status) opt.selected = true;
        repoStatus.appendChild(opt);
      });
      repoStatusWrap.appendChild(repoStatus);
      row.appendChild(repoStatusWrap);

      var findingsWrap = el('div');
      (repoPlan.findings || []).slice(0, 6).forEach(function(finding) {
        var line = finding.severity + ' · ' + (finding.title || '');
        if (finding.deferred) line += ' (deferred)';
        findingsWrap.appendChild(el('div', {style: 'font-size:0.72rem;color:' + (finding.deferred ? 'var(--text-dim)' : 'var(--text)') + ';margin-bottom:0.2rem;', textContent: line}));
      });
      if ((repoPlan.findings || []).length > 6) {
        findingsWrap.appendChild(el('div', {style: 'font-size:0.7rem;color:var(--text-dim);', textContent: '+' + ((repoPlan.findings || []).length - 6) + ' more'}));
      }
      row.appendChild(findingsWrap);

      var repoAction = el('div', {style: 'display:flex;flex-direction:column;gap:0.45rem;align-items:flex-end;'});
      repoAction.appendChild(el('div', {style: 'font-size:0.7rem;color:var(--text-dim);text-align:right;', textContent: (repoPlan.verification || []).join(' | ') || 'No verification command'}));
      var repoSave = el('button', {className: 'ops-btn ops-btn-primary', textContent: 'Save'});
      repoAction.appendChild(repoSave);
      row.appendChild(repoAction);
      card.appendChild(row);

      var repoNotes = el('input', {className: 'ops-form-input', value: repoPlan.notes || '', placeholder: 'Repo notes', style: 'margin:0 0 0.9rem 0;'});
      card.appendChild(repoNotes);
      repoSave.addEventListener('click', function() {
        opsRemediationSaveItem('repositories', repoPlan.repo, repoStatus.value, repoNotes.value, repoSave, container);
      });
    });

    container.appendChild(card);
  }

  function opsRenderRemediationTab() {
    var container = document.getElementById('ops-remediation');
    if (!container) return;
    clearChildren(container);
    if (!remediationPlanData) {
      container.appendChild(el('div', {style: 'padding:2rem;text-align:center;color:var(--text-dim);font-size:0.85rem;', textContent: 'Loading remediation plan…'}));
      refreshRemediationPlanCache()
        .then(function() { opsRenderRemediationTab(); })
        .catch(function(err) {
          clearChildren(container);
          container.appendChild(el('div', {className: 'empty-state', textContent: 'Could not load remediation plan: ' + err}));
        });
      return;
    }

    var intro = el('div', {className: 'ops-card'});
    intro.appendChild(el('div', {className: 'ops-card-title', textContent: 'Portfolio QA Remediation Plan'}));
    intro.appendChild(el('div', {className: 'ops-card-subtitle', textContent: remediationPlanData.goal || ''}));
    if ((remediationPlanData.principles || []).length > 0) {
      var principleList = el('div', {style: 'margin-top:0.75rem;font-size:0.78rem;color:var(--text-dim);'});
      remediationPlanData.principles.forEach(function(line) {
        principleList.appendChild(el('div', {textContent: '• ' + line}));
      });
      intro.appendChild(principleList);
    }

    var seedRow = el('div', {style: 'display:flex;gap:0.75rem;align-items:center;margin-top:1rem;flex-wrap:wrap;'});
    var seedBtn = el('button', {className: 'ops-btn ops-btn-primary', textContent: 'Seed Wave 1 To Queue'});
    seedBtn.addEventListener('click', function() {
      seedBtn.disabled = true;
      seedBtn.textContent = 'Seeding…';
      fetch('/api/remediation-plan/seed-wave-one', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({})
      })
      .then(function(r) { return r.json().then(function(d) { return {ok: r.ok, data: d}; }); })
      .then(function(res) {
        seedBtn.disabled = false;
        seedBtn.textContent = 'Seed Wave 1 To Queue';
        if (res.ok) {
          refreshTaskQueueCache().catch(function() { return null; }).then(function() {
            opsFeedback(container, 'Wave 1 tasks seeded: ' + ((res.data.created_task_ids || []).length), false);
            opsRenderApprovalTab();
          });
        } else {
          opsFeedback(container, 'Error: ' + (res.data.error || 'Unknown error'), true);
        }
      })
      .catch(function(err) {
        seedBtn.disabled = false;
        seedBtn.textContent = 'Seed Wave 1 To Queue';
        opsFeedback(container, 'Network error: ' + err, true);
      });
    });
    seedRow.appendChild(seedBtn);
    seedRow.appendChild(el('span', {style: 'font-size:0.72rem;color:var(--text-dim);', textContent: 'Creates approval-queue tasks for the Wave 1 repo passes.'}));
    intro.appendChild(seedRow);
    container.appendChild(intro);

    opsRenderRemediationSummary(container, remediationPlanData.summary || {});
    (remediationPlanData.waves || []).forEach(function(wave) {
      opsRenderRemediationWave(container, wave);
    });

    var updatesCard = el('div', {className: 'ops-card'});
    updatesCard.appendChild(el('div', {className: 'ops-card-title', style: 'margin-bottom:0.75rem;', textContent: 'Remediation Updates'}));
    var actionRow = el('div', {style: 'display:grid;grid-template-columns:1fr auto;gap:0.75rem;margin-bottom:1rem;'});
    var updateInput = el('input', {className: 'ops-form-input', placeholder: 'Add a remediation update'});
    var addBtn = el('button', {className: 'ops-btn ops-btn-primary', textContent: 'Add Update'});
    actionRow.appendChild(updateInput);
    actionRow.appendChild(addBtn);
    updatesCard.appendChild(actionRow);
    addBtn.addEventListener('click', function() {
      if (!updateInput.value.trim()) {
        opsFeedback(container, 'Update message is required.', true);
        return;
      }
      addBtn.disabled = true;
      addBtn.textContent = 'Adding…';
      fetch('/api/remediation-plan/updates/add', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({actor: 'dashboard', kind: 'note', message: updateInput.value.trim()})
      })
      .then(function(r) { return r.json().then(function(d) { return {ok: r.ok, data: d}; }); })
      .then(function(res) {
        addBtn.disabled = false;
        addBtn.textContent = 'Add Update';
        if (res.ok) {
          remediationPlanData = res.data.plan;
          updateInput.value = '';
          opsFeedback(container, 'Remediation update added.', false);
          opsRenderRemediationTab();
        } else {
          opsFeedback(container, 'Error: ' + (res.data.error || 'Unknown error'), true);
        }
      })
      .catch(function(err) {
        addBtn.disabled = false;
        addBtn.textContent = 'Add Update';
        opsFeedback(container, 'Network error: ' + err, true);
      });
    });

    var updates = (remediationPlanData.updates || []).slice(0, 12);
    if (updates.length === 0) {
      updatesCard.appendChild(el('div', {className: 'empty-state', textContent: 'No remediation updates yet.'}));
    } else {
      updates.forEach(function(update) {
        updatesCard.appendChild(el('div', {className: 'ops-cycle-row'}, [
          el('span', {className: 'ops-cycle-id', textContent: timeAgo(update.at)}),
          el('span', {textContent: update.actor || 'operator'}),
          el('span', {textContent: update.kind || 'note'}),
          el('span', {style: 'grid-column: span 2;', textContent: update.message || ''})
        ]));
      });
    }
    container.appendChild(updatesCard);
  }

  /* ════════════════════════════════════════════════
     TAB 6: BACKENDS
  ════════════════════════════════════════════════ */

  function opsRenderBackendsTab() {
    var container = document.getElementById('ops-backends');
    if (!container) return;
    clearChildren(container);

    var loading = el('div', {style: 'padding:2rem;text-align:center;color:var(--text-dim);font-size:0.85rem;', textContent: 'Loading backends\u2026'});
    container.appendChild(loading);

    fetch('/api/ops/backends?t=' + Date.now())
      .then(function(r) { return r.ok ? r.json() : Promise.reject('HTTP ' + r.status); })
      .then(function(data) {
        clearChildren(container);

        // API shape: data.backends is dict keyed by name (e.g. "claude"), data.routing_policy is dict
        var backendsDict = data.backends || {};
        var backendNames = Object.keys(backendsDict);
        var routingDict = data.routing_policy || {};
        var routingKeys = Object.keys(routingDict);

        // Backend cards
        var grid = el('div', {className: 'ops-backend-grid'});
        backendNames.forEach(function(name) {
          var b = backendsDict[name];
          var card = el('div', {className: 'ops-backend-card'});
          var bStatus = b.healthy ? 'Healthy' : (b.status || 'Unavailable');
          if (!b.healthy) card.style.opacity = '0.6';

          var nameDiv = el('div', {className: 'ops-backend-name'}, [
            document.createTextNode(name.charAt(0).toUpperCase() + name.slice(1)),
            el('span', {className: opsBadgeClass(bStatus), textContent: bStatus})
          ]);
          card.appendChild(nameDiv);

          // Description from limits or capabilities
          var lim = b.limits || {};
          var caps = b.capabilities || {};
          var descParts = [];
          if (lim.backend) descParts.push(lim.backend + ' backend');
          if (lim.supports_structured_output) descParts.push('structured output');
          if (descParts.length > 0) {
            card.appendChild(el('div', {style: 'font-size:0.78rem;color:var(--text-dim);', textContent: descParts.join(' \u00B7 ')}));
          }

          var stats = el('div', {className: 'ops-backend-stats'});
          var ctxTokens = lim.context_window_tokens;
          var ctxStr = ctxTokens ? (Math.round(ctxTokens / 1000) + 'K tokens') : '\u2014';
          stats.appendChild(el('div', {className: 'ops-backend-stat'}, [
            document.createTextNode('Context: '),
            el('strong', {textContent: ctxStr})
          ]));
          stats.appendChild(el('div', {className: 'ops-backend-stat'}, [
            document.createTextNode('Parallelism: '),
            el('strong', {textContent: lim.recommended_parallelism != null ? String(lim.recommended_parallelism) : '\u2014'})
          ]));
          stats.appendChild(el('div', {className: 'ops-backend-stat'}, [
            document.createTextNode('Rate limit: '),
            el('strong', {textContent: lim.rate_limit_state || '\u2014'})
          ]));
          stats.appendChild(el('div', {className: 'ops-backend-stat'}, [
            document.createTextNode('Structured output: '),
            el('strong', {textContent: lim.supports_structured_output ? 'Yes' : 'No'})
          ]));
          card.appendChild(stats);

          // Show capabilities summary
          var capNames = Object.keys(caps).filter(function(k) { return caps[k]; });
          if (capNames.length > 0) {
            card.appendChild(el('div', {style: 'margin-top:0.75rem;font-size:0.72rem;color:var(--text-dim);', textContent: 'Capabilities: ' + capNames.join(', ').replace(/_/g, ' ')}));
          }

          grid.appendChild(card);
        });

        if (backendNames.length === 0) {
          grid.appendChild(el('div', {style: 'padding:1rem;text-align:center;color:var(--text-dim);grid-column:1/-1;', textContent: 'No backends configured'}));
        }
        container.appendChild(grid);

        // Routing policy
        if (routingKeys.length > 0) {
          var routeCard = el('div', {className: 'ops-card'});
          routeCard.appendChild(el('div', {className: 'ops-card-title', style: 'margin-bottom:0.75rem;', textContent: 'Routing Policy'}));

          var routeTable = el('div', {className: 'ops-routing-table'});
          routingKeys.forEach(function(task) {
            var order = routingDict[task];
            var orderStr = Array.isArray(order) ? order.join(' \u2192 ') : String(order);
            routeTable.appendChild(el('div', {className: 'ops-routing-row'}, [
              el('span', {className: 'ops-routing-task', textContent: task}),
              el('span', {textContent: orderStr})
            ]));
          });
          routeCard.appendChild(routeTable);
          container.appendChild(routeCard);
        }
      })
      .catch(function(err) {
        clearChildren(container);
        container.appendChild(el('div', {className: 'empty-state', textContent: 'Could not load backend data: ' + err}));
      });
  }

  /* ════════════════════════════════════════════════
     TAB 6: ADD PRODUCT
  ════════════════════════════════════════════════ */

  var opsSelectedSource = 'github';

  function opsRenderAddProductTab() {
    var container = document.getElementById('ops-products');
    if (!container) return;
    clearChildren(container);

    var card = el('div', {className: 'ops-card'});
    card.appendChild(el('div', {className: 'ops-card-title', style: 'margin-bottom:1rem;', textContent: 'Suggest a Product'}));

    // Source cards
    card.appendChild(el('label', {className: 'ops-form-label', textContent: 'Source'}));
    var sourcesWrap = el('div', {className: 'ops-source-cards'});
    var sourceDefs = [
      {key: 'local', icon: '\uD83D\uDCC1', label: 'Local Only', desc: 'Already on disk. Just add to Back Office config.'},
      {key: 'github', icon: '\uD83D\uDC19', label: 'GitHub', desc: 'Clone from GitHub and add to config.'},
      {key: 'both', icon: '\uD83D\uDD03', label: 'GitHub + Local', desc: 'Link existing local repo to GitHub remote and add to config.'}
    ];
    sourceDefs.forEach(function(src) {
      var srcCard = el('div', {className: 'ops-source-card' + (opsSelectedSource === src.key ? ' selected' : '')}, [
        el('div', {className: 'ops-source-icon', textContent: src.icon}),
        el('div', {className: 'ops-source-label', textContent: src.label}),
        el('div', {className: 'ops-source-desc', textContent: src.desc})
      ]);
      srcCard.addEventListener('click', function() {
        opsSelectedSource = src.key;
        sourcesWrap.querySelectorAll('.ops-source-card').forEach(function(c) { c.classList.remove('selected'); });
        srcCard.classList.add('selected');
        updateProductPreview();
      });
      sourcesWrap.appendChild(srcCard);
    });
    card.appendChild(sourcesWrap);

    // Form fields
    var row1 = el('div', {className: 'ops-form-row'});
    var nameGroup = el('div', {className: 'ops-form-group'});
    nameGroup.appendChild(el('label', {className: 'ops-form-label', textContent: 'Product Name'}));
    var nameInput = el('input', {className: 'ops-form-input', placeholder: 'my-app', id: 'opsProductName'});
    nameGroup.appendChild(nameInput);
    row1.appendChild(nameGroup);

    var repoGroup = el('div', {className: 'ops-form-group'});
    repoGroup.appendChild(el('label', {className: 'ops-form-label', textContent: 'GitHub Repo (owner/name)'}));
    var repoInput = el('input', {className: 'ops-form-input', placeholder: 'CodyJo/my-app', id: 'opsProductRepo'});
    repoGroup.appendChild(repoInput);
    row1.appendChild(repoGroup);
    card.appendChild(row1);

    var row2 = el('div', {className: 'ops-form-row'});
    var langGroup = el('div', {className: 'ops-form-group'});
    langGroup.appendChild(el('label', {className: 'ops-form-label', textContent: 'Language'}));
    var langSelect = el('select', {className: 'ops-form-select', id: 'opsProductLang'});
    ['typescript', 'python', 'astro', 'terraform'].forEach(function(lang) {
      langSelect.appendChild(el('option', {value: lang, textContent: lang}));
    });
    langGroup.appendChild(langSelect);
    row2.appendChild(langGroup);

    var pathGroup = el('div', {className: 'ops-form-group'});
    pathGroup.appendChild(el('label', {className: 'ops-form-label', textContent: 'Local Path'}));
    var pathInput = el('input', {className: 'ops-form-input', placeholder: '/home/merm/projects/...', id: 'opsProductPath'});
    pathGroup.appendChild(pathInput);
    row2.appendChild(pathGroup);
    card.appendChild(row2);

    // Department checkboxes
    var deptGroup = el('div', {className: 'ops-form-group'});
    deptGroup.appendChild(el('label', {className: 'ops-form-label', textContent: 'Departments'}));
    var deptWrap = el('div', {style: 'display:flex;gap:1rem;flex-wrap:wrap;'});
    var deptNamesP = ['QA', 'SEO', 'ADA', 'Compliance', 'Monetization', 'Product'];
    var deptKeysP = ['qa', 'seo', 'ada', 'compliance', 'monetization', 'product'];
    deptKeysP.forEach(function(dk, i) {
      var cb = el('input', {type: 'checkbox', 'data-product-dept': dk});
      cb.checked = true;
      var lbl = el('label', {className: 'ops-form-check'});
      lbl.appendChild(cb);
      lbl.appendChild(document.createTextNode(' ' + deptNamesP[i]));
      deptWrap.appendChild(lbl);
    });
    deptGroup.appendChild(deptWrap);
    card.appendChild(deptGroup);

    // Autonomy checkboxes
    var autoGroup = el('div', {className: 'ops-form-group'});
    autoGroup.appendChild(el('label', {className: 'ops-form-label', textContent: 'Autonomy Policy'}));
    var autoWrap = el('div', {style: 'display:flex;gap:1rem;flex-wrap:wrap;'});
    var autoOpts = [
      {key: 'allow_fixes', label: 'Allow fixes', checked: true},
      {key: 'allow_features', label: 'Allow feature dev', checked: false},
      {key: 'allow_merge', label: 'Allow auto-merge', checked: false},
      {key: 'allow_deploy', label: 'Allow auto-deploy', checked: false}
    ];
    autoOpts.forEach(function(opt) {
      var cb = el('input', {type: 'checkbox', 'data-autonomy': opt.key});
      cb.checked = opt.checked;
      var lbl = el('label', {className: 'ops-form-check'});
      lbl.appendChild(cb);
      lbl.appendChild(document.createTextNode(' ' + opt.label));
      autoWrap.appendChild(lbl);
    });
    autoGroup.appendChild(autoWrap);
    card.appendChild(autoGroup);

    // Add button
    var actionRow = el('div', {style: 'display:flex;gap:0.75rem;align-items:center;margin-top:1.25rem;'});
    var addBtn = el('button', {className: 'ops-btn ops-btn-primary', textContent: 'Submit Suggestion'});
    actionRow.appendChild(addBtn);
    actionRow.appendChild(el('span', {style: 'font-size:0.72rem;color:var(--text-dim);', textContent: 'This will:'}));
    card.appendChild(actionRow);

    // Steps preview
    var stepsDiv = el('div', {style: 'font-size:0.78rem;color:var(--text-dim);margin-top:0.5rem;padding-left:1rem;', id: 'opsProductSteps'});
    card.appendChild(stepsDiv);

    // Command box
    var cmdBox = el('div', {className: 'ops-cmd-box', style: 'margin-top:0.75rem;'});
    var cmdText = el('span', {id: 'opsProductCmdText', textContent: ''});
    var cmdCopy = el('button', {className: 'ops-cmd-copy', textContent: 'Copy'});
    cmdCopy.addEventListener('click', function() { opsCopyToClipboard(cmdText.textContent, cmdCopy); });
    cmdBox.appendChild(cmdText);
    cmdBox.appendChild(cmdCopy);
    card.appendChild(cmdBox);

    container.appendChild(card);
    opsRenderMentorCard(container);

    // Update preview on input changes
    function updateProductPreview() {
      var name = nameInput.value.trim() || 'my-app';
      var repo = repoInput.value.trim() || 'CodyJo/' + name;
      var localPath = pathInput.value.trim() || '/home/merm/projects/' + name;

      var steps = [];
      if (opsSelectedSource === 'github' || opsSelectedSource === 'both') {
        steps.push('1. Clone ' + repo + ' to ' + localPath);
        steps.push('2. Add target entry to config/targets.yaml');
        steps.push('3. Run initial QA audit to verify setup');
        steps.push('4. Refresh dashboard data');
      } else {
        steps.push('1. Add target entry to config/targets.yaml');
        steps.push('2. Run initial QA audit to verify setup');
        steps.push('3. Refresh dashboard data');
      }

      clearChildren(stepsDiv);
      steps.forEach(function(s) {
        stepsDiv.appendChild(document.createTextNode(s));
        stepsDiv.appendChild(document.createElement('br'));
      });

      if (opsSelectedSource === 'github' || opsSelectedSource === 'both') {
        cmdText.textContent = 'gh repo clone ' + repo + ' ' + localPath;
      } else {
        cmdText.textContent = 'python3 -m backoffice add-target ' + name + ' --path ' + localPath;
      }
    }

    nameInput.addEventListener('input', updateProductPreview);
    repoInput.addEventListener('input', updateProductPreview);
    pathInput.addEventListener('input', updateProductPreview);
    updateProductPreview();

    // Add product handler
    addBtn.addEventListener('click', function() {
      var name = nameInput.value.trim();
      if (!name) {
        opsFeedback(container, 'Product name is required.', true);
        return;
      }

      addBtn.disabled = true;
      addBtn.textContent = 'Submitting\u2026';

      var depts = [];
      card.querySelectorAll('input[data-product-dept]:checked').forEach(function(cb) {
        depts.push(cb.getAttribute('data-product-dept'));
      });
      var autonomy = {};
      card.querySelectorAll('input[data-autonomy]').forEach(function(cb) {
        autonomy[cb.getAttribute('data-autonomy')] = cb.checked;
      });

      var payload = {
        name: name,
        source: opsSelectedSource,
        language: langSelect.value,
        departments: depts,
        autonomy: autonomy
      };
      if (repoInput.value.trim()) payload.github_repo = repoInput.value.trim();
      if (pathInput.value.trim()) payload.local_path = pathInput.value.trim();

      fetch('/api/ops/product/suggest', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(payload)
      })
      .then(function(r) { return r.json().then(function(d) { return {ok: r.ok, data: d}; }); })
      .then(function(res) {
        addBtn.disabled = false;
        addBtn.textContent = 'Submit Suggestion';
        if (res.ok) {
          opsFeedback(container, 'Product "' + name + '" sent to the approval queue.', false);
          nameInput.value = '';
          repoInput.value = '';
          pathInput.value = '';
          updateProductPreview();
          refreshTaskQueueCache().then(function() { opsRenderApprovalTab(); });
        } else {
          opsFeedback(container, 'Error: ' + (res.data.error || 'Unknown error'), true);
        }
      })
      .catch(function(err) {
        addBtn.disabled = false;
        addBtn.textContent = 'Submit Suggestion';
        opsFeedback(container, 'Network error: ' + err, true);
      });
    });
  }


  function opsRenderMentorCard(container) {
    var card = el('div', {className: 'ops-card'});
    card.appendChild(el('div', {className: 'ops-card-title', style: 'margin-bottom:0.35rem;', textContent: 'Mentor Me'}));
    card.appendChild(el('div', {className: 'ops-card-subtitle', textContent: 'Turn a learning goal into an approval-gated study plan tied to your real environment.'}));

    var goalGroup = el('div', {className: 'ops-form-group', style: 'margin-top:1rem;'});
    goalGroup.appendChild(el('label', {className: 'ops-form-label', textContent: 'Goal'}));
    var goalInput = el('input', {className: 'ops-form-input', id: 'opsMentorGoal', value: 'Renew Google Cloud Associate Cloud Engineer'});
    goalGroup.appendChild(goalInput);
    card.appendChild(goalGroup);

    var currentGroup = el('div', {className: 'ops-form-group'});
    currentGroup.appendChild(el('label', {className: 'ops-form-label', textContent: 'Current State'}));
    var currentInput = el('textarea', {className: 'ops-form-input', id: 'opsMentorCurrent', rows: '3'});
    currentInput.value = 'Expired GCP Cloud Associate. Expired AWS SA, but not renewing AWS right now.';
    currentGroup.appendChild(currentInput);
    card.appendChild(currentGroup);

    var row = el('div', {className: 'ops-form-row'});
    var cloudGroup = el('div', {className: 'ops-form-group'});
    cloudGroup.appendChild(el('label', {className: 'ops-form-label', textContent: 'Target Cloud'}));
    var cloudSelect = el('select', {className: 'ops-form-select', id: 'opsMentorCloud'});
    [['gcp', 'GCP'], ['aws', 'AWS']].forEach(function(opt) { cloudSelect.appendChild(el('option', {value: opt[0], textContent: opt[1]})); });
    cloudGroup.appendChild(cloudSelect);
    row.appendChild(cloudGroup);

    var hoursGroup = el('div', {className: 'ops-form-group'});
    hoursGroup.appendChild(el('label', {className: 'ops-form-label', textContent: 'Hours / Week'}));
    var hoursInput = el('input', {className: 'ops-form-input', id: 'opsMentorHours', type: 'number', min: '2', max: '20', value: '6'});
    hoursGroup.appendChild(hoursInput);
    row.appendChild(hoursGroup);

    var weeksGroup = el('div', {className: 'ops-form-group'});
    weeksGroup.appendChild(el('label', {className: 'ops-form-label', textContent: 'Weeks'}));
    var weeksInput = el('input', {className: 'ops-form-input', id: 'opsMentorWeeks', type: 'number', min: '2', max: '16', value: '8'});
    weeksGroup.appendChild(weeksInput);
    row.appendChild(weeksGroup);
    card.appendChild(row);

    var portfolioWrap = el('label', {className: 'ops-form-check', style: 'margin-top:0.25rem;display:inline-flex;align-items:center;gap:0.4rem;'});
    var portfolioCb = el('input', {type: 'checkbox', id: 'opsMentorPortfolio'});
    portfolioCb.checked = true;
    portfolioWrap.appendChild(portfolioCb);
    portfolioWrap.appendChild(document.createTextNode(' Use portfolio repos as labs'));
    card.appendChild(portfolioWrap);

    var preview = el('div', {className: 'ops-cmd-box', style: 'margin-top:0.9rem;white-space:normal;line-height:1.5;', id: 'opsMentorPreview'});
    card.appendChild(preview);

    var actions = el('div', {style: 'display:flex;gap:0.75rem;align-items:center;margin-top:1rem;'});
    var submitBtn = el('button', {className: 'ops-btn ops-btn-primary', textContent: 'Queue Mentor Plan'});
    actions.appendChild(submitBtn);
    card.appendChild(actions);
    container.appendChild(card);

    function updatePreview(plan) {
      var goal = goalInput.value.trim() || 'Mentorship plan';
      var hours = Number(hoursInput.value) || 6;
      var weeks = Number(weeksInput.value) || 8;
      var cloud = cloudSelect.value === 'aws' ? 'AWS' : 'GCP';
      clearChildren(preview);
      preview.appendChild(el('div', {textContent: 'Plan focus: ' + goal}));
      preview.appendChild(el('div', {style: 'margin-top:0.35rem;color:var(--text-dim);', textContent: cloud + ' · ' + hours + ' hrs/week · ' + weeks + ' weeks'}));
      if (plan && plan.summary) {
        preview.appendChild(el('div', {style: 'margin-top:0.6rem;', textContent: plan.summary}));
        if (plan.milestones && plan.milestones.length) {
          var ul = el('ul', {style: 'margin:0.6rem 0 0 1rem;padding:0;'});
          plan.milestones.slice(0, 3).forEach(function(item) {
            ul.appendChild(el('li', {textContent: 'Week ' + item.week + ': ' + item.title}));
          });
          preview.appendChild(ul);
        }
      } else {
        preview.appendChild(el('div', {style: 'margin-top:0.6rem;', textContent: 'Queue a plan to get milestone guidance tied to your environment and certification goal.'}));
      }
    }

    [goalInput, currentInput, cloudSelect, hoursInput, weeksInput, portfolioCb].forEach(function(node) {
      node.addEventListener('input', function() { updatePreview(null); });
      node.addEventListener('change', function() { updatePreview(null); });
    });
    updatePreview(null);

    submitBtn.addEventListener('click', function() {
      var goal = goalInput.value.trim();
      if (!goal) {
        opsFeedback(container, 'Mentor goal is required.', true);
        return;
      }
      submitBtn.disabled = true;
      submitBtn.textContent = 'Planning…';
      var payload = {
        goal: goal,
        target_cloud: cloudSelect.value,
        current_state: currentInput.value.trim(),
        weekly_hours: Number(hoursInput.value) || 6,
        horizon_weeks: Number(weeksInput.value) || 8,
        use_portfolio_context: portfolioCb.checked
      };
      fetch('/api/ops/mentor/plan', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(payload)
      })
      .then(function(r) { return r.json().then(function(d) { return {ok: r.ok, data: d}; }); })
      .then(function(res) {
        submitBtn.disabled = false;
        submitBtn.textContent = 'Queue Mentor Plan';
        if (res.ok) {
          opsFeedback(container, 'Mentor plan queued for approval.', false);
          updatePreview(res.data.plan || null);
          refreshTaskQueueCache().then(function() { opsRenderApprovalTab(); });
        } else {
          opsFeedback(container, 'Error: ' + (res.data.error || 'Unknown error'), true);
        }
      })
      .catch(function(err) {
        submitBtn.disabled = false;
        submitBtn.textContent = 'Queue Mentor Plan';
        opsFeedback(container, 'Network error: ' + err, true);
      });
    });
  }

  /* ════════════════════════════════════════════════
     OPS PANEL MAIN RENDERER
  ════════════════════════════════════════════════ */

  function renderOpsPanel() {
    var body = document.getElementById('slideoverBody');
    clearChildren(body);

    var wrap = el('div', {style: 'padding:1.25rem 1.5rem;'});

    // Title + subtitle
    wrap.appendChild(el('h2', {style: 'font-size:1.2rem;margin-bottom:0.25rem;', textContent: 'Operations'}));
    wrap.appendChild(el('p', {style: 'color:var(--text-dim);font-size:0.85rem;margin-bottom:1.5rem;', textContent: 'Control plane for Back Office \u2014 manage audits, approvals, backends, and product suggestions'}));

    // Tabs
    var tabBar = el('div', {className: 'ops-tabs', id: 'opsTabsWrap', role: 'tablist'});
    var tabDefs = [
      {key: 'jobs', label: 'Live Jobs'},
      {key: 'audit', label: 'Run Audit'},
      {key: 'remediation', label: 'Remediation'},
      {key: 'migration', label: 'Migration'},
      {key: 'approval', label: 'Approval Queue'},
      {key: 'backends', label: 'Backends'},
      {key: 'products', label: 'Suggest Product'}
    ];
    tabDefs.forEach(function(t) {
      var isActive = t.key === opsActiveTab;
      var btn = el('button', {className: 'ops-tab' + (isActive ? ' active' : ''), 'data-tab': t.key, id: 'ops-tab-' + t.key, textContent: t.label, role: 'tab', 'aria-selected': isActive ? 'true' : 'false', 'aria-controls': 'ops-sec-' + t.key});
      btn.addEventListener('click', function() { opsShowTab(t.key); });
      tabBar.appendChild(btn);
    });
    wrap.appendChild(tabBar);

    // Section containers — Live Jobs uses a separate id so polling can target it
    wrap.appendChild(el('div', {className: 'ops-section' + (opsActiveTab === 'jobs' ? ' active' : ''), id: 'ops-sec-jobs', role: 'tabpanel', 'aria-labelledby': 'ops-tab-jobs'}, [
      el('div', {id: 'ops-live-jobs'})
    ]));
    wrap.appendChild(el('div', {className: 'ops-section' + (opsActiveTab === 'audit' ? ' active' : ''), id: 'ops-sec-audit', role: 'tabpanel', 'aria-labelledby': 'ops-tab-audit'}, [
      el('div', {id: 'ops-run-audit'})
    ]));
    wrap.appendChild(el('div', {className: 'ops-section' + (opsActiveTab === 'remediation' ? ' active' : ''), id: 'ops-sec-remediation', role: 'tabpanel', 'aria-labelledby': 'ops-tab-remediation'}, [
      el('div', {id: 'ops-remediation'})
    ]));
    wrap.appendChild(el('div', {className: 'ops-section' + (opsActiveTab === 'migration' ? ' active' : ''), id: 'ops-sec-migration', role: 'tabpanel', 'aria-labelledby': 'ops-tab-migration'}, [
      el('div', {id: 'ops-migration'})
    ]));
    wrap.appendChild(el('div', {className: 'ops-section' + (opsActiveTab === 'approval' ? ' active' : ''), id: 'ops-sec-approval', role: 'tabpanel', 'aria-labelledby': 'ops-tab-approval'}, [
      el('div', {id: 'ops-approval'})
    ]));
    wrap.appendChild(el('div', {className: 'ops-section' + (opsActiveTab === 'backends' ? ' active' : ''), id: 'ops-sec-backends', role: 'tabpanel', 'aria-labelledby': 'ops-tab-backends'}, [
      el('div', {id: 'ops-backends'})
    ]));
    wrap.appendChild(el('div', {className: 'ops-section' + (opsActiveTab === 'products' ? ' active' : ''), id: 'ops-sec-products', role: 'tabpanel', 'aria-labelledby': 'ops-tab-products'}, [
      el('div', {id: 'ops-products'})
    ]));

    body.appendChild(wrap);

    // Fetch initial status then render all tabs
    fetch('/api/ops/status?t=' + Date.now())
      .then(function(r) { return r.ok ? r.json() : {}; })
      .catch(function() { return {}; })
      .then(function(data) {
        opsStatusCache = data;
        opsRenderLiveJobs(data);
        opsRenderAuditTab();
        refreshRemediationPlanCache()
          .catch(function() { return null; })
          .then(function() { opsRenderRemediationTab(); });
        refreshMigrationPlanCache()
          .catch(function() { return null; })
          .then(function() { opsRenderMigrationTab(); });
        opsRenderApprovalTab();
        opsRenderBackendsTab();
        opsRenderAddProductTab();

        // Start polling if on live jobs tab
        if (opsActiveTab === 'jobs') {
          opsStopPolling();
          opsPollingTimer = setInterval(opsRefreshLiveJobs, 5000);
        }
      });
  }

  function openOpsPanel() {
    supportPanelMode = 'ops';

    document.getElementById('slideoverTitle').textContent = 'Operations';
    document.getElementById('slideoverSubtitle').textContent = 'Control plane';

    setFilterBarVisible(false);
    renderOpsPanel();

    document.getElementById('overlay').classList.add('open');
    document.getElementById('slideover').classList.add('open');
    closeFindingDetail();
  }

  /* ── Wire Ops button ── */
  document.getElementById('opsBtn').addEventListener('click', openOpsPanel);

  /* ══════════════════════════════════════════════════════════════
     Operator Run Panel — drives backoffice.api_server endpoints
  ══════════════════════════════════════════════════════════════ */

  var API_KEY_STORAGE = 'bo.api_key';
  var _liveJobsTimer = null;

  function getApiKey() {
    var k = null;
    try { k = localStorage.getItem(API_KEY_STORAGE); } catch (_) { k = null; }
    if (!k) {
      k = window.prompt('Back Office API key:') || '';
      if (k) {
        try { localStorage.setItem(API_KEY_STORAGE, k); } catch (_) {}
      }
    }
    return k;
  }

  function apiPost(path, body) {
    var key = getApiKey();
    if (!key) return Promise.reject(new Error('API key required'));
    return fetch(path, {
      method: 'POST',
      headers: {'Content-Type': 'application/json', 'X-API-Key': key},
      body: JSON.stringify(body || {})
    }).then(function(resp) {
      return resp.json().catch(function() { return {}; }).then(function(data) {
        if (!resp.ok) {
          var err = new Error(data.error || ('HTTP ' + resp.status));
          err.status = resp.status;
          throw err;
        }
        return data;
      });
    });
  }

  function apiGet(path) {
    return fetch(path).then(function(resp) {
      if (!resp.ok) throw new Error('GET ' + path + ': HTTP ' + resp.status);
      return resp.json();
    });
  }

  function populateRunTargets() {
    var select = document.getElementById('runTarget');
    if (!select || select.dataset.populated === '1') return;
    while (select.firstChild) select.removeChild(select.firstChild);
    apiGet('/api/status').then(function(status) {
      (status.targets || []).forEach(function(t) {
        var opt = document.createElement('option');
        opt.value = t;
        opt.textContent = t;
        select.appendChild(opt);
      });
      select.dataset.populated = '1';
    }).catch(function() {
      var opt = document.createElement('option');
      opt.textContent = '\u2014 API unreachable \u2014';
      opt.disabled = true;
      select.appendChild(opt);
    });
  }

  function renderLiveJobs(data) {
    var host = document.getElementById('runLiveJobs');
    if (!host) return;
    if (!data || !data.jobs) { host.textContent = 'Idle.'; return; }
    var rows = Object.keys(data.jobs).map(function(dept) {
      var j = data.jobs[dept];
      var state = (j.status || '?');
      while (state.length < 10) state += ' ';
      var elapsed = j.elapsed != null ? (j.elapsed + 's') : '';
      while (elapsed.length < 6) elapsed += ' ';
      var found = j.findings_count != null ? (j.findings_count + ' findings') : '';
      var name = dept;
      while (name.length < 14) name += ' ';
      return name + ' ' + state + ' ' + elapsed + ' ' + found;
    });
    host.textContent = rows.length ? rows.join('\n') : 'Idle.';
  }

  function startLiveJobsPoll() {
    if (_liveJobsTimer) return;
    var tick = function() {
      apiGet('/api/jobs').then(renderLiveJobs).catch(function() {});
    };
    tick();
    _liveJobsTimer = setInterval(tick, 3000);
  }

  function stopLiveJobsPoll() {
    if (_liveJobsTimer) clearInterval(_liveJobsTimer);
    _liveJobsTimer = null;
  }

  function openRunPanel() {
    var panel = document.getElementById('runPanel');
    panel.hidden = false;
    // Next tick so the CSS transition engages
    requestAnimationFrame(function() { panel.classList.add('open'); });
    populateRunTargets();
    startLiveJobsPoll();
  }

  function closeRunPanel() {
    var panel = document.getElementById('runPanel');
    panel.classList.remove('open');
    setTimeout(function() { panel.hidden = true; }, 250);
    stopLiveJobsPoll();
  }

  function setRunStatus(msg) {
    var s = document.getElementById('runStatus');
    if (s) s.textContent = msg || '';
  }

  document.getElementById('runBtn').addEventListener('click', openRunPanel);
  document.getElementById('runPanelClose').addEventListener('click', closeRunPanel);

  document.getElementById('runScanBtn').addEventListener('click', function() {
    var target = document.getElementById('runTarget').value;
    var dept = document.getElementById('runDept').value;
    var parallel = document.getElementById('runParallel').checked;
    var btn = document.getElementById('runScanBtn');
    btn.disabled = true;
    setRunStatus('Starting\u2026');
    var path = dept === '__all__' ? '/api/run-all' : '/api/run-scan';
    var body = dept === '__all__' ? {target: target, parallel: parallel} : {target: target, department: dept};
    apiPost(path, body).then(function(r) {
      setRunStatus(r.status === 'started' ? 'Running' : (r.status || 'ok'));
    }).catch(function(e) {
      setRunStatus('Error: ' + e.message);
    }).then(function() {
      btn.disabled = false;
    });
  });

  document.getElementById('runFixBtn').addEventListener('click', function() {
    var target = document.getElementById('runTarget').value;
    var preview = document.getElementById('runFixPreview').checked;
    var btn = document.getElementById('runFixBtn');
    btn.disabled = true;
    setRunStatus('Starting fix\u2026');
    apiPost('/api/run-fix', {target: target, preview: preview}).then(function(r) {
      if (r.status === 'started') {
        setRunStatus(preview ? 'Running (preview branch — check Review)' : 'Running');
      } else {
        setRunStatus(r.status || 'ok');
      }
    }).catch(function(e) {
      setRunStatus('Error: ' + e.message);
    }).then(function() {
      btn.disabled = false;
    });
  });

  document.getElementById('runStopBtn').addEventListener('click', function() {
    apiPost('/api/stop', {}).then(function(r) {
      setRunStatus(r.message || 'Stop requested');
    }).catch(function(e) {
      setRunStatus('Error: ' + e.message);
    });
  });

  // ------------------------------------------------------------------
  // Review & Approve panel
  // ------------------------------------------------------------------

  var _reviewPreviews = [];
  var _reviewCurrent = null;
  var _reviewBadgeTimer = null;

  function reviewSetStatus(msg) {
    var s = document.getElementById('reviewStatus');
    if (s) s.textContent = msg || '';
  }

  function reviewUpdateBadge(count) {
    var badge = document.getElementById('reviewBadge');
    if (!badge) return;
    if (count && count > 0) {
      badge.textContent = String(count);
      badge.hidden = false;
    } else {
      badge.hidden = true;
    }
  }

  function pollReviewBadge() {
    apiGet('/api/previews').then(function(data) {
      var list = (data && data.previews) || [];
      reviewUpdateBadge(list.length);
    }).catch(function() {
      reviewUpdateBadge(0);
    });
  }

  function startReviewBadgePoll() {
    if (_reviewBadgeTimer) return;
    pollReviewBadge();
    _reviewBadgeTimer = setInterval(pollReviewBadge, 15000);
  }

  function renderReviewList() {
    var host = document.getElementById('reviewList');
    var empty = document.getElementById('reviewEmpty');
    if (!host) return;
    while (host.firstChild) host.removeChild(host.firstChild);

    if (!_reviewPreviews.length) {
      empty.hidden = false;
      return;
    }
    empty.hidden = true;

    _reviewPreviews.forEach(function(p) {
      var li = document.createElement('li');
      li.className = 'review-item';
      li.tabIndex = 0;
      li.setAttribute('role', 'button');

      var top = document.createElement('div');
      top.className = 'review-item-top';
      var repo = document.createElement('span');
      repo.className = 'review-item-repo';
      repo.textContent = p.repo || '(unknown)';
      var job = document.createElement('span');
      job.className = 'review-item-job';
      job.textContent = p.job_id || '';
      top.appendChild(repo);
      top.appendChild(job);
      li.appendChild(top);

      var meta = document.createElement('div');
      meta.className = 'review-item-meta';
      meta.textContent = (p.branch || '') + (p.created_at ? ' · ' + p.created_at : '');
      li.appendChild(meta);

      var stats = document.createElement('div');
      stats.className = 'review-item-stats';
      var files = document.createElement('span');
      files.className = 'review-item-stat';
      var filesStrong = document.createElement('strong');
      filesStrong.textContent = String((p.changes || []).length);
      files.appendChild(filesStrong);
      files.appendChild(document.createTextNode(' files'));
      var commits = document.createElement('span');
      commits.className = 'review-item-stat';
      var commitsStrong = document.createElement('strong');
      commitsStrong.textContent = String((p.commits || []).length);
      commits.appendChild(commitsStrong);
      commits.appendChild(document.createTextNode(' commits'));
      var checks = document.createElement('span');
      checks.className = 'review-item-stat';
      var checksStrong = document.createElement('strong');
      checksStrong.textContent = String((p.checklist || []).length);
      checks.appendChild(checksStrong);
      checks.appendChild(document.createTextNode(' checks'));
      stats.appendChild(files);
      stats.appendChild(commits);
      stats.appendChild(checks);
      li.appendChild(stats);

      var open = function() { openReviewDetail(p); };
      li.addEventListener('click', open);
      li.addEventListener('keydown', function(e) {
        if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); open(); }
      });
      host.appendChild(li);
    });
  }

  function loadReviewList() {
    return apiGet('/api/previews').then(function(data) {
      _reviewPreviews = (data && data.previews) || [];
      reviewUpdateBadge(_reviewPreviews.length);
      renderReviewList();
    }).catch(function(e) {
      _reviewPreviews = [];
      renderReviewList();
      reviewSetStatus('Could not load previews: ' + e.message);
    });
  }

  function showReviewList() {
    document.getElementById('reviewListView').hidden = false;
    document.getElementById('reviewDetailView').hidden = true;
    _reviewCurrent = null;
    reviewSetStatus('');
  }

  function openReviewDetail(preview) {
    _reviewCurrent = preview;
    document.getElementById('reviewListView').hidden = true;
    var view = document.getElementById('reviewDetailView');
    view.hidden = false;

    document.getElementById('reviewDetailTitle').textContent =
      preview.repo + ' · ' + (preview.job_id || '');

    var meta = document.getElementById('reviewDetailMeta');
    while (meta.firstChild) meta.removeChild(meta.firstChild);
    var branch = document.createElement('div');
    branch.textContent = 'Branch: ' + (preview.branch || '');
    branch.style.fontFamily = 'var(--mono)';
    branch.style.fontSize = 'var(--text-sm)';
    branch.style.color = 'var(--text-dim)';
    meta.appendChild(branch);
    if (preview.compare_url) {
      var link = document.createElement('a');
      link.className = 'review-compare';
      link.href = preview.compare_url;
      link.target = '_blank';
      link.rel = 'noreferrer';
      link.textContent = 'Open compare view →';
      meta.appendChild(link);
    }

    var commits = document.getElementById('reviewCommits');
    while (commits.firstChild) commits.removeChild(commits.firstChild);
    (preview.commits || []).forEach(function(c) {
      var li = document.createElement('li');
      var sha = document.createElement('span');
      sha.className = 'review-commit-sha';
      sha.textContent = (c.sha || '').slice(0, 7);
      var subj = document.createElement('span');
      subj.textContent = c.subject || '';
      li.appendChild(sha);
      li.appendChild(subj);
      commits.appendChild(li);
    });

    var changes = document.getElementById('reviewChanges');
    while (changes.firstChild) changes.removeChild(changes.firstChild);
    (preview.changes || []).forEach(function(ch) {
      var li = document.createElement('li');
      var ins = document.createElement('span');
      ins.className = 'review-diff-ins';
      ins.textContent = '+' + (ch.insertions || 0);
      var del = document.createElement('span');
      del.className = 'review-diff-del';
      del.textContent = '-' + (ch.deletions || 0);
      var file = document.createElement('span');
      file.textContent = ch.file || '';
      li.appendChild(ins);
      li.appendChild(del);
      li.appendChild(file);
      changes.appendChild(li);
    });

    var checklist = document.getElementById('reviewChecklist');
    while (checklist.firstChild) checklist.removeChild(checklist.firstChild);
    var items = preview.checklist || [];
    if (!items.length) {
      var li = document.createElement('li');
      li.textContent = 'No checklist items — approve or discard based on the diff.';
      li.style.color = 'var(--text-dim)';
      checklist.appendChild(li);
    } else {
      items.forEach(function(item, idx) {
        var li = document.createElement('li');
        var chk = document.createElement('input');
        chk.type = 'checkbox';
        chk.id = 'review-chk-' + idx;
        chk.dataset.idx = String(idx);
        chk.addEventListener('change', updateApproveEnabled);
        var label = document.createElement('label');
        label.htmlFor = chk.id;
        var title = document.createElement('div');
        title.textContent = '[' + (item.severity || '?') + '] ' + (item.title || item.finding_id || '');
        var where = document.createElement('div');
        where.style.fontFamily = 'var(--mono)';
        where.style.fontSize = 'var(--text-xs)';
        where.style.color = 'var(--text-dim)';
        where.textContent = (item.file || '') + (item.line ? ':' + item.line : '');
        var verify = document.createElement('div');
        verify.className = 'review-checklist-trust-' + (item.trust_class || 'objective');
        verify.textContent = item.verify || '';
        label.appendChild(title);
        label.appendChild(where);
        label.appendChild(verify);
        li.appendChild(chk);
        li.appendChild(label);
        checklist.appendChild(li);
      });
    }
    updateApproveEnabled();
  }

  function updateApproveEnabled() {
    var btn = document.getElementById('reviewApproveBtn');
    if (!btn || !_reviewCurrent) return;
    var items = _reviewCurrent.checklist || [];
    if (!items.length) {
      btn.disabled = false;
      return;
    }
    var boxes = document.querySelectorAll('#reviewChecklist input[type=checkbox]');
    var all = true;
    for (var i = 0; i < boxes.length; i++) {
      if (!boxes[i].checked) { all = false; break; }
    }
    btn.disabled = !all;
  }

  function openReviewPanel() {
    var panel = document.getElementById('reviewPanel');
    panel.hidden = false;
    requestAnimationFrame(function() { panel.classList.add('open'); });
    showReviewList();
    loadReviewList();
  }

  function closeReviewPanel() {
    var panel = document.getElementById('reviewPanel');
    panel.classList.remove('open');
    setTimeout(function() { panel.hidden = true; }, 250);
  }

  document.getElementById('reviewBtn').addEventListener('click', openReviewPanel);
  document.getElementById('reviewPanelClose').addEventListener('click', closeReviewPanel);
  document.getElementById('reviewBackBtn').addEventListener('click', showReviewList);

  document.getElementById('reviewApproveBtn').addEventListener('click', function() {
    if (!_reviewCurrent) return;
    var btn = document.getElementById('reviewApproveBtn');
    btn.disabled = true;
    reviewSetStatus('Approving…');
    apiPost('/api/approve', {
      target: _reviewCurrent.repo,
      job_id: _reviewCurrent.job_id,
    }).then(function(r) {
      reviewSetStatus('Merged into ' + (r.merged_into || 'base'));
      loadReviewList().then(showReviewList);
    }).catch(function(e) {
      reviewSetStatus('Error: ' + e.message);
      btn.disabled = false;
    });
  });

  document.getElementById('reviewDiscardBtn').addEventListener('click', function() {
    if (!_reviewCurrent) return;
    if (!window.confirm('Discard preview ' + _reviewCurrent.job_id + '? This deletes the branch and artifact.')) return;
    reviewSetStatus('Discarding…');
    apiPost('/api/discard', {
      target: _reviewCurrent.repo,
      job_id: _reviewCurrent.job_id,
    }).then(function() {
      reviewSetStatus('Discarded');
      loadReviewList().then(showReviewList);
    }).catch(function(e) {
      reviewSetStatus('Error: ' + e.message);
    });
  });

  startReviewBadgePoll();

})();
