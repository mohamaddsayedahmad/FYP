"""Unit tests for RegistrationService."""

from __future__ import annotations

import contextlib
import json
import sys
from unittest.mock import MagicMock

import numpy as np
import pytest

from core.exceptions import RegistrationError, ValidationError
from services.registration_service import RegistrationService


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def registration_service(student_repo, encryption_service):
    return RegistrationService(student_repo, encryption_service)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

@contextlib.contextmanager
def _mock_face_recognition(locations=None, encodings=None):
    """Temporarily replace the face_recognition module in sys.modules."""
    if locations is None:
        locations = [(10, 90, 90, 10)]  # one face, large enough
    if encodings is None:
        encodings = [np.zeros(128, dtype="float32")]

    mock_fr = MagicMock()
    mock_fr.load_image_file.return_value = np.zeros((100, 100, 3), dtype=np.uint8)
    mock_fr.face_locations.return_value = locations
    mock_fr.face_encodings.return_value = encodings

    orig = sys.modules.get("face_recognition")
    sys.modules["face_recognition"] = mock_fr
    try:
        yield mock_fr
    finally:
        if orig is None:
            sys.modules.pop("face_recognition", None)
        else:
            sys.modules["face_recognition"] = orig


# ---------------------------------------------------------------------------
# Validation branches
# ---------------------------------------------------------------------------

class TestValidation:

    def test_empty_uid_raises(self, registration_service, tmp_path):
        with pytest.raises(ValidationError):
            registration_service.register_from_folder("", "Alice", "a@a.com", str(tmp_path))

    def test_whitespace_uid_raises(self, registration_service, tmp_path):
        with pytest.raises(ValidationError):
            registration_service.register_from_folder("  ", "Alice", "a@a.com", str(tmp_path))

    def test_empty_name_raises(self, registration_service, tmp_path):
        with pytest.raises(ValidationError):
            registration_service.register_from_folder("S001", "", "a@a.com", str(tmp_path))

    def test_invalid_email_raises(self, registration_service, tmp_path):
        with pytest.raises(ValidationError):
            registration_service.register_from_folder("S001", "Alice", "not-an-email", str(tmp_path))

    def test_nonexistent_folder_raises(self, registration_service):
        with pytest.raises(ValidationError):
            registration_service.register_from_folder(
                "S001", "Alice", "a@a.com", "/this/path/does/not/exist"
            )

    def test_empty_folder_raises_registration_error(self, registration_service, tmp_path):
        # No image files → face_recognition returns nothing → RegistrationError
        with _mock_face_recognition(locations=[], encodings=[]):
            with pytest.raises(RegistrationError):
                registration_service.register_from_folder(
                    "S001", "Alice", "a@a.com", str(tmp_path)
                )


# ---------------------------------------------------------------------------
# Registration with mocked face_recognition
# ---------------------------------------------------------------------------

class TestRegisterFromFolder:

    def test_register_saves_student_and_returns_count(self, registration_service, tmp_path):
        (tmp_path / "face.jpg").write_bytes(b"fake-image")
        with _mock_face_recognition():
            student, count = registration_service.register_from_folder(
                "S100", "Test Student", "ts@test.com", str(tmp_path)
            )
        assert student.student_uid == "S100"
        assert student.name == "Test Student"
        assert count == 1

    def test_multiple_images_all_count(self, registration_service, tmp_path):
        (tmp_path / "face1.jpg").write_bytes(b"img1")
        (tmp_path / "face2.jpg").write_bytes(b"img2")
        with _mock_face_recognition():
            _student, count = registration_service.register_from_folder(
                "S101", "Multi", "m@test.com", str(tmp_path)
            )
        assert count == 2

    def test_skips_image_with_no_face(self, registration_service, tmp_path):
        (tmp_path / "no_face.jpg").write_bytes(b"img")
        (tmp_path / "one_face.jpg").write_bytes(b"img")

        call_count = 0

        def _varying_locations(_img, model="hog"):
            nonlocal call_count
            call_count += 1
            return [] if call_count == 1 else [(10, 90, 90, 10)]

        with _mock_face_recognition() as mock_fr:
            mock_fr.face_locations.side_effect = _varying_locations
            _student, count = registration_service.register_from_folder(
                "S102", "Partial", "p@test.com", str(tmp_path)
            )
        assert count == 1

    def test_skips_image_with_multiple_faces(self, registration_service, tmp_path):
        (tmp_path / "multi.jpg").write_bytes(b"img")
        (tmp_path / "single.jpg").write_bytes(b"img")

        call_count = 0

        def _varying_locations(_img, model="hog"):
            nonlocal call_count
            call_count += 1
            return [(0, 50, 50, 0), (50, 100, 100, 50)] if call_count == 1 else [(10, 90, 90, 10)]

        with _mock_face_recognition() as mock_fr:
            mock_fr.face_locations.side_effect = _varying_locations
            _student, count = registration_service.register_from_folder(
                "S103", "SFace", "sf@test.com", str(tmp_path)
            )
        assert count == 1
