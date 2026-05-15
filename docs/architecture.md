# System Architecture Documentation

**AI Face Recognition Attendance System**  
**Author:** Mohamad Ali Sayed Ahmad

---

## 1. Layered Architecture Diagram

```
╔══════════════════════════════════════════════════════════════════╗
║                        CLIENTS                                   ║
║  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐  ║
║  │  Tkinter GUI    │  │ Streamlit Dash  │  │  External HTTP  │  ║
║  │ (Desktop App)   │  │ (Web Analytics) │  │   (REST Calls)  │  ║
║  └────────┬────────┘  └────────┬────────┘  └────────┬────────┘  ║
╚═══════════╪════════════════════╪════════════════════╪════════════╝
            │                   │ JWT Bearer          │
╔═══════════╪════════════════════╪════════════════════╪════════════╗
║           │    PRESENTATION / TRANSPORT LAYER       │            ║
║  ┌────────▼────────────────────▼────────────────────▼────────┐   ║
║  │                    FastAPI (api/)                         │   ║
║  │  /auth/login  /users/  /courses/  /attendance/            │   ║
║  │  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐     │   ║
║  │  │ JWT Security │  │  Pydantic    │  │  Exception   │     │   ║
║  │  │ (HS256)      │  │  Validation  │  │  Handlers    │     │   ║
║  │  └──────────────┘  └──────────────┘  └──────────────┘     │   ║
║  └────────────────────────────┬──────────────────────────────┘   ║
╚═══════════════════════════════╪════════════════════════════════════╝
                                │ calls
╔═══════════════════════════════╪════════════════════════════════════╗
║                APPLICATION / SERVICE LAYER (services/)            ║
║  ┌─────────────┐ ┌──────────────────┐ ┌──────────────────────┐    ║
║  │ AuthService │ │AttendanceService │ │ RegistrationService  │    ║
║  │             │ │                  │ │                      │    ║
║  │ - auth      │ │ - sign_in/out    │ │ - extract_encodings  │    ║
║  │ - rehash    │ │ - finalize sess  │ │ - quality_filter     │    ║
║  │ - defaults  │ │ - load face data │ │ - encrypt & store    │    ║
║  └─────────────┘ └──────────────────┘ └──────────────────────┘    ║
║  ┌─────────────┐ ┌──────────────────┐                             ║
║  │CourseService│ │NotificationSvc   │                             ║
║  │             │ │                  │                             ║
║  │ - create    │ │ - absence emails │                             ║
║  │ - enroll    │ │ - deduplication  │                             ║
║  └─────────────┘ └──────────────────┘                             ║
╚═══════════════════════════════╪════════════════════════════════════╝
                                │ depends on (via interfaces)
╔═══════════════════════════════╪════════════════════════════════════╗
║                        DOMAIN LAYER (core/)                       ║
║  ┌──────────────────────────────────────────────────────────────┐  ║
║  │  Entities (dataclasses, pure Python):                        │  ║
║  │  Student · Course · AttendanceRecord · Account · Enrollment  │  ║
║  ├──────────────────────────────────────────────────────────────┤  ║
║  │  Exceptions:                                                 │  ║
║  │  DomainError → NotFoundError, AuthError, ValidationError...  │  ║
║  ├──────────────────────────────────────────────────────────────┤  ║
║  │  Interfaces (ABCs):                                          │  ║
║  │  IStudentRepo · ICourseRepo · IAttendanceRepo · IAccountRepo  │  ║
║  │  IEmailGateway · IEncryptionService · IEnrollmentRepo        │  ║
║  └──────────────────────────────────────────────────────────────┘  ║
╚═══════════════════════════════╪════════════════════════════════════╝
                                │ implements
╔═══════════════════════════════╪════════════════════════════════════╗
║                  INFRASTRUCTURE LAYER (infrastructure/)           ║
║  ┌───────────────────┐  ┌──────────────────┐  ┌───────────────┐   ║
║  │  SQLite Database  │  │    Security      │  │    Email      │   ║
║  │                   │  │                  │  │               │   ║
║  │  connection.py    │  │  encryption.py   │  │  smtp_       │   ║
║  │  (WAL mode)       │  │  (Fernet/env)    │  │  gateway.py  │   ║
║  │                   │  │                  │  │               │   ║
║  │  migrator.py      │  │  password.py     │  │               │   ║
║  │  (SQL migration)  │  │  (PBKDF2 600k)   │  │               │   ║
║  │                   │  │                  │  │               │   ║
║  │  *_repo.py ×5     │  │                  │  │               │   ║
║  └───────────────────┘  └──────────────────┘  └───────────────┘   ║
╚══════════════════════════════════════════════════════════════════╝
```

