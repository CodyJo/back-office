"""Tests for backoffice.aggregate."""
import json
import logging
import os

import pytest

from backoffice.aggregate import (
    PRIVACY_KEYWORDS,
    PRIVACY_REPO_META,
    aggregate,
    aggregate_department,
    aggregate_privacy,
    aggregate_qa,
    aggregate_self_audit,
    count_severities,
    is_privacy_finding,
    load_json,
    load_valid_repos,
    normalize_precalculated_summary,
    privacy_score,
    write_json,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write(path, data):
    """Write a JSON fixture to *path*, creating parent dirs."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f)


def _findings(*severities):
    """Build a minimal findings list from a sequence of severity strings."""
    return [
        {"id": f"F{i}", "severity": s, "category": "test", "title": f"finding {i}"}
        for i, s in enumerate(severities)
    ]


# ---------------------------------------------------------------------------
# count_severities
# ---------------------------------------------------------------------------

class TestCountSeverities:
    def test_empty_findings(self):
        result = count_severities([])
        assert result == {"critical": 0, "high": 0, "medium": 0, "low": 0, "info": 0}

    def test_counts_each_level(self):
        findings = _findings("critical", "high", "high", "medium", "low", "info", "info")
        result = count_severities(findings)
        assert result["critical"] == 1
        assert result["high"] == 2
        assert result["medium"] == 1
        assert result["low"] == 1
        assert result["info"] == 2

    def test_unknown_severity_maps_to_info(self):
        findings = [{"id": "X1", "severity": "banana"}]
        result = count_severities(findings)
        assert result["info"] == 1

    def test_missing_severity_maps_to_info(self):
        findings = [{"id": "X2"}]
        result = count_severities(findings)
        assert result["info"] == 1

    def test_all_severities_present_in_result(self):
        result = count_severities(_findings("critical"))
        assert set(result.keys()) == {"critical", "high", "medium", "low", "info"}


# ---------------------------------------------------------------------------
# load_json
# ---------------------------------------------------------------------------

class TestLoadJson:
    def test_loads_valid_file(self, tmp_path):
        p = tmp_path / "test.json"
        p.write_text('{"key": "value"}')
        assert load_json(str(p)) == {"key": "value"}

    def test_missing_file_returns_none(self, tmp_path):
        assert load_json(str(tmp_path / "missing.json")) is None

    def test_malformed_json_returns_none(self, tmp_path):
        p = tmp_path / "bad.json"
        p.write_text("{not valid json")
        assert load_json(str(p)) is None

    def test_malformed_json_emits_warning(self, tmp_path, caplog):
        p = tmp_path / "bad.json"
        p.write_text("{not valid json")
        with caplog.at_level(logging.WARNING, logger="backoffice.aggregate"):
            load_json(str(p))
        assert any("malformed" in r.message.lower() for r in caplog.records)


# ---------------------------------------------------------------------------
# normalize_precalculated_summary
# ---------------------------------------------------------------------------

class TestNormalizePrecalculatedSummary:
    def test_overwrites_stale_counts_with_live_counts(self):
        data = {"summary": {"total": 999, "critical": 99}}
        findings = _findings("critical", "high")
        result = normalize_precalculated_summary(data, findings, "qa")
        assert result["total"] == 2
        assert result["critical"] == 1
        assert result["high"] == 1

    def test_no_summary_dict_still_works(self):
        data = {}
        findings = _findings("low")
        result = normalize_precalculated_summary(data, findings, "qa")
        assert result["total"] == 1
        assert result["low"] == 1

    def test_string_summary_ignored(self):
        data = {"summary": "some text"}
        findings = _findings("medium")
        result = normalize_precalculated_summary(data, findings, "qa")
        assert result["total"] == 1

    def test_seo_score_from_overall_score(self):
        data = {"summary": {}, "overall_score": 82}
        findings = []
        result = normalize_precalculated_summary(data, findings, "seo")
        assert result["seo_score"] == 82

    def test_seo_score_prefers_summary_value(self):
        data = {"summary": {"seo_score": 90}, "overall_score": 75}
        findings = []
        result = normalize_precalculated_summary(data, findings, "seo")
        assert result["seo_score"] == 90

    def test_monetization_score_from_nested_scores(self):
        data = {"summary": {}, "scores": {"monetizationReadiness": 55}}
        findings = []
        result = normalize_precalculated_summary(data, findings, "monetization")
        assert result["monetization_readiness_score"] == 55

    def test_product_score_from_nested_snake_case(self):
        data = {"summary": {}, "scores": {"product_readiness": 70}}
        findings = []
        result = normalize_precalculated_summary(data, findings, "product")
        assert result["product_readiness_score"] == 70

    def test_cloud_ops_score_from_data(self):
        data = {"summary": {}, "cloud_ops_score": 79}
        findings = []
        result = normalize_precalculated_summary(data, findings, "cloud-ops")
        assert result["cloud_ops_score"] == 79

    def test_cloud_ops_score_prefers_summary_value(self):
        data = {"summary": {"cloud_ops_score": 85}, "cloud_ops_score": 70}
        findings = []
        result = normalize_precalculated_summary(data, findings, "cloud-ops")
        assert result["cloud_ops_score"] == 85

    def test_scanned_at_promoted_from_data(self):
        data = {"summary": {}, "scanned_at": "2026-01-01T00:00:00Z"}
        findings = []
        result = normalize_precalculated_summary(data, findings, "qa")
        assert result["scanned_at"] == "2026-01-01T00:00:00Z"

    def test_timestamp_fallback_for_scanned_at(self):
        data = {"summary": {}, "timestamp": "2026-02-01T00:00:00Z"}
        findings = []
        result = normalize_precalculated_summary(data, findings, "qa")
        assert result["scanned_at"] == "2026-02-01T00:00:00Z"

    def test_scanned_at_not_overwritten_if_present_in_summary(self):
        data = {
            "summary": {"scanned_at": "original"},
            "scanned_at": "override",
        }
        findings = []
        result = normalize_precalculated_summary(data, findings, "qa")
        assert result["scanned_at"] == "original"


# ---------------------------------------------------------------------------
# is_privacy_finding / privacy_score
# ---------------------------------------------------------------------------

class TestIsPrivacyFinding:
    def test_keyword_in_title(self):
        finding = {"id": "P1", "title": "Missing cookie consent banner"}
        assert is_privacy_finding(finding) is True

    def test_keyword_in_description(self):
        finding = {"id": "P2", "title": "XSS", "description": "User tracking enabled"}
        assert is_privacy_finding(finding) is True

    def test_keyword_in_regulation(self):
        finding = {"id": "P3", "title": "Issue", "regulation": "GDPR consent requirement"}
        assert is_privacy_finding(finding) is True

    def test_keyword_in_category(self):
        finding = {"id": "P4", "title": "Thing", "category": "privacy-policy"}
        assert is_privacy_finding(finding) is True

    def test_non_privacy_finding(self):
        finding = {
            "id": "NP1",
            "title": "SQL injection vulnerability",
            "category": "security",
            "description": "User input not sanitised",
        }
        assert is_privacy_finding(finding) is False

    def test_case_insensitive_match(self):
        finding = {"id": "P5", "title": "COOKIE Settings Missing"}
        assert is_privacy_finding(finding) is True

    def test_all_keywords_are_lowercase(self):
        """All entries in PRIVACY_KEYWORDS must already be lowercase."""
        for kw in PRIVACY_KEYWORDS:
            assert kw == kw.lower(), f"keyword not lowercase: {kw!r}"


class TestPrivacyScore:
    def test_perfect_score_no_findings(self):
        assert privacy_score([]) == 100

    def test_critical_deducts_18_each(self):
        findings = _findings("critical", "critical")
        assert privacy_score(findings) == 100 - 36

    def test_score_floors_at_zero(self):
        # 6 criticals * 18 = 108 > 100
        findings = _findings(*["critical"] * 6)
        assert privacy_score(findings) == 0

    def test_mixed_severity_deduction(self):
        findings = _findings("critical", "high", "medium", "low", "info")
        expected = 100 - 18 - 10 - 4 - 2 - 1
        assert privacy_score(findings) == expected


# ---------------------------------------------------------------------------
# aggregate_qa
# ---------------------------------------------------------------------------

class TestAggregateQa:
    def _make_repo(self, tmp_path, repo_name, findings, fixes=None):
        repo_dir = tmp_path / "results" / repo_name
        repo_dir.mkdir(parents=True)
        _write(
            str(repo_dir / "findings.json"),
            {
                "scanned_at": "2026-01-01T00:00:00Z",
                "summary": {
                    "total": len(findings),
                    "critical": sum(1 for f in findings if f["severity"] == "critical"),
                    "high": 0,
                    "medium": 0,
                    "low": 0,
                    "info": 0,
                },
                "findings": findings,
            },
        )
        if fixes:
            _write(str(repo_dir / "fixes.json"), {"fixes": fixes})
        return repo_dir

    def test_empty_results_dir(self, tmp_path):
        results = tmp_path / "results"
        results.mkdir()
        result = aggregate_qa(str(results), str(tmp_path / "dashboard"))
        assert result["department"] == "qa"
        assert result["repos"] == []
        assert result["totals"]["total_findings"] == 0

    def test_single_repo_aggregated(self, tmp_path):
        findings = _findings("critical", "high", "medium")
        self._make_repo(tmp_path, "my-app", findings)
        result = aggregate_qa(
            str(tmp_path / "results"), str(tmp_path / "dashboard")
        )
        assert len(result["repos"]) == 1
        repo = result["repos"][0]
        assert repo["name"] == "my-app"
        assert len(repo["findings"]) == 3

    def test_fix_status_applied(self, tmp_path):
        findings = _findings("high")
        findings[0]["id"] = "BUG-1"
        fixes = [{"finding_id": "BUG-1", "status": "fixed", "commit_hash": "abc123", "fixed_at": "2026-01-02"}]
        self._make_repo(tmp_path, "my-app", findings, fixes=fixes)
        result = aggregate_qa(
            str(tmp_path / "results"), str(tmp_path / "dashboard")
        )
        enriched = result["repos"][0]["findings"][0]
        assert enriched["status"] == "fixed"
        assert enriched["commit"] == "abc123"
        assert result["totals"]["total_fixed"] == 1

    def test_missing_findings_file_skipped_silently(self, tmp_path):
        results = tmp_path / "results" / "empty-repo"
        results.mkdir(parents=True)
        result = aggregate_qa(
            str(tmp_path / "results"), str(tmp_path / "dashboard")
        )
        assert result["repos"] == []

    def test_repos_sorted_alphabetically(self, tmp_path):
        for name in ("zebra", "alpha", "mango"):
            self._make_repo(tmp_path, name, _findings("low"))
        result = aggregate_qa(
            str(tmp_path / "results"), str(tmp_path / "dashboard")
        )
        names = [r["name"] for r in result["repos"]]
        assert names == sorted(names)

    def test_fix_summary_counts_open_correctly(self, tmp_path):
        findings = _findings("high", "high", "high")
        for i, f in enumerate(findings):
            f["id"] = f"F{i}"
        fixes = [
            {"finding_id": "F0", "status": "fixed", "commit_hash": "", "fixed_at": ""},
        ]
        self._make_repo(tmp_path, "app", findings, fixes=fixes)
        result = aggregate_qa(
            str(tmp_path / "results"), str(tmp_path / "dashboard")
        )
        fix_summary = result["repos"][0]["fix_summary"]
        assert fix_summary["fixed"] == 1
        assert fix_summary["open"] == 2


# ---------------------------------------------------------------------------
# aggregate_department
# ---------------------------------------------------------------------------

class TestAggregateDepartment:
    def _make_dept_repo(self, tmp_path, repo_name, dept_file, data):
        repo_dir = tmp_path / "results" / repo_name
        repo_dir.mkdir(parents=True)
        _write(str(repo_dir / dept_file), data)

    def test_empty_results_dir(self, tmp_path):
        (tmp_path / "results").mkdir()
        result = aggregate_department(str(tmp_path / "results"), "seo-findings.json", "seo")
        assert result["department"] == "seo"
        assert result["repos"] == []

    def test_single_repo_included(self, tmp_path):
        findings = _findings("medium", "low")
        data = {
            "scanned_at": "2026-01-01T00:00:00Z",
            "summary": {"total": 2, "medium": 1, "low": 1},
            "findings": [
                {
                    "id": "SEO-1",
                    "severity": "medium",
                    "category": "meta",
                    "title": "Missing description",
                },
                {
                    "id": "SEO-2",
                    "severity": "low",
                    "category": "links",
                    "title": "Broken link",
                },
            ],
        }
        self._make_dept_repo(tmp_path, "site", "seo-findings.json", data)
        result = aggregate_department(
            str(tmp_path / "results"), "seo-findings.json", "seo"
        )
        assert len(result["repos"]) == 1
        assert result["repos"][0]["name"] == "site"
        assert len(result["repos"][0]["findings"]) == 2

    def test_missing_findings_file_skipped_silently(self, tmp_path):
        repo_dir = tmp_path / "results" / "no-seo"
        repo_dir.mkdir(parents=True)
        result = aggregate_department(
            str(tmp_path / "results"), "seo-findings.json", "seo"
        )
        assert result["repos"] == []

    def test_malformed_json_skipped_with_warning(self, tmp_path, caplog):
        repo_dir = tmp_path / "results" / "bad-repo"
        repo_dir.mkdir(parents=True)
        bad = repo_dir / "seo-findings.json"
        bad.write_text("{broken json")
        with caplog.at_level(logging.WARNING, logger="backoffice.aggregate"):
            result = aggregate_department(
                str(tmp_path / "results"), "seo-findings.json", "seo"
            )
        assert result["repos"] == []
        assert any("malformed" in r.message.lower() for r in caplog.records)

    def test_totals_accumulated_across_repos(self, tmp_path):
        for name in ("repo-a", "repo-b"):
            data = {
                "summary": {"total": 2, "high": 1, "medium": 1},
                "findings": [
                    {"id": f"{name}-1", "severity": "high", "category": "c", "title": "t"},
                    {"id": f"{name}-2", "severity": "medium", "category": "c", "title": "t"},
                ],
            }
            self._make_dept_repo(tmp_path, name, "ada-findings.json", data)
        result = aggregate_department(
            str(tmp_path / "results"), "ada-findings.json", "ada"
        )
        assert result["totals"]["total_findings"] == 4
        assert result["totals"]["high"] == 2
        assert result["totals"]["medium"] == 2

    def test_monetization_revenue_estimate_included(self, tmp_path):
        data = {
            "summary": {},
            "findings": [
                {
                    "id": "MON-1",
                    "severity": "medium",
                    "category": "ads",
                    "title": "Add display ads",
                    "revenue_estimate": "$500/mo",
                    "phase": 1,
                },
            ],
        }
        self._make_dept_repo(tmp_path, "shop", "monetization-findings.json", data)
        result = aggregate_department(
            str(tmp_path / "results"),
            "monetization-findings.json",
            "monetization",
        )
        f = result["repos"][0]["findings"][0]
        assert f["revenue_estimate"] == "$500/mo"
        assert f["phase"] == 1

    def test_department_metadata_included_when_present(self, tmp_path):
        data = {
            "summary": {"seo_score": 78},
            "categories": ["technical", "content"],
            "scores": {"overall": 78},
            "scoring_breakdown": {"technical": 80},
            "findings": [],
        }
        self._make_dept_repo(tmp_path, "web", "seo-findings.json", data)
        result = aggregate_department(
            str(tmp_path / "results"), "seo-findings.json", "seo"
        )
        repo = result["repos"][0]
        assert repo["categories"] == ["technical", "content"]
        assert repo["seo_score"] == 78
        assert "scores" in repo
        assert "scoring_breakdown" in repo

    def test_cloud_ops_pillar_scores_included(self, tmp_path):
        data = {
            "summary": {"cloud_ops_score": 82},
            "cloud_ops_score": 82,
            "pillar_scores": {
                "cost_optimization": 70,
                "security": 90,
                "reliability": 80,
                "performance_efficiency": 95,
                "operational_excellence": 85,
                "sustainability": 100,
            },
            "findings": [
                {
                    "id": "COPS-1",
                    "severity": "high",
                    "category": "over-provisioned",
                    "title": "Lambda memory too high",
                    "pillar": "cost_optimization",
                }
            ],
        }
        self._make_dept_repo(tmp_path, "infra-repo", "cloud-ops-findings.json", data)
        result = aggregate_department(
            str(tmp_path / "results"), "cloud-ops-findings.json", "cloud-ops"
        )
        repo = result["repos"][0]
        assert "pillar_scores" in repo
        assert repo["pillar_scores"]["cost_optimization"] == 70
        assert repo["pillar_scores"]["security"] == 90


# ---------------------------------------------------------------------------
# aggregate_privacy
# ---------------------------------------------------------------------------

class TestAggregatePrivacy:
    def _make_compliance_repo(self, tmp_path, repo_name, findings, frameworks=None):
        repo_dir = tmp_path / "results" / repo_name
        repo_dir.mkdir(parents=True)
        data = {
            "scanned_at": "2026-01-01T00:00:00Z",
            "summary": {"compliance_score": 75},
            "findings": findings,
        }
        if frameworks:
            data["frameworks"] = frameworks
        _write(str(repo_dir / "compliance-findings.json"), data)
        return repo_dir

    def test_filters_non_privacy_findings(self, tmp_path):
        findings = [
            {
                "id": "C1",
                "severity": "high",
                "category": "sql",
                "title": "SQL injection",
                "description": "Unsanitised input",
            },
            {
                "id": "C2",
                "severity": "critical",
                "category": "privacy-policy",
                "title": "Missing cookie consent",
                "description": "",
            },
        ]
        self._make_compliance_repo(tmp_path, "site", findings)
        result = aggregate_privacy(str(tmp_path / "results"))
        assert result["totals"]["total_findings"] == 1
        assert result["repos"][0]["findings"][0]["id"] == "C2"

    def test_uses_known_repo_meta(self, tmp_path):
        findings = [
            {
                "id": "P1",
                "severity": "high",
                "category": "privacy",
                "title": "Privacy issue",
            }
        ]
        self._make_compliance_repo(tmp_path, "codyjo.com", findings)
        result = aggregate_privacy(str(tmp_path / "results"))
        repo = result["repos"][0]
        assert repo["label"] == "Cody Jo Method"
        assert repo["privacy_url"] == "https://www.codyjo.com/privacy/#codyjo-com"

    def test_unknown_repo_gets_defaults(self, tmp_path):
        findings = [
            {
                "id": "P1",
                "severity": "medium",
                "category": "cookie",
                "title": "Cookie issue",
            }
        ]
        self._make_compliance_repo(tmp_path, "unknown-repo", findings)
        result = aggregate_privacy(str(tmp_path / "results"))
        repo = result["repos"][0]
        assert repo["label"] == "unknown-repo"
        assert repo["processors"] == []

    def test_privacy_score_calculated(self, tmp_path):
        findings = [
            {
                "id": "P1",
                "severity": "high",
                "category": "cookie",
                "title": "Cookie consent missing",
            }
        ]
        self._make_compliance_repo(tmp_path, "site", findings)
        result = aggregate_privacy(str(tmp_path / "results"))
        assert result["repos"][0]["summary"]["privacy_score"] == 90  # 100 - 10

    def test_gdpr_score_extracted_from_frameworks(self, tmp_path):
        findings = [
            {"id": "P1", "severity": "low", "category": "privacy", "title": "Privacy gap"}
        ]
        frameworks = {"gdpr": {"score": 65}, "age_verification": {"score": 80}}
        self._make_compliance_repo(tmp_path, "site", findings, frameworks=frameworks)
        result = aggregate_privacy(str(tmp_path / "results"))
        summary = result["repos"][0]["summary"]
        assert summary["gdpr_score"] == 65
        assert summary["age_score"] == 80

    def test_privacy_findings_written_to_repo_dir(self, tmp_path):
        findings = [
            {
                "id": "P1",
                "severity": "medium",
                "category": "tracking",
                "title": "Tracking without consent",
            }
        ]
        repo_dir = self._make_compliance_repo(tmp_path, "site", findings)
        aggregate_privacy(str(tmp_path / "results"))
        output = repo_dir / "privacy-findings.json"
        assert output.exists()
        written = json.loads(output.read_text())
        assert written["name"] == "site"

    def test_missing_compliance_file_skipped_silently(self, tmp_path):
        (tmp_path / "results" / "no-compliance").mkdir(parents=True)
        result = aggregate_privacy(str(tmp_path / "results"))
        assert result["repos"] == []

    def test_all_privacy_keywords_covered(self):
        """Spot-check a selection of keywords are present."""
        required = {"privacy", "consent", "cookie", "gdpr", "tracking", "geolocation"}
        # gdpr not in PRIVACY_KEYWORDS directly but everything else should be
        present = set(PRIVACY_KEYWORDS)
        for kw in required - {"gdpr"}:
            assert kw in present, f"missing keyword: {kw}"


# ---------------------------------------------------------------------------
# aggregate_self_audit
# ---------------------------------------------------------------------------

class TestAggregateSelfAudit:
    def test_writes_self_audit_data(self, tmp_path):
        payload = {"summary": {"total": 3}, "findings": _findings("low", "low", "info")}
        back_office_dir = tmp_path / "results" / "back-office"
        back_office_dir.mkdir(parents=True)
        _write(str(back_office_dir / "findings.json"), payload)
        dashboard = tmp_path / "dashboard"
        dashboard.mkdir()

        result = aggregate_self_audit(str(tmp_path / "results"), str(dashboard))
        assert result is not None
        assert (dashboard / "self-audit-data.json").exists()

    def test_missing_back_office_findings_returns_none(self, tmp_path):
        (tmp_path / "results").mkdir()
        (tmp_path / "dashboard").mkdir()
        result = aggregate_self_audit(
            str(tmp_path / "results"), str(tmp_path / "dashboard")
        )
        assert result is None


# ---------------------------------------------------------------------------
# write_json
# ---------------------------------------------------------------------------

class TestWriteJson:
    def test_creates_parent_dirs(self, tmp_path):
        path = str(tmp_path / "nested" / "dir" / "out.json")
        write_json({"x": 1}, path)
        assert json.loads(open(path).read()) == {"x": 1}

    def test_output_is_indented(self, tmp_path):
        path = str(tmp_path / "out.json")
        write_json({"a": 1}, path)
        raw = open(path).read()
        assert "\n" in raw  # indented JSON has newlines


# ---------------------------------------------------------------------------
# aggregate (main orchestrator)
# ---------------------------------------------------------------------------

class TestAggregate:
    """Integration-style tests for the top-level aggregate() function."""

    def _setup_results(self, tmp_path):
        """Create a minimal results tree with one repo per department."""
        results = tmp_path / "results"
        repo = results / "test-repo"
        repo.mkdir(parents=True)

        # QA
        _write(
            str(repo / "findings.json"),
            {
                "scanned_at": "2026-01-01T00:00:00Z",
                "summary": {"total": 1, "high": 1},
                "findings": [
                    {
                        "id": "Q1",
                        "severity": "high",
                        "category": "security",
                        "title": "XSS",
                    }
                ],
            },
        )

        # SEO
        _write(
            str(repo / "seo-findings.json"),
            {
                "summary": {"total": 1, "medium": 1},
                "findings": [
                    {
                        "id": "S1",
                        "severity": "medium",
                        "category": "meta",
                        "title": "Missing title",
                    }
                ],
            },
        )

        # ADA
        _write(
            str(repo / "ada-findings.json"),
            {
                "summary": {"total": 1, "low": 1},
                "findings": [
                    {
                        "id": "A1",
                        "severity": "low",
                        "category": "contrast",
                        "title": "Low contrast",
                    }
                ],
            },
        )

        # Compliance
        _write(
            str(repo / "compliance-findings.json"),
            {
                "summary": {"total": 1, "critical": 1},
                "findings": [
                    {
                        "id": "C1",
                        "severity": "critical",
                        "category": "cookie",
                        "title": "No cookie consent (privacy)",
                    }
                ],
            },
        )

        # Monetization
        _write(
            str(repo / "monetization-findings.json"),
            {
                "summary": {"total": 1, "info": 1},
                "findings": [
                    {
                        "id": "M1",
                        "severity": "info",
                        "category": "ads",
                        "title": "Add ads",
                    }
                ],
            },
        )

        # Product
        _write(
            str(repo / "product-findings.json"),
            {
                "summary": {"total": 1, "medium": 1},
                "findings": [
                    {
                        "id": "P1",
                        "severity": "medium",
                        "category": "ux",
                        "title": "Improve onboarding",
                    }
                ],
            },
        )

        # Cloud Ops
        _write(
            str(repo / "cloud-ops-findings.json"),
            {
                "summary": {"total": 1, "high": 1},
                "cloud_ops_score": 85,
                "pillar_scores": {
                    "cost_optimization": 80,
                    "security": 90,
                    "reliability": 85,
                    "performance_efficiency": 95,
                    "operational_excellence": 80,
                    "sustainability": 100,
                },
                "findings": [
                    {
                        "id": "COPS-1",
                        "severity": "high",
                        "category": "over-provisioned",
                        "title": "Lambda over-provisioned",
                        "pillar": "cost_optimization",
                    }
                ],
            },
        )
        return results

    def test_produces_all_department_files(self, tmp_path):
        results = self._setup_results(tmp_path)
        dashboard = tmp_path / "dashboard"
        dashboard.mkdir()
        output_path = str(dashboard / "data.json")

        aggregate(str(results), output_path, valid_repos=None)

        expected_files = [
            "data.json",
            "qa-data.json",
            "seo-data.json",
            "ada-data.json",
            "compliance-data.json",
            "privacy-data.json",
            "monetization-data.json",
            "product-data.json",
            "cloud-ops-data.json",
        ]
        for fname in expected_files:
            assert (dashboard / fname).exists(), f"Missing: {fname}"

    def test_data_json_equals_qa_data_json(self, tmp_path):
        """data.json is a backward-compatible copy of qa-data.json."""
        results = self._setup_results(tmp_path)
        dashboard = tmp_path / "dashboard"
        dashboard.mkdir()
        aggregate(str(results), str(dashboard / "data.json"), valid_repos=None)

        data = json.loads((dashboard / "data.json").read_text())
        qa = json.loads((dashboard / "qa-data.json").read_text())
        assert data == qa

    def test_department_field_set_correctly(self, tmp_path):
        results = self._setup_results(tmp_path)
        dashboard = tmp_path / "dashboard"
        dashboard.mkdir()
        aggregate(str(results), str(dashboard / "data.json"), valid_repos=None)

        for fname, expected_dept in [
            ("qa-data.json", "qa"),
            ("seo-data.json", "seo"),
            ("ada-data.json", "ada"),
            ("compliance-data.json", "compliance"),
            ("privacy-data.json", "privacy"),
            ("monetization-data.json", "monetization"),
            ("product-data.json", "product"),
            ("cloud-ops-data.json", "cloud-ops"),
        ]:
            data = json.loads((dashboard / fname).read_text())
            assert data["department"] == expected_dept, f"Wrong dept in {fname}"

    def test_generated_at_present_in_each_file(self, tmp_path):
        results = self._setup_results(tmp_path)
        dashboard = tmp_path / "dashboard"
        dashboard.mkdir()
        aggregate(str(results), str(dashboard / "data.json"), valid_repos=None)

        for fname in ["qa-data.json", "seo-data.json", "privacy-data.json"]:
            data = json.loads((dashboard / fname).read_text())
            assert "generated_at" in data

    def test_logs_summary_for_each_department(self, tmp_path, caplog):
        results = self._setup_results(tmp_path)
        dashboard = tmp_path / "dashboard"
        dashboard.mkdir()

        with caplog.at_level(logging.INFO, logger="backoffice.aggregate"):
            aggregate(str(results), str(dashboard / "data.json"), valid_repos=None)

        messages = " ".join(r.message for r in caplog.records)
        for dept in ("QA", "SEO", "ADA", "Compliance", "Privacy", "Monetization", "Product", "Cloud Ops"):
            assert dept in messages, f"No log for {dept}"
        assert "Total across all departments" in messages

    def test_privacy_keyword_filter_applied_in_aggregate(self, tmp_path):
        """Privacy department should only contain keyword-matching findings."""
        results = self._setup_results(tmp_path)
        dashboard = tmp_path / "dashboard"
        dashboard.mkdir()
        aggregate(str(results), str(dashboard / "data.json"), valid_repos=None)

        privacy = json.loads((dashboard / "privacy-data.json").read_text())
        # The compliance finding has "privacy" in its title -> should appear
        assert privacy["totals"]["total_findings"] >= 1

    def test_valid_repos_filters_stale_repos(self, tmp_path):
        """Repos not in valid_repos are excluded from all departments."""
        results = self._setup_results(tmp_path)
        dashboard = tmp_path / "dashboard"
        dashboard.mkdir()

        # Pass a valid_repos set that does NOT include "test-repo"
        aggregate(str(results), str(dashboard / "data.json"), valid_repos={"other-repo"})

        qa = json.loads((dashboard / "qa-data.json").read_text())
        assert qa["repos"] == []
        assert qa["totals"]["total_findings"] == 0

        seo = json.loads((dashboard / "seo-data.json").read_text())
        assert seo["repos"] == []

    def test_valid_repos_includes_matching_repos(self, tmp_path):
        """Repos present in valid_repos are included normally."""
        results = self._setup_results(tmp_path)
        dashboard = tmp_path / "dashboard"
        dashboard.mkdir()

        aggregate(str(results), str(dashboard / "data.json"), valid_repos={"test-repo"})

        qa = json.loads((dashboard / "qa-data.json").read_text())
        assert len(qa["repos"]) == 1
        assert qa["repos"][0]["name"] == "test-repo"


# ---------------------------------------------------------------------------
# load_valid_repos
# ---------------------------------------------------------------------------

class TestLoadValidRepos:
    def test_skips_targets_with_missing_paths(self, monkeypatch):
        """Targets whose paths don't exist on disk are excluded."""
        fake_config = {
            "targets": [
                {"name": "exists", "path": "/tmp"},
                {"name": "gone", "path": "/nonexistent/path/that/does/not/exist"},
            ]
        }
        import backoffice.delivery
        monkeypatch.setattr(backoffice.delivery, "load_targets_config", lambda: fake_config)

        result = load_valid_repos()
        assert "exists" in result
        assert "gone" not in result
