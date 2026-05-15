# AI Face Attendance System — Claude Code Guide

## Project Overview

Final Year Project: AI Face Recognition Attendance System.
Python 3.11, FastAPI, SQLite, OpenCV, dlib/face_recognition, Streamlit, Tkinter.

**Target:** German university master's admission portfolio (DS, AI, SE, Intelligent Systems).

---

## Architecture (Clean Architecture, strict layer order)

```
core/           → domain (entities, exceptions, interfaces) — NO imports from other layers
infrastructure/ → SQLite repos, Fernet encryption, SMTP gateway — implements core interfaces
services/       → business logic — imports core + infrastructure
api/            → FastAPI transport — imports services + core
ai/             → face recognition pipeline — imports core + infrastructure
dashboard/      → Streamlit UI — calls api/ via HTTP
tests/          → pytest — imports core + infrastructure + services
```

**Never import upward** (infrastructure must never import from services; domain must never import from infrastructure).

---

## How to Run

```bash
# FastAPI (port 8000)
attendance_env/Scripts/python -m uvicorn api.main:app --reload --port 8000

# Streamlit dashboard (port 8501) — separate terminal
attendance_env/Scripts/python -m streamlit run dashboard/streamlit_app.py

# Tkinter desktop GUI
attendance_env/Scripts/python tk_attendance_app.py

# Tests (57 passing)
attendance_env/Scripts/python -m pytest tests/ -v
```

---

## Key Files

| File | Purpose |
|------|---------|
| `core/entities.py` | Domain dataclasses — Student, Course, AttendanceRecord, Account |
| `core/interfaces.py` | Abstract base classes for all repos and gateways |
| `infrastructure/database/connection.py` | WAL-mode SQLite context manager; reads DB path at call time (not import time) |
| `infrastructure/database/migrator.py` | Numbered SQL migrations with idempotency |
| `infrastructure/security/encryption.py` | Fernet from `ATTENDANCE_FERNET_KEY` env var |
| `infrastructure/security/password.py` | PBKDF2-SHA256, 600k iterations, legacy-compatible |
| `api/security.py` | JWT HS256 tokens, `require_role()` dependency |
| `api/dependencies.py` | DI container — `_make_repos()` cached with `lru_cache` |
| `ai/face_encoder.py` | Multi-encoding registration, quality scoring, IQR outlier rejection |
| `ai/face_recognizer.py` | N-vs-K search, confidence, margin guard, TTL cache |
| `ai/liveness_detector.py` | EAR blink + texture + optical flow anti-spoofing |
| `ai/metrics.py` | Accuracy, F1, FAR, FRR, EER, d-prime, ROC |

---

## Test Infrastructure

Each test gets an isolated in-memory SQLite database via the `tmp_db_path` fixture in `tests/conftest.py`.
The `patch_env` autouse fixture resets `_default_service` and `_make_repos` cache between tests.

**Critical detail:** `ATTENDANCE_DB_PATH` must be set via `os.environ` (not just `monkeypatch.setenv`) *before* `run_migrations()` is called in `tmp_db_path`, because `connection.py` reads the env var at call time. The fixture order in `conftest.py` is intentional.

---

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `ATTENDANCE_FERNET_KEY` | Yes (prod) | Fernet key for biometric encryption |
| `ATTENDANCE_JWT_SECRET` | Yes (prod) | JWT signing secret |
| `ATTENDANCE_DB_PATH` | No | SQLite file path (default: `./attendance.db`) |
| `ATTENDANCE_SMTP_HOST/PORT/USER/PASS` | No | Email sending (absent = log-only mode) |

---

## Legacy Files (backward-compatible, do not delete)

`database.py`, `app.py` (Flask), `attendance.py`, `tk_attendance_app.py`, `registration.py`, `encrypt.py` — the Tkinter GUI still imports from these. The new architecture runs *alongside* them; the database schema is shared.

The fixed bugs in these files:
- `database.py:clear_attendance_for_course_date` — duplicate docstring removed
- `app.py` — was calling `sign_in_user`/`sign_out_user` (non-existent); fixed to `sign_in_student`/`sign_out_student`

---

## Adding a New Feature

1. Add entity/exception to `core/` if needed.
2. Add interface method to `core/interfaces.py`.
3. Implement in the appropriate `infrastructure/` class.
4. Add business logic to the relevant `services/` class.
5. Add API route to `api/routes/`.
6. Write tests in `tests/unit/`.

---

## Docker

```bash
docker-compose up --build     # starts api (8000) + dashboard (8501)
```

Requires `.env` with `ATTENDANCE_FERNET_KEY` and `ATTENDANCE_JWT_SECRET` set.
