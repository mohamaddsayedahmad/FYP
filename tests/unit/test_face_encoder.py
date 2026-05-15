"""
Unit tests for the face encoding module.

These tests validate the quality-scoring, outlier-rejection, and
serialisation logic without requiring a camera or real face images.
All test encodings are synthetic random numpy vectors.
"""

from __future__ import annotations

import json
import numpy as np
import pytest

from ai.face_encoder import (
    EncodingResult,
    RegistrationReport,
    _compute_quality_score,
    _reject_outliers,
    blob_to_encodings,
    encodings_to_blob,
)


def _make_encoding(seed: int = 0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    v = rng.normal(0, 0.1, 128).astype("float32")
    return v / (np.linalg.norm(v) + 1e-9)


def _make_result(seed: int = 0, quality: float = 0.8) -> EncodingResult:
    return EncodingResult(
        encoding=_make_encoding(seed),
        quality_score=quality,
        image_path=f"/fake/{seed}.jpg",
        face_bbox=(100, 200, 200, 100),
    )


class TestQualityScoring:

    def test_high_quality_large_sharp_face(self):
        score = _compute_quality_score(sharpness=300.0, face_height=250, face_width=250)
        assert score > 0.8

    def test_low_quality_blurry_small_face(self):
        score = _compute_quality_score(sharpness=5.0, face_height=40, face_width=40)
        assert score < 0.3

    def test_score_between_zero_and_one(self):
        for sharpness in [0, 50, 200, 1000]:
            for size in [10, 60, 150, 500]:
                score = _compute_quality_score(sharpness, size, size)
                assert 0.0 <= score <= 1.0, f"Score out of range: {score}"


class TestOutlierRejection:

    def test_no_rejection_when_fewer_than_three(self):
        results = [_make_result(i) for i in range(2)]
        accepted, rejected = _reject_outliers(results)
        assert len(accepted) == 2
        assert len(rejected) == 0

    def test_outlier_is_identified(self):
        # Create 5 close encodings and one extreme outlier
        base = np.ones(128, dtype="float32") * 0.01
        close = [
            EncodingResult(
                encoding=base + np.random.default_rng(i).normal(0, 0.01, 128).astype("float32"),
                quality_score=0.9, image_path=f"/f/{i}.jpg", face_bbox=(0, 0, 0, 0),
            )
            for i in range(5)
        ]
        outlier = EncodingResult(
            encoding=np.ones(128, dtype="float32"),  # far from cluster
            quality_score=0.9, image_path="/f/outlier.jpg", face_bbox=(0, 0, 0, 0),
        )
        results = close + [outlier]
        accepted, rejected = _reject_outliers(results, quantile=0.75)
        accepted_paths = {r.image_path for r in accepted}
        rejected_paths = {r.image_path for r in rejected}
        assert outlier.image_path not in accepted_paths
        assert outlier.image_path in rejected_paths

    def test_never_rejects_all_encodings(self):
        # Extreme case: only 3 encodings, all very different
        results = [
            EncodingResult(
                encoding=np.eye(128, dtype="float32")[i % 128],
                quality_score=0.5, image_path=f"/f/{i}.jpg", face_bbox=(0, 0, 0, 0),
            )
            for i in range(3)
        ]
        accepted, rejected = _reject_outliers(results)
        assert len(accepted) > 0


class TestEncodingSerialization:

    def test_round_trip_single_encoding(self, encryption_service):
        enc = _make_encoding(42)
        blob = encodings_to_blob([enc], encryption_service)
        restored = blob_to_encodings(blob, encryption_service)
        assert len(restored) == 1
        np.testing.assert_array_almost_equal(enc, restored[0], decimal=5)

    def test_round_trip_multiple_encodings(self, encryption_service):
        encs = [_make_encoding(i) for i in range(5)]
        blob = encodings_to_blob(encs, encryption_service)
        restored = blob_to_encodings(blob, encryption_service)
        assert len(restored) == 5
        for orig, res in zip(encs, restored):
            np.testing.assert_array_almost_equal(orig, res, decimal=5)

    def test_backward_compatible_with_legacy_flat_format(self, encryption_service):
        enc = _make_encoding(7)
        # Legacy format: encrypt a flat list (not list-of-lists)
        legacy_json = json.dumps(enc.tolist())
        legacy_blob = encryption_service.encrypt(legacy_json)
        restored = blob_to_encodings(legacy_blob, encryption_service)
        assert len(restored) == 1
        np.testing.assert_array_almost_equal(enc, restored[0], decimal=5)