---

## 2. Entity Relationship Diagram (ERD)

```
┌─────────────────────┐         ┌─────────────────────┐
│       users         │         │      courses         │
├─────────────────────┤         ├─────────────────────┤
│ PK  student_uid TEXT│         │ PK  id INTEGER       │
│     name       TEXT │         │     code  TEXT UNIQUE│
│     email      TEXT │         │     name  TEXT       │
│     face_enc   BLOB │         │     created_at TEXT  │
│     image_folder    │         └──────────┬──────────┘
│     created_at TEXT │                    │
└──────────┬──────────┘                    │
           │  1                            │ 1
           │                               │
           │  N       ┌────────────────────┴─┐  N
           └──────────►     enrollments       ◄──────────────┐
                      ├──────────────────────┤               │
                      │ PK  id INTEGER        │               │
                      │ FK  student_uid TEXT  │               │
                      │ FK  course_id INT     │               │
                      │ FK  teacher_acct_id   │               │
                      │     created_at TEXT   │               │
                      └──────────────────────┘               │
                                                              │
┌──────────────────────┐                                      │
│      accounts        │                                      │
├──────────────────────┤                                      │
│ PK  id  INTEGER      │──── teacher_account_id FK ───────────┘
│     username TEXT    │
│     password_hash    │         ┌────────────────────────┐
│     salt TEXT        │         │    teacher_courses     │
│     iterations INT   │         ├────────────────────────┤
│     role TEXT        │◄────────┤ FK  teacher_account_id │
│     student_uid FK   │         │ FK  course_id          │
│     is_active INT    │         │     created_at TEXT    │
│     created_at TEXT  │         └────────────────────────┘
└──────────────────────┘

           student_uid FK                course_id FK
               │                              │
               ▼                              ▼
┌─────────────────────────────────────────────────────────────┐
│                        attendance                            │
├─────────────────────────────────────────────────────────────┤
│ PK  id           INTEGER                                     │
│ FK  student_uid  TEXT                                        │
│ FK  course_id    INTEGER                                     │
│     date         TEXT  (YYYY-MM-DD)                          │
│     sign_in_time TEXT  (HH:MM:SS, nullable)                  │
│     sign_out_time TEXT (HH:MM:SS, nullable)                  │
│     duration     REAL  (minutes, nullable)                   │
│     status       TEXT  ('Present' | 'Absent')                │
│     created_at   TEXT                                        │
└─────────────────────────────────────────────────────────────┘

               │                              │
               ▼                              ▼
┌─────────────────────────────────────────────────────────────┐
│                   email_notifications                        │
├─────────────────────────────────────────────────────────────┤
│ PK  id                   INTEGER                             │
│ FK  student_uid          TEXT                                │
│ FK  course_id            INTEGER                             │
│     recipient_email      TEXT                                │
│     subject              TEXT                                │
│     body                 TEXT                                │
│     sent_at              TEXT                                │
│     status               TEXT  ('sent'|'failed'|'logged')   │
│     error_message        TEXT  (nullable)                    │
│     attendance_record_id INTEGER (nullable, FK)              │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│                   schema_migrations                          │
├─────────────────────────────────────────────────────────────┤
│ PK  version    INTEGER                                       │
│     filename   TEXT                                          │
│     applied_at TEXT                                          │
└─────────────────────────────────────────────────────────────┘
```

---

## 3. Face Recognition Pipeline Sequence

