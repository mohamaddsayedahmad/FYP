"""
Camera attendance loop — rebuilt on the new AI pipeline.

Architecture improvements over the original attendance.py:

1. SEPARATION OF CONCERNS
   - face_recognizer.CameraSession handles recognition + frame annotation.
   - liveness_detector.LivenessDetector handles anti-spoofing.
   - This module orchestrates them; it does not contain recognition logic.

2. LIVENESS GATE
   A student is only signed in after liveness is confirmed (blink detected).
   Without this, holding a printed photograph marks attendance.

3. CONFIDENCE DISPLAY
   Each face label shows identity + confidence percentage, giving the operator
   real-time feedback on match quality (e.g. "Alice (87%)").

4. GRACEFUL SHUTDOWN
   The loop signals completion via a threading.Event so the GUI thread can
   join cleanly without busy-waiting. All sign-outs happen in the finally block.

5. CALLBACK ARCHITECTURE
   on_sign_in / on_sign_out callbacks allow the GUI layer to update its display
   without the camera loop needing to import Tkinter.

6. STRUCTURED LOGGING
   All events are logged with student_uid, course_id, and timestamp so the
   audit trail is complete even if the GUI is closed during a session.
"""

from __future__ import annotations

import logging
import threading
from typing import Callable, Dict, Optional, Set

import numpy as np

from ai.face_recognizer import CameraSession, FaceRecognizer, KnownFaceStore
from ai.liveness_detector import LivenessDetector, LivenessState

logger = logging.getLogger(__name__)

# ---- Camera open helper (robust, tries multiple indices and backends) -------

def _open_camera(preferred_indices=(0, 1, 2)):
    import cv2
    backends = []
    for attr in ("CAP_DSHOW", "CAP_MSMF", "CAP_ANY"):
        if hasattr(cv2, attr):
            backends.append(getattr(cv2, attr))
    if not backends:
        backends = [0]

    for idx in preferred_indices:
        for api in backends:
            try:
                cap = cv2.VideoCapture(idx, api)
                if cap and cap.isOpened():
                    ok, frame = cap.read()
                    if ok and frame is not None and frame.size > 0:
                        return cap
                    cap.release()
            except Exception:
                pass

    raise RuntimeError(
        "Cannot open camera.\n"
        "  - Close other applications using the camera (Zoom, Teams, Camera app).\n"
        "  - Check Windows privacy settings → Camera.\n"
        "  - Try a different camera index (0, 1, 2)."
    )


def _ensure_highgui():
    import cv2
    try:
        cv2.namedWindow("__probe__", cv2.WINDOW_NORMAL)
        cv2.destroyWindow("__probe__")
    except Exception as exc:
        raise RuntimeError(
            "OpenCV HighGUI (window / imshow) is unavailable.\n"
            "Fix: uninstall opencv-python-headless, install opencv-python."
        ) from exc


# ---- Main loop function ----------------------------------------------------

def run_attendance_loop(
    store: KnownFaceStore,
    course_id: int,
    sign_in_callback: Callable[[str, str], None],   # (uid, name)
    sign_out_callback: Callable[[str, str], None],  # (uid, name)
    stop_event: Optional[threading.Event] = None,
    enable_liveness: bool = True,
    window_title: str = "AI Face Attendance — press Q to stop",
) -> Set[str]:
    """
    Run the camera-based attendance session.

    Args:
        store: pre-loaded KnownFaceStore from AttendanceService.
        course_id: course being attended (for sign-in/sign-out calls).
        sign_in_callback: called when a student is newly signed in.
        sign_out_callback: called when a student is signed out at session end.
        stop_event: set this event to request clean shutdown from another thread.
        enable_liveness: whether to require a blink before sign-in.
        window_title: OpenCV window title.

    Returns:
        Set of student UIDs signed in during this session.
    """
    import cv2

    _ensure_highgui()

    if not store or store.is_empty():
        logger.warning("No enrolled face data — session will show all faces as Unknown.")

    recognizer = FaceRecognizer()
    session = CameraSession(store=store, course_id=course_id, recognizer=recognizer)
    liveness = LivenessDetector() if enable_liveness else None

    # Per-face liveness state; keyed by coarse bbox position string
    liveness_states: Dict[str, LivenessState] = {}
    liveness_confirmed: Set[str] = set()   # UIDs whose liveness is confirmed

    cap = _open_camera()
    logger.info(
        "Camera session started for course %d | %d enrolled students | %d encodings",
        course_id, store.student_count, store.encoding_count,
    )

    try:
        while True:
            if stop_event and stop_event.is_set():
                logger.info("Stop event received — ending session.")
                break

            ret, frame = cap.read()
            if not ret or frame is None or frame.size == 0:
                logger.warning("Frame read failed — retrying...")
                continue

            results = session.process_frame(frame)

            for result in results:
                if not result.is_known:
                    continue

                uid = result.student_uid
                bbox_key = f"{result.face_bbox[0]//64},{result.face_bbox[2]//64}"

                # ---- Liveness gate ----------------------------------------
                if enable_liveness and uid not in liveness_confirmed:
                    if bbox_key not in liveness_states:
                        liveness_states[bbox_key] = LivenessState()
                    ls = liveness_states[bbox_key]
                    liveness.update(ls, frame, result.face_bbox)

                    if ls.is_live:
                        liveness_confirmed.add(uid)
                        logger.info(
                            "Liveness confirmed for %s (%s) — signing in",
                            uid, result.name,
                        )
                    else:
                        continue  # hold off sign-in until liveness is confirmed

                # ---- Sign in ----------------------------------------------
                if result.is_new_sign_in:
                    logger.info(
                        "Sign-in: %s (%s) course=%d confidence=%.2f",
                        uid, result.name, course_id, result.confidence,
                    )
                    try:
                        sign_in_callback(uid, result.name)
                    except Exception as exc:
                        logger.error("sign_in_callback failed for %s: %s", uid, exc)

            annotated = session.draw_annotations(frame, results)

            # Liveness status overlay
            if enable_liveness:
                for result in results:
                    if result.is_known and result.student_uid not in liveness_confirmed:
                        top, right, bottom, left = result.face_bbox
                        cv2.putText(
                            annotated, "BLINK TO CONFIRM",
                            (left, top - 8),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 165, 255), 1,
                        )

            cv2.imshow(window_title, annotated)
            if cv2.waitKey(1) & 0xFF == ord("q"):
                logger.info("User pressed Q — ending session.")
                break

    finally:
        try:
            cap.release()
        except Exception:
            pass
        try:
            cv2.destroyAllWindows()
        except Exception:
            pass

        signed_in = session.signed_in_uids
        logger.info("Session ended. Signing out %d student(s).", len(signed_in))

        for uid in signed_in:
            name = store.names_by_uid.get(uid, uid)
            try:
                sign_out_callback(uid, name)
            except Exception as exc:
                logger.error("sign_out_callback failed for %s: %s", uid, exc)

        logger.info("Camera session for course %d complete.", course_id)

    return signed_in
