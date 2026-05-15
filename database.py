"""
SQLite database helpers for AI Face Attendance System.

Tables:
    users(
        id INTEGER PK,
        student_uid TEXT UNIQUE,
        name TEXT,
        email TEXT,
        image_folder TEXT,        <-- used for face image path (can be NULL)
        created_at TEXT
    )

    courses(
        id INTEGER PK,
        code TEXT UNIQUE,
        name TEXT,
        created_at TEXT
    )

    enrollments(
        id INTEGER PK,
        student_uid TEXT,
        course_id INTEGER,
        created_at TEXT
    )

    attendance(
        id INTEGER PK,
        student_uid TEXT,
        course_id INTEGER,
        date TEXT,
        sign_in_time TEXT,
        sign_out_time TEXT,
        duration REAL,
        status TEXT,
        created_at TEXT
    )

    email_notifications(
        id INTEGER PK,
        student_uid TEXT,
        course_id INTEGER,
        recipient_email TEXT,
        subject TEXT,
        body TEXT,
        sent_at TEXT,
        status TEXT
    )

    accounts(
        id INTEGER PK,
        username TEXT UNIQUE,
        password_hash TEXT,
        salt TEXT,
        role TEXT ('admin'|'teacher'|'student'),
        student_uid TEXT (nullable; links student accounts to users.student_uid),
        created_at TEXT,
        is_active INTEGER
    )
"""

import os
import sqlite3
import base64
import hashlib
import hmac
import re
import secrets
import ssl
import smtplib
from email.message import EmailMessage
from typing import List, Dict, Optional, Tuple
from datetime import datetime

# Always create/use the DB next to this file (avoids "where is my DB?" issues)
DB_PATH = os.path.join(os.path.dirname(__file__), "attendance.db")


# ---------------- basic connection & init ----------------

def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, col_def: str) -> None:
    """
    Make sure 'table.column' exists. If not, ALTER TABLE to add it.
    This is what fixes the 'no such column: image_folder' error on old DBs.
    """
    cur = conn.cursor()
    cur.execute(f"PRAGMA table_info({table});")
    cols = [r["name"] for r in cur.fetchall()]
    if column not in cols:
        cur.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_def};")
        conn.commit()


# ---------------- password hashing (PBKDF2) ----------------
# (OWASP recommends PBKDF2 as a safe option; compare_digest avoids timing leaks.)
PBKDF2_ITERATIONS = 200_000
PBKDF2_ALGO = "sha256"
SALT_BYTES = 16


def _get_table_columns(conn: sqlite3.Connection, table: str) -> set:
    """Return a set of column names for a table (empty set if table doesn't exist)."""
    try:
        cur = conn.cursor()
        cur.execute(f"PRAGMA table_info({table});")
        return {row[1] for row in cur.fetchall()}
    except Exception:
        return set()




def _get_table_info(conn: sqlite3.Connection, table: str) -> dict:
    """Return dict of column_name -> {type, notnull, dflt}. Works with sqlite3.Row or tuples."""
    info = {}
    try:
        cur = conn.cursor()
        cur.execute(f"PRAGMA table_info({table});")
        rows = cur.fetchall()
        for r in rows:
            # PRAGMA table_info returns: cid, name, type, notnull, dflt_value, pk
            name = r[1]
            info[name] = {
                "type": r[2],
                "notnull": int(r[3]) if r[3] is not None else 0,
                "dflt": r[4],
                "pk": int(r[5]) if r[5] is not None else 0,
            }
    except Exception:
        return {}
    return info