```
Actor         GUI Thread          Camera Thread          Database
  │               │                     │                   │
  │  Click        │                     │                   │
  │ "Start Att."  │                     │                   │
  │──────────────►│                     │                   │
  │               │  load_enrolled_     │                   │
  │               │  face_data()        │                   │
  │               │────────────────────────────────────────►│
  │               │◄────────────────────────────────────────│
  │               │  KnownFaceStore     │                   │
  │               │                     │                   │
  │               │  spawn thread       │                   │
  │               │────────────────────►│                   │
  │               │                     │ open_camera()     │
  │               │                     │──────►[camera]    │
  │               │                     │                   │
  │               │                     │ ┌──── frame loop ─┤
  │               │                     │ │                 │
  │               │                     │ │ process_frame() │
  │               │                     │ │  → detect faces │
  │               │                     │ │  → recognize    │
  │               │                     │ │  → liveness     │
  │               │                     │ │                 │
  │               │                     │ │ if new sign-in: │
  │               │                     │ │  sign_in_cb()  ►│ INSERT attendance
  │               │                     │ │◄────────────────│
  │               │                     │ └─────────────────┤
  │               │                     │                   │
  │  Press Q      │                     │                   │
  │──────────────►│                     │                   │
  │               │  set stop_event     │                   │
  │               │────────────────────►│                   │
  │               │                     │ sign_out_cb() for │
  │               │                     │  all signed-in   ►│ UPDATE attendance
  │               │                     │◄────────────────  │
  │               │  thread joins       │                   │
  │               │◄────────────────────│                   │
```

---

## 4. Authentication Flow

```
Client                    FastAPI                  AuthService           DB
  │                          │                         │                  │
  │  POST /auth/login        │                         │                  │
  │  {user, pass, role}      │                         │                  │
  │─────────────────────────►│                         │                  │
  │                          │  authenticate(u,p,r)    │                  │
  │                          │────────────────────────►│                  │
  │                          │                         │  get_by_username │
  │                          │                         │─────────────────►│
  │                          │                         │◄─────────────────│
  │                          │                         │  get_credentials │
  │                          │                         │─────────────────►│
  │                          │                         │◄─────────────────│
  │                          │                         │                  │
  │                          │                         │ PBKDF2 verify    │
  │                          │                         │ (compare_digest) │
  │                          │                         │                  │
  │                          │                         │ needs_rehash?    │
  │                          │                         │ → rehash silently│
  │                          │◄────────────────────────│                  │
  │                          │  Account entity         │                  │
  │                          │                         │                  │
  │                          │  create_access_token()  │                  │
  │                          │  JWT HS256              │                  │
  │                          │                         │                  │
  │◄─────────────────────────│                         │                  │
  │  {access_token, role...} │                         │                  │
  │                          │                         │                  │
  │  GET /api/v1/attendance/ │                         │                  │
  │  Authorization: Bearer   │                         │                  │
  │─────────────────────────►│                         │                  │
  │                          │  decode_token()         │                  │
  │                          │  require_role()         │                  │
  │                          │  → 403 if wrong role    │                  │
  │◄─────────────────────────│                         │                  │
  │  200 [attendance data]   │                         │                  │
```

---

## 5. Liveness Detection Signal Combination

```
Camera Frame
     │
     ├──► EAR Blink Detection ──► blink_score  (weight: 60%)
     │    (Soukupová & Čech 2016)
     │    EAR = (||p2-p6|| + ||p3-p5||) / (2 × ||p1-p4||)
     │    Blink: EAR < 0.22 for ≥ 2 consecutive frames
     │
     ├──► Texture Analysis ──────► texture_score (weight: 25%)
     │    Laplacian variance on face crop
     │    Low variance → flat texture → likely photo
     │
     └──► Motion Analysis ────────► motion_score  (weight: 15%)
          Optical flow (Farneback) between consecutive crops
          Near-zero flow → suspiciously still → likely photo

          composite = 0.60 × blink + 0.25 × texture + 0.15 × motion
          is_live = (blink_count ≥ 1) AND (composite ≥ 0.50)
```
