#!/usr/bin/env python3
"""
Scoring Logic Tests — Validates all dashboard calculation formulas.

Run: python3 scripts/test-scoring.py
  - Tests pure logic with synthetic data (no external deps)
  - Tests against real findings data when available
  - Exit code 0 = all pass, 1 = failures

This is a pre-deploy gate — must pass before syncing dashboards.
"""

import json
import os
import sys

PASS = 0
FAIL = 0
ERRORS = []


def check(name, actual, expected, context=""):
    global PASS, FAIL, ERRORS
    if actual == expected:
        PASS += 1
    else:
        FAIL += 1
        msg = f"  FAIL: {name}: got {actual!r}, expected {expected!r}"
        if context:
            msg += f" ({context})"
        ERRORS.append(msg)
        print(msg)


# ══════════════════════════════════════════════════════════════════════════════
# QA DEPARTMENT — Health Score
# ══════════════════════════════════════════════════════════════════════════════

def qa_health_score(findings):
    """Mirrors qa.html computeHealthScore()"""
    open_f = [f for f in findings if f.get("status") not in ("fixed", "wontfix")]
    if not open_f:
        return 100
    weights = {"critical": 15, "high": 8, "medium": 3, "low": 1, "info": 0}
    penalty = sum(weights.get(f.get("severity", "info"), 1) for f in open_f)
    return max(0, round(100 - penalty))


def test_qa_scoring():
    print("\n── QA Department ──")

    # No findings → 100
    check("qa_empty", qa_health_score([]), 100)

    # All fixed → 100
    check("qa_all_fixed", qa_health_score([
        {"severity": "critical", "status": "fixed"},
        {"severity": "high", "status": "wontfix"},
    ]), 100)

    # Single critical → 85
    check("qa_one_critical", qa_health_score([{"severity": "critical"}]), 85)

    # Mixed severities
    findings = [
        {"severity": "critical"},  # -15
        {"severity": "high"},      # -8
        {"severity": "medium"},    # -3
        {"severity": "low"},       # -1
        {"severity": "info"},      # -0
    ]
    check("qa_mixed", qa_health_score(findings), 73)

    # Floor at 0
    findings = [{"severity": "critical"} for _ in range(10)]
    check("qa_floor_zero", qa_health_score(findings), 0)

    # No status field = open
    check("qa_no_status_is_open", qa_health_score([{"severity": "high"}]), 92)

    # Info-only → 100
    check("qa_info_only", qa_health_score([{"severity": "info"}] * 50), 100)

    # Edge: exactly 100 penalty
    findings = [{"severity": "critical"}] * 6 + [{"severity": "high"}] + [{"severity": "medium"}] + [{"severity": "low"}]
    # 6*15=90 + 8 + 3 + 1 = 102 → clamped to 0
    check("qa_overflow_clamp", qa_health_score(findings), 0)


# ══════════════════════════════════════════════════════════════════════════════
# ADA DEPARTMENT — Compliance Score + WCAG Level
# ══════════════════════════════════════════════════════════════════════════════

def ada_compliance_score(findings):
    """Mirrors ada.html computeOverallScore() (no pre-calculated score)"""
    open_f = [f for f in findings if f.get("status") not in ("fixed", "wontfix")]
    if not open_f:
        return 100
    weights = {"critical": 15, "high": 8, "medium": 3, "low": 1, "info": 0}
    penalty = sum(weights.get(f.get("severity", "info"), 0) for f in open_f)
    return max(0, round(100 - penalty))


def ada_wcag_level(findings, score=None):
    """Mirrors ada.html computeComplianceLevel()"""
    if score is None:
        score = ada_compliance_score(findings)
    open_f = [f for f in findings if f.get("status") not in ("fixed", "wontfix")]
    has_critical = any(f.get("severity") == "critical" for f in open_f)
    has_high = any(f.get("severity") == "high" for f in open_f)
    has_medium = any(f.get("severity") == "medium" for f in open_f)
    has_critical_a = any(
        f.get("severity") == "critical" and f.get("level") == "A"
        for f in open_f
    )

    if score >= 95 and not has_critical and not has_high and not has_medium:
        return "AAA"
    if score >= 70 and not has_critical:
        return "AA"
    if score >= 40 and not has_critical_a:
        return "A"
    return "Non-Compliant"


