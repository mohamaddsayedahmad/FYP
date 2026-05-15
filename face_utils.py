# face_utils.py
import json
import numpy as np
import face_recognition

from encrypt import decrypt_data
from database import get_users


def encode_face(image_path: str):
    img = face_recognition.load_image_file(image_path)
    locs = face_recognition.face_locations(img, model="hog")  # 'cnn' if GPU available
    if not locs:
        return None
    encs = face_recognition.face_encodings(img, locs)
    return encs[0] if encs else None


def load_known_faces():
    """
    Loads all users' encrypted face encodings from DB and returns:
      - encs: np.ndarray [N,128]
      - user_ids: list[int]
      - names: list[str]
    """
    rows = get_users()
    all_encs, user_ids, names = [], [], []

    for r in rows:
        try:
            raw = decrypt_data(r["face_encoding"])
            vec = np.array(json.loads(raw), dtype=float)
            if vec.shape == (128,):
                all_encs.append(vec)
                user_ids.append(r["id"])
                names.append(r["name"])
        except Exception:
            # skip corrupted/invalid encodings
            continue

    if all_encs:
        return np.vstack(all_encs), user_ids, names

    return np.empty((0, 128)), [], []
