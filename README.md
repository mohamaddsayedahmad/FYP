# AI Face Recognition Attendance System

**Author:** Mohamad Ali Sayed Ahmad · Computer Science Final Year Project  
**Stack:** Python 3.11 · FastAPI · SQLite · OpenCV · dlib/face_recognition · Streamlit · Tkinter  
**Tests:** 127 passing · Architecture: Clean Architecture (Domain → Infrastructure → Services → API)

---

## Table of Contents

1. [Project Overview](#1-project-overview)
2. [Architecture](#2-architecture)
3. [AI Pipeline](#3-ai-pipeline)
4. [Security Design](#4-security-design)
5. [Quick Start](#5-quick-start)
6. [Docker Deployment](#6-docker-deployment)
7. [API Reference](#7-api-reference)
8. [Project Structure](#8-project-structure)
9. [Running Tests](#9-running-tests)
10. [Configuration Reference](#10-configuration-reference)

---

## 1. Project Overview

An end-to-end face recognition attendance system that automates student attendance using real-time camera feeds, encrypted biometric storage, and role-based access control.

### Core Features

| Feature | Implementation |
|---------|---------------|
| Face registration | Multi-image quality-filtered encoding with IQR outlier rejection |
| Real-time recognition | N-vs-K nearest-neighbour search with confidence scoring |
| Anti-spoofing | EAR blink detection + texture analysis + optical flow |
| Anti-proxy policy | Sign-in requires matching sign-out; incomplete sessions → Absent |
| Biometric privacy | Fernet symmetric encryption on all stored face embeddings |
| Authentication | PBKDF2-SHA256 (600,000 iterations) + JWT Bearer tokens |
| RBAC | Admin / Teacher / Student roles enforced at every API endpoint |
| Notifications | Absence email via SMTP with deduplication and audit logging |
| Analytics | Streamlit dashboard with KPI cards, trend charts, export |
| Teacher registration | Admin-only page: register teacher accounts with name, email, and password |
| Evaluation | Accuracy, Precision, Recall, F1, FAR, FRR, EER, d-prime, ROC |

---

## 2. Architecture

The system follows **Clean Architecture** with strict layer dependencies:

```
┌──────────────────────────────────────────────────────────┐
│                  PRESENTATION LAYER                      │
│  Tkinter GUI  │  FastAPI REST  │  Streamlit Dashboard    │
└──────────────────────┬───────────────────────────────────┘
                       │ depends on ↓
┌──────────────────────▼───────────────────────────────────┐
│                  APPLICATION LAYER                       │
│  AuthService  AttendanceService  RegistrationService     │
│  CourseService  NotificationService                      │
└──────────────────────┬───────────────────────────────────┘
                       │ depends on ↓
┌──────────────────────▼───────────────────────────────────┐
│                    DOMAIN LAYER                          │
│  Entities (Student, Course, AttendanceRecord, Account)   │
│  Exceptions  │  Interfaces (IStudentRepo, IEmailGateway) │
└──────────────────────┬───────────────────────────────────┘
                       │ depends on ↓
┌──────────────────────▼───────────────────────────────────┐
│                INFRASTRUCTURE LAYER                      │
│  SQLite Repositories  │  SMTP Gateway                    │
│  Fernet Encryption    │  PBKDF2 Password                 │
│  Schema Migrations    │  WAL Connection Pool             │
└──────────────────────────────────────────────────────────┘
```

**Key architectural decisions:**

- **Dependency Inversion**: Services depend on `IStudentRepository` (interface), never on `SQLiteStudentRepository` (implementation). Swapping the database requires changing only the infrastructure layer.
- **No side effects at import time**: `init_db()` does not run on `import database`. Migrations run explicitly at application startup via `run_migrations()`.
- **Repository pattern**: Each entity has its own repository class. No 1,600-line god object.
- **Domain exceptions**: `AuthenticationError`, `NotFoundError`, etc. propagate cleanly through all layers; the API layer converts them to HTTP status codes.

---

## 3. AI Pipeline

### Face Registration

```
Image folder
    │
    ├─ Sort files (deterministic)
    ├─ Detect face (dlib HOG)
    ├─ Quality gate: size ≥ 60px, sharpness (Laplacian) ≥ threshold
    ├─ Extract 128-d dlib embedding
    ├─ IQR outlier rejection (centroid distance > 75th percentile → discard)
    ├─ Keep top-K by quality score
    └─ Fernet-encrypt JSON → store in users.face_encoding
```

### Recognition (per camera frame)

```
BGR frame
    │
    ├─ Scale to 25% (speed)
    ├─ HOG face detection
    ├─ Every N frames: full recognition; other frames: use TTL cache
    │
    ├─ For each detected face:
    │   ├─ Extract 128-d embedding
    │   ├─ Euclidean distance to ALL stored encodings (vectorised)
    │   ├─ Per-student: take minimum distance
    │   ├─ Accept if: best_dist < 0.50 AND margin > 0.05
    │   └─ Confidence = max(0, 1 − best_distance)
    │
    └─ Liveness gate (if enabled):
        ├─ EAR blink detection (Soukupová & Čech 2016)
        ├─ Laplacian texture score (printed photo → low variance)
        ├─ Optical flow motion score
        └─ Sign in only after composite liveness score ≥ 0.5
```

### Evaluation Metrics

| Metric | Formula |
|--------|---------|
| Accuracy | (TP + TN) / N |
| Precision | TP / (TP + FP) |
| Recall / TAR | TP / (TP + FN) |
| F1-score | 2 × Precision × Recall / (P + R) |
| FAR | FP / (FP + TN) |
| FRR | FN / (FN + TP) |
| EER | Operating point where FAR ≈ FRR |
| d-prime | \|μ_genuine − μ_impostor\| / √((σ²_g + σ²_i) / 2) |

Run the benchmark on a labelled test set:
```python
from ai.metrics import run_benchmark
report = run_benchmark(store, test_folder="data/test_images/", threshold=0.50)
print(report.summary_table())
```

---

## 4. Security Design

| Concern | Mechanism |
|---------|-----------|
| Password storage | PBKDF2-HMAC-SHA256, 600,000 iterations, 32-byte random salt per user |
| Biometric data | Fernet (AES-128-CBC + HMAC-SHA256) encryption at rest |
| Encryption key | `ATTENDANCE_FERNET_KEY` env var — never stored in the repository |
| API authentication | JWT HS256 Bearer tokens, configurable expiry |
| RBAC | admin / teacher / student roles, enforced per endpoint via FastAPI `Depends` |
| Timing attacks | `hmac.compare_digest()` for all password comparisons |
| Password upgrade | Transparent PBKDF2 rehash on login when iteration count < 600,000 |
| Password policy | Minimum 8 chars, at least one letter and one digit (enforced at API layer) |
| Rate limiting | Login endpoint capped at 5 req/min per IP via slowapi |
| SQL injection | 100% parameterised queries throughout |
| CORS | Restrictive allowlist from env var, no wildcard `*` |

---

## 5. Quick Start

### Prerequisites

- Python 3.11+
- Windows: Visual C++ Build Tools (for dlib compilation) or use pre-built wheels

### Installation

```bash
# Clone / navigate to project
cd AttendanceSystem

# Create virtual environment
python -m venv attendance_env
attendance_env\Scripts\activate          # Windows
# source attendance_env/bin/activate     # Linux/macOS

# Install dependencies
pip install -r requirements.txt

# Configure environment
copy .env.example .env
# Edit .env — set ATTENDANCE_FERNET_KEY and ATTENDANCE_JWT_SECRET
```

### Generate secure keys

```bash
# Fernet key
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

# JWT secret
python -c "import secrets; print(secrets.token_hex(32))"
```

### Run the FastAPI server

```bash
python -m uvicorn api.main:app --reload --port 8000
# API docs: http://localhost:8000/docs
# Redoc:    http://localhost:8000/redoc
```

### Run the Streamlit dashboard

```bash
python -m streamlit run dashboard/streamlit_app.py
# Dashboard: http://localhost:8501
# Default credentials: admin/admin123 (change immediately)
```

### Run the Tkinter desktop GUI

```bash
python tk_attendance_app.py
```

---

## 6. Docker Deployment

```bash
# Build image
docker build -t attendance-system:latest .

# Run full stack (API + Dashboard)
docker-compose up --build

# Services:
#   API:       http://localhost:8000
#   API Docs:  http://localhost:8000/docs
#   Dashboard: http://localhost:8501
```

**Required env vars in `.env` before starting:**
```
ATTENDANCE_FERNET_KEY=<generate with command above>
ATTENDANCE_JWT_SECRET=<generate with command above>
```

---

## 7. API Reference

Full interactive documentation available at **`/docs`** (Swagger UI) once the server is running.

### Authentication

```http
POST /api/v1/auth/login
Content-Type: application/json

{"username": "admin", "password": "admin123", "role": "admin"}
```

Response:
```json
{"access_token": "eyJ...", "token_type": "bearer", "role": "admin", ...}
```

All subsequent requests require:
```http
Authorization: Bearer <access_token>
```

### Permissions Matrix

| Action | Admin | Teacher | Student |
|--------|-------|---------|---------|
| Login / obtain JWT | ✓ | ✓ | ✓ |
| View all courses | ✓ | ✗ | ✗ |
| View own assigned courses | — | ✓ | ✗ |
| Create a course | ✓ | ✗ | ✗ |
| Enroll a student in a course | ✓ | ✓ (own courses) | ✗ |
| Register a student (face images) | ✓ | ✗ | ✗ |
| Register a teacher account | ✓ | ✗ | ✗ |
| View all attendance records | ✓ | ✗ | ✗ |
| View own-course attendance records | ✓ | ✓ | ✗ |
| Finalize a session (anti-proxy) | ✓ | ✓ (own courses) | ✗ |
| Send absence notifications | ✓ | ✓ (own courses) | ✗ |
| View own student list | — | ✓ | ✗ |
| View own KPI summary | — | ✓ | ✗ |
| View global KPI summary | ✓ | ✗ | ✗ |

### Key Endpoints

| Method | Endpoint | Role | Description |
|--------|----------|------|-------------|
| `GET` | `/health` | Public | DB health probe — returns 200 ok or 503 degraded |
| `POST` | `/api/v1/auth/login` | Public | Obtain JWT token (rate-limited: 5/min per IP) |
| `GET` | `/api/v1/users/` | admin, teacher | List all students |
| `POST` | `/api/v1/users/register` | admin, teacher | Register student with face images |
| `GET` | `/api/v1/courses/` | all | List courses |
| `POST` | `/api/v1/courses/` | admin | Create course |
| `POST` | `/api/v1/admin/register-teacher` | admin | Register a new teacher account with course assignments |
| `GET` | `/api/v1/teachers/me/courses` | teacher | Courses assigned to the calling teacher |
| `GET` | `/api/v1/teachers/me/students` | teacher | Distinct students across all teacher's courses |
| `GET` | `/api/v1/teachers/me/summary` | teacher | KPI summary (courses, students, today, this week) |
| `POST` | `/api/v1/courses/enroll` | admin, teacher | Enroll student in course |
| `GET` | `/api/v1/attendance/` | all | List attendance records |
| `POST` | `/api/v1/attendance/sign-in/{course}/{uid}` | admin, teacher | Manual sign-in |
| `POST` | `/api/v1/attendance/finalize/{course_id}` | admin, teacher | Finalize session (anti-proxy) |
| `GET` | `/api/v1/attendance/stats/{course_id}` | admin, teacher | Attendance statistics |
| `POST` | `/api/v1/attendance/notify-absent/{course_id}` | admin, teacher | Send absence emails |

---

## 8. Project Structure

```
AttendanceSystem/
├── core/                    # Domain layer — pure Python, no framework deps
│   ├── entities.py          # Student, Course, AttendanceRecord, Account
│   ├── exceptions.py        # DomainError, NotFoundError, AuthError, ...
│   └── interfaces.py        # IStudentRepo, ICourseRepo, IEmailGateway, ...
│
├── infrastructure/          # Implementation details
│   ├── database/
│   │   ├── connection.py    # WAL-mode SQLite context manager
│   │   ├── migrator.py      # Numbered SQL migration runner
│   │   ├── migrations/      # 001_initial_schema.sql, 002_add_iterations.sql
│   │   ├── student_repo.py  # IStudentRepository → SQLite
│   │   ├── course_repo.py
│   │   ├── enrollment_repo.py
│   │   ├── attendance_repo.py
│   │   └── account_repo.py
│   ├── security/
│   │   ├── encryption.py    # Fernet, key from env var
│   │   └── password.py      # PBKDF2-SHA256, 600k iterations
│   └── email/
│       └── smtp_gateway.py  # IEmailGateway → SMTP
│
├── services/                # Application / business logic layer
│   ├── auth_service.py
│   ├── attendance_service.py
│   ├── registration_service.py
│   ├── course_service.py
│   └── notification_service.py
│
├── api/                     # FastAPI transport layer
│   ├── main.py              # App factory, middleware, exception handlers, /health
│   ├── security.py          # JWT creation and verification
│   ├── limiter.py           # slowapi rate-limiter instance and reset helper
│   ├── dependencies.py      # Dependency injection container
│   └── routes/
│       ├── auth.py          # POST /login (rate-limited)
│       ├── admin.py         # POST /admin/register-teacher (admin only)
│       ├── teachers.py      # GET /teachers/me/* (teacher-scoped)
│       ├── users.py
│       ├── courses.py
│       └── attendance.py
│
├── ai/                      # AI / computer vision pipeline
│   ├── face_encoder.py      # Multi-encoding, quality scoring, outlier rejection
│   ├── face_recognizer.py   # N-vs-K search, confidence, margin guard, cache
│   ├── liveness_detector.py # EAR blink + texture + optical flow
│   ├── metrics.py           # Accuracy, F1, FAR, FRR, EER, d-prime, ROC
│   └── camera_loop.py       # Orchestration, liveness gate, callbacks
│
├── dashboard/
│   └── streamlit_app.py     # Analytics dashboard with JWT auth
│
├── tests/
│   ├── conftest.py          # Isolated per-test SQLite DB, env patching, rate-limit reset
│   └── unit/
│       ├── test_auth_service.py
│       ├── test_attendance_service.py
│       ├── test_course_service.py
│       ├── test_notification_service.py
│       ├── test_registration_service.py
│       ├── test_teacher_api.py
│       ├── test_admin_api.py
│       ├── test_health_api.py
│       ├── test_entities.py
│       ├── test_face_encoder.py
│       ├── test_metrics.py
│       └── test_password.py
│
├── Dockerfile               # Multi-stage build (builder + runtime)
├── docker-compose.yml       # API + Dashboard services
├── .env.example             # All configurable env vars with documentation
├── requirements.txt
│
└── [Legacy files — backward-compatible with Tkinter GUI]
    ├── tk_attendance_app.py
    ├── attendance.py
    ├── database.py
    ├── registration.py
    ├── encrypt.py
    └── app.py               # Flask API (legacy; use FastAPI for new work)
```

---

## 9. Running Tests

```bash
# Run all tests
python -m pytest tests/ -v

# Run a specific module
python -m pytest tests/unit/test_auth_service.py -v

# With coverage report
python -m pytest tests/ --cov=. --cov-report=term-missing
```

**Current test results: 127 passed, 0 failed · Services coverage: 92%**

Test suites:
- `test_entities.py` — domain invariants (pure Python, zero I/O)
- `test_password.py` — PBKDF2 correctness, timing safety, legacy format compatibility
- `test_auth_service.py` — authentication, RBAC, default accounts, transparent rehash
- `test_attendance_service.py` — sign-in/out, finalize session, face data loading, statistics
- `test_course_service.py` — enrollment, course assignment, enrolled-student queries
- `test_notification_service.py` — absent notifications, deduplication, SMTP log-only mode
- `test_registration_service.py` — validation, face_recognition mocking, multi-image handling
- `test_admin_api.py` — POST /admin/register-teacher, password policy enforcement
- `test_teacher_api.py` — teacher-scoped /me endpoints, data isolation between teachers
- `test_health_api.py` — GET /health happy path and DB-failure 503 path
- `test_face_encoder.py` — quality scoring, outlier rejection, encryption round-trips
- `test_metrics.py` — accuracy metrics, d-prime, EER calculation

Each test runs against an isolated in-memory SQLite database — no test touches the real `attendance.db`.

---

## 10. Configuration Reference

All configuration is via environment variables. See `.env.example` for the full list.

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `ATTENDANCE_FERNET_KEY` | **Yes** (production) | auto-generated | Fernet key for biometric encryption |
| `ATTENDANCE_JWT_SECRET` | **Yes** (production) | auto-generated | JWT signing secret (min 32 bytes) |
| `ATTENDANCE_DB_PATH` | No | `./attendance.db` | SQLite database path |
| `ATTENDANCE_TOKEN_EXPIRE_MINUTES` | No | `60` | JWT access token TTL |
| `ATTENDANCE_SMTP_HOST` | No | — | SMTP server (leave unset to only log emails) |
| `ATTENDANCE_SMTP_PORT` | No | `587` | SMTP port (465 forces SSL) |
| `ATTENDANCE_SMTP_USER` | No | — | SMTP username |
| `ATTENDANCE_SMTP_PASS` | No | — | SMTP password |
| `ATTENDANCE_CORS_ORIGINS` | No | `http://localhost:3000,...` | Comma-separated CORS origins |
| `ATTENDANCE_LOGIN_RATE_LIMIT` | No | `5/minute` | Override login rate limit (e.g. `100/minute` for testing) |

---

## Academic Context

This project was built as a Final Year Project for a Computer Science degree, targeting German university master's programme admission in Data Science, Artificial Intelligence, and Software Engineering.

**Software engineering competencies demonstrated:**
- Clean Architecture / Domain-Driven Design principles
- SOLID (Single Responsibility, Open/Closed, Dependency Inversion)
- Repository pattern, service layer, dependency injection
- Schema migration infrastructure
- Security-first design (encryption, PBKDF2, JWT, RBAC)
- Test-driven development with isolated fixtures

**AI/ML research competencies demonstrated:**
- Face recognition pipeline design (registration → recognition → evaluation)
- Image quality assessment (Laplacian sharpness, bounding box size)
- Statistical outlier rejection (IQR on embedding distances)
- Liveness detection (EAR blink, texture analysis, optical flow)
- Biometric evaluation metrics (FAR, FRR, EER, d-prime, ROC)
- Operating point selection on ROC curves