def _ensure_email_notifications_schema(conn: sqlite3.Connection) -> None:
    """Ensure email_notifications table exists and is compatible across schema versions.

    Fixes legacy DBs where:
    - student_uid column is missing
    - attendance_record_id exists but is NOT NULL (causing finalize-session crashes)
    """
    cur = conn.cursor()

    # Create canonical table (if not exists)
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS email_notifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_uid TEXT,
            course_id INTEGER,
            recipient_email TEXT,
            subject TEXT,
            body TEXT,
            sent_at TEXT,
            status TEXT,
            error_message TEXT,
            attendance_record_id INTEGER,
            FOREIGN KEY (student_uid) REFERENCES users(student_uid) ON DELETE CASCADE,
            FOREIGN KEY (course_id)   REFERENCES courses(id)      ON DELETE CASCADE
        );
        """
    )
    conn.commit()

    info = _get_table_info(conn, "email_notifications")

    # Add missing canonical columns (safe on old DBs)
    required_cols = {
        "student_uid": "TEXT",
        "course_id": "INTEGER",
        "recipient_email": "TEXT",
        "subject": "TEXT",
        "body": "TEXT",
        "sent_at": "TEXT",
        "status": "TEXT",
        "error_message": "TEXT",
        "attendance_record_id": "INTEGER",
    }
    for col, col_def in required_cols.items():
        if col not in info:
            cur.execute(f"ALTER TABLE email_notifications ADD COLUMN {col} {col_def};")
    conn.commit()

    # If legacy schema has attendance_record_id as NOT NULL, rebuild table to make it nullable.
    info = _get_table_info(conn, "email_notifications")
    if "attendance_record_id" in info and info["attendance_record_id"]["notnull"] == 1:
        # Rebuild (SQLite can't drop NOT NULL constraints in-place).
        cur.execute("ALTER TABLE email_notifications RENAME TO email_notifications_old;")
        cur.execute(
            """
            CREATE TABLE email_notifications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                student_uid TEXT,
                course_id INTEGER,
                recipient_email TEXT,
                subject TEXT,
                body TEXT,
                sent_at TEXT,
                status TEXT,
                error_message TEXT,
                attendance_record_id INTEGER
            );
            """
        )

        old_info = _get_table_info(conn, "email_notifications_old")
        new_cols = ["id","student_uid","course_id","recipient_email","subject","body","sent_at","status","error_message","attendance_record_id"]

        select_exprs = []
        for c in new_cols:
            if c in old_info:
                select_exprs.append(c)
            else:
                # try common legacy names
                if c == "student_uid" and "student_id" in old_info:
                    select_exprs.append("student_id")
                elif c == "recipient_email" and "student_email" in old_info:
                    select_exprs.append("student_email")
                elif c == "recipient_email" and "email" in old_info:
                    select_exprs.append("email")
                else:
                    select_exprs.append("NULL")

        cur.execute(
            f"INSERT INTO email_notifications ({', '.join(new_cols)}) "
            f"SELECT {', '.join(select_exprs)} FROM email_notifications_old;"
        )
        cur.execute("DROP TABLE email_notifications_old;")
        conn.commit()



def _email_notif_where_clause(cols: set, sid: str, course_id: int, email: str, subject: str):
    """Build a safe WHERE clause for de-duplication across schema versions."""
    clauses = []
    params = []

    if "student_uid" in cols:
        clauses.append("student_uid = ?")
        params.append(sid)
    elif "student_id" in cols:
        clauses.append("student_id = ?")
        params.append(sid)
    elif "student_email" in cols:
        clauses.append("student_email = ?")
        params.append(email)
    elif "recipient_email" in cols:
        clauses.append("recipient_email = ?")
        params.append(email)

    if "course_id" in cols:
        clauses.append("course_id = ?")
        params.append(course_id)

    if "subject" in cols:
        clauses.append("subject = ?")
        params.append(subject)

    if not clauses:
        return None, None

    return " AND ".join(clauses), params


def _insert_email_notification(
    cur: sqlite3.Cursor,
    cols: set,
    sid: str,
    course_id: int,
    email: str,
    subject: str,
    body: str,
    sent_at: str,
    status: str,
    error_message: Optional[str] = None,
    attendance_record_id: Optional[int] = None,
) -> None:
    """Insert into email_notifications while remaining compatible with older schemas."""
    if not cols:
        return

    colnames = []
    values = []

    def add(col, val):
        if col in cols:
            colnames.append(col)
            values.append(val)

    # identity
    add("student_uid", sid)
    add("student_id", sid)

    # course
    add("course_id", course_id)

    # email fields (support legacy column names)
    add("recipient_email", email)
    add("student_email", email)
    add("email", email)

    # message fields
    add("subject", subject)
    add("body", body)
    add("sent_at", sent_at)
    add("status", status)

    # optional error column
    add("error_message", error_message)

    # attendance_record_id (some schemas require it)
    if "attendance_record_id" in cols:
        rid = attendance_record_id
        if rid is None:
            # Derive from attendance table using date extracted from sent_at (YYYY-MM-DD ...)
            try:
                date_part = str(sent_at).split()[0] if sent_at else None
                if date_part:
                    cur.execute(
                        "SELECT id FROM attendance WHERE student_uid=? AND course_id=? AND date=? ORDER BY id DESC LIMIT 1;",
                        (sid, course_id, date_part),
                    )
                    row = cur.fetchone()
                    if row is not None:
                        rid = row[0]
            except Exception:
                rid = attendance_record_id
        add("attendance_record_id", rid)

    if not colnames:
        return

    placeholders = ", ".join(["?"] * len(colnames))
    sql = f"INSERT INTO email_notifications ({', '.join(colnames)}) VALUES ({placeholders});"
    cur.execute(sql, values)

def _b64e(b: bytes) -> str:
    return base64.b64encode(b).decode("utf-8")


def _decode_bytes(s: str) -> bytes:
    """Decode stored bytes from either HEX or Base64 (legacy-safe)."""
    if s is None:
        return b""
    s = str(s).strip()
    if not s:
        return b""

    # Prefer HEX if it clearly looks like hex
    if re.fullmatch(r"[0-9a-fA-F]+", s) and (len(s) % 2 == 0) and len(s) >= 16:
        try:
            return bytes.fromhex(s)
        except Exception:
            pass

    # Then try Base64 (with/without padding)
    try:
        return base64.b64decode(s.encode("utf-8"), validate=True)
    except Exception:
        try:
            pad = (-len(s)) % 4
            return base64.b64decode((s + ("=" * pad)).encode("utf-8"))
        except Exception:
            return s.encode("utf-8", errors="ignore")


def _b64d(s: str) -> bytes:
    """Backward-compatible alias."""
    return _decode_bytes(s)


def _hash_password(password: str, salt: bytes) -> bytes:
    return hashlib.pbkdf2_hmac(
        PBKDF2_ALGO,
        password.encode("utf-8"),
        salt,
        PBKDF2_ITERATIONS,
    )


def create_account(username: str, password: str, role: str, student_uid: Optional[str] = None) -> None:
    """
    Create or update an account. For student accounts, pass student_uid to link it.
    """
    conn = _get_conn()
    cur = conn.cursor()
    now = datetime.now().isoformat(timespec="seconds")

    salt = secrets.token_bytes(SALT_BYTES)
    pw_hash = _hash_password(password, salt)

    cur.execute(
        """
        INSERT INTO accounts(username, password_hash, salt, role, student_uid, created_at, is_active)
        VALUES (?, ?, ?, ?, ?, ?, 1)
        ON CONFLICT(username) DO UPDATE SET
            password_hash = excluded.password_hash,
            salt         = excluded.salt,
            role         = excluded.role,
            student_uid  = excluded.student_uid,
            is_active    = 1;
        """,
        (username, _b64e(pw_hash), _b64e(salt), role, student_uid, now),
    )
    conn.commit()
    conn.close()


def authenticate(username: str, password: str, role: str) -> Optional[Dict]:
    """
    Returns an auth context dict if valid, otherwise None.
    """
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id, username, password_hash, salt, role, student_uid, is_active
        FROM accounts
        WHERE username = ? AND role = ? AND is_active = 1
        LIMIT 1;
        """,
        (username, role),
    )
    row = cur.fetchone()
    conn.close()

    if not row:
        return None

    salt = _b64d(row["salt"])
    expected = _b64d(row["password_hash"])
    actual = _hash_password(password, salt)

    if not hmac.compare_digest(actual, expected):
        return None

    return {
        "account_id": row["id"],
        "role": row["role"],
        "username": row["username"],
        "student_uid": row["student_uid"],
    }



