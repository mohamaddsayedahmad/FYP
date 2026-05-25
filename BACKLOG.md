# Backlog

Planned improvements and deferred work items.

---

## High Priority

### Audit Log Table (Migration 004)
- Add an `audit_log` table tracking admin/teacher actions (who created an account, who finalized a session, etc.)
- Requires a new numbered SQL migration file `infrastructure/database/migrations/004_audit_log.sql`
- Add `IAuditLogRepository` interface to `core/interfaces.py`
- Implement `SQLiteAuditLogRepository` in `infrastructure/database/audit_repo.py`
- Wire into `AuthService.create_account()`, `AttendanceService.finalize_session()`, and `NotificationService`
- **Deferred**: explicitly scoped out of the current hardening pass

### Student Self-Service Endpoints
- `GET /api/v1/students/me/attendance` — student views own attendance history
- `GET /api/v1/students/me/courses` — student views enrolled courses
- Currently the `student` role exists in RBAC but has no self-service endpoints

---

## Medium Priority

### Refresh Tokens
- Current JWT tokens expire after 60 minutes with no rotation mechanism
- Add `POST /api/v1/auth/refresh` accepting a long-lived refresh token; return a new short-lived access token
- Store refresh token hash in `accounts` table with expiry

### Admin Account Management Endpoints
- `GET /api/v1/admin/accounts` — list all accounts (admin only)
- `PATCH /api/v1/admin/accounts/{id}/deactivate` — disable an account
- Currently `account_repo.set_active()` exists in infrastructure but has no API surface

### Pagination for List Endpoints
- `GET /api/v1/users/`, `GET /api/v1/attendance/` return unbounded lists
- Add `?limit=` / `?offset=` query parameters with sane defaults (e.g. `limit=100`)

### Structured Error Responses
- Standardise all HTTP error bodies to `{"error": "...", "code": "NOT_FOUND", "detail": {...}}`
- Currently some endpoints return FastAPI defaults and others return custom shapes

---

## Low Priority

### OpenTelemetry Tracing
- Instrument FastAPI routes with OTEL spans
- Export to Jaeger or OTLP endpoint via `opentelemetry-sdk`

### `process_recognized_face` Integration Test
- `services/attendance_service.py` lines 174–197 are uncovered because they require a live `face_recognition` import
- Add a test that mocks `face_recognition.face_distance` at the module level and exercises the sign-in side-effect path

### Docker Image Size Reduction
- The current multi-stage Dockerfile still installs build tools in the runtime image
- Move all dlib compilation to the builder stage; copy only compiled `.so` files to runtime

### CI Pipeline
- Add a GitHub Actions workflow: `pytest --cov` + `bandit -r .` + `pip-audit` on every push
- Currently all checks run manually
