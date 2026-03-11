(function () {
  'use strict';

  var DEPARTMENT_FILES = ['qa', 'seo', 'ada', 'compliance', 'privacy', 'monetization', 'product'];
  var STATUS_BUCKETS = ['open', 'in-progress', 'fixed', 'other'];
  var statusTitles = {
    open: 'Open backlog',
    'in-progress': 'In progress',
    fixed: 'Fixed recently',
    other: 'Other status'
  };
  var severityWeight = { critical: 5, high: 4, medium: 3, low: 2, info: 1 };
  var originalFetch = window.fetch.bind(window);
  var contextState = {
    productKey: 'all',
    product: null,
    orgData: null,
    departmentKey: null,
    filteredData: null
  };

  function getDepartmentKey() {
    var match = window.location.pathname.match(/\/([a-z-]+)\.html$/);
    if (!match) return null;
    return DEPARTMENT_FILES.indexOf(match[1]) !== -1 ? match[1] : null;
  }

  contextState.departmentKey = getDepartmentKey();
  if (!contextState.departmentKey) return;

  contextState.productKey = new URLSearchParams(window.location.search).get('product') || 'all';

  function getOrgData() {
    if (contextState.orgData) return Promise.resolve(contextState.orgData);
    return originalFetch('org-data.json')
      .then(function (resp) { return resp.ok ? resp.json() : null; })
      .then(function (json) {
        contextState.orgData = json || { products: [], departments: [], employees: [] };
        contextState.product = (contextState.orgData.products || []).find(function (product) {
          return product.key === contextState.productKey;
        }) || null;
        return contextState.orgData;
      })
      .catch(function () {
        contextState.orgData = { products: [], departments: [], employees: [] };
        return contextState.orgData;
      });
  }

  function shouldFilterResponse(url) {
    if (contextState.productKey === 'all') return false;
    if (!url) return false;
    return new RegExp('(?:^|/)' + contextState.departmentKey + '-data\\.json(?:\\?|$)').test(url);
  }

  function cloneHeaders(headers) {
    var out = new Headers();
    if (!headers) return out;
    headers.forEach(function (value, key) {
      out.set(key, value);
    });
    return out;
  }

  function extractRepoScore(repo) {
    var summary = repo && repo.summary ? repo.summary : {};
    var keys = [
      'health_score',
      'seo_score',
      'compliance_score',
      'privacy_score',
      'gdpr_score',
      'age_score',
      'product_readiness_score',
      'monetization_readiness_score'
    ];
    for (var i = 0; i < keys.length; i++) {
      if (typeof summary[keys[i]] === 'number') return summary[keys[i]];
    }
    return null;
  }

  function buildTotals(repos) {
    var totals = {
      total_findings: 0,
      total: 0,
      critical: 0,
      high: 0,
      medium: 0,
      low: 0,
      info: 0,
      statuses: {
        open: 0,
        'in-progress': 0,
        fixed: 0,
        other: 0
      }
    };
    var scoreSum = 0;
    var scoreCount = 0;

    repos.forEach(function (repo) {
      var findings = repo.findings || [];
      totals.total_findings += findings.length;
      totals.total += findings.length;
      findings.forEach(function (finding) {
        var severity = finding.severity || 'info';
        totals[severity] = (totals[severity] || 0) + 1;
        var status = normalizeStatus(finding.status);
        totals.statuses[status] = (totals.statuses[status] || 0) + 1;
      });
      var score = extractRepoScore(repo);
      if (typeof score === 'number') {
        scoreSum += score;
        scoreCount += 1;
      }
    });

    if (scoreCount) {
      totals.average_score = Math.round(scoreSum / scoreCount);
    }

    return totals;
  }

  function filterDataForProduct(raw) {
    if (!raw || !raw.repos || !contextState.product || contextState.productKey === 'all') return raw;
    var allowedRepos = new Set(contextState.product.repos || []);
    var repos = raw.repos.filter(function (repo) {
      return allowedRepos.has(repo.name);
    });
    return {
      department: raw.department,
      generated_at: raw.generated_at,
      repos: repos,
      totals: buildTotals(repos)
    };
  }

  window.fetch = function (input, init) {
    var url = typeof input === 'string' ? input : (input && input.url ? input.url : '');
    if (!shouldFilterResponse(url)) {
      return originalFetch(input, init);
    }
    return Promise.all([originalFetch(input, init), getOrgData()])
      .then(function (results) {
        var response = results[0];
        return response.json().then(function (raw) {
          var filtered = filterDataForProduct(raw);
          var headers = cloneHeaders(response.headers);
          headers.set('content-type', 'application/json');
          contextState.filteredData = filtered;
          return new Response(JSON.stringify(filtered), {
            status: response.status,
            statusText: response.statusText,
            headers: headers
          });
        });
      });
  };

  function esc(value) {
    return String(value == null ? '' : value)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  function normalizeStatus(status) {
    if (!status) return 'open';
    var normalized = String(status).toLowerCase().trim();
    if (normalized === 'in progress') return 'in-progress';
    if (STATUS_BUCKETS.indexOf(normalized) !== -1) return normalized;
    return normalized === 'fixed' ? 'fixed' : (normalized === 'open' ? 'open' : 'other');
  }

  function getDepartmentMeta(orgData) {
    var departments = orgData.departments || [];
    var match = departments.find(function (department) {
      return department.key === contextState.departmentKey || department.source_key === contextState.departmentKey;
    });
    if (match) return match;
    if (contextState.departmentKey === 'monetization') {
      return {
        key: 'monetization',
        name: 'Monetization',
        purpose: 'Packaging, pricing, offer strategy, and revenue clarity.',
        persona: 'Translates user value into repeatable revenue without degrading trust.'
      };
    }
    return {
      key: contextState.departmentKey,
      name: contextState.departmentKey,
      purpose: '',
      persona: ''
    };
  }

  function getDepartmentEmployees(orgData) {
    var department = getDepartmentMeta(orgData);
    var eligibleDepartments = [department.key];
    (orgData.departments || []).forEach(function (item) {
      if (item.source_key === contextState.departmentKey && eligibleDepartments.indexOf(item.key) === -1) {
        eligibleDepartments.push(item.key);
      }
    });
    return (orgData.employees || []).filter(function (employee) {
      return eligibleDepartments.indexOf(employee.department) !== -1;
    });
  }

  function getReposFromData(data) {
    return data && data.repos ? data.repos : [];
  }

  function getFindingsFromData(data) {
    return getReposFromData(data).reduce(function (all, repo) {
      var repoFindings = (repo.findings || []).map(function (finding) {
        return Object.assign({ repo_name: repo.name }, finding);
      });
      return all.concat(repoFindings);
    }, []);
  }

  function getSummaryRatings(repos) {
    var ratingTotals = {};
    var ratingCounts = {};
    repos.forEach(function (repo) {
      var summary = repo.summary || {};
      Object.keys(summary).forEach(function (key) {
        if (/_score$/.test(key) && typeof summary[key] === 'number') {
          ratingTotals[key] = (ratingTotals[key] || 0) + summary[key];
          ratingCounts[key] = (ratingCounts[key] || 0) + 1;
        }
      });
    });
    return Object.keys(ratingTotals).map(function (key) {
      return {
        key: key,
        label: key.replace(/_/g, ' ').replace(/\b\w/g, function (char) { return char.toUpperCase(); }),
        value: Math.round(ratingTotals[key] / ratingCounts[key])
      };
    }).sort(function (a, b) { return b.value - a.value; });
  }

  function getStatusCounts(findings) {
    return findings.reduce(function (counts, finding) {
      var status = normalizeStatus(finding.status);
      counts[status] = (counts[status] || 0) + 1;
      return counts;
    }, { open: 0, 'in-progress': 0, fixed: 0, other: 0 });
  }

  function getCategoryBreakdown(findings) {
    var counts = {};
    findings.forEach(function (finding) {
      var category = finding.category || 'uncategorized';
      if (!counts[category]) {
        counts[category] = { count: 0, severity: 0 };
      }
      counts[category].count += 1;
      counts[category].severity += severityWeight[finding.severity] || 1;
    });
    return Object.keys(counts)
      .map(function (key) {
        return {
          key: key,
          count: counts[key].count,
          averageSeverity: Math.round((counts[key].severity / counts[key].count) * 10) / 10
        };
      })
      .sort(function (a, b) {
        return b.count - a.count || b.averageSeverity - a.averageSeverity;
      });
  }

  function statCard(label, value, sublabel) {
    return (
      '<article class="ops-stat-card">' +
        '<div class="ops-stat-label">' + esc(label) + '</div>' +
        '<div class="ops-stat-value">' + esc(value) + '</div>' +
        '<div class="ops-stat-sub">' + esc(sublabel) + '</div>' +
      '</article>'
    );
  }

  function renderOverview(data) {
    var repos = getReposFromData(data);
    var findings = getFindingsFromData(data);
    var statusCounts = getStatusCounts(findings);
    var ratings = getSummaryRatings(repos);
    var headlineScore = ratings[0] ? ratings[0].value : '--';
    var categoryBreakdown = getCategoryBreakdown(findings).slice(0, 6);

    return (
      '<div class="ops-overview-grid">' +
        statCard('Department rating', headlineScore, ratings[0] ? ratings[0].label : 'No score reported') +
        statCard('Backlog items', statusCounts.open + statusCounts['in-progress'], statusCounts.open + ' open / ' + statusCounts['in-progress'] + ' active') +
        statCard('Fixed items', statusCounts.fixed, 'Status tracked in current lane data') +
        statCard('Repos in scope', repos.length, contextState.product && contextState.productKey !== 'all' ? contextState.product.name : 'Whole estate view') +
      '</div>' +
      '<div class="ops-detail-grid">' +
        '<section class="ops-panel-card">' +
          '<div class="ops-panel-title">Ratings</div>' +
          (ratings.length
            ? ratings.map(function (rating) {
                return '<div class="ops-line-item"><span>' + esc(rating.label) + '</span><strong>' + esc(rating.value) + '</strong></div>';
              }).join('')
            : '<div class="ops-empty">No structured score data reported for this department yet.</div>') +
        '</section>' +
        '<section class="ops-panel-card">' +
          '<div class="ops-panel-title">Category backlog</div>' +
          (categoryBreakdown.length
            ? categoryBreakdown.map(function (item) {
                return '<div class="ops-line-item"><span>' + esc(item.key.replace(/-/g, ' ')) + '</span><strong>' + item.count + ' items</strong></div>';
              }).join('')
            : '<div class="ops-empty">No categorized findings in scope.</div>') +
        '</section>' +
      '</div>'
    );
  }

  function renderBacklog(data) {
    var findings = getFindingsFromData(data);
    var grouped = { open: [], 'in-progress': [], fixed: [], other: [] };
    findings.forEach(function (finding) {
      grouped[normalizeStatus(finding.status)].push(finding);
    });
    return (
      '<div class="ops-backlog-grid">' +
      STATUS_BUCKETS.map(function (status) {
        var items = grouped[status].sort(function (a, b) {
          return (severityWeight[b.severity] || 0) - (severityWeight[a.severity] || 0);
        });
        return (
          '<section class="ops-panel-card">' +
            '<div class="ops-panel-title">' + esc(statusTitles[status]) + ' <span class="ops-count-badge">' + items.length + '</span></div>' +
            (items.length
              ? items.slice(0, 18).map(function (finding) {
                  return (
                    '<article class="ops-finding-card">' +
                      '<div class="ops-finding-top">' +
                        '<span class="ops-severity ops-severity-' + esc(finding.severity || 'info') + '">' + esc(finding.severity || 'info') + '</span>' +
                        '<span class="ops-finding-id">' + esc(finding.id || '') + '</span>' +
                      '</div>' +
                      '<h4>' + esc(finding.title || 'Untitled finding') + '</h4>' +
                      '<div class="ops-finding-meta">' + esc(finding.repo_name || 'unknown repo') + ' · ' + esc(finding.category || 'uncategorized') + '</div>' +
                      '<div class="ops-finding-meta">' + esc(finding.file || 'no file') + (finding.line ? ':' + esc(finding.line) : '') + '</div>' +
                    '</article>'
                  );
                }).join('')
              : '<div class="ops-empty">Nothing in this status bucket.</div>') +
          '</section>'
        );
      }).join('') +
      '</div>'
    );
  }

  function getEmployeeStats(employee, data) {
    var repos = getReposFromData(data).filter(function (repo) {
      return !employee.repos || employee.repos.indexOf(repo.name) !== -1;
    });
    var findings = repos.reduce(function (all, repo) {
      return all.concat((repo.findings || []).map(function (finding) {
        return Object.assign({ repo_name: repo.name }, finding);
      }));
    }, []);
    var statusCounts = getStatusCounts(findings);
    var fixableCount = findings.filter(function (finding) {
      return finding.fixable || finding.fixable_by_agent;
    }).length;
    return {
      repoCount: repos.length,
      findings: findings.length,
      open: statusCounts.open + statusCounts['in-progress'],
      fixed: statusCounts.fixed,
      fixable: fixableCount
    };
  }

  function renderEmployees(orgData, data) {
    var employees = getDepartmentEmployees(orgData);
    if (!employees.length) {
      return '<div class="ops-panel-card"><div class="ops-panel-title">Employees</div><div class="ops-empty">No employee profile is assigned to this department yet.</div></div>';
    }
    return (
      '<div class="ops-employee-grid">' +
      employees.map(function (employee) {
        var stats = getEmployeeStats(employee, data);
        return (
          '<article class="ops-panel-card">' +
            '<div class="ops-employee-top">' +
              '<div><div class="ops-employee-name">' + esc(employee.name) + '</div><div class="ops-employee-title">' + esc(employee.title) + '</div></div>' +
              '<div class="ops-employee-score">' + esc(employee.daily_score) + '</div>' +
            '</div>' +
            '<div class="ops-employee-bio">' + esc(employee.persona || employee.bio || '') + '</div>' +
            '<div class="ops-line-item"><span>Repos in lane</span><strong>' + stats.repoCount + '</strong></div>' +
            '<div class="ops-line-item"><span>Items touched</span><strong>' + stats.findings + '</strong></div>' +
            '<div class="ops-line-item"><span>Open / active</span><strong>' + stats.open + '</strong></div>' +
            '<div class="ops-line-item"><span>Fixed tracked</span><strong>' + stats.fixed + '</strong></div>' +
            '<div class="ops-line-item"><span>Agent-fixable now</span><strong>' + stats.fixable + '</strong></div>' +
            '<div class="ops-chip-row">' + (employee.skills || []).slice(0, 6).map(function (skill) {
              return '<span class="ops-chip">' + esc(skill) + '</span>';
            }).join('') + '</div>' +
          '</article>'
        );
      }).join('') +
      '</div>'
    );
  }

  function ensureStyles() {
    if (document.getElementById('departmentContextStyles')) return;
    var style = document.createElement('style');
    style.id = 'departmentContextStyles';
    style.textContent =
      '.ops-shell{margin:0 0 2rem;background:var(--surface);border:1px solid var(--border);border-radius:var(--radius);overflow:hidden;}' +
      '.ops-header{padding:1.25rem 1.25rem 1rem;border-bottom:1px solid var(--border);background:linear-gradient(180deg,rgba(255,255,255,0.02),rgba(255,255,255,0));}' +
      '.ops-eyebrow{font-size:0.72rem;letter-spacing:0.08em;text-transform:uppercase;color:var(--text-muted);margin-bottom:0.45rem;}' +
      '.ops-title-row{display:flex;justify-content:space-between;gap:1rem;align-items:flex-start;flex-wrap:wrap;}' +
      '.ops-title{font-size:1.1rem;font-weight:600;}' +
      '.ops-copy{font-size:0.82rem;color:var(--text-dim);max-width:760px;line-height:1.6;margin-top:0.25rem;}' +
      '.ops-meta{font-size:0.76rem;color:var(--text-dim);}' +
      '.ops-tabs{display:flex;gap:0.5rem;padding:0 1.25rem;border-bottom:1px solid var(--border);flex-wrap:wrap;background:var(--surface-2);}' +
      '.ops-tab{appearance:none;border:none;background:none;color:var(--text-dim);padding:0.9rem 0.1rem;font:inherit;font-size:0.82rem;font-weight:600;cursor:pointer;border-bottom:2px solid transparent;}' +
      '.ops-tab.active{color:var(--accent);border-bottom-color:var(--accent);}' +
      '.ops-panel{padding:1.25rem;display:none;}' +
      '.ops-panel.active{display:block;}' +
      '.ops-overview-grid,.ops-detail-grid,.ops-backlog-grid,.ops-employee-grid{display:grid;gap:1rem;}' +
      '.ops-overview-grid{grid-template-columns:repeat(auto-fit,minmax(170px,1fr));margin-bottom:1rem;}' +
      '.ops-detail-grid,.ops-backlog-grid,.ops-employee-grid{grid-template-columns:repeat(auto-fit,minmax(250px,1fr));}' +
      '.ops-stat-card,.ops-panel-card{background:var(--surface-2);border:1px solid var(--border);border-radius:var(--radius-sm);padding:1rem;}' +
      '.ops-stat-label{font-size:0.7rem;text-transform:uppercase;letter-spacing:0.08em;color:var(--text-muted);margin-bottom:0.45rem;}' +
      '.ops-stat-value{font-family:var(--mono);font-size:1.75rem;font-weight:700;}' +
      '.ops-stat-sub,.ops-employee-bio{font-size:0.76rem;color:var(--text-dim);line-height:1.6;margin-top:0.35rem;}' +
      '.ops-panel-title{font-size:0.82rem;font-weight:600;margin-bottom:0.75rem;display:flex;justify-content:space-between;align-items:center;gap:0.5rem;}' +
      '.ops-line-item{display:flex;justify-content:space-between;gap:0.75rem;padding:0.42rem 0;border-bottom:1px solid var(--border);font-size:0.8rem;}' +
      '.ops-line-item:last-child{border-bottom:none;padding-bottom:0;}' +
      '.ops-empty{font-size:0.8rem;color:var(--text-dim);line-height:1.6;}' +
      '.ops-count-badge{font-family:var(--mono);font-size:0.72rem;padding:0.15rem 0.45rem;border-radius:999px;background:var(--surface-3);color:var(--text-dim);}' +
      '.ops-finding-card{padding:0.8rem;border:1px solid var(--border);border-radius:var(--radius-sm);background:var(--surface);margin-bottom:0.75rem;}' +
      '.ops-finding-card:last-child{margin-bottom:0;}' +
      '.ops-finding-top,.ops-employee-top{display:flex;justify-content:space-between;gap:0.75rem;align-items:flex-start;margin-bottom:0.45rem;}' +
      '.ops-severity{font-size:0.62rem;font-weight:700;text-transform:uppercase;letter-spacing:0.06em;padding:0.15rem 0.4rem;border-radius:999px;background:var(--surface-3);color:var(--text-dim);}' +
      '.ops-severity-critical{background:var(--critical-bg);color:var(--critical);}' +
      '.ops-severity-high{background:var(--high-bg);color:var(--high);}' +
      '.ops-severity-medium{background:var(--medium-bg);color:#cfa447;}' +
      '.ops-severity-low{background:var(--low-bg);color:var(--low);}' +
      '.ops-finding-id{font-family:var(--mono);font-size:0.68rem;color:var(--text-muted);}' +
      '.ops-finding-card h4{font-size:0.82rem;margin:0 0 0.35rem;line-height:1.45;}' +
      '.ops-finding-meta{font-size:0.72rem;color:var(--text-dim);line-height:1.5;}' +
      '.ops-employee-name{font-size:0.92rem;font-weight:600;}' +
      '.ops-employee-title{font-size:0.72rem;text-transform:uppercase;letter-spacing:0.08em;color:var(--accent);margin-top:0.2rem;}' +
      '.ops-employee-score{font-family:var(--mono);font-size:1.05rem;font-weight:700;color:var(--accent);}' +
      '.ops-chip-row{display:flex;gap:0.45rem;flex-wrap:wrap;margin-top:0.85rem;}' +
      '.ops-chip{font-size:0.68rem;padding:0.2rem 0.45rem;border-radius:999px;background:var(--surface-3);color:var(--text-dim);}' +
      '@media (max-width:768px){.ops-shell{margin-bottom:1.5rem;}.ops-header,.ops-panel{padding:1rem;}.ops-tabs{padding:0 1rem;}.ops-tab{padding:0.8rem 0;flex:1 1 auto;text-align:center;}.ops-overview-grid,.ops-detail-grid,.ops-backlog-grid,.ops-employee-grid{grid-template-columns:1fr;}}';
    document.head.appendChild(style);
  }

  function mountPanels(orgData, data) {
    ensureStyles();
    var meta = getDepartmentMeta(orgData);
    var target = document.getElementById('statsGrid');
    if (!target) return;

    var shell = document.createElement('section');
    shell.className = 'ops-shell fade-in';
    shell.innerHTML =
      '<div class="ops-header">' +
        '<div class="ops-eyebrow">Department operating view</div>' +
        '<div class="ops-title-row">' +
          '<div>' +
            '<div class="ops-title">' + esc(meta.name) + ' · ' + esc(contextState.product ? contextState.product.name : 'All products') + '</div>' +
            '<div class="ops-copy">' + esc(meta.persona || meta.purpose || 'Operational backlog, status, ratings, and agent coverage for this lane.') + '</div>' +
          '</div>' +
          '<div class="ops-meta">Product filter: ' + esc(contextState.product ? contextState.product.name : 'All products') + '</div>' +
        '</div>' +
      '</div>' +
      '<div class="ops-tabs">' +
        '<button class="ops-tab active" data-ops-tab="overview">Overview</button>' +
        '<button class="ops-tab" data-ops-tab="backlog">Backlog</button>' +
        '<button class="ops-tab" data-ops-tab="employees">Employees</button>' +
      '</div>' +
      '<div class="ops-panel active" data-ops-panel="overview">' + renderOverview(data) + '</div>' +
      '<div class="ops-panel" data-ops-panel="backlog">' + renderBacklog(data) + '</div>' +
      '<div class="ops-panel" data-ops-panel="employees">' + renderEmployees(orgData, data) + '</div>';

    target.parentNode.insertBefore(shell, target);

    shell.querySelectorAll('.ops-tab').forEach(function (button) {
      button.addEventListener('click', function () {
        var tab = button.getAttribute('data-ops-tab');
        shell.querySelectorAll('.ops-tab').forEach(function (item) { item.classList.remove('active'); });
        shell.querySelectorAll('.ops-panel').forEach(function (panel) { panel.classList.remove('active'); });
        button.classList.add('active');
        var activePanel = shell.querySelector('[data-ops-panel="' + tab + '"]');
        if (activePanel) activePanel.classList.add('active');
      });
    });
  }

  function updateContextLinks() {
    var backLink = document.querySelector('a[href="index.html"]');
    if (backLink && contextState.productKey !== 'all') {
      backLink.href = 'index.html?product=' + encodeURIComponent(contextState.productKey);
      backLink.textContent = '\u2190 Back to ' + (contextState.product ? contextState.product.name : 'HQ');
    }
  }

  function initPanels() {
    Promise.all([
      getOrgData(),
      originalFetch(contextState.departmentKey + '-data.json').then(function (resp) { return resp.ok ? resp.json() : { repos: [] }; })
    ]).then(function (results) {
      var orgData = results[0];
      var rawData = results[1];
      var filtered = filterDataForProduct(rawData);
      contextState.filteredData = filtered;
      updateContextLinks();
      mountPanels(orgData, filtered);
    }).catch(function () {
      updateContextLinks();
    });
  }

  document.addEventListener('DOMContentLoaded', initPanels);
})();