def get_account_id(username: str, role: Optional[str] = None) -> Optional[int]:
    """Return the account id for a given username (and optional role)."""
    conn = _get_conn()
    cur = conn.cursor()
    if role:
        cur.execute(
            "SELECT id FROM accounts WHERE username = ? AND role = ? AND is_active = 1 LIMIT 1;",
            (username, role),
        )
    else:
        cur.execute(
            "SELECT id FROM accounts WHERE username = ? AND is_active = 1 LIMIT 1;",
            (username,),
        )
    row = cur.fetchone()
    conn.close()
    return int(row["id"]) if row else None


def get_active_teachers() -> list[dict]:
    """Return active teacher accounts as list of dicts: {id, username}."""
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute(
        "SELECT id, username FROM accounts WHERE role = 'teacher' AND is_active = 1 ORDER BY username ASC;"
    )
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows



def set_teacher_courses(teacher_account_id: int, course_ids: List[int]) -> None:
    """Replace teacher's assigned courses with the given list."""
    conn = _get_conn()
    cur = conn.cursor()
    now = datetime.now().isoformat(timespec="seconds")

    # Clear previous assignments
    cur.execute("DELETE FROM teacher_courses WHERE teacher_account_id = ?;", (teacher_account_id,))

    # Insert new ones
    for cid in course_ids:
        cur.execute(
            "INSERT OR IGNORE INTO teacher_courses(teacher_account_id, course_id, created_at) VALUES (?, ?, ?);",
            (teacher_account_id, int(cid), now),
        )

    conn.commit()
    conn.close()


def get_teacher_courses(teacher_account_id: int) -> List[Dict]:
    """Return courses assigned to the teacher account (id, code, name)."""
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT c.id, c.code, c.name
        FROM teacher_courses tc
        JOIN courses c ON c.id = tc.course_id
        WHERE tc.teacher_account_id = ?
        ORDER BY c.code ASC;
        """,
        (teacher_account_id,),
    )
    rows = cur.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def set_account_active(username: str, role: str, is_active: bool) -> None:
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute(
        "UPDATE accounts SET is_active = ? WHERE username = ? AND role = ?;",
        (1 if is_active else 0, username, role),
    )
    conn.commit()
    conn.close()


def ensure_default_admin() -> None:
    """
    Ensure at least one admin exists, so first run is not locked out.
    Change the default password after first login.
    """
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM accounts WHERE role='admin' AND is_active=1 LIMIT 1;")
    exists = cur.fetchone() is not None
    conn.close()
    if not exists:
        create_account("admin", "admin123", "admin", None)


def ensure_default_teacher() -> None:
    """
    Convenience: create a default teacher if none exists.
    """
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM accounts WHERE role='teacher' AND is_active=1 LIMIT 1;")
    exists = cur.fetchone() is not None
    conn.close()
    if not exists:
        create_account("teacher", "teacher123", "teacher", None)


def init_db() -> None:
    """Create tables if they do not exist, and upgrade old schemas."""
    conn = _get_conn()
    cur = conn.cursor()

    # users
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_uid TEXT UNIQUE NOT NULL,
            name TEXT NOT NULL,
            email TEXT NOT NULL,
            face_encoding BLOB,
            image_folder TEXT,
            created_at TEXT NOT NULL
        );
        """

    )

    # --- migrations (safe for older DBs) ---
    try:
        cur.execute("ALTER TABLE users ADD COLUMN face_encoding BLOB;")
    except sqlite3.OperationalError:
        pass

    # courses
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS courses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT UNIQUE NOT NULL,
            name TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        """
    )

    # enrollments
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS enrollments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_uid TEXT NOT NULL,
            course_id INTEGER NOT NULL,
            teacher_account_id INTEGER,
            created_at TEXT NOT NULL,
            UNIQUE(student_uid, course_id),
            FOREIGN KEY (student_uid) REFERENCES users(student_uid) ON DELETE CASCADE,
            FOREIGN KEY (course_id)   REFERENCES courses(id)      ON DELETE CASCADE
        );
        """
    )

    # attendance
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS attendance (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_uid TEXT NOT NULL,
            course_id INTEGER NOT NULL,
            date TEXT NOT NULL,
            sign_in_time TEXT,
            sign_out_time TEXT,
            duration REAL,
            status TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY (student_uid) REFERENCES users(student_uid) ON DELETE CASCADE,
            FOREIGN KEY (course_id)   REFERENCES courses(id)      ON DELETE CASCADE
        );
        """
    )

    # email notifications (for absence emails log)
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS email_notifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_uid TEXT NOT NULL,
            course_id INTEGER NOT NULL,
            recipient_email TEXT NOT NULL,
            subject TEXT NOT NULL,
            body TEXT NOT NULL,
            sent_at TEXT NOT NULL,
            status TEXT NOT NULL,
            FOREIGN KEY (student_uid) REFERENCES users(student_uid) ON DELETE CASCADE,
            FOREIGN KEY (course_id)   REFERENCES courses(id)      ON DELETE CASCADE
        );
        """
    )

    # accounts (admin/teacher/student login)
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS accounts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            salt TEXT NOT NULL,
            role TEXT NOT NULL CHECK(role IN ('admin','teacher','student')),
            student_uid TEXT,
            created_at TEXT NOT NULL,
            is_active INTEGER NOT NULL DEFAULT 1,
            FOREIGN KEY (student_uid) REFERENCES users(student_uid) ON DELETE SET NULL
        );
        """
    )


    # teacher-course assignments (admin assigns courses to teachers)
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS teacher_courses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            teacher_account_id INTEGER NOT NULL,
            course_id INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE(teacher_account_id, course_id),
            FOREIGN KEY (teacher_account_id) REFERENCES accounts(id) ON DELETE CASCADE,
            FOREIGN KEY (course_id) REFERENCES courses(id) ON DELETE CASCADE
        );
        """
    )

    # ------- schema upgrade for existing DBs -------
    _ensure_column(conn, "users", "image_folder", "TEXT")
    _ensure_column(conn, "enrollments", "teacher_account_id", "INTEGER")
    _ensure_column(conn, "courses", "created_at", "TEXT")
    _ensure_column(conn, "enrollments", "created_at", "TEXT")
    _ensure_column(conn, "attendance", "created_at", "TEXT")

    # email_notifications schema/migration (legacy-safe)
    _ensure_email_notifications_schema(conn)

    conn.commit()
    conn.close()

    # Ensure default accounts exist (after tables exist)
    ensure_default_admin()
    ensure_default_teacher()


