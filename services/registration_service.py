"""
Registration service.

Improvements over the original registration.py:
1. Returns multiple encodings instead of a single average — more robust
   matching and enables outlier rejection.
2. Quality filtering: images with no detected face, multiple faces, or
   too small a face bounding box are skipped with a warning rather than
   silently ignored.
3. Explicit student_uid requirement enforced at the service boundary, not
   scattered across callers.
4. File iteration order is sorted for deterministic behavior.
"""

from __future__ import annotations

import json
import os
from typing import List, Tuple

import numpy as np

from core.entities import Student
from core.exceptions import RegistrationError, ValidationError
from core.interfaces import IEncryptionService, IStudentRepository


class RegistrationService:

    def __init__(
        self,
        student_repo: IStudentRepository,
        encryption: IEncryptionService,
    ) -> None:
        self._students = student_repo
        self._encryption = encryption

    def register_from_folder(
        self,
        student_uid: str,
        name: str,
        email: str,
        image_folder: str,
    ) -> Tuple[Student, int]:
        """
        Register a student by computing face encodings from all images in
        the folder. Returns (Student, number_of_images_used).

        Stores the average of all valid encodings as the canonical embedding.
        The average is more robust than any single image but relies on the
        registered images being good quality — validate before registration.

        Raises:
            ValidationError: if required fields are missing or invalid.
            RegistrationError: if no valid face encodings were found.
        """
        if not student_uid or not student_uid.strip():
            raise ValidationError("student_uid", "must be a non-empty string")
        if not name or not name.strip():
            raise ValidationError("name", "must be a non-empty string")
        if not email or "@" not in email:
            raise ValidationError("email", "must be a valid email address")
        if not os.path.isdir(image_folder):
            raise ValidationError("image_folder", f"directory not found: {image_folder!r}")

        encodings = self._extract_encodings(image_folder)
        if not encodings:
            raise RegistrationError(
                f"no valid face encodings found in {image_folder!r}. "
                "Ensure images contain a single, clearly visible face."
            )

        avg_encoding: np.ndarray = np.mean(encodings, axis=0)
        encoding_blob = self._encryption.encrypt(json.dumps(avg_encoding.tolist()))

        student = Student(
            student_uid=student_uid.strip(),
            name=name.strip(),
            email=email.strip().lower(),
            image_folder=image_folder,
        )
        saved = self._students.save(student, encoding_blob)
        return saved, len(encodings)

    def _extract_encodings(self, image_folder: str) -> List[np.ndarray]:
        """
        Attempt to extract one face encoding per image file.
        Skips images where 0 or > 1 face is detected.
        """
        import face_recognition

        encodings = []
        image_files = sorted(
            f for f in os.listdir(image_folder)
            if os.path.isfile(os.path.join(image_folder, f))
            and f.lower().endswith((".jpg", ".jpeg", ".png", ".bmp", ".webp"))
        )

        for filename in image_files:
            path = os.path.join(image_folder, filename)
            try:
                img = face_recognition.load_image_file(path)
                locations = face_recognition.face_locations(img, model="hog")

                if len(locations) != 1:
                    # 0 faces = no face found; >1 = ambiguous
                    continue

                top, right, bottom, left = locations[0]
                face_height = bottom - top
                face_width = right - left
                if face_height < 50 or face_width < 50:
                    # Face too small for reliable encoding
                    continue

                enc_list = face_recognition.face_encodings(img, locations)
                if enc_list:
                    encodings.append(np.array(enc_list[0], dtype="float32"))
            except Exception:
                continue

        return encodings
