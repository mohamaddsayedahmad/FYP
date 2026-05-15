-- Migration 001: Initial schema
-- Creates all tables from scratch for new installations.
-- For existing databases, the migrator skips CREATE TABLE IF NOT EXISTS
-- and applies only the ALTER TABLE statements that add missing columns.

CREATE TABLE IF NOT EXISTS users (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    student_uid TEXT    UNIQUE NOT NULL,
    name        TEXT    NOT NULL,
    email       TEXT    NOT NULL,
    face_encoding BLOB,
    image_folder  TEXT,
    created_at  TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS courses (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    code       TEXT    UNIQUE NOT NULL,
    name       TEXT    NOT NULL,
    created_at TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S', 'now'))
);

CREATE TABLE IF NOT EXISTS accounts (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT    UNIQUE NOT NULL,
    password_hash TEXT    NOT NULL,
    salt          TEXT    NOT NULL,
    iterations    INTEGER NOT NULL DEFAULT 200000,
    role          TEXT    NOT NULL CHECK (role IN ('admin', 'teacher', 'student')),
    student_uid   TEXT,
    created_at    TEXT    NOT NULL,
    is_active     INTEGER NOT NULL DEFAULT 1,
    FOREIGN KEY (student_uid) REFERENCES users (student_uid) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS enrollments (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    student_uid        TEXT    NOT NULL,
    course_id          INTEGER NOT NULL,
    teacher_account_id INTEGER,
    created_at         TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S', 'now')),
    UNIQUE (student_uid, course_id),
    FOREIGN KEY (student_uid) REFERENCES users (student_uid)   ON DELETE CASCADE,
    FOREIGN KEY (course_id)   REFERENCES courses (id)          ON DELETE CASCADE,
    FOREIGN KEY (teacher_account_id) REFERENCES accounts (id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS teacher_courses (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    teacher_account_id INTEGER NOT NULL,
    course_id          INTEGER NOT NULL,
    created_at         TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S', 'now')),
    UNIQUE (teacher_account_id, course_id),
    FOREIGN KEY (teacher_account_id) REFERENCES accounts (id) ON DELETE CASCADE,
    FOREIGN KEY (course_id)          REFERENCES courses (id)  ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS attendance (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    student_uid   TEXT    NOT NULL,
    course_id     INTEGER NOT NULL,
    date          TEXT    NOT NULL,
    sign_in_time  TEXT,
    sign_out_time TEXT,
    duration      REAL,
    status        TEXT    CHECK (status IN ('Present', 'Absent')),
    created_at    TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S', 'now')),
    FOREIGN KEY (student_uid) REFERENCES users (student_uid) ON DELETE CASCADE,
    FOREIGN KEY (course_id)   REFERENCES courses (id)        ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS email_notifications (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    student_uid         TEXT    NOT NULL,
    course_id           INTEGER NOT NULL,
    recipient_email     TEXT    NOT NULL,
    subject             TEXT    NOT NULL,
    body                TEXT    NOT NULL,
    sent_at             TEXT    NOT NULL,
    status              TEXT    NOT NULL CHECK (status IN ('sent', 'failed', 'logged')),
    error_message       TEXT,
    attendance_record_id INTEGER,
    FOREIGN KEY (student_uid) REFERENCES users (student_uid) ON DELETE CASCADE,
    FOREIGN KEY (course_id)   REFERENCES courses (id)        ON DELETE CASCADE
);

-- Indexes for common query patterns
CREATE INDEX IF NOT EXISTS idx_attendance_student_course_date
    ON attendance (student_uid, course_id, date);

CREATE INDEX IF NOT EXISTS idx_attendance_course_date
    ON attendance (course_id, date);

CREATE INDEX IF NOT EXISTS idx_enrollments_course
    ON enrollments (course_id);

CREATE INDEX IF NOT EXISTS idx_enrollments_teacher
    ON enrollments (teacher_account_id);