def test_ada_scoring():
    print("\n── ADA Compliance ──")

    # No findings → score 100, AAA
    check("ada_empty_score", ada_compliance_score([]), 100)
    check("ada_empty_level", ada_wcag_level([]), "AAA")

    # All fixed → 100, AAA
    fixed = [{"severity": "critical", "status": "fixed", "level": "A"}]
    check("ada_all_fixed_score", ada_compliance_score(fixed), 100)
    check("ada_all_fixed_level", ada_wcag_level(fixed), "AAA")

    # Score 95+, no crit/high/med → AAA
    low_only = [{"severity": "low", "level": "A"}] * 4  # -4 → 96
    check("ada_aaa_score", ada_compliance_score(low_only), 96)
    check("ada_aaa_level", ada_wcag_level(low_only), "AAA")

    # Score 95, with one low → AAA
    check("ada_aaa_boundary", ada_wcag_level([{"severity": "low"}] * 5), "AAA")
    check("ada_aaa_boundary_score", ada_compliance_score([{"severity": "low"}] * 5), 95)

    # Score 94 with only lows → NOT AAA (score < 95)
    lows_6 = [{"severity": "low"}] * 6  # -6 → 94
    check("ada_not_aaa_score_94", ada_compliance_score(lows_6), 94)
    check("ada_not_aaa_score_94_level", ada_wcag_level(lows_6), "AA")

    # Score 95 but has medium → NOT AAA
    check("ada_not_aaa_has_medium", ada_wcag_level(
        [{"severity": "medium"}],  # score=97 but has medium
        score=97
    ), "AA")

    # Score 70, no critical → AA
    findings_aa = [{"severity": "high"}, {"severity": "medium"}, {"severity": "low"}]  # 8+3+1=12 → 88
    check("ada_aa", ada_wcag_level(findings_aa), "AA")

    # Score exactly 70, no critical → AA
    # Need penalty exactly 30: e.g., 3 high (24) + 2 medium (6) = 30
    exactly_70 = [{"severity": "high"}] * 3 + [{"severity": "medium"}] * 2
    check("ada_aa_boundary_score", ada_compliance_score(exactly_70), 70)
    check("ada_aa_boundary_level", ada_wcag_level(exactly_70), "AA")

    # Score 69, no critical → A (not AA)
    score_69 = [{"severity": "high"}] * 3 + [{"severity": "medium"}] * 2 + [{"severity": "low"}]
    check("ada_a_score_69", ada_compliance_score(score_69), 69)
    check("ada_a_level_69", ada_wcag_level(score_69), "A")

    # Score 70 but has critical → NOT AA → check A: score>=40, no critical on Level A
    with_crit = [{"severity": "critical", "level": "AA"}, {"severity": "medium"}]
    score_wc = ada_compliance_score(with_crit)  # 100-15-3=82
    check("ada_crit_not_aa_score", score_wc, 82)
    check("ada_crit_not_aa_level", ada_wcag_level(with_crit), "A")

    # Critical on Level A → Non-Compliant
    crit_a = [{"severity": "critical", "level": "A"}]
    check("ada_crit_a_level", ada_wcag_level(crit_a), "Non-Compliant")

    # Score < 40 → Non-Compliant
    many_high = [{"severity": "high"}] * 8  # -64 → 36
    check("ada_low_score", ada_compliance_score(many_high), 36)
    check("ada_low_score_level", ada_wcag_level(many_high), "Non-Compliant")

    # Score exactly 40, no critical on A → A
    # Need penalty=60: 7 high (56) + 1 medium (3) + 1 low (1) = 60
    exactly_40 = [{"severity": "high"}] * 7 + [{"severity": "medium"}] + [{"severity": "low"}]
    check("ada_a_boundary_score", ada_compliance_score(exactly_40), 40)
    check("ada_a_boundary_level", ada_wcag_level(exactly_40), "A")

    # Score 39 → Non-Compliant
    score_39 = [{"severity": "high"}] * 7 + [{"severity": "medium"}] + [{"severity": "low"}] * 2
    check("ada_nc_boundary_score", ada_compliance_score(score_39), 39)
    check("ada_nc_boundary_level", ada_wcag_level(score_39), "Non-Compliant")

    # Info findings don't affect score
    info_only = [{"severity": "info", "level": "AAA"}] * 100
    check("ada_info_only_score", ada_compliance_score(info_only), 100)
    check("ada_info_only_level", ada_wcag_level(info_only), "AAA")

    # Real scenario: codyjo.com ADA (0 crit, 1 high, 6 med, 4 low, 3 info)
    # Score: 100 - 0 - 8 - 18 - 4 - 0 = 70 → AA (no critical)
    codyjo_ada = (
        [{"severity": "high", "level": "A"}] +
        [{"severity": "medium", "level": "A"}] * 4 +
        [{"severity": "medium", "level": "AA"}] * 2 +
        [{"severity": "low", "level": "A"}] * 4 +
        [{"severity": "info", "level": "AAA"}] * 3
    )
    check("ada_codyjo_score", ada_compliance_score(codyjo_ada), 70)
    check("ada_codyjo_level", ada_wcag_level(codyjo_ada), "AA")


