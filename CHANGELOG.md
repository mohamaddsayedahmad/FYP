# Changelog

All notable changes are documented here. Follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/) conventions.

---

## [Unreleased]

### Added
- `GET /health` endpoint — probes SQLite with `SELECT 1`; returns `200 ok` or `503 degraded`
- JSON structured logging via `_JsonFormatter`; all request middleware emits structured `extra={}` fields
- `slowapi` rate limiting on `POST /api/v1/auth/login` — default 5 requests/minute per IP
- Password strength policy: minimum 8 characters, at least one letter and one digit (enforced at API layer via Pydantic `@field_validator`)
- `api/limiter.py` — shared `Limiter` instance; `reset_limiter()` helper for test isolation
- `POST /admin/register-teacher` route (`api/routes/admin.py`) — admin-only teacher account creation
- `/api/v1/teachers/me/courses`, `/me/students`, `/me/summary` — teacher-scoped self-service endpoints
- Role-aware Streamlit dashboard — admin sees global view; teacher sees "My X" scoped data
- **Test coverage**: 127 tests (up from 57), services layer at 92% overall
  - `test_attendance_service.py` — 20 tests covering sign-in/out, finalize, face data loading, statistics
  - `test_course_service.py` — 10 tests covering enrollment, assignment, queries
  - `test_notification_service.py` — 8 tests covering absent notifications and deduplication
  - `test_registration_service.py` — 9 tests covering validation and face_recognition mocking
  - `test_auth_service.py` — added transparent PBKDF2 rehash test
  - `test_admin_api.py` — password policy enforcement at API boundary
  - `test_teacher_api.py` — scoped data isolation between teachers
  - `test_health_api.py` — `/health` happy path and DB-failure 503

### Changed
- Docker `HEALTHCHECK` URL updated from `/` to `/health`
- `docker-compose.yml` health check updated to `/health`
- Dockerfile stage-2 pip install now includes `slowapi`, `Pillow`, `ttkbootstrap` (were previously missing)
- `GET /` renamed to `ping()` — remains a lightweight liveness ping; `/health` is the full readiness probe
- `core/interfaces.py` `get_credentials()` return type corrected to `Optional[Tuple[str, str, int]]` (was missing the `iterations` int)
- `infrastructure/database/attendance_repo.py` `params` annotated as `List[Any]` (was untyped `list`)

### Fixed
- `app.py` (legacy Flask): was calling `sign_in_user`/`sign_out_user` (non-existent); fixed to `sign_in_student`/`sign_out_student`
- `database.py`: duplicate docstring removed from `clear_attendance_for_course_date`

### Security
- `opencv-python` upgraded `4.8.0.76` → `4.8.1.78` (CVE-2023-4863)
- `Pillow` upgraded `10.0.1` → `10.2.0` (CVE-2023-50447)

---

## [1.0.0] — 2025-05 (Initial Release)

### Added
- Clean Architecture scaffolding: `core/`, `infrastructure/`, `services/`, `api/`, `ai/`, `dashboard/`
- Domain entities: `Student`, `Course`, `AttendanceRecord`, `Account`, `Enrollment`, `EmailNotification`
- SQLite repositories with WAL mode and numbered schema migrations
- Fernet encryption for biometric face embeddings (`ATTENDANCE_FERNET_KEY`)
- PBKDF2-SHA256 password hashing, 600,000 iterations, 32-byte random salt
- JWT HS256 Bearer token authentication with configurable TTL
- RBAC: admin / teacher / student roles enforced per endpoint via `require_role()` FastAPI dependency
- Face registration pipeline: multi-image, quality scoring (Laplacian + size), IQR outlier rejection
- Face recognition: N-vs-K Euclidean search, confidence scoring, margin guard, TTL frame cache
- Liveness detection: EAR blink (Soukupová & Čech 2016), Laplacian texture, optical flow
- Anti-proxy policy: incomplete sessions finalized as Absent at session end
- Email absence notifications via SMTP with deduplication and log-only fallback
- Streamlit analytics dashboard (KPI cards, trend charts, attendance table, CSV export)
- Tkinter desktop GUI (legacy entry point)
- Biometric evaluation metrics: Accuracy, F1, FAR, FRR, EER, d-prime, ROC
- Docker multi-stage build + `docker-compose.yml` for API + Dashboard
- 57 initial unit tests
