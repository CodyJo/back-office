"""Tests for the cloud migration comparison model."""

from __future__ import annotations

from pathlib import Path

from backoffice import cloud_migration_compare


def test_load_seeds_default_comparison_files(tmp_path: Path) -> None:
    (tmp_path / "config").mkdir()
    (tmp_path / "results").mkdir()
    (tmp_path / "dashboard").mkdir()

    payload = cloud_migration_compare.load(tmp_path)

    assert payload["baseline"]["normalized_basis_month_to_date"] > 0
    assert len(payload["scenarios"]) == 4
    assert (tmp_path / "config" / "cloud-cost-comparison.yaml").exists()
    assert (tmp_path / "dashboard" / "cloud-cost-comparison.json").exists()


def test_load_flags_cloudfront_invalidation_anomaly(tmp_path: Path) -> None:
    (tmp_path / "config").mkdir()
    (tmp_path / "results").mkdir()
    (tmp_path / "dashboard").mkdir()

    payload = cloud_migration_compare.load(tmp_path)

    anomalies = payload["baseline"]["anomalies"]
    assert len(anomalies) == 1
    assert anomalies[0]["service"] == "Amazon CloudFront"
    assert "invalidations" in anomalies[0]["summary"].lower()