# ══════════════════════════════════════════════════════════════════════════════
# REGULATORY COMPLIANCE — Framework Scores + Overall
# ══════════════════════════════════════════════════════════════════════════════

def compliance_framework_score(findings):
    """Mirrors compliance.html computeFrameworkScore()"""
    open_f = [f for f in findings if f.get("status") in ("open", "in-progress", None)
              or "status" not in f]
    if not open_f:
        return 100
    weights = {"critical": 25, "high": 15, "medium": 8, "low": 3, "info": 1}
    penalty = sum(weights.get(f.get("severity", "info"), 0) for f in open_f)
    return max(0, round(100 - penalty))


def compliance_overall_score(findings):
    """Mirrors compliance.html computeOverallScore()"""
    fw_map = {"gdpr": "GDPR", "iso27001": "ISO 27001", "age-verification": "Age Verification"}
    normalized = []
    for f in findings:
        nf = dict(f)
        if "framework" not in nf and "category" in nf:
            nf["framework"] = fw_map.get(nf["category"].lower(), nf["category"])
        if "status" not in nf:
            nf["status"] = "open"
        normalized.append(nf)

    gdpr = [f for f in normalized if f.get("framework") == "GDPR"]
    iso = [f for f in normalized if f.get("framework") == "ISO 27001"]
    age = [f for f in normalized if f.get("framework") == "Age Verification"]

    s_gdpr = compliance_framework_score(gdpr)
    s_iso = compliance_framework_score(iso)
    s_age = compliance_framework_score(age)
    return round((s_gdpr + s_iso + s_age) / 3)


def compliance_status(score):
    if score >= 90:
        return "compliant"
    if score >= 60:
        return "partial"
    return "non-compliant"


def test_compliance_scoring():
    print("\n── Regulatory Compliance ──")

    # Empty → 100 for each framework → overall 100
    check("comp_empty", compliance_overall_score([]), 100)

    # Single framework with issues
    gdpr_findings = [
        {"category": "gdpr", "severity": "high"},   # -15
        {"category": "gdpr", "severity": "medium"},  # -8
    ]
    check("comp_gdpr_only", compliance_framework_score(gdpr_findings), 77)

    # Overall with mixed frameworks
    mixed = [
        {"category": "gdpr", "severity": "critical"},        # GDPR: -25 → 75
        {"category": "iso27001", "severity": "medium"},       # ISO: -8 → 92
        {"category": "age-verification", "severity": "low"},  # Age: -3 → 97
    ]
    # Overall: round((75 + 92 + 97) / 3) = round(88) = 88
    check("comp_mixed_overall", compliance_overall_score(mixed), 88)

    # Status thresholds
    check("comp_status_compliant", compliance_status(90), "compliant")
    check("comp_status_partial", compliance_status(89), "partial")
    check("comp_status_partial_60", compliance_status(60), "partial")
    check("comp_status_nc", compliance_status(59), "non-compliant")

    # Floor at 0
    many = [{"category": "gdpr", "severity": "critical"}] * 5  # -125 → 0
    check("comp_floor", compliance_framework_score(many), 0)

    # Fixed findings excluded
    fixed_f = [{"category": "gdpr", "severity": "critical", "status": "fixed"}]
    # getOpenFindings only includes 'open' or 'in-progress', so 'fixed' is excluded
    # But our function checks status in (open, in-progress, None) — fixed is excluded
    check("comp_fixed_excluded", compliance_framework_score(fixed_f), 100)

    # Missing status = open
    no_status = [{"severity": "high"}]
    check("comp_no_status_is_open", compliance_framework_score(no_status), 85)

    # Info findings cost 1 point each
    info_f = [{"category": "gdpr", "severity": "info"}] * 3
    check("comp_info_penalty", compliance_framework_score(info_f), 97)


