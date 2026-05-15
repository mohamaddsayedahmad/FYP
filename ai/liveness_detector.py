"""
Liveness / anti-spoofing detector.

Problem: without liveness detection, any printed photograph held in front
of the camera will be recognised and mark attendance. This defeats the entire
purpose of a face attendance system.

This module implements TWO complementary liveness signals:

1. EYE ASPECT RATIO (EAR) BLINK DETECTION
   Based on the landmark paper:
     Soukupová, T. & Čech, J. (2016). Real-Time Eye Blink Detection using
     Facial Landmarks. In CVWW 2016.

   The Eye Aspect Ratio measures the ratio of eye height to eye width:
       EAR = (||p2-p6|| + ||p3-p5||) / (2 × ||p1-p4||)
   where p1..p6 are the six eye landmarks.

   A blink causes EAR to drop sharply below EAR_THRESHOLD.
   A real person blinks; a printed photograph never does.

   Implementation uses dlib's 68-point facial landmark predictor via the
   face_recognition library's face_landmarks() function.

2. TEXTURE ANALYSIS (LBP-BASED)
   Local Binary Patterns on the face crop measure micro-texture.
   A printed photograph has regular, flat texture characteristic of paper.
   A live face has the complex, irregular micro-texture of skin.
   We use a simple frequency-domain sharpness proxy as a lightweight
   substitute when dlib landmarks are unavailable.

3. MOTION CONSISTENCY CHECK
   The face region's optical flow between consecutive frames is measured.
   A still photograph has near-zero motion; a live person has natural
   micro-movements (breathing, head sway).
   This is an additional signal, not a standalone test.

IMPORTANT LIMITATIONS (stated openly for academic honesty):
- This is a *passive* liveness check. It does not require user interaction
  (no "please blink now" prompt). Active liveness (challenge-response) is
  more robust but degrades UX.
- High-quality video of the subject playing on a screen can defeat blink
  detection. 3D-printed face masks can defeat texture analysis.
- For production deployment requiring strong anti-spoofing, dedicated
  liveness SDKs (FaceTec, iProov) should be evaluated.
- This implementation targets the threat model of casual attendance proxying
  (a friend holding a photo), not adversarial attacks.

Academic value:
   Implementing and discussing liveness detection demonstrates awareness of
   real-world security constraints in biometric systems — a topic covered in
   graduate-level courses on computer vision and biometric security.
"""

from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass, field
from typing import Deque, List, Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)

# ---- EAR blink detection parameters ----------------------------------------

EAR_THRESHOLD = 0.22       # EAR below this = eye closed
EAR_CONSEC_FRAMES = 2      # eye must be closed for ≥ N consecutive frames
BLINKS_REQUIRED = 1        # minimum blinks to consider subject live
LIVENESS_WINDOW_FRAMES = 150  # frames to assess liveness (~5 s at 30 fps)

# ---- Motion analysis parameters --------------------------------------------

MOTION_THRESHOLD = 0.5     # mean optical flow magnitude; below = suspiciously still


@dataclass
class LivenessState:
    """
    Per-face liveness tracking state. One instance per tracked face / person.
    The camera session creates one per detected face bounding box.
    """
    blink_count: int = 0
    ear_below_count: int = 0         # consecutive frames with EAR < threshold
    frame_count: int = 0
    is_live: bool = False            # set to True once liveness confirmed
    confidence: float = 0.0         # 0–1 liveness confidence
    _ear_history: Deque[float] = field(default_factory=lambda: deque(maxlen=30))
    _prev_face_crop: Optional[np.ndarray] = field(default=None, repr=False)

    def reset(self) -> None:
        self.blink_count = 0
        self.ear_below_count = 0
        self.frame_count = 0
        self.is_live = False
        self.confidence = 0.0
        self._ear_history.clear()
        self._prev_face_crop = None


def _eye_aspect_ratio(eye_landmarks: List[Tuple[int, int]]) -> float:
    """
    Compute Eye Aspect Ratio from 6 landmark points.
    Points are (x, y) tuples in the order: left-corner, upper-left, upper-right,
    right-corner, lower-right, lower-left.
    """
    if len(eye_landmarks) != 6:
        return 0.3  # neutral value

    p = [np.array(pt, dtype=float) for pt in eye_landmarks]
    # Vertical distances
    A = np.linalg.norm(p[1] - p[5])
    B = np.linalg.norm(p[2] - p[4])
    # Horizontal distance
    C = np.linalg.norm(p[0] - p[3])
    if C < 1e-6:
        return 0.3
    return (A + B) / (2.0 * C)


def _compute_ear_from_landmarks(landmarks: dict) -> Optional[float]:
    """
    Extract EAR from face_recognition landmarks dict.
    Returns None if landmark keys are missing.
    """
    left_eye = landmarks.get("left_eye")
    right_eye = landmarks.get("right_eye")

    if not left_eye or not right_eye:
        return None
    if len(left_eye) < 6 or len(right_eye) < 6:
        return None

    ear_left = _eye_aspect_ratio(left_eye[:6])
    ear_right = _eye_aspect_ratio(right_eye[:6])
    return (ear_left + ear_right) / 2.0