# Run init when module is imported
init_db()


# ---------------- user helpers ----------------

def get_users() -> List[Dict]:
    """Return all users as list of dicts."""
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute("SELECT student_uid, name, email, face_encoding, image_folder FROM users ORDER BY student_uid;")
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


def get_user_by_uid(student_uid: str) -> Optional[Dict]:
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute("SELECT student_uid, name, email FROM users WHERE student_uid = ? LIMIT 1;", (student_uid,))
    row = cur.fetchone()
    conn.close()
    return dict(row) if row else None





def add_user(name: str, email: str, face_encoding_np_array, student_uid: str, image_folder: Optional[str] = None):
    """Backward-compatible helper used by registration.py.

    Stores/updates a row in `users` and saves the face encoding in `users.face_encoding`
    as an **encrypted JSON** list of floats (Fernet), matching how attendance.py loads it.

    Args:
        name: Student name
        email: Student email
        face_encoding_np_array: numpy array (128-d) or list-like of floats
        student_uid: Student ID (required)
        image_folder: optional path to the student's face images folder

    Returns:
        (user_id, final_student_uid)
    """
    if student_uid is None or not str(student_uid).strip():
        raise ValueError("student_uid is required")
    student_uid = str(student_uid).strip()

    # Convert encoding to a JSON-serializable list[float]
    try:
        enc_list = face_encoding_np_array.tolist()  # numpy
    except Exception:
        enc_list = list(face_encoding_np_array)

    import json
    from encrypt import encrypt_data  # local project module (Fernet)

    enc_blob = encrypt_data(json.dumps(enc_list))

    conn = _get_conn()
    cur = conn.cursor()
    now = datetime.now().isoformat(timespec="seconds")

    cur.execute(
        """
        INSERT INTO users(student_uid, name, email, face_encoding, image_folder, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(student_uid) DO UPDATE SET
            name = excluded.name,
            email = excluded.email,
            face_encoding = excluded.face_encoding,
            image_folder = excluded.image_folder;
        """,
        (student_uid, name, email, enc_blob, image_folder, now),
    )
    conn.commit()

    cur.execute("SELECT id FROM users WHERE student_uid = ? LIMIT 1;", (student_uid,))
    row = cur.fetchone()
    user_id = int(row[0]) if row else None
    conn.close()
    return user_id, student_uid

def get_students_for_teacher(teacher_account_id: int, course_id: Optional[int] = None) -> List[Dict]:
    """Return distinct students assigned to a teacher (optionally within one course)."""
    conn = _get_conn()
    cur = conn.cursor()
    sql = """
        SELECT DISTINCT u.student_uid, u.name, u.email
        FROM enrollments e
        JOIN users u ON u.student_uid = e.student_uid
        WHERE e.teacher_account_id = ?
    """
    params = [int(teacher_account_id)]
    if course_id is not None:
        sql += " AND e.course_id = ?"
        params.append(int(course_id))
    sql += " ORDER BY u.student_uid;"
    cur.execute(sql, params)
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


def get_face_users_for_course(course_id: int, teacher_account_id: Optional[int] = None) -> List[Dict]:
    """Return users enrolled in a course, optionally filtered by teacher assignment.

    Includes face_encoding so the camera loop can load only the correct faces.
    """
    conn = _get_conn()
    cur = conn.cursor()
    sql = """
        SELECT u.student_uid, u.name, u.email, u.face_encoding, u.image_folder
        FROM enrollments e
        JOIN users u ON u.student_uid = e.student_uid
        WHERE e.course_id = ?
    """
    params = [int(course_id)]
    if teacher_account_id is not None:
        sql += " AND e.teacher_account_id = ?"
        params.append(int(teacher_account_id))
    sql += " ORDER BY u.student_uid;"
    cur.execute(sql, params)
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