# ══════════════════════════════════════════════════════════════════════════════
# SEO, MONETIZATION, PRODUCT — Pre-calculated scores (validation only)
# ══════════════════════════════════════════════════════════════════════════════

def test_precalculated_departments():
    print("\n── Pre-calculated Departments (SEO/Monetization/Product) ──")

    # These use agent-calculated scores, so we validate data structure
    # and ensure score is within bounds
    for dept_name, fname in [
        ("seo", "seo-findings.json"),
        ("monetization", "monetization-findings.json"),
        ("product", "product-findings.json"),
    ]:
        for repo in ["codyjo.com", "thenewbeautifulme"]:
            fpath = os.path.join("results", repo, fname)
            if not os.path.exists(fpath):
                continue
            with open(fpath) as f:
                data = json.load(f)

            summary = data.get("summary", {})
            if not isinstance(summary, dict):
                summary = {}

            findings = data.get("findings", [])
            actual_count = len(findings)

            # Normalize alternate agent payloads so validation reflects dashboard behavior.
            score_candidates = {
                "seo": [summary.get("seo_score"), data.get("overall_score")],
                "monetization": [
                    summary.get("monetization_readiness_score"),
                    data.get("overall_score"),
                    (data.get("scores") or {}).get("monetizationReadiness"),
                ],
                "product": [
                    summary.get("product_readiness_score"),
                    data.get("overall_score"),
                    (data.get("scores") or {}).get("productReadiness"),
                ],
            }

            # Check score is present and in range
            score = next((value for value in score_candidates[dept_name]
                          if isinstance(value, (int, float))), None)
            label = f"{dept_name}_{repo}_score"

            if score is not None:
                check(f"{label}_in_range", 0 <= score <= 100, True, f"score={score}")

            # Verify findings count matches summary (warn-only, agent data may be inconsistent)
            summary_total = summary.get("total", summary.get("total_findings"))
            if summary_total is not None and actual_count != summary_total:
                print(f"  WARN: {label} findings count mismatch: {actual_count} vs summary {summary_total}")


# ══════════════════════════════════════════════════════════════════════════════
# REAL DATA VALIDATION — Test against actual findings files
# ══════════════════════════════════════════════════════════════════════════════

def test_real_data():
    print("\n── Real Data Validation ──")

    for repo in ["codyjo.com", "thenewbeautifulme"]:
        # QA
        qa_path = os.path.join("results", repo, "findings.json")
        if os.path.exists(qa_path):
            with open(qa_path) as f:
                data = json.load(f)
            score = qa_health_score(data.get("findings", []))
            check(f"qa_{repo}_score_range", 0 <= score <= 100, True, f"score={score}")

        # ADA
        ada_path = os.path.join("results", repo, "ada-findings.json")
        if os.path.exists(ada_path):
            with open(ada_path) as f:
                data = json.load(f)
            findings = data.get("findings", [])
            # Normalize field names like the dashboard does
            for finding in findings:
                if "level" not in finding:
                    finding["level"] = finding.get("wcag_level") or finding.get("wcagLevel")
                if "status" not in finding:
                    finding["status"] = "open"

            score = ada_compliance_score(findings)
            level = ada_wcag_level(findings, score)

            check(f"ada_{repo}_score_range", 0 <= score <= 100, True, f"score={score}")
            check(f"ada_{repo}_level_valid", level in ("AAA", "AA", "A", "Non-Compliant"), True, f"level={level}")

            # Cross-check: AAA requires score >= 95
            if level == "AAA":
                check(f"ada_{repo}_aaa_score", score >= 95, True, f"score={score}")
            # AA requires score >= 70
            if level == "AA":
                check(f"ada_{repo}_aa_score", score >= 70, True, f"score={score}")
                has_crit = any(f.get("severity") == "critical" for f in findings
                              if f.get("status") not in ("fixed", "wontfix"))
                check(f"ada_{repo}_aa_no_crit", has_crit, False)

        # Compliance
        comp_path = os.path.join("results", repo, "compliance-findings.json")
        if os.path.exists(comp_path):
            with open(comp_path) as f:
                data = json.load(f)
            score = compliance_overall_score(data.get("findings", []))
            check(f"comp_{repo}_score_range", 0 <= score <= 100, True, f"score={score}")
            status = compliance_status(score)
            check(f"comp_{repo}_status_valid",
                  status in ("compliant", "partial", "non-compliant"), True, f"status={status}")