def _texture_score(face_crop_gray: np.ndarray) -> float:
    """
    Estimate face texture richness using Laplacian variance.
    A printed photo has smooth, regular texture → low variance.
    A live face has complex micro-texture → higher variance.
    Returns a score in [0, 1]; higher = more likely live.
    """
    try:
        import cv2
        laplacian_var = cv2.Laplacian(face_crop_gray, cv2.CV_64F).var()
        # Normalise: variance < 10 → likely flat/printed; > 200 → definitely live
        return float(min(laplacian_var / 200.0, 1.0))
    except Exception:
        return 0.5  # neutral if computation fails


def _motion_score(
    prev_crop: Optional[np.ndarray],
    curr_crop: np.ndarray,
) -> float:
    """
    Compute optical flow magnitude between consecutive face crops.
    Near-zero flow → suspiciously still → lower liveness score.
    Returns a score in [0, 1].
    """
    if prev_crop is None:
        return 0.5  # neutral on first frame

    try:
        import cv2
        # Resize to small fixed size for speed
        sz = (40, 40)
        prev_s = cv2.resize(prev_crop, sz)
        curr_s = cv2.resize(curr_crop, sz)

        flow = cv2.calcOpticalFlowFarneback(
            prev_s, curr_s, None,
            pyr_scale=0.5, levels=2, winsize=8,
            iterations=2, poly_n=5, poly_sigma=1.1, flags=0,
        )
        magnitude = float(np.mean(np.linalg.norm(flow, axis=2)))
        # Normalise: magnitude < 0.2 → very still; > 2.0 → strong motion
        return float(min(magnitude / 2.0, 1.0))
    except Exception:
        return 0.5


class LivenessDetector:
    """
    Stateless detector. The caller maintains LivenessState per face.
    """

    def __init__(
        self,
        ear_threshold: float = EAR_THRESHOLD,
        ear_consec_frames: int = EAR_CONSEC_FRAMES,
        blinks_required: int = BLINKS_REQUIRED,
        liveness_window: int = LIVENESS_WINDOW_FRAMES,
        use_motion: bool = True,
        use_texture: bool = True,
    ) -> None:
        self._ear_threshold = ear_threshold
        self._ear_consec = ear_consec_frames
        self._blinks_required = blinks_required
        self._window = liveness_window
        self._use_motion = use_motion
        self._use_texture = use_texture

    def update(
        self,
        state: LivenessState,
        frame_bgr: np.ndarray,
        face_bbox: Tuple[int, int, int, int],
    ) -> LivenessState:
        """
        Update liveness state for one face in one frame.
        Modifies state in place and returns it.

        Args:
            state: per-face LivenessState (caller owns).
            frame_bgr: full-resolution BGR camera frame.
            face_bbox: (top, right, bottom, left) in full-res coords.
        """
        import cv2
        import face_recognition as fr

        state.frame_count += 1
        top, right, bottom, left = face_bbox

        # Extract face crop for texture and motion analysis
        h, w = frame_bgr.shape[:2]
        t = max(0, top); b = min(h, bottom)
        l = max(0, left); r = min(w, right)
        face_crop_bgr = frame_bgr[t:b, l:r]
        if face_crop_bgr.size == 0:
            return state

        face_crop_gray = cv2.cvtColor(face_crop_bgr, cv2.COLOR_BGR2GRAY)

        # ---- EAR blink detection ------------------------------------------
        rgb_frame = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        landmarks_list = fr.face_landmarks(rgb_frame, [face_bbox])
        ear = None
        if landmarks_list:
            ear = _compute_ear_from_landmarks(landmarks_list[0])

        if ear is not None:
            state._ear_history.append(ear)
            if ear < self._ear_threshold:
                state.ear_below_count += 1
            else:
                if state.ear_below_count >= self._ear_consec:
                    state.blink_count += 1
                    logger.debug("Blink detected (EAR=%.3f, count=%d)", ear, state.blink_count)
                state.ear_below_count = 0

        # ---- Texture score ------------------------------------------------
        texture = _texture_score(face_crop_gray) if self._use_texture else 0.5

        # ---- Motion score -------------------------------------------------
        motion = (
            _motion_score(state._prev_face_crop, face_crop_gray)
            if self._use_motion else 0.5
        )
        state._prev_face_crop = face_crop_gray.copy()

        # ---- Composite liveness confidence --------------------------------
        blink_score = min(state.blink_count / self._blinks_required, 1.0)
        # Weighted combination: blink is strongest signal
        state.confidence = 0.60 * blink_score + 0.25 * texture + 0.15 * motion

        if (
            state.blink_count >= self._blinks_required
            and state.confidence >= 0.5
            and not state.is_live
        ):
            state.is_live = True
            logger.info(
                "Liveness confirmed: blinks=%d, texture=%.2f, motion=%.2f, confidence=%.2f",
                state.blink_count, texture, motion, state.confidence,
            )

        # Expire liveness window: reset if no blink in too many frames
        if state.frame_count > self._window and state.blink_count == 0:
            logger.debug("Liveness window expired with no blinks — resetting")
            state.reset()

        return state
