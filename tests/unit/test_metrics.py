"""
Unit tests for the evaluation metrics module.

Validates statistical correctness of:
- accuracy, precision, recall, F1
- FAR / FRR computation
- d-prime calculation
- EER finding
"""

from __future__ import annotations

import numpy as np
import pytest

from ai.metrics import (
    IdentificationResult,
    _safe_div,
    compute_d_prime,
    evaluate,
    find_eer_threshold,
)


def _result(true_uid, predicted_uid, distance=0.3, confidence=0.7):
    return IdentificationResult(
        true_uid=true_uid,
        predicted_uid=predicted_uid,
        confidence=confidence,
        distance=distance,
    )


class TestSafeDiv:
    def test_normal_division(self):
        assert _safe_div(3.0, 4.0) == pytest.approx(0.75)

    def test_division_by_zero_returns_default(self):
        assert _safe_div(1.0, 0.0) == 0.0
        assert _safe_div(1.0, 0.0, default=1.0) == 1.0


class TestDPrime:

    def test_well_separated_distributions(self):
        genuine = np.random.default_rng(0).normal(0.2, 0.05, 100)
        impostor = np.random.default_rng(1).normal(0.8, 0.05, 100)
        dp = compute_d_prime(genuine, impostor)
        assert dp > 5.0  # Very well separated → large d'

    def test_overlapping_distributions(self):
        genuine = np.random.default_rng(0).normal(0.5, 0.2, 100)
        impostor = np.random.default_rng(1).normal(0.5, 0.2, 100)
        dp = compute_d_prime(genuine, impostor)
        assert dp < 1.0  # Nearly identical → small d'

    def test_insufficient_data_returns_nan(self):
        dp = compute_d_prime(np.array([0.3]), np.array([0.7]))
        assert np.isnan(dp)


class TestEvaluate:

    def test_perfect_classifier(self):
        known = ["A", "B", "C"]
        results = [
            _result("A", "A", 0.2), _result("A", "A", 0.2),
            _result("B", "B", 0.2), _result("C", "C", 0.2),
        ]
        report = evaluate(results, known, threshold=0.5)
        assert report.accuracy == pytest.approx(1.0)
        assert report.precision == pytest.approx(1.0)
        assert report.recall == pytest.approx(1.0)
        assert report.f1_score == pytest.approx(1.0)
        assert report.false_accept_rate == pytest.approx(0.0)
        assert report.false_reject_rate == pytest.approx(0.0)

    def test_all_wrong_classifier(self):
        known = ["A", "B"]
        results = [
            _result("A", "B", 0.2),  # TP wrong identity → FN
            _result("B", "A", 0.2),  # TP wrong identity → FN
        ]
        report = evaluate(results, known, threshold=0.5)
        assert report.recall == pytest.approx(0.0)

    def test_empty_results_raises(self):
        with pytest.raises(ValueError, match="empty"):
            evaluate([], ["A"])

    def test_report_fields_populated(self):
        known = ["S001", "S002"]
        results = [
            _result("S001", "S001", 0.2),
            _result("S002", "S002", 0.25),
            _result("S001", None, 0.6),    # FN (distance > threshold → unknown)
        ]
        report = evaluate(results, known, threshold=0.5)
        assert 0.0 <= report.accuracy <= 1.0
        assert 0.0 <= report.f1_score <= 1.0
        assert report.n_probes == 3
        assert report.n_known_identities == 2


class TestFindEer:

    def test_eer_at_crossing_point(self):
        thresholds = np.linspace(0, 1, 100)
        far = thresholds            # FAR increases with threshold
        frr = 1.0 - thresholds     # FRR decreases with threshold
        eer, thresh = find_eer_threshold(far, frr, thresholds)
        assert eer == pytest.approx(0.5, abs=0.02)
        assert thresh == pytest.approx(0.5, abs=0.02)