# ══════════════════════════════════════════════════════════════════════════════
# FIELD NAME NORMALIZATION TESTS
# ══════════════════════════════════════════════════════════════════════════════

def test_field_normalization():
    print("\n── Field Normalization ──")

    # ADA: wcagLevel (camelCase) should work
    findings_camel = [{"severity": "high", "wcagLevel": "A"}]
    for f in findings_camel:
        f["level"] = f.get("wcag_level") or f.get("wcagLevel")
        f["status"] = f.get("status", "open")
    check("ada_camelcase_level", findings_camel[0]["level"], "A")

    # ADA: wcag_level (snake_case) should work
    findings_snake = [{"severity": "high", "wcag_level": "AA"}]
    for f in findings_snake:
        f["level"] = f.get("wcag_level") or f.get("wcagLevel")
    check("ada_snakecase_level", findings_snake[0]["level"], "AA")

    # Compliance: category → framework mapping
    fw_map = {"gdpr": "GDPR", "iso27001": "ISO 27001", "age-verification": "Age Verification"}
    check("comp_fw_gdpr", fw_map.get("gdpr"), "GDPR")
    check("comp_fw_iso", fw_map.get("iso27001"), "ISO 27001")
    check("comp_fw_age", fw_map.get("age-verification"), "Age Verification")

    # Compliance: missing status treated as open
    f_no_status = {"severity": "high"}
    is_open = f_no_status.get("status") in ("open", "in-progress", None) or "status" not in f_no_status
    check("comp_missing_status_open", is_open, True)

    # Compliance: status=fixed is NOT open
    f_fixed = {"severity": "high", "status": "fixed"}
    is_open2 = f_fixed.get("status") in ("open", "in-progress", None) or "status" not in f_fixed
    check("comp_fixed_not_open", is_open2, False)


# ══════════════════════════════════════════════════════════════════════════════
# HQ DASHBOARD — getDeptHealthScore
# ══════════════════════════════════════════════════════════════════════════════

def hq_dept_score(totals):
    """Mirrors index.html getDeptHealthScore() fallback calculation"""
    total = totals.get("total_findings", 0)
    if total == 0:
        return 100
    score = max(0, 100
                - totals.get("critical", 0) * 15
                - totals.get("high", 0) * 8
                - totals.get("medium", 0) * 3
                - totals.get("low", 0) * 1)
    return round(score)


def test_hq_scoring():
    print("\n── HQ Dashboard ──")

    check("hq_empty", hq_dept_score({"total_findings": 0}), 100)
    check("hq_one_crit", hq_dept_score({"total_findings": 1, "critical": 1}), 85)
    check("hq_mixed", hq_dept_score({
        "total_findings": 5, "critical": 1, "high": 1, "medium": 1, "low": 1, "info": 1
    }), 73)
    check("hq_floor", hq_dept_score({
        "total_findings": 10, "critical": 10
    }), 0)


# ══════════════════════════════════════════════════════════════════════════════
# RUN
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    # cd to project root
    script_dir = os.path.dirname(os.path.abspath(__file__))
    os.chdir(os.path.dirname(script_dir))

    test_qa_scoring()
    test_ada_scoring()
    test_compliance_scoring()
    test_hq_scoring()
    test_field_normalization()
    test_precalculated_departments()
    test_real_data()

    print(f"\n{'='*50}")
    print(f"  {PASS} passed, {FAIL} failed")
    print(f"{'='*50}")

    if ERRORS:
        print("\nFailures:")
        for e in ERRORS:
            print(e)

    sys.exit(1 if FAIL > 0 else 0)
