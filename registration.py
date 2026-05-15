# registration.py
import os
import numpy as np
from face_utils import encode_face  # uses encode_face from face_utils.py


def register_user(name, email, image_folder, student_uid=None):
    """
    Register a user by computing an average face encoding from all images
    in the folder, then storing it in the database.

    Student ID is REQUIRED:
    - If student_uid is None or empty -> registration fails.

    Returns:
        (ok: bool, message: str, student_uid: str | None)
    """
    # 🔴 ID REQUIRED: no ID → fail
    if student_uid is None or not str(student_uid).strip():
        msg = "Student ID is required."
        print(msg)
        return False, msg, None

    student_uid = str(student_uid).strip()

    encodings = []

    if not os.path.isdir(image_folder):
        return False, f"Image folder not found: {image_folder}", None

    for img_file in os.listdir(image_folder):
        img_path = os.path.join(image_folder, img_file)
        if not os.path.isfile(img_path):
            continue
        encoding = encode_face(img_path)
        if encoding is not None:
            encodings.append(encoding)

    if not encodings:
        msg = "No faces detected in the provided images. Please check the folder."
        print(msg)
        return False, msg, None

    avg_encoding = np.mean(encodings, axis=0)  # Average encoding for robustness

    from database import add_user  # Import here to avoid circular imports

    # ✅ matches your signature: def add_user(name, email, face_encoding_np_array, student_uid: str | None = None)
    user_id, final_sid = add_user(name, email, avg_encoding, student_uid, image_folder=image_folder)

    msg = f"Student '{name}' registered successfully with ID: {final_sid}"
    print(msg)
    return True, msg, final_sid