def create_or_update_user(student_uid: str, name: str, email: str, image_folder: Optional[str] = None) -> Tuple[bool, str, str]:
    """Insert or update a user. Returns (ok, message, student_uid)."""
    conn = _get_conn()
    cur = conn.cursor()
    now = datetime.now().isoformat(timespec="seconds")

    try:
        cur.execute(
            """
            INSERT INTO users(student_uid, name, email, image_folder, created_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(student_uid) DO UPDATE SET
                name = excluded.name,
                email = excluded.email,
                image_folder = excluded.image_folder;
            """,
            (student_uid, name, email, image_folder, now),
        )
        conn.commit()
        return True, "User registered/updated successfully.", student_uid
    except sqlite3.IntegrityError as e:
        conn.rollback()
        return False, f"Database integrity error: {e}", student_uid
    except Exception as e:
        conn.rollback()
        return False, f"Database error: {e}", student_uid
    finally:
        conn.close()


# ---------------- course & enrollment helpers ----------------

def get_courses() -> List[Dict]:
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute("SELECT id, code, name FROM courses ORDER BY code;")
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


def get_courses_for_student(student_uid: str) -> List[Dict]:
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT c.id, c.code, c.name
        FROM enrollments e
        JOIN courses c ON c.id = e.course_id
        WHERE e.student_uid = ?
        ORDER BY c.code;
        """,
        (student_uid,),
    )
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


def add_course(code: str, name: str) -> None:
    conn = _get_conn()
    cur = conn.cursor()
    now = datetime.now().isoformat(timespec="seconds")
    cur.execute(
        """
        INSERT INTO courses(code, name, created_at)
        VALUES (?, ?, ?)
        ON CONFLICT(code) DO UPDATE SET
            name = excluded.name;
        """,
        (code, name, now),
    )
    conn.commit()
    conn.close()


def get_course_by_id(course_id: int) -> Optional[Dict]:
    """Fetch one course by id."""
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute("SELECT id, code, name FROM courses WHERE id = ? LIMIT 1;", (course_id,))
    row = cur.fetchone()
    conn.close()
    return dict(row) if row else None


def enroll_student_in_course(student_uid: str, course_id: int, teacher_account_id: int | None = None) -> None:
    """Enroll a student in a course.

    If the (student_uid, course_id) enrollment already exists, this will update the
    teacher_account_id (when provided).
    """
    conn = _get_conn()
    cur = conn.cursor()
    now = datetime.now().isoformat(timespec="seconds")

    # Prefer SQLite UPSERT (3.24+). Fallback to INSERT OR IGNORE + UPDATE.
    try:
        cur.execute(
            """
            INSERT INTO enrollments(student_uid, course_id, teacher_account_id, created_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(student_uid, course_id) DO UPDATE SET
                teacher_account_id = excluded.teacher_account_id;
            """,
            (student_uid, int(course_id), teacher_account_id, now),
        )
    except Exception:
        cur.execute(
            """
            INSERT OR IGNORE INTO enrollments(student_uid, course_id, teacher_account_id, created_at)
            VALUES (?, ?, ?, ?);
            """,
            (student_uid, int(course_id), teacher_account_id, now),
        )
        if teacher_account_id is not None:
            cur.execute(
                "UPDATE enrollments SET teacher_account_id = ? WHERE student_uid = ? AND course_id = ?;",
                (int(teacher_account_id), student_uid, int(course_id)),
            )

    conn.commit()
    conn.close()


def is_student_enrolled_in_course(student_uid: str, course_id: int) -> bool:
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM enrollments WHERE student_uid = ? AND course_id = ? LIMIT 1;", (student_uid, course_id))
    row = cur.fetchone()
    conn.close()
    return row is not None


# ---------------- attendance helpers ----------------

def _today_str() -> str:
    return datetime.now().date().isoformat()


def _now_time_str() -> str:
    return datetime.now().time().isoformat(timespec="seconds")


def get_attendance(course_id: Optional[int] = None, teacher_account_id: Optional[int] = None) -> List[Dict]:
    """Return attendance rows joined with user + course info.

    Optional filters:
      - course_id: restrict to one course
      - teacher_account_id: restrict to students assigned to that teacher (via enrollments)
    """
    conn = _get_conn()
    cur = conn.cursor()

    sql = """
        SELECT
            a.id,
            a.student_uid,
            u.name,
            u.email,
            a.course_id,
            c.code AS course_code,
            c.name AS course_name,
            a.date,
            a.sign_in_time,
            a.sign_out_time,
            a.duration,
            a.status
        FROM attendance a
        JOIN users   u ON u.student_uid = a.student_uid
        JOIN courses c ON c.id          = a.course_id
    """
    params = []
    where = []
    if teacher_account_id is not None:
        sql += "\n        JOIN enrollments e ON e.student_uid = a.student_uid AND e.course_id = a.course_id"
        where.append("e.teacher_account_id = ?")
        params.append(int(teacher_account_id))
    if course_id is not None:
        where.append("a.course_id = ?")
        params.append(int(course_id))

    if where:
        sql += "\n        WHERE " + " AND ".join(where)

    sql += "\n        ORDER BY a.date DESC, a.sign_in_time DESC;"

    cur.execute(sql, params)
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


def sign_in_student(student_uid: str, course_id: int) -> None:
    """Record sign-in for a student in a course for today."""
    conn = _get_conn()
    cur = conn.cursor()
    today = _today_str()

    cur.execute(
        """
        SELECT id FROM attendance
        WHERE student_uid = ? AND course_id = ? AND date = ?
          AND sign_in_time IS NOT NULL
          AND sign_out_time IS NULL
        ORDER BY id DESC
        LIMIT 1;
        """,
        (student_uid, course_id, today),
    )
    row = cur.fetchone()
    if row:
        conn.close()
        return

    now_time = _now_time_str()
    now_full = datetime.now().isoformat(timespec="seconds")

    cur.execute(
        """
        INSERT INTO attendance(
            student_uid, course_id, date,
            sign_in_time, sign_out_time, duration, status, created_at
        )
        VALUES (?, ?, ?, ?, NULL, NULL, 'Present', ?);
        """,
        (student_uid, course_id, today, now_time, now_full),
    )
    conn.commit()
    conn.close()


def sign_out_student(student_uid: str, course_id: int) -> None:
    """Sign out the latest open attendance record (no sign_out_time)."""
    conn = _get_conn()
    cur = conn.cursor()

    cur.execute(
        """
        SELECT id, date, sign_in_time
        FROM attendance
        WHERE student_uid = ?
          AND course_id   = ?
          AND sign_in_time IS NOT NULL
          AND sign_out_time IS NULL
        ORDER BY date DESC, sign_in_time DESC
        LIMIT 1;
        """,
        (student_uid, course_id),
    )
    row = cur.fetchone()
    if not row:
        conn.close()
        return

    att_id = row["id"]
    date_str = row["date"]
    sin_str = row["sign_in_time"]

    try:
        dt_in = datetime.fromisoformat(f"{date_str}T{sin_str}")
    except Exception:
        dt_in = datetime.now()

    dt_out = datetime.now()
    duration_minutes = (dt_out - dt_in).total_seconds() / 60.0
    sign_out_time = dt_out.time().isoformat(timespec="seconds")

    cur.execute(
        """
        UPDATE attendance
        SET sign_out_time = ?,
            duration      = ?,
            status        = 'Present'
        WHERE id = ?;
        """,
        (sign_out_time, duration_minutes, att_id),
    )
    conn.commit()
    conn.close()


# ---------------- per-course overview for View Data ----------------

def get_course_attendance_overview(course_id: int, date: Optional[str] = None, teacher_account_id: Optional[int] = None) -> List[Dict]:
    """Return one row per enrolled student with latest (or date-filtered) attendance.

    If teacher_account_id is provided, only students assigned to that teacher are included
    (based on enrollments.teacher_account_id).
    """
    conn = _get_conn()
    cur = conn.cursor()

    # Build WHERE clause for enrollments
    where = ["e.course_id = ?"]
    params: List = [int(course_id)]
    if teacher_account_id is not None:
        where.append("e.teacher_account_id = ?")
        params.append(int(teacher_account_id))

    where_sql = " AND ".join(where)

    if date:
        sql = f"""
        SELECT
            u.student_uid,
            u.name,
            u.email,
            a.date,
            a.sign_in_time,
            a.sign_out_time,
            a.duration,
            COALESCE(a.status, 'Absent') AS status
        FROM enrollments e
        JOIN users u
          ON u.student_uid = e.student_uid
        LEFT JOIN attendance a
          ON a.course_id   = e.course_id
         AND a.student_uid = e.student_uid
         AND a.date        = ?
        WHERE {where_sql}
        ORDER BY u.student_uid;
        """
        # date goes first in this query
        cur.execute(sql, [date] + params)
    else:
        sql = f"""
        SELECT
            u.student_uid,
            u.name,
            u.email,
            a.date,
            a.sign_in_time,
            a.sign_out_time,
            a.duration,
            COALESCE(a.status, 'Absent') AS status
        FROM enrollments e
        JOIN users u
          ON u.student_uid = e.student_uid
        LEFT JOIN attendance a
          ON a.id = (
              SELECT at2.id
              FROM attendance at2
              WHERE at2.course_id   = e.course_id
                AND at2.student_uid = e.student_uid
              ORDER BY at2.date DESC, at2.sign_in_time DESC
              LIMIT 1
          )
        WHERE {where_sql}
        ORDER BY u.student_uid;
        """
        cur.execute(sql, params)

    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


# ---------------- SMTP email helpers ----------------

def _get_smtp_settings() -> Optional[Dict]:
    """Read SMTP configuration from environment variables.

    Required env vars:
        ATTENDANCE_SMTP_HOST
        ATTENDANCE_SMTP_PORT
        ATTENDANCE_SMTP_USER
        ATTENDANCE_SMTP_PASS
    Optional:
        ATTENDANCE_EMAIL_FROM  (defaults to ATTENDANCE_SMTP_USER)
        ATTENDANCE_SMTP_USE_SSL ("1"/"true" to force SMTP_SSL; otherwise STARTTLS is used)

    If any required value is missing, returns None (so the system only *logs* emails).
    """
    host = (os.getenv("ATTENDANCE_SMTP_HOST") or "").strip()
    port_raw = (os.getenv("ATTENDANCE_SMTP_PORT") or "").strip()
    user = (os.getenv("ATTENDANCE_SMTP_USER") or "").strip()
    password = (os.getenv("ATTENDANCE_SMTP_PASS") or "").strip()
    from_email = (os.getenv("ATTENDANCE_EMAIL_FROM") or user).strip()

    try:
        port = int(port_raw) if port_raw else 0
    except ValueError:
        port = 0

    if not host or not port or not user or not password or not from_email:
        return None

    use_ssl = (os.getenv("ATTENDANCE_SMTP_USE_SSL") or "").strip().lower() in ("1", "true", "yes")
    if port == 465:
        use_ssl = True

    return {
        "host": host,
        "port": port,
        "user": user,
        "pass": password,
        "from": from_email,
        "use_ssl": use_ssl,
    }


def _send_email_smtp(*, to_email: str, subject: str, body: str, smtp: Dict) -> Tuple[bool, Optional[str]]:
    """Send one email using SMTP settings returned by _get_smtp_settings()."""
    msg = EmailMessage()
    msg["From"] = smtp["from"]
    msg["To"] = to_email
    msg["Subject"] = subject
    msg.set_content(body)

    context = ssl.create_default_context()
    try:
        if smtp.get("use_ssl"):
            with smtplib.SMTP_SSL(smtp["host"], int(smtp["port"]), context=context, timeout=30) as server:
                server.login(smtp["user"], smtp["pass"])
                server.send_message(msg)
        else:
            with smtplib.SMTP(smtp["host"], int(smtp["port"]), timeout=30) as server:
                server.ehlo()
                server.starttls(context=context)
                server.ehlo()
                server.login(smtp["user"], smtp["pass"])
                server.send_message(msg)
        return True, None
    except Exception as e:
        return False, str(e)


# ---------------- absence + email helper ----------------

def mark_absences_and_send_emails(course_id: int, date: Optional[str] = None) -> Dict[str, int]:
    """Insert 'Absent' records for missing students.

    Email behavior:
    - If SMTP env vars are configured, send the email and log status='sent' or 'failed'.
    - Otherwise, only log status='logged' (for demo/testing without SMTP).

    Returns counts: {"absent_marked": X, "sent": Y, "logged": Z, "failed": K}
    """
    if date is None:
        date = _today_str()

    smtp = _get_smtp_settings()
    course = get_course_by_id(course_id)
    course_label = f"{course['code']} - {course['name']}" if course else f"Course #{course_id}"

    conn = _get_conn()
    cur = conn.cursor()
    email_cols = _get_table_columns(conn, "email_notifications")

    cur.execute(
        """
        SELECT u.student_uid, u.email, u.name
        FROM enrollments e
        JOIN users u ON u.student_uid = e.student_uid
        WHERE e.course_id = ?;
        """,
        (course_id,),
    )
    enrolled = cur.fetchall()

    absent_marked = 0
    sent_count = 0
    logged_count = 0
    failed_count = 0
    now_full = datetime.now().isoformat(timespec="seconds")

    for row in enrolled:
        sid = row["student_uid"]
        email = row["email"]
        name = row["name"]

        cur.execute(
            """
            SELECT 1 FROM attendance
            WHERE student_uid = ? AND course_id = ? AND date = ?
            LIMIT 1;
            """,
            (sid, course_id, date),
        )
        if cur.fetchone() is not None:
            continue

        cur.execute(
            """
            INSERT INTO attendance(
                student_uid, course_id, date,
                sign_in_time, sign_out_time, duration, status, created_at
            )
            VALUES (?, ?, ?, NULL, NULL, NULL, 'Absent', ?);
            """,
            (sid, course_id, date, now_full),
        )

        subject = f"Absence Notification - {course_label} ({date})"
        body = (
            f"Dear {name},\n\n"
            f"Our system detected that you were absent from {course_label} on {date}.\n"
            f"If you believe this is a mistake, please contact your instructor/HR.\n"
        )

        status = "logged"
        err: Optional[str] = None
        if smtp is not None:
            ok, err = _send_email_smtp(
                to_email=email,
                subject=subject,
                body=body,
                smtp=smtp,
            )
            if ok:
                status = "sent"
                sent_count += 1
            else:
                status = "failed"
                failed_count += 1
        else:
            logged_count += 1

        _insert_email_notification(cur, email_cols, sid, course_id, email, subject, body, now_full, status, err)
        absent_marked += 1

    conn.commit()
    conn.close()
    return {
        "absent_marked": absent_marked,
        "sent": sent_count,
        "logged": logged_count,
        "failed": failed_count,
    }


def auto_sign_out_open_attendance(course_id: int, date: Optional[str] = None) -> int:
    """Auto sign-out any students who signed-in but have no sign-out time yet."""
    if date is None:
        date = _today_str()

    conn = _get_conn()
    cur = conn.cursor()

    cur.execute(
        """
        SELECT id, date, sign_in_time
        FROM attendance
        WHERE course_id = ?
          AND date = ?
          AND sign_in_time IS NOT NULL
          AND sign_out_time IS NULL
        ORDER BY id ASC;
        """,
        (course_id, date),
    )
    rows = cur.fetchall()
    if not rows:
        conn.close()
        return 0

    dt_out = datetime.now()
    sign_out_time = dt_out.time().isoformat(timespec="seconds")

    count = 0
    for r in rows:
        att_id = r["id"]
        date_str = r["date"]
        sin_str = r["sign_in_time"]
        try:
            dt_in = datetime.fromisoformat(f"{date_str}T{sin_str}")
        except Exception:
            dt_in = dt_out
        duration_minutes = (dt_out - dt_in).total_seconds() / 60.0
        cur.execute(
            """
            UPDATE attendance
            SET sign_out_time = ?,
                duration      = ?,
                status        = 'Present'
            WHERE id = ?;
            """,
            (sign_out_time, duration_minutes, att_id),
        )
        count += 1

    conn.commit()
    conn.close()
    return count


def mark_open_signins_as_absent_and_notify(course_id: int, date: Optional[str] = None) -> Dict[str, int]:
    """Mark as Absent any students who signed-in but did NOT sign-out.

    Policy (anti-proxy): attendance is valid only when BOTH sign-in and sign-out exist.
    Therefore, any attendance record for (course_id, date) where:
        sign_in_time IS NOT NULL AND sign_out_time IS NULL
    will be treated as Absent, and an absence email will be sent/logged.

    Returns counts:
        {"open_marked_absent": X, "sent": Y, "logged": Z, "failed": K}
    """
    if date is None:
        date = _today_str()

    conn = _get_conn()
    cur = conn.cursor()
    email_cols = _get_table_columns(conn, "email_notifications")

    # course label for email content
    cur.execute("SELECT code, name FROM courses WHERE id = ? LIMIT 1;", (course_id,))
    c = cur.fetchone()
    course_label = f"{c['code']} - {c['name']}" if c else f"Course #{course_id}"

    smtp = _get_smtp_settings()

    # Select "open" attendance rows for that date that are not already Absent
    cur.execute(
        """
        SELECT a.id, a.student_uid, a.sign_in_time, u.email, u.name
        FROM attendance a
        JOIN users u ON u.student_uid = a.student_uid
        WHERE a.course_id = ?
          AND a.date = ?
          AND a.sign_in_time IS NOT NULL
          AND a.sign_out_time IS NULL
          AND COALESCE(a.status, '') <> 'Absent'
        ORDER BY a.id DESC;
        """,
        (course_id, date),
    )
    rows = cur.fetchall()

    open_marked = 0
    sent = logged = failed = 0
    now_full = datetime.now().isoformat(timespec="seconds")

    for r in rows:
        att_id = r["id"]
        sid = r["student_uid"]
        email = r["email"]
        name = r["name"]
        sign_in_time = r["sign_in_time"] or ""

        # Update record: treat as Absent (keep sign_in_time for audit)
        cur.execute(
            """
            UPDATE attendance
            SET status = 'Absent',
                duration = NULL
            WHERE id = ?;
            """,
            (att_id,),
        )
        open_marked += 1

        subject = f"Absence Notification - {course_label} ({date})"
        body = (
            f"Dear {name},\n\n"
            f"Our system detected that your attendance for {course_label} on {date} is NOT valid.\n"
            f"A sign-in was recorded at {sign_in_time}, but no sign-out was recorded before the session ended.\n"
            f"For integrity (anti-proxy), the system marks this as Absent.\n\n"
            f"If you believe this is a mistake, please contact your instructor/HR.\n"
        )

        # Avoid duplicate emails if finalize is pressed multiple times
        where, params = _email_notif_where_clause(email_cols, sid, course_id, email, subject)

        if where:

            cur.execute(f"SELECT 1 FROM email_notifications WHERE {where} LIMIT 1;", params)

            if cur.fetchone() is not None:

                continue

        # Send or log email
        if smtp is None:
            _insert_email_notification(cur, email_cols, sid, course_id, email, subject, body, now_full, "logged", None)
            logged += 1
        else:
            ok, err = _send_email_smtp(to_email=email, subject=subject, body=body, smtp=smtp)
            _insert_email_notification(cur, email_cols, sid, course_id, email, subject, body, now_full, "sent" if ok else "failed", err)
            if ok:
                sent += 1
            else:
                failed += 1

    conn.commit()
    conn.close()

    return {
        "open_marked_absent": open_marked,
        "sent": sent,
        "logged": logged,
        "failed": failed,
    }


def finalize_course_session(course_id: int, date: Optional[str] = None) -> Dict[str, int]:
    """Finalize a course session (anti-proxy policy).

    Rules applied when the teacher ends the session:
    1) Any student who signed-in but did NOT sign-out is treated as Absent (and notified).
    2) Any enrolled student with no attendance record for that date is marked Absent (and notified).

    Returns counts:
        {
          "open_marked_absent": X,
          "absent_marked": Y,
          "sent": A,
          "logged": B,
          "failed": C
        }
    """
    if date is None:
        date = _today_str()

    open_res = mark_open_signins_as_absent_and_notify(course_id, date)
    abs_res = mark_absences_and_send_emails(course_id, date)

    return {
        "open_marked_absent": int(open_res.get("open_marked_absent", 0)),
        "absent_marked": int(abs_res.get("absent_marked", 0)),
        "sent": int(open_res.get("sent", 0)) + int(abs_res.get("sent", 0)),
        "logged": int(open_res.get("logged", 0)) + int(abs_res.get("logged", 0)),
        "failed": int(open_res.get("failed", 0)) + int(abs_res.get("failed", 0)),
    }



def clear_attendance_for_course_date(course_id: int, date: str) -> int:
    """Delete ALL attendance rows for a given course/date.

    This is intended for demo/reset workflows (e.g., after exporting).
    If date is empty/None, defaults to today (the UI leaves it blank for today).
    Returns the number of rows deleted.
    """
    if not date:
        date = _today_str()
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) AS n FROM attendance WHERE course_id = ? AND date = ?;", (course_id, date))
    row = cur.fetchone()
    to_delete = int(row[0]) if row else 0
    cur.execute("DELETE FROM attendance WHERE course_id = ? AND date = ?;", (course_id, date))
    conn.commit()
    conn.close()
    return to_delete

# ---------------- lookup helpers ----------------

def get_latest_attendance_for_student_course(student_uid: str, course_id: int, date: Optional[str] = None) -> Optional[Dict]:
    """Return the latest attendance row for a student in a specific course (optionally for a specific date)."""
    conn = _get_conn()
    cur = conn.cursor()
    if date:
        cur.execute(
            """
            SELECT date, sign_in_time, sign_out_time, duration, status
            FROM attendance
            WHERE student_uid = ? AND course_id = ? AND date = ?
            ORDER BY id DESC
            LIMIT 1;
            """,
            (student_uid, course_id, date),
        )
    else:
        cur.execute(
            """
            SELECT date, sign_in_time, sign_out_time, duration, status
            FROM attendance
            WHERE student_uid = ? AND course_id = ?
            ORDER BY date DESC, sign_in_time DESC, id DESC
            LIMIT 1;
            """,
            (student_uid, course_id),
        )
    row = cur.fetchone()
    conn.close()
    return dict(row) if row else None