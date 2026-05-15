# attendance.py
"""
Camera attendance loop (OpenCV window) for AI Face Attendance System.

Robustness features:
- Detects headless OpenCV builds early (no HighGUI support => cv2.imshow crashes).
- Tries multiple camera indices and common Windows backends (CAP_DSHOW, CAP_MSMF, CAP_ANY).
- Clear exceptions so tk_attendance_app can log the real reason.

References:
- OpenCV VideoCapture / read / isOpened docs: https://docs.opencv.org/3.4/d8/dfe/classcv_1_1VideoCapture.html
- OpenCV HighGUI imshow / waitKey docs: https://docs.opencv.org/3.4/d7/dfc/group__highgui.html
"""

import cv2
import face_recognition
import numpy as np
import json
from datetime import datetime

from encrypt import decrypt_data
from database import (
    get_face_users_for_course,
    sign_in_student,
    sign_out_student,
)

def _ensure_highgui_available() -> None:
    """
    Headless OpenCV wheels do not contain GUI functionality.
    The easiest runtime check is to try creating a window.
    """
    try:
        cv2.namedWindow("__test__", cv2.WINDOW_NORMAL)
        cv2.destroyWindow("__test__")
    except Exception as e:
        raise RuntimeError(
            "OpenCV HighGUI (window/imshow) is not available in your environment.\n"
            "This usually means you installed a *headless* OpenCV package.\n"
            "Fix: uninstall opencv-python-headless and install opencv-python."
        ) from e

def _load_known_faces(course_id: int, teacher_account_id=None):
    rows = get_face_users_for_course(course_id, teacher_account_id)

    known_face_encodings = []
    known_student_uids = []
    known_names = []

    for r in rows:
        # r is expected to be sqlite3.Row (dict-like)
        enc_blob = r["face_encoding"]
        try:
            if enc_blob is None:
                continue
            enc_json = decrypt_data(enc_blob)
            if isinstance(enc_json, (bytes, bytearray)):
                enc_json = enc_json.decode("utf-8", errors="ignore")
            enc_list = json.loads(enc_json)
            enc = np.array(enc_list, dtype="float32")

            known_face_encodings.append(enc)
            known_student_uids.append(r["student_uid"])
            known_names.append(r["name"])
        except Exception as e:
            # Skip bad user encoding but continue session
            try:
                suid = r["student_uid"]
                nm = r["name"]
            except Exception:
                suid, nm = "?", "?"
            print(f"[WARN] Failed to load encoding for {suid} - {nm}: {e}")

    return known_face_encodings, known_student_uids, known_names

def _open_camera(preferred_indices=(0, 1, 2)):
    """
    Try to open a webcam using common OpenCV backends.
    Returns an opened cv2.VideoCapture or raises RuntimeError.
    """
    # Backends: DirectShow often works best on Windows. MSMF is another common one.
    backends = []
    for attr in ("CAP_DSHOW", "CAP_MSMF", "CAP_ANY"):
        if hasattr(cv2, attr):
            backends.append(getattr(cv2, attr))
    if not backends:
        backends = [0]

    last_err = None
    for idx in preferred_indices:
        for api in backends:
            try:
                cap = cv2.VideoCapture(idx, api)
                if cap is not None and cap.isOpened():
                    # quick sanity read
                    ok, frame = cap.read()
                    if ok and frame is not None and frame.size > 0:
                        return cap
                    cap.release()
            except Exception as e:
                last_err = e

    raise RuntimeError(
        "Unable to open the camera.\n"
        "Tips:\n"
        " - Close other apps using the camera (Camera app, Zoom, Teams, etc.)\n"
        " - Check Windows camera privacy settings (allow desktop apps)\n"
        " - Try changing camera index (0/1/2) if you have multiple cameras"
    ) from last_err

def run_attendance_system(course_id: int, teacher_account_id=None):
    """
    Runs the camera-based attendance system for a given course_id.
    Press 'q' in the OpenCV window to stop.
    """
    # Fail fast if GUI is not available (prevents mysterious crashes)
    _ensure_highgui_available()

    print("[INFO] Loading known faces from database...")
    known_face_encodings, known_student_uids, known_names = _load_known_faces(course_id, teacher_account_id)

    if not known_face_encodings:
        print("[WARN] No known faces found in DB. Register users first.")
    else:
        print(f"[INFO] Loaded {len(known_face_encodings)} face encodings.")

    signed_in_uids = set()

    cap = _open_camera()
    print("[INFO] Camera started. Press 'q' in the video window to stop.")

    try:
        while True:
            ret, frame = cap.read()
            if not ret or frame is None or frame.size == 0:
                print("[WARN] Failed to read frame from camera.")
                break

            # Speed-up
            small_frame = cv2.resize(frame, (0, 0), fx=0.25, fy=0.25)
            rgb_small_frame = cv2.cvtColor(small_frame, cv2.COLOR_BGR2RGB)

            face_locations = face_recognition.face_locations(rgb_small_frame)
            face_encodings = face_recognition.face_encodings(rgb_small_frame, face_locations)

            names_in_frame = []

            for face_encoding in face_encodings:
                name_to_show = "Unknown"
                student_uid = None

                if known_face_encodings:
                    matches = face_recognition.compare_faces(known_face_encodings, face_encoding, tolerance=0.5)
                    face_distances = face_recognition.face_distance(known_face_encodings, face_encoding)

                    if len(face_distances) > 0:
                        best_match_index = int(np.argmin(face_distances))
                        if matches[best_match_index]:
                            student_uid = known_student_uids[best_match_index]
                            name_to_show = known_names[best_match_index]

                            if student_uid not in signed_in_uids:
                                try:
                                    print(f"[INFO] Signing in {student_uid} ({name_to_show}) for course {course_id}")
                                    sign_in_student(student_uid, course_id)
                                    signed_in_uids.add(student_uid)
                                except Exception as e:
                                    print(f"[ERROR] Failed to sign in {student_uid}: {e}")

                names_in_frame.append(name_to_show)

            # Draw boxes (scale back up)
            for (top, right, bottom, left), name_to_show in zip(face_locations, names_in_frame):
                top *= 4; right *= 4; bottom *= 4; left *= 4
                cv2.rectangle(frame, (left, top), (right, bottom), (0, 255, 0), 2)
                cv2.rectangle(frame, (left, bottom - 25), (right, bottom), (0, 255, 0), cv2.FILLED)
                cv2.putText(frame, name_to_show, (left + 6, bottom - 6), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 1)

            cv2.imshow("AI Face Attendance", frame)

            # waitKey is required for HighGUI window events
            if cv2.waitKey(1) & 0xFF == ord("q"):
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

        # Sign out everyone who was signed in during this session
        print("[INFO] Signing out all students recognized in this session...")
        for uid in list(signed_in_uids):
            try:
                print(f"[INFO] Signing out {uid} for course {course_id}")
                sign_out_student(uid, course_id)
            except Exception as e:
                print(f"[ERROR] Failed to sign out {uid}: {e}")

        print("[INFO] Attendance session ended.")
