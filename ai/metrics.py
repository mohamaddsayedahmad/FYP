"""
Face recognition evaluation metrics.

A system that cannot measure itself cannot be improved.
This module provides the evaluation infrastructure required to:
  - Report recognition performance on a labelled test set.
  - Select the optimal decision threshold on the ROC curve.
  - Compare performance across different operating conditions
    (lighting, angle, distance).
  - Produce thesis-ready tables and plots.

Metrics implemented:
  - Accuracy, Precision, Recall, F1-score (per-class and macro-averaged)
  - False Accept Rate (FAR) / False Reject Rate (FRR)
  - Equal Error Rate (EER) — the operating point where FAR == FRR
  - ROC curve data (TPR vs FPR at each threshold)
  - Confusion matrix
  - d-prime (d') — signal detection theory measure of discriminability

References:
  - ISO/IEC 19795-1: Biometric Performance Testing and Reporting
  - Duda, Hart & Stork (2001): Pattern Classification, Chapter 2
  - Jain et al. (2011): Introduction to Biometrics
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class IdentificationResult:
    """One probe–gallery matching result for evaluation."""
    true_uid: str              # ground truth identity
    predicted_uid: Optional[str]  # None = "Unknown" (rejected)
    confidence: float
    distance: float


@dataclass
class EvaluationReport:
    """
    Complete evaluation report for a face recognition system.
    All fields serialisable to JSON for logging and thesis appendices.
    """
    n_probes: int
    n_known_identities: int
    threshold_used: float

    # Closed-set metrics (probe identity IS in gallery)
    accuracy: float            # (TP + TN) / N
    precision: float           # TP / (TP + FP)
    recall: float              # TP / (TP + FN)  — also True Accept Rate
    f1_score: float
    false_accept_rate: float   # FP / (FP + TN)  — FAR
    false_reject_rate: float   # FN / (FN + TP)  — FRR
    equal_error_rate: float    # EER (FAR ≈ FRR operating point)
    d_prime: float             # discriminability index (higher = better separation)

    # Confusion matrix (dict of dict for JSON serializability)
    confusion_matrix: Dict[str, Dict[str, int]] = field(default_factory=dict)

    # ROC curve data
    roc_thresholds: List[float] = field(default_factory=list)
    roc_fpr: List[float] = field(default_factory=list)
    roc_tpr: List[float] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "n_probes": self.n_probes,
            "n_known_identities": self.n_known_identities,
            "threshold_used": self.threshold_used,
            "accuracy": round(self.accuracy, 4),
            "precision": round(self.precision, 4),
            "recall": round(self.recall, 4),
            "f1_score": round(self.f1_score, 4),
            "false_accept_rate": round(self.false_accept_rate, 4),
            "false_reject_rate": round(self.false_reject_rate, 4),
            "equal_error_rate": round(self.equal_error_rate, 4),
            "d_prime": round(self.d_prime, 4),
        }

    def summary_table(self) -> str:
        """Human-readable table for console output / thesis appendix."""
        lines = [
            "=" * 50,
            "  Face Recognition Evaluation Report",
            "=" * 50,
            f"  Probes evaluated:    {self.n_probes}",
            f"  Known identities:    {self.n_known_identities}",
            f"  Decision threshold:  {self.threshold_used:.4f}",
            "-" * 50,
            f"  Accuracy:            {self.accuracy:.4f} ({self.accuracy*100:.2f}%)",
            f"  Precision:           {self.precision:.4f}",
            f"  Recall (TAR):        {self.recall:.4f}",
            f"  F1-score:            {self.f1_score:.4f}",
            "-" * 50,
            f"  False Accept Rate:   {self.false_accept_rate:.4f} ({self.false_accept_rate*100:.2f}%)",
            f"  False Reject Rate:   {self.false_reject_rate:.4f} ({self.false_reject_rate*100:.2f}%)",
            f"  Equal Error Rate:    {self.equal_error_rate:.4f} ({self.equal_error_rate*100:.2f}%)",
            f"  d-prime (d'):        {self.d_prime:.4f}",
            "=" * 50,
        ]
        return "\n".join(lines)


def _safe_div(numerator: float, denominator: float, default: float = 0.0) -> float:
    return numerator / denominator if denominator > 1e-9 else default


def compute_d_prime(genuine_distances: np.ndarray, impostor_distances: np.ndarray) -> float:
    """
    d-prime (d') from signal detection theory.

    Measures the separation between genuine (same-identity) and impostor
    (different-identity) distance distributions.

    d' = |μ_genuine - μ_impostor| / sqrt((σ²_genuine + σ²_impostor) / 2)

    Higher d' → better discrimination. d' < 1 is poor; d' > 2 is good.
    Perfect separation → d' = ∞.
    """
    if len(genuine_distances) < 2 or len(impostor_distances) < 2:
        return float("nan")

    mu_g = np.mean(genuine_distances)
    mu_i = np.mean(impostor_distances)
    var_g = np.var(genuine_distances)
    var_i = np.var(impostor_distances)
    pooled_std = np.sqrt((var_g + var_i) / 2.0)

    if pooled_std < 1e-9:
        return float("inf") if mu_g != mu_i else 0.0

    return float(abs(mu_g - mu_i) / pooled_std)


def compute_roc_curve(
    results: List[IdentificationResult],
    known_uids: List[str],
    n_thresholds: int = 100,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    Compute ROC curve (FPR, TPR) across N thresholds.

    Returns:
        (thresholds, fpr_array, tpr_array) — arrays of length n_thresholds.
    """
    thresholds = np.linspace(0.0, 1.0, n_thresholds)
    fpr_list, tpr_list = [], []

    known_set = set(known_uids)

    for threshold in thresholds:
        tp = fp = tn = fn = 0
        for r in results:
            predicted = r.predicted_uid if r.distance <= threshold else None
            is_genuine = r.true_uid in known_set

            if is_genuine:
                if predicted == r.true_uid:
                    tp += 1
                else:
                    fn += 1
            else:
                if predicted is not None:
                    fp += 1
                else:
                    tn += 1

        tpr = _safe_div(tp, tp + fn, default=0.0)
        fpr = _safe_div(fp, fp + tn, default=0.0)
        tpr_list.append(tpr)
        fpr_list.append(fpr)

    return thresholds, np.array(fpr_list), np.array(tpr_list)


def find_eer_threshold(
    far_values: np.ndarray,
    frr_values: np.ndarray,
    thresholds: np.ndarray,
) -> Tuple[float, float]:
    """
    Find the Equal Error Rate and the threshold at which FAR ≈ FRR.
    Returns (eer, threshold_at_eer).
    """
    diff = np.abs(far_values - frr_values)
    idx = int(np.argmin(diff))
    eer = (far_values[idx] + frr_values[idx]) / 2.0
    return float(eer), float(thresholds[idx])


def evaluate(
    results: List[IdentificationResult],
    known_uids: List[str],
    threshold: float = 0.50,
) -> EvaluationReport:
    """
    Full evaluation pipeline.

    Args:
        results: identification results for each probe image.
        known_uids: list of enrolled student UIDs (gallery).
        threshold: decision distance threshold used during evaluation.

    Returns:
        EvaluationReport with all metrics populated.
    """
    if not results:
        raise ValueError("results list is empty")

    known_set = set(known_uids)
    tp = fp = tn = fn = 0
    genuine_distances, impostor_distances = [], []

    confusion: Dict[str, Dict[str, int]] = {}

    for r in results:
        is_genuine = r.true_uid in known_set

        if is_genuine:
            genuine_distances.append(r.distance)
            true_label = r.true_uid
            pred_label = r.predicted_uid if r.predicted_uid else "Unknown"

            if not confusion.get(true_label):
                confusion[true_label] = {}
            confusion[true_label][pred_label] = confusion[true_label].get(pred_label, 0) + 1

            if r.predicted_uid == r.true_uid:
                tp += 1
            else:
                fn += 1
        else:
            impostor_distances.append(r.distance)
            if r.predicted_uid is not None:
                fp += 1
            else:
                tn += 1

    precision = _safe_div(tp, tp + fp)
    recall = _safe_div(tp, tp + fn)
    f1 = _safe_div(2 * precision * recall, precision + recall)
    accuracy = _safe_div(tp + tn, tp + fp + tn + fn)
    far = _safe_div(fp, fp + tn)
    frr = _safe_div(fn, fn + tp)

    # ROC and EER
    thresholds_arr = np.linspace(0.0, 1.0, 200)
    frr_arr = np.array([
        _safe_div(
            sum(1 for r in results if r.true_uid in known_set and (r.predicted_uid != r.true_uid or r.distance > t)),
            sum(1 for r in results if r.true_uid in known_set)
        )
        for t in thresholds_arr
    ])
    far_arr = np.array([
        _safe_div(
            sum(1 for r in results if r.true_uid not in known_set and r.distance <= t),
            sum(1 for r in results if r.true_uid not in known_set) or 1
        )
        for t in thresholds_arr
    ])

    eer, _ = find_eer_threshold(far_arr, frr_arr, thresholds_arr)

    _, roc_fpr, roc_tpr = compute_roc_curve(results, known_uids)

    dp = compute_d_prime(
        np.array(genuine_distances) if genuine_distances else np.array([0.0]),
        np.array(impostor_distances) if impostor_distances else np.array([1.0]),
    )

    return EvaluationReport(
        n_probes=len(results),
        n_known_identities=len(known_set),
        threshold_used=threshold,
        accuracy=accuracy,
        precision=precision,
        recall=recall,
        f1_score=f1,
        false_accept_rate=far,
        false_reject_rate=frr,
        equal_error_rate=eer,
        d_prime=dp if not (dp != dp) else 0.0,  # NaN guard
        confusion_matrix=confusion,
        roc_thresholds=thresholds_arr.tolist(),
        roc_fpr=roc_fpr.tolist(),
        roc_tpr=roc_tpr.tolist(),
    )


def run_benchmark(
    store,
    test_image_folder: str,
    threshold: float = 0.50,
) -> EvaluationReport:
    """
    Convenience function: run the full evaluation pipeline on a labelled
    test set.

    Expected folder structure:
        test_image_folder/
            student_uid_1/
                img1.jpg
                img2.jpg
            student_uid_2/
                img1.jpg

    Each subfolder name is the ground-truth student_uid.
    """
    import os
    import face_recognition as fr
    from ai.face_recognizer import FaceRecognizer

    recognizer = FaceRecognizer(match_threshold=threshold)
    results = []
    known_uids = list(store.encodings_by_uid.keys())

    for uid_folder in sorted(os.listdir(test_image_folder)):
        folder_path = os.path.join(test_image_folder, uid_folder)
        if not os.path.isdir(folder_path):
            continue
        true_uid = uid_folder

        for img_file in sorted(os.listdir(folder_path)):
            img_path = os.path.join(folder_path, img_file)
            if not img_path.lower().endswith((".jpg", ".jpeg", ".png", ".bmp")):
                continue
            try:
                img = fr.load_image_file(img_path)
                locs = fr.face_locations(img, model="hog")
                if not locs:
                    continue
                encs = fr.face_encodings(img, locs[:1])
                if not encs:
                    continue
                probe = np.array(encs[0], dtype="float32")
                uid, name, conf, dist = recognizer.identify(probe, store)
                results.append(IdentificationResult(
                    true_uid=true_uid,
                    predicted_uid=uid,
                    confidence=conf,
                    distance=dist,
                ))
            except Exception as exc:
                logger.warning("Failed to process %s: %s", img_path, exc)

    if not results:
        raise ValueError(f"No probe images found in {test_image_folder}")

    report = evaluate(results, known_uids, threshold)
    print(report.summary_table())
    return report
