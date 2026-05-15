"""
AI Face Attendance System - Enhanced UI + Login (Admin/Teacher/Student)

RBAC:
- Admin   -> all tabs
- Teacher -> Run Attendance tab
- Student -> View Data tab (records only)

Important: uses ONE Tk root. Extra windows (login) are Toplevel windows.
Creating multiple Tk() roots can cause the app to not show or behave oddly.
"""

import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import csv
import datetime
import os
# Write crash logs next to this script (stable path)
LOG_PATH = os.path.join(os.path.dirname(__file__), "startup_error.log")

import traceback
from typing import Dict, List, Optional

# Optional: hide pkg_resources deprecation warning from face_recognition_models
import warnings
warnings.filterwarnings(
    "ignore",
    message=r"pkg_resources is deprecated as an API.*",
    category=UserWarning,
)

# Try to import ttkbootstrap, fall back to standard ttk if not available
try:
    import ttkbootstrap as tb
    USE_BOOTSTRAP = True
except Exception:
    USE_BOOTSTRAP = False

from registration import register_user
from attendance import run_attendance_system
from database import (
    get_users, get_attendance, get_courses, add_course,
    enroll_student_in_course, sign_out_student,
    mark_absences_and_send_emails, is_student_enrolled_in_course,
    finalize_course_session,
    get_course_attendance_overview, get_courses_for_student, get_user_by_uid,
    create_account, authenticate, get_latest_attendance_for_student_course,
    get_teacher_courses, set_teacher_courses, get_account_id, get_active_teachers, get_students_for_teacher,
    clear_attendance_for_course_date,
    init_db, ensure_default_admin, ensure_default_teacher,
)

# UI constants
PADDING_LARGE = 16
PADDING_MEDIUM = 12
PADDING_SMALL = 8

FONT_HEADING = ("Segoe UI", 14, "bold")
FONT_SUBHEADING = ("Segoe UI", 11, "bold")
FONT_LABEL = ("Segoe UI", 10)
FONT_SMALL = ("Segoe UI", 9)

COLOR_SUCCESS = "#10B981"
COLOR_WARNING = "#F59E0B"
COLOR_ERROR = "#EF4444"
COLOR_INFO = "#3B82F6"


class LoginDialog(tk.Toplevel):
    """Modal login dialog. Returns auth context dict on success."""
    def __init__(self, master: tk.Tk):
        super().__init__(master)
        self.title("Login — AI Face Attendance")
        self.resizable(False, False)

        self.result: Optional[dict] = None
        self.role_var = tk.StringVar(value="admin")
        self.user_var = tk.StringVar()
        self.pass_var = tk.StringVar()

        frm = ttk.Frame(self, padding=14)
        frm.grid(row=0, column=0, sticky="nsew")

        ttk.Label(frm, text="Role:").grid(row=0, column=0, sticky="w", pady=6)
        ttk.Combobox(frm, textvariable=self.role_var, state="readonly",
                     values=["admin", "teacher", "student"], width=18).grid(row=0, column=1, sticky="ew", pady=6)

        ttk.Label(frm, text="Username (Student ID for students):").grid(row=1, column=0, sticky="w", pady=6)
        ttk.Entry(frm, textvariable=self.user_var, width=28).grid(row=1, column=1, sticky="ew", pady=6)

        ttk.Label(frm, text="Password:").grid(row=2, column=0, sticky="w", pady=6)
        ttk.Entry(frm, textvariable=self.pass_var, show="*", width=28).grid(row=2, column=1, sticky="ew", pady=6)

        ttk.Button(frm, text="Login", command=self._do_login).grid(
            row=3, column=0, columnspan=2, sticky="ew", pady=(10, 0)
        )
        ttk.Label(
            frm,
            text="Default admin: admin/admin123 | Default teacher: teacher/teacher123",
            font=("Segoe UI", 8),
            foreground="#6B7280"
        ).grid(row=4, column=0, columnspan=2, sticky="w", pady=(10, 0))

        frm.columnconfigure(1, weight=1)

        self.protocol("WM_DELETE_WINDOW", self._cancel)
        self.grab_set()
        self.transient(master)
        self.update_idletasks()
        self._center_on_parent(master)

    def _center_on_parent(self, parent: tk.Tk):
        try:
            px = parent.winfo_rootx()
            py = parent.winfo_rooty()
            pw = parent.winfo_width()
            ph = parent.winfo_height()
            w = self.winfo_width()
            h = self.winfo_height()
            x = px + (pw - w) // 2
            y = py + (ph - h) // 2
            self.geometry(f"+{x}+{y}")
        except Exception:
            pass

    def _cancel(self):
        self.result = None
        self.destroy()

    def _do_login(self):
        role = self.role_var.get().strip().lower()
        username = self.user_var.get().strip()
        password = self.pass_var.get().strip()

        if not username or not password:
            messagebox.showwarning("Missing", "Enter username and password.")
            return

        ctx = authenticate(username, password, role)
        if not ctx:
            messagebox.showerror("Login Failed", "Invalid credentials.")
            return

        if ctx["role"] == "student" and not ctx.get("student_uid"):
            messagebox.showerror("Account Error", "Student account is not linked to a student record.")
            return

        self.result = ctx
        self.destroy()


class CourseSelectDialog(tk.Toplevel):
    """
    Modal dialog: teacher must choose ONE active course for this session.
    courses: list of dicts with keys: id, code, name
    Returns selected course dict in .result, or None if cancelled.
    """
    def __init__(self, master: tk.Tk, courses: List[Dict]):
        super().__init__(master)
        self.title("Select Course")
        self.resizable(False, False)
        self.result: Optional[Dict] = None
        self.courses = courses or []

        self.transient(master)
        self.grab_set()

        root = ttk.Frame(self, padding=PADDING_LARGE)
        root.pack(fill="both", expand=True)

        ttk.Label(root, text="Choose one course for this session:", font=FONT_SUBHEADING).pack(anchor="w")

        # Combobox instead of listbox (cleaner UX)
        self.course_var = tk.StringVar()
        values = [f"{c['code']} — {c['name']}" for c in self.courses]

        self.combo = ttk.Combobox(
            root,
            textvariable=self.course_var,
            state="readonly",
            values=values,
            font=FONT_LABEL,
            width=52,
        )
        self.combo.pack(fill="x", pady=(PADDING_SMALL, PADDING_MEDIUM))

        if values:
            self.course_var.set(values[0])

        btns = ttk.Frame(root)
        btns.pack(fill="x")
        ttk.Button(btns, text="Cancel", command=self._cancel).pack(side="right")
        ttk.Button(btns, text="Continue", command=self._ok).pack(side="right", padx=(0, PADDING_SMALL))

        self.bind("<Return>", lambda _e: self._ok())
        self.bind("<Escape>", lambda _e: self._cancel())

        self.update_idletasks()
        self._center_on_parent(master)

    def _center_on_parent(self, parent: tk.Tk):
        try:
            px = parent.winfo_rootx()
            py = parent.winfo_rooty()
            pw = parent.winfo_width()
            ph = parent.winfo_height()
            w = self.winfo_width()
            h = self.winfo_height()
            x = px + (pw - w) // 2
            y = py + (ph - h) // 2
            self.geometry(f"+{x}+{y}")
        except Exception:
            pass

    def _ok(self):
        key = (self.course_var.get() or "").strip()
        if not key:
            messagebox.showwarning("Select a course", "Please choose a course to continue.")
            return

        try:
            idx = self.combo.current()
        except Exception:
            idx = -1

        if idx is None or idx < 0:
            idx = next((i for i, c in enumerate(self.courses) if f"{c['code']} — {c['name']}" == key), -1)

        if idx < 0 or idx >= len(self.courses):
            messagebox.showwarning("Select a course", "Please choose a valid course.")
            return

        self.result = self.courses[int(idx)]
        self.destroy()

    def _cancel(self):
        self.result = None
        self.destroy()

class AttendanceGUI(tb.Window if USE_BOOTSTRAP else tk.Tk):
    def __init__(self):
        if USE_BOOTSTRAP:
            super().__init__(themename="flatly")
        else:
            super().__init__()

        self.title("AI Face Attendance — Courses")
        self.geometry("1400x900")
        self.minsize(1000, 700)
        self.protocol("WM_DELETE_WINDOW", self.destroy)

        # Auth
        self.auth: Optional[dict] = None
        self.role: str = "guest"
        self.username: str = ""
        self.logged_student_uid: Optional[str] = None
        self.account_id: Optional[int] = None
        # Teacher session course (selected at login if teacher)
        self.active_course_id: Optional[int] = None
        self.active_course_key: str = ""
        self.active_course_name: str = ""

        # Data
        self.users_map: Dict[str, str] = {}
        self.courses_map: Dict[str, int] = {}
        self._reg_course_ids: List[int] = []
        self.att_thread: Optional[threading.Thread] = None
        self.data_selected_course_id: Optional[int] = None
        if self.role in ("teacher", "admin"):
            self._toggle_records_auto_refresh()



        # Auto-refresh jobs (live record / records tab)
        self._live_job = None
        self._records_job = None
        self.live_auto_var = tk.BooleanVar(value=True)
        self.records_auto_var = tk.BooleanVar(value=True)
        self.refresh_ms = 3000
        # Start UI + login
        self._create_status_bar()     # status first
        if not self._login_or_exit(exit_on_cancel=True):  # login modal
            return
        self._create_header()
        # Clear stale widget handles (they may point to destroyed Tk commands)

        for _attr in ("course_combo", "user_combo", "reg_course_list", "users_tree",

                      "course_overview_tree", "course_record_tree", "live_record_tree"):

            try:

                setattr(self, _attr, None)

            except Exception:

                pass



        self._create_tabs()

        # Initial loads
        if self.role in ("admin", "teacher"):
            self._refresh_courses()
            if self.role == "admin":
                self._refresh_teachers_filtered()
        elif self.role == "student":
            self._refresh_courses_for_student()

        if hasattr(self, "data_frame"):
            if self.role == "admin":
                self._load_users()
                self._load_courses_overview()
            elif self.role == "student":
                try:
                    self._load_student_records()
                except Exception:
                    pass

    # ---------------- login ----------------

    def _login_or_exit(self, exit_on_cancel: bool = True) -> bool:
        """
        Login modal. For teachers, enforce course assignment and choose ONE active course per session.
        """
        while True:
            dlg = LoginDialog(self)
            self.wait_window(dlg)

            if not dlg.result:
                if exit_on_cancel:
                    self.destroy()
                return False

            self.auth = dlg.result
            self.role = (self.auth.get("role", "guest") or "guest").strip().lower()
            self.username = self.auth.get("username", "")
            self.logged_student_uid = self.auth.get("student_uid")
            self.account_id = self.auth.get("account_id")

            # Teacher: load assigned courses and force selection of ONE course (session-scoped)
            if self.role == "teacher":
                try:
                    if self.account_id is None:
                        # Defensive: if DB didn't return it, look it up.
                        self.account_id = get_account_id(self.username, "teacher")
                    assigned = get_teacher_courses(int(self.account_id)) if self.account_id else []
                except Exception as e:
                    messagebox.showerror("Login Error", f"Could not load teacher courses.\n\n{e}")
                    continue

                if not assigned:
                    messagebox.showerror(
                        "No Courses Assigned",
                        "No courses are assigned to this teacher account.\n\nPlease contact the admin to assign course(s)."
                    )
                    # let them try a different login
                    continue

                if len(assigned) == 1:
                    chosen = assigned[0]
                else:
                    sel = CourseSelectDialog(self, assigned)
                    self.wait_window(sel)
                    if not sel.result:
                        # treat as cancel => allow retry login
                        continue
                    chosen = sel.result

                self.active_course_id = int(chosen["id"])
                self.active_course_key = f"{chosen['code']} — {chosen['name']}"
                self.active_course_name = f"{chosen['code']} — {chosen['name']}"

            else:
                # Non-teacher session does not lock a course here
                self.active_course_id = None
                self.active_course_key = ""
                self.active_course_name = ""

            self._update_status(f"Logged in as {self.role.upper()} — {self.username}", COLOR_SUCCESS)
            return True

    def _logout(self):
        """Log out and show login dialog again (without closing the app)."""
        # Avoid switching users while camera thread is running
        if self.att_thread is not None and self.att_thread.is_alive():
            messagebox.showwarning(
                "Session Running",
                "Stop the camera session first (press 'q' in the OpenCV window) before logging out."
            )
            return

        prev = self.auth.copy() if isinstance(self.auth, dict) else None

        # Re-login. Cancel keeps the current session.
        ok = self._login_or_exit(exit_on_cancel=False)
        if not ok:
            if prev:
                self.auth = prev
                self.role = (prev.get("role", "guest") or "guest").strip().lower()
                self.username = prev.get("username", "")
                self.logged_student_uid = prev.get("student_uid")
            self._update_status("Logout canceled", COLOR_INFO)
            if hasattr(self, "user_info_label"):
                try:
                    self.user_info_label.config(text=f"Role: {self.role.upper()} | User: {self.username}")
                except Exception:
                    pass
            return

        # Update header info
        if hasattr(self, "user_info_label"):
            try:
                self.user_info_label.config(text=f"Role: {self.role.upper()} | User: {self.username}")
            except Exception:
                pass

                # Stop any auto-refresh loops
        self._cancel_auto_refresh_jobs()

        # Rebuild role-based tabs
        try:
            if hasattr(self, "notebook") and self.notebook is not None:
                self.notebook.destroy()
        except Exception:
            pass

        # Reset role-dependent state
        self.users_map = {}
        self.courses_map = {}
        self._reg_course_ids = []
        self.data_selected_course_id = None

        self._create_tabs()

        # Reload data based on new role
        # Reload data based on new role
        if self.role in ("admin", "teacher"):
            self._refresh_courses()
            if self.role == "admin":
                self._refresh_teachers_filtered()
        elif self.role == "student":
            self._refresh_courses_for_student()
        if hasattr(self, "data_frame"):
            if self.role == "admin":
                self._load_users()
                self._load_courses_overview()
            elif self.role == "student":
                try:
                    self._load_student_records()
                except Exception:
                    pass

        self._update_status(f"Switched to {self.role.upper()} — {self.username}", COLOR_SUCCESS)


    # ---------------- header/status ----------------
    def _create_header(self):
        # Keep references so we can update on logout
        self.header_frame = ttk.Frame(self)
        self.header_frame.pack(fill="x", padx=0, pady=0)

        title_frame = ttk.Frame(self.header_frame)
        title_frame.pack(fill="x", padx=PADDING_LARGE, pady=PADDING_MEDIUM)

        ttk.Label(
            title_frame,
            text="🎓 AI Face Attendance System",
            font=("Segoe UI", 16, "bold")
        ).pack(side="left")

        self.user_info_label = ttk.Label(
            title_frame,
            text=f"Role: {self.role.upper()} | User: {self.username}",
            font=FONT_SMALL
        )
        self.user_info_label.pack(side="left", padx=12)

        # Actions (right side). Pack logout first so it stays rightmost.
        ttk.Button(title_frame, text="🚪 Logout", command=self._logout).pack(side="right", padx=(PADDING_SMALL, 0))
        if USE_BOOTSTRAP:
            ttk.Button(title_frame, text="🌙 Dark Mode", command=self._toggle_theme).pack(side="right", padx=PADDING_SMALL)


    def _create_status_bar(self):
        status_frame = ttk.Frame(self)
        status_frame.pack(fill="x", side="bottom")
        self.status_label = ttk.Label(status_frame, text="✓ Starting...", font=FONT_SMALL)
        self.status_label.pack(side="left", padx=PADDING_LARGE, pady=PADDING_SMALL)
        ttk.Label(status_frame, text=f"Today: {datetime.datetime.now().strftime('%B %d, %Y')}", font=FONT_SMALL).pack(side="right", padx=PADDING_LARGE, pady=PADDING_SMALL)


    def _widget_alive(self, w) -> bool:
        """
        True if 'w' is a real Tk widget that still exists.
        Fixes: _tkinter.TclError: invalid command name "...!combobox"
        that happens when we keep a Python reference after destroying/rebuilding tabs.
        """
        try:
            return w is not None and hasattr(w, "winfo_exists") and bool(w.winfo_exists())
        except Exception:
            return False


    def _update_status(self, message: str, color: Optional[str] = None):
        try:
            self.status_label.config(text=f"✓ {message}")
        except Exception:
            pass

    # ---------------- tabs ----------------
    def _create_tabs(self):
        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill="both", expand=True, padx=PADDING_LARGE, pady=PADDING_MEDIUM)

        allowed = {
            "admin":   ["register", "attendance", "data"],
            "teacher": ["attendance", "data"],
            "student": ["data"],
        }.get(self.role, ["attendance"])

        if "register" in allowed:
            self.register_frame = ttk.Frame(self.notebook)
            self.notebook.add(self.register_frame, text="📝 Register User")
            self._build_register_tab()

        if "attendance" in allowed:
            self.attendance_frame = ttk.Frame(self.notebook)
            self.notebook.add(self.attendance_frame, text="📷 Run Attendance")
            self._build_attendance_tab()

        if "data" in allowed:
            self.data_frame = ttk.Frame(self.notebook)
            self.notebook.add(self.data_frame, text="📊 View Data")
            self._build_data_tab()

        # Select the first visible tab (role-based landing page)
        try:
            if self.role == "teacher" and hasattr(self, "attendance_frame"):
                self.notebook.select(self.attendance_frame)
            elif self.role == "student" and hasattr(self, "data_frame"):
                self.notebook.select(self.data_frame)
            elif self.role == "admin" and hasattr(self, "register_frame"):
                self.notebook.select(self.register_frame)
        except Exception:
            pass

    # ---------------- register (admin) ----------------
    def _build_register_tab(self):
        frm = self.register_frame
        container = ttk.Frame(frm, padding=PADDING_LARGE)
        container.pack(fill="both", expand=True)

        form_section = ttk.Labelframe(container, text="User Registration", padding=PADDING_LARGE)
        form_section.pack(side="left", fill="both", expand=True, padx=(0, PADDING_MEDIUM))

        self.name_var = tk.StringVar()
        self.email_var = tk.StringVar()
        self.student_id_var = tk.StringVar()
        self.student_pass_var = tk.StringVar()  # student login password (optional)
        self.folder_var = tk.StringVar()

        self.teacher_var = tk.StringVar()
        self.teachers_map = {}  # display -> teacher_account_id

        def field(row, label, var):
            ttk.Label(form_section, text=label, font=FONT_LABEL).grid(row=row, column=0, sticky="w", pady=PADDING_SMALL)
            ttk.Entry(form_section, textvariable=var, font=FONT_LABEL).grid(row=row, column=1, sticky="ew", pady=PADDING_SMALL, padx=(PADDING_SMALL, 0))

        field(0, "Full Name:", self.name_var)
        field(1, "Email:", self.email_var)
        field(2, "Student ID:", self.student_id_var)
        field(3, "Student Password:", self.student_pass_var)

        # Teacher selection (required)
        ttk.Label(form_section, text="Teacher:", font=FONT_LABEL).grid(row=4, column=0, sticky="w", pady=PADDING_SMALL)
        self.teacher_combo = ttk.Combobox(
            form_section,
            textvariable=self.teacher_var,
            state="readonly",
            font=FONT_LABEL
        )
        self.teacher_combo.grid(row=4, column=1, sticky="ew", pady=PADDING_SMALL, padx=(PADDING_SMALL, 0))
        try:
            self.teacher_combo.bind("<<ComboboxSelected>>", lambda _e: self._on_teacher_combo_selected())
        except Exception:
            pass

        # Teachers list (separate from course selection)
        teachers_box = ttk.Labelframe(form_section, text="Teachers (click to select)", padding=PADDING_SMALL)
        teachers_box.grid(row=5, column=0, columnspan=2, sticky="ew", pady=(PADDING_SMALL, PADDING_MEDIUM))
        teachers_box.columnconfigure(0, weight=1)

        t_list_frame = ttk.Frame(teachers_box)
        t_list_frame.grid(row=0, column=0, sticky="nsew")
        t_list_frame.columnconfigure(0, weight=1)
        t_list_frame.rowconfigure(0, weight=1)

        self.teacher_list = tk.Listbox(
            t_list_frame,
            selectmode="browse",
            font=FONT_LABEL,
            exportselection=False,
            height=5
        )
        self.teacher_list.grid(row=0, column=0, sticky="nsew")
        t_sb = ttk.Scrollbar(t_list_frame, orient="vertical", command=self.teacher_list.yview)
        t_sb.grid(row=0, column=1, sticky="ns")
        self.teacher_list.config(yscrollcommand=t_sb.set)

        try:
            self.teacher_list.bind("<<ListboxSelect>>", lambda _e: self._on_teacher_list_select())
        except Exception:
            pass

        ttk.Button(
            teachers_box,
            text="Refresh Teachers",
            command=self._refresh_teachers_filtered
        ).grid(row=1, column=0, sticky="ew", pady=(PADDING_SMALL, 0))

        ttk.Label(form_section, text="Image Folder:", font=FONT_LABEL).grid(row=6, column=0, sticky="w", pady=PADDING_SMALL)
        folder_row = ttk.Frame(form_section)
        folder_row.grid(row=6, column=1, sticky="ew", pady=PADDING_SMALL, padx=(PADDING_SMALL, 0))
        ttk.Entry(folder_row, textvariable=self.folder_var, font=FONT_LABEL).pack(side="left", fill="x", expand=True)
        ttk.Button(folder_row, text="Browse…", command=self._choose_folder).pack(side="right", padx=(PADDING_SMALL, 0))

        btn_row = ttk.Frame(form_section)
        btn_row.grid(row=7, column=0, columnspan=2, sticky="ew", pady=(PADDING_MEDIUM, 0))
        ttk.Button(btn_row, text="📸 Register User & Enroll", command=self._do_register).pack(fill="x")
        ttk.Button(btn_row, text="🔄 Clear", command=self._clear_form).pack(fill="x", pady=(PADDING_SMALL, 0))

        form_section.columnconfigure(1, weight=1)


        right = ttk.Labelframe(container, text="Courses", padding=PADDING_LARGE)
        right.pack(side="right", fill="both", expand=True)

        # Use grid inside the "Courses" panel so the course list can grow/shrink and
        # the bottom account-creation buttons stay visible on smaller screens.
        right.columnconfigure(0, weight=1)
        right.rowconfigure(1, weight=1)

        ttk.Label(right, text="Select Courses (Multi-select):", font=FONT_SUBHEADING).grid(row=0, column=0, sticky="w")

        list_frame = ttk.Frame(right)
        list_frame.grid(row=1, column=0, sticky="nsew", pady=(PADDING_SMALL, PADDING_MEDIUM))
        list_frame.columnconfigure(0, weight=1)
        list_frame.rowconfigure(0, weight=1)

        self.reg_course_list = tk.Listbox(
            list_frame,
            selectmode="extended",
            font=FONT_LABEL,
            exportselection=False
        )
        self.reg_course_list.grid(row=0, column=0, sticky="nsew")

        sb = ttk.Scrollbar(list_frame, orient="vertical", command=self.reg_course_list.yview)
        sb.grid(row=0, column=1, sticky="ns")
        self.reg_course_list.config(yscrollcommand=sb.set)

        # Keep teachers list in sync with selected courses
        try:
            self.reg_course_list.bind("<<ListboxSelect>>", lambda _e: self._refresh_teachers_filtered())
        except Exception:
            pass

        add_course_box = ttk.Labelframe(right, text="Add New Course", padding=PADDING_MEDIUM)
        add_course_box.grid(row=2, column=0, sticky="ew")

        self.reg_new_code = tk.StringVar()
        self.reg_new_name = tk.StringVar()
        ttk.Label(add_course_box, text="Course Code:", font=FONT_LABEL).pack(anchor="w")
        ttk.Entry(add_course_box, textvariable=self.reg_new_code, font=FONT_LABEL).pack(fill="x", pady=(0, PADDING_SMALL))
        ttk.Label(add_course_box, text="Course Name:", font=FONT_LABEL).pack(anchor="w")
        ttk.Entry(add_course_box, textvariable=self.reg_new_name, font=FONT_LABEL).pack(fill="x", pady=(0, PADDING_SMALL))

        row_btn = ttk.Frame(add_course_box)
        row_btn.pack(fill="x")
        ttk.Button(row_btn, text="Add Course", command=self._reg_add_course).pack(side="left", fill="x", expand=True, padx=(0, 4))
        ttk.Button(row_btn, text="Refresh", command=self._refresh_courses).pack(side="right", fill="x", expand=True, padx=(4, 0))

        # Account creation for staff
        acct_box = ttk.Labelframe(right, text="Create Teacher/Admin Account", padding=PADDING_MEDIUM)
        acct_box.grid(row=3, column=0, sticky="ew", pady=(PADDING_MEDIUM, 0))
        acct_box.columnconfigure(1, weight=1)

        self.new_role_var = tk.StringVar(value="teacher")
        self.new_user_var = tk.StringVar()
        self.new_pass_var = tk.StringVar()

        ttk.Label(acct_box, text="Role:", font=FONT_LABEL).grid(row=0, column=0, sticky="w", pady=(0, 6))
        ttk.Combobox(
            acct_box,
            textvariable=self.new_role_var,
            state="readonly",
            values=["teacher", "admin"],
            width=12
        ).grid(row=0, column=1, sticky="w", padx=(8, 0), pady=(0, 6))

        ttk.Label(acct_box, text="Username:", font=FONT_LABEL).grid(row=1, column=0, sticky="w", pady=(0, 6))
        ttk.Entry(acct_box, textvariable=self.new_user_var, font=FONT_LABEL).grid(row=1, column=1, sticky="ew", padx=(8, 0), pady=(0, 6))

        ttk.Label(acct_box, text="Password:", font=FONT_LABEL).grid(row=2, column=0, sticky="w", pady=(0, 8))
        ttk.Entry(acct_box, textvariable=self.new_pass_var, font=FONT_LABEL, show="*").grid(row=2, column=1, sticky="ew", padx=(8, 0), pady=(0, 8))

        # Teacher course assignment: admin selects course(s) from the main Courses list above.
        self.staff_courses_map: Dict[str, int] = {}
        self.staff_course_frame = ttk.Frame(acct_box)
        self.staff_course_frame.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(PADDING_SMALL, PADDING_SMALL))
        ttk.Label(
            self.staff_course_frame,
            text="Assign Courses to Teacher (select from Courses list above):",
            font=FONT_LABEL
        ).pack(anchor="w")
        ttk.Label(
            self.staff_course_frame,
            text="Tip: Select the teacher's course(s) from the 'Select Courses' list above (Ctrl/Shift for multi-select).",
            font=FONT_SMALL
        ).pack(anchor="w", pady=(2, 0))

        # Buttons (always visible)
        staff_btn_row = ttk.Frame(acct_box)
        staff_btn_row.grid(row=4, column=0, columnspan=2, sticky="ew", pady=(PADDING_SMALL, 0))
        staff_btn_row.columnconfigure(0, weight=1)
        staff_btn_row.columnconfigure(1, weight=1)
        ttk.Button(staff_btn_row, text="Create Account", command=self._create_staff_account).grid(row=0, column=0, sticky="ew")
        ttk.Button(staff_btn_row, text="Clear", command=self._clear_staff_form).grid(row=0, column=1, sticky="ew", padx=(PADDING_SMALL, 0))

        # show/hide based on role selection
        self._on_new_staff_role_changed()
        try:
            self.new_role_var.trace_add("write", lambda *_: self._on_new_staff_role_changed())
        except Exception:
            pass

        self._refresh_courses()
    def _refresh_teachers_filtered(self):
        # Refresh teacher list + combobox.
        # If courses are selected, prefer teachers who cover ALL selected courses.
        if not hasattr(self, "teacher_var"):
            return

        # Gather selected course ids
        required_course_ids = []
        try:
            if hasattr(self, "reg_course_list") and self._widget_alive(self.reg_course_list):
                for idx in self.reg_course_list.curselection():
                    try:
                        if idx < len(getattr(self, "_reg_course_ids", [])):
                            required_course_ids.append(int(self._reg_course_ids[idx]))
                    except Exception:
                        pass
        except Exception:
            required_course_ids = []

        # Load teachers
        try:
            teachers = get_active_teachers()
        except Exception:
            teachers = []

        items_all = []
        items_cover_all = []
        self.teachers_map = {}

        for t in teachers:
            try:
                tid = int(t["id"]) if isinstance(t, dict) else int(getattr(t, "id"))
                uname = t.get("username") if isinstance(t, dict) else str(t)
            except Exception:
                continue

            try:
                t_courses = [int(c["id"]) for c in get_teacher_courses(tid)]
            except Exception:
                t_courses = []

            if required_course_ids:
                n = len(required_course_ids)
                k = len(set(required_course_ids).intersection(set(t_courses)))
                disp = f"{uname} (teaches {k}/{n})"
            else:
                disp = uname

            items_all.append((disp, tid, t_courses))
            if (not required_course_ids) or set(required_course_ids).issubset(set(t_courses)):
                items_cover_all.append((disp, tid, t_courses))

        # Prefer teachers that cover all selected courses; if none, show all with the (teaches k/n) hint.
        final_items = items_cover_all if (required_course_ids and items_cover_all) else items_all

        # Update listbox
        try:
            if hasattr(self, "teacher_list") and self._widget_alive(self.teacher_list):
                cur_sel_text = (self.teacher_var.get() or "").strip()
                self.teacher_list.delete(0, tk.END)
                for disp, tid, _tc in final_items:
                    self.teacher_list.insert(tk.END, disp)
                    self.teachers_map[disp] = tid

                # Restore selection if possible
                if cur_sel_text:
                    for i in range(self.teacher_list.size()):
                        if self.teacher_list.get(i) == cur_sel_text:
                            self.teacher_list.selection_set(i)
                            self.teacher_list.see(i)
                            break
        except Exception:
            pass

        # Update combobox
        try:
            if hasattr(self, "teacher_combo") and self._widget_alive(self.teacher_combo):
                values = [disp for disp, _tid, _tc in final_items]
                self.teacher_combo["values"] = values
                # Keep current if still valid
                if (self.teacher_var.get() or "") not in values:
                    self.teacher_var.set("")
        except Exception:
            pass

    def _on_teacher_list_select(self):
        try:
            sel = self.teacher_list.curselection()
            if not sel:
                return
            val = self.teacher_list.get(sel[0])
            self.teacher_var.set(val)
        except Exception:
            pass

    def _on_teacher_combo_selected(self):
        # Sync listbox highlight with combobox selection
        try:
            val = (self.teacher_var.get() or "").strip()
            if not val:
                return
            if hasattr(self, "teacher_list") and self._widget_alive(self.teacher_list):
                self.teacher_list.selection_clear(0, tk.END)
                for i in range(self.teacher_list.size()):
                    if self.teacher_list.get(i) == val:
                        self.teacher_list.selection_set(i)
                        self.teacher_list.see(i)
                        break
        except Exception:
            pass


        self._refresh_teachers_filtered()

    def _choose_folder(self):
        p = filedialog.askdirectory(title="Select folder with face images")
        if p:
            self.folder_var.set(p)
            self._update_status(f"Selected folder: {os.path.basename(p)}", COLOR_INFO)

    def _clear_form(self):
        self.name_var.set("")
        self.email_var.set("")
        self.student_id_var.set("")
        try:
            self.student_pass_var.set("")
        except Exception:
            pass
        try:
            self.teacher_var.set("")
        except Exception:
            pass
        try:
            if hasattr(self, "teacher_list") and self._widget_alive(self.teacher_list):
                self.teacher_list.selection_clear(0, tk.END)
        except Exception:
            pass
        self.folder_var.set("")
        self.reg_course_list.selection_clear(0, tk.END)
        self._update_status("Form cleared", COLOR_INFO)

    def _reg_add_course(self):
        code = (self.reg_new_code.get() or "").strip()
        name = (self.reg_new_name.get() or "").strip()
        if not code or not name:
            messagebox.showwarning("Missing", "Enter course code and name.")
            return
        try:
            add_course(code, name)
            self.reg_new_code.set(""); self.reg_new_name.set("")
            self._refresh_courses()
            self._refresh_teachers_filtered()
            messagebox.showinfo("✓ Success", f"Course added:\n{code} - {name}")
            self._update_status(f"Course added: {code}", COLOR_SUCCESS)
        except Exception as e:
            messagebox.showerror("Error", str(e))
            self._update_status("Failed to add course", COLOR_ERROR)



    def _on_new_staff_role_changed(self):
        """
        Show teacher course assignment UI only when role=teacher.
        """
        try:
            role = (self.new_role_var.get() or "").strip().lower()
        except Exception:
            role = "teacher"

        # Show/hide the teacher-course hint frame
        try:
            if hasattr(self, "staff_course_frame") and self._widget_alive(self.staff_course_frame):
                if role == "teacher":
                    self.staff_course_frame.grid()
                else:
                    self.staff_course_frame.grid_remove()
        except Exception:
            pass

        # Keep list fresh when switching role (if the older listbox exists)
        try:
            self._refresh_staff_course_list()
        except Exception:
            pass


    def _refresh_staff_course_list(self):
        """
        Populate the admin's teacher-course assignment listbox with all available courses.
        """
        if not hasattr(self, "staff_course_list") or not self._widget_alive(self.staff_course_list):
            return

        courses = get_courses()

        # Preserve current selection keys (if any)
        selected_keys = set()
        try:
            for i in self.staff_course_list.curselection():
                selected_keys.add(self.staff_course_list.get(i))
        except Exception:
            pass

        self.staff_course_list.delete(0, "end")
        self.staff_courses_map = {}
        for c in courses:
            key = f"{c['code']} — {c['name']}"
            self.staff_courses_map[key] = int(c["id"])
            self.staff_course_list.insert("end", key)

        # Restore selections
        for idx in range(self.staff_course_list.size()):
            if self.staff_course_list.get(idx) in selected_keys:
                self.staff_course_list.selection_set(idx)


    def _clear_staff_form(self):
        """Clear the Create Teacher/Admin Account form."""
        try:
            self.new_user_var.set("")
            self.new_pass_var.set("")
            try:
                self._refresh_teachers_filtered()
            except Exception:
                pass
        except Exception:
            pass

        # Clear selected assigned courses (if the list exists)
        try:
            if hasattr(self, "staff_course_list") and self._widget_alive(self.staff_course_list):
                self.staff_course_list.selection_clear(0, tk.END)
        except Exception:
            pass

        self._update_status("Account form cleared", COLOR_INFO)


    def _create_staff_account(self):
        role = (self.new_role_var.get() or "").strip().lower()
        username = (self.new_user_var.get() or "").strip()
        password = (self.new_pass_var.get() or "").strip()
        if not role or not username or not password:
            messagebox.showwarning("Missing", "Enter role, username, and password.")
            return
        if role not in ("teacher", "admin"):
            messagebox.showwarning("Invalid role", "Role must be teacher or admin.")
            return

        # If creating/updating teacher, require assigned courses
        course_ids: List[int] = []
        if role == "teacher":
            # Courses are selected from the main "Select Courses" list on the right (top).
            if not hasattr(self, "reg_course_list") or not self._widget_alive(self.reg_course_list):
                messagebox.showerror("UI Error", "Courses list is not available.")
                return

            sel = list(self.reg_course_list.curselection())
            if not sel:
                messagebox.showwarning(
                    "Assign Courses",
                    "Please select at least one course (from the Courses list) for this teacher."
                )
                return

            for idx in sel:
                cid = None
                # Prefer aligned list if available
                try:
                    if idx < len(self._reg_course_ids):
                        cid = int(self._reg_course_ids[idx])
                except Exception:
                    cid = None

                # Fallback: map from displayed key -> courses_map id
                if cid is None:
                    try:
                        key = self.reg_course_list.get(idx)
                        cid = int(self.courses_map.get(key))
                    except Exception:
                        cid = None

                if cid is not None and cid not in course_ids:
                    course_ids.append(cid)

            # Defensive: if mapping failed and no valid IDs were collected, block creation
            if not course_ids:
                messagebox.showwarning(
                    'Assign Courses',
                    'Please select at least one valid course (from the Courses list) for this teacher.'
                )
                return

        try:
            create_account(username, password, role, None)

            if role == "teacher":
                tid = get_account_id(username, "teacher")
                if not tid:
                    raise RuntimeError("Could not resolve teacher account ID after creation.")
                set_teacher_courses(int(tid), course_ids)

            messagebox.showinfo("✓ Account Saved", f"Role: {role}\nUsername: {username}")
            self._update_status(f"Account saved: {role}/{username}", COLOR_SUCCESS)
            self.new_user_var.set("")
            self.new_pass_var.set("")
            try:
                self._refresh_teachers_filtered()
            except Exception:
                pass
        except Exception as e:
            messagebox.showerror("Error", str(e))
            self._update_status("Failed to save account", COLOR_ERROR)

    def _do_register(self):
        name = self.name_var.get().strip()
        email = self.email_var.get().strip()
        folder = self.folder_var.get().strip()
        sid_input = (self.student_id_var.get() or "").strip()

        if not sid_input:
            messagebox.showwarning("Missing Student ID", "Please enter a Student ID before registering.")
            return
        if not name or not email or not folder:
            messagebox.showwarning("Missing info", "Please fill in name, email and folder.")
            return
        if not os.path.isdir(folder):
            messagebox.showerror("Folder not found", folder)
            return

        # Course selection is required
        if not hasattr(self, "reg_course_list") or not self._widget_alive(self.reg_course_list):
            messagebox.showerror("UI Error", "Courses list is not available.")
            return

        selected_course_idx = list(self.reg_course_list.curselection())
        if not selected_course_idx:
            messagebox.showwarning("Select Course", "Please select at least one course for this student.")
            return

        # Teacher selection is required
        teacher_key = (self.teacher_var.get() or "").strip()
        if not teacher_key:
            # Fallback: listbox selection
            try:
                if hasattr(self, "teacher_list") and self._widget_alive(self.teacher_list):
                    sel = self.teacher_list.curselection()
                    if sel:
                        teacher_key = self.teacher_list.get(sel[0])
                        self.teacher_var.set(teacher_key)
            except Exception:
                pass

        if not teacher_key:
            messagebox.showwarning("Select Teacher", "Please select a teacher before registering the student.")
            return

        teacher_id = None
        try:
            teacher_id = int(self.teachers_map.get(teacher_key))
        except Exception:
            teacher_id = None

        if not teacher_id:
            messagebox.showwarning("Select Teacher", "Please select a valid teacher before registering the student.")
            return

        # Validate that the selected teacher teaches ALL selected courses
        try:
            req_course_ids = []
            for idx in selected_course_idx:
                if idx < len(getattr(self, "_reg_course_ids", [])):
                    req_course_ids.append(int(self._reg_course_ids[idx]))
            t_course_ids = [int(c["id"]) for c in get_teacher_courses(int(teacher_id))]
            if req_course_ids and not set(req_course_ids).issubset(set(t_course_ids)):
                messagebox.showwarning(
                    "Teacher/Course Mismatch",
                    "The selected teacher is not assigned to all selected courses.\n\nFix: assign these courses to the teacher (Create Teacher/Admin Account) or change your selection."
                )
                return
        except Exception:
            messagebox.showwarning("Teacher Validation", "Could not validate teacher courses. Please refresh teachers and try again.")
            return

        try:
            ok, msg, sid = register_user(name, email, folder, sid_input)
            if not ok:
                messagebox.showerror("Registration failed", msg or "Unknown error")
                self._update_status("Registration failed", COLOR_ERROR)
                return

            selected = list(self.reg_course_list.curselection())
            enrolled_count = 0
            for idx in selected:
                course_id = self._reg_course_ids[idx]
                enroll_student_in_course(sid, course_id, teacher_account_id=int(teacher_id))
                enrolled_count += 1
            # create/update student login account (username=StudentID)
            try:
                student_pw = (self.student_pass_var.get() or "").strip()
            except Exception:
                student_pw = ""

            if not student_pw:
                # auto-generate 6-digit PIN if admin left password empty
                student_pw = str((int.from_bytes(os.urandom(3), "big") % 900000) + 100000)
                pw_label = f"Password (PIN): {student_pw}"
            else:
                pw_label = f"Password: {student_pw}"

            try:
                # create_account() upserts on username conflict (updates password)
                create_account(username=sid, password=student_pw, role="student", student_uid=sid)
            except Exception:
                pw_label = "Password: <not-created>"
            self._refresh_courses()
            self._refresh_teachers_filtered()

            messagebox.showinfo(
                "✓ Success",
                f"{msg}\n\nStudent ID: {sid}\nEnrolled in {enrolled_count} course(s).\n\n"
                f"Student Login:\nRole: student\nUsername: {sid}\n{pw_label}"
            )
            self._update_status(f"Registered: {name} ({sid})", COLOR_SUCCESS)
            self._clear_form()

        except Exception as e:
            messagebox.showerror("Registration failed", str(e))
            self._update_status("Registration error", COLOR_ERROR)

    # ---------------- attendance (admin + student) ----------------
    def _build_attendance_tab(self):
        frm = self.attendance_frame
        container = ttk.Frame(frm, padding=PADDING_LARGE)
        container.pack(fill="both", expand=True)

        top = ttk.Labelframe(container, text="Session Configuration", padding=PADDING_LARGE)
        top.pack(fill="x", pady=(0, PADDING_MEDIUM))

        row = ttk.Frame(top); row.pack(fill="x")

        # Admin: can select any course. Teacher: course is locked from login (no selector shown).
        ttk.Label(row, text="Course:", font=FONT_SUBHEADING).pack(side="left", padx=(0, PADDING_MEDIUM))

        # Create the widget in all cases so the rest of the code can keep using self.course_combo.get().
        self.course_combo = ttk.Combobox(row, state="readonly", font=FONT_LABEL, width=40)

        if self.role == "teacher":
            # Lock to the chosen session course (selected at login)
            fixed = self.active_course_key or self.active_course_name or "<No Course>"
            self.course_fixed_label = ttk.Label(row, text=fixed, font=FONT_LABEL)
            self.course_fixed_label.pack(side="left", fill="x", expand=True)
            # Keep combobox hidden but set its value for internal reads
            try:
                self.course_combo["values"] = [fixed]
                self.course_combo.set(fixed)
            except Exception:
                pass
        else:
            self.course_combo.pack(side="left", fill="x", expand=True)
            # refresh live/records view when course changes
            try:
                self.course_combo.bind("<<ComboboxSelected>>", lambda _e: self._on_course_change_live())
            except Exception:
                pass




        # Teacher/Admin attendance control
        if self.role == "teacher":
            ttk.Label(container, text="👨‍🏫 Teacher Mode — Start a course session", font=FONT_SUBHEADING)\
                .pack(anchor="w", pady=(0, PADDING_MEDIUM))

            # For manual sign-out, teacher selects a user (no enrollment controls)
            box = ttk.Labelframe(container, text="Manual Sign-Out (Teacher)", padding=PADDING_LARGE)
            box.pack(fill="x", pady=(0, PADDING_MEDIUM))
            urow = ttk.Frame(box); urow.pack(fill="x")
            ttk.Label(urow, text="Select User:", font=FONT_LABEL).pack(side="left", padx=(0, PADDING_MEDIUM))
            self.user_combo = ttk.Combobox(urow, state="readonly", font=FONT_LABEL, width=40)
            self.user_combo.pack(side="left", fill="x", expand=True, padx=(0, PADDING_MEDIUM))
            self._load_users_for_combo_only()

        elif self.role == "admin":
            # Admin: can enroll + sign-out
            box = ttk.Labelframe(container, text="Manual Enrollment & Sign-Out (Admin)", padding=PADDING_LARGE)
            box.pack(fill="x", pady=(0, PADDING_MEDIUM))
            urow = ttk.Frame(box); urow.pack(fill="x")
            ttk.Label(urow, text="Select User:", font=FONT_LABEL).pack(side="left", padx=(0, PADDING_MEDIUM))
            self.user_combo = ttk.Combobox(urow, state="readonly", font=FONT_LABEL, width=40)
            self.user_combo.pack(side="left", fill="x", expand=True, padx=(0, PADDING_MEDIUM))
            ttk.Button(urow, text="Enroll in Course", command=self._enroll_user).pack(side="right")
            self._load_users_for_combo_only()

        # sign-out

        so = ttk.Labelframe(container, text="Manual Sign-Out", padding=PADDING_LARGE)
        so.pack(fill="x", pady=(0, PADDING_MEDIUM))
        ttk.Button(so, text="✗ Manual Sign-Out", command=self._manual_sign_out).pack(fill="x")

        # camera
        cam = ttk.Labelframe(container, text="Face Recognition Session", padding=PADDING_LARGE)
        cam.pack(fill="x")
        ttk.Label(cam, text="💡 Press 'q' in the video window to stop the camera session", font=FONT_LABEL).pack(anchor="w", pady=(0, PADDING_SMALL))

        brow = ttk.Frame(cam); brow.pack(fill="x")
        self.start_btn = ttk.Button(brow, text="▶ Start Face ID & Attend", command=self._start_attendance)
        self.stop_btn = ttk.Button(brow, text="⏹ Stop (press 'q' in video)", command=self._stop_attendance_hint, state="disabled")
        self.start_btn.pack(side="left", fill="x", expand=True, padx=(0, 4))
        self.stop_btn.pack(side="right", fill="x", expand=True, padx=(4, 0))

        # quick navigation to records (teacher/admin)
        if self.role in ("teacher", "admin") and hasattr(self, "data_frame"):
            nav = ttk.Frame(container); nav.pack(fill="x", pady=(PADDING_SMALL, 0))
            ttk.Button(nav, text="📊 Open Records (Live)", command=self._open_records_live).pack(side="right")

        # teacher/admin: end session + live record
        if self.role in ("teacher", "admin"):
            # Shared date used by End Session and live tracking.
            # Empty means *today* for live tracking and for session finalize.
            if not hasattr(self, "finalize_date_var"):
                self.finalize_date_var = tk.StringVar()

            # ---- End Session (keep it visible) ----
            fin = ttk.Labelframe(container, text="End Session & Finalize Attendance", padding=PADDING_LARGE)
            fin.pack(fill="x", pady=(PADDING_MEDIUM, 0))
            frow = ttk.Frame(fin)
            frow.pack(fill="x")
            ttk.Label(frow, text="Date (YYYY-MM-DD, empty=today):", font=FONT_LABEL).pack(side="left")
            ttk.Entry(frow, textvariable=self.finalize_date_var, width=16).pack(side="left", padx=8)
            ttk.Button(frow, text="✅ End Session", command=self._end_session_finalize).pack(side="right")
            ttk.Label(
                fin,
                text="Anti-proxy rule: students who signed in but did NOT sign out are marked Absent, and enrolled non-attendees are marked Absent (emails sent/logged).",
                font=FONT_SMALL,
            ).pack(anchor="w", pady=(PADDING_SMALL, 0))

            # Optional reset after finalize (useful for demos): delete today's records from DB
            if not hasattr(self, "clear_after_finalize_var"):
                # Default ON so the live table stays empty after End Session (even after restart)
                self.clear_after_finalize_var = tk.BooleanVar(value=False)

            ttk.Checkbutton(
                fin,
                text="Clear today's records from database after finalizing (demo/reset)",
                variable=self.clear_after_finalize_var
            ).pack(anchor="w", pady=(PADDING_SMALL, 0))

            # ---- Live record (compact) ----
            live = ttk.Labelframe(container, text="📡 Live Course Record (Auto Updates)", padding=PADDING_LARGE)
            # expand=False so it won't push End Session off-screen on smaller windows
            live.pack(fill="both", expand=False, pady=(PADDING_MEDIUM, PADDING_MEDIUM))

            controls = ttk.Frame(live)
            controls.pack(fill="x")
            ttk.Label(controls, text="Date (YYYY-MM-DD, empty=today):", font=FONT_LABEL).pack(side="left")
            ttk.Entry(controls, textvariable=self.finalize_date_var, width=16).pack(side="left", padx=8)
            ttk.Button(controls, text="🔄 Refresh Now", command=self._load_live_record).pack(side="left", padx=8)
            ttk.Checkbutton(
                controls,
                text="Auto refresh",
                variable=self.live_auto_var,
                command=self._toggle_live_auto_refresh
            ).pack(side="left", padx=8)

            live_frame = ttk.Frame(live)
            live_frame.pack(fill="both", expand=True, pady=(PADDING_SMALL, 0))

            self.live_record_tree = ttk.Treeview(
                live_frame,
                columns=("student_uid", "name", "email", "status", "sign_in", "sign_out", "duration", "date"),
                show="headings",
                height=6
            )

            cols = [
                ("student_uid", 120, "Student ID"),
                ("name", 150, "Name"),
                ("email", 200, "Email"),
                ("status", 90, "Status"),
                ("sign_in", 130, "Sign In"),
                ("sign_out", 130, "Sign Out"),
                ("duration", 90, "Duration"),
                ("date", 90, "Date"),
            ]
            for c, w, t in cols:
                self.live_record_tree.heading(c, text=t)
                self.live_record_tree.column(c, width=w, anchor="w")

            self.live_record_tree.pack(side="left", fill="both", expand=True)
            lsb = ttk.Scrollbar(live_frame, orient="vertical", command=self.live_record_tree.yview)
            lsb.pack(side="right", fill="y")
            self.live_record_tree.configure(yscrollcommand=lsb.set)

            # Load immediately and start auto-refresh
            self._load_live_record()
            self._toggle_live_auto_refresh()

        # admin-only: absences

        if self.role == "admin":
            abs_box = ttk.Labelframe(container, text="Mark Absences (Admin)", padding=PADDING_LARGE)
            abs_box.pack(fill="x", pady=(PADDING_MEDIUM, 0))
            arow = ttk.Frame(abs_box); arow.pack(fill="x")
            ttk.Label(arow, text="Date (YYYY-MM-DD, empty=today):", font=FONT_LABEL).pack(side="left")
            self.abs_date_var = tk.StringVar()
            ttk.Entry(arow, textvariable=self.abs_date_var, width=16).pack(side="left", padx=8)
            ttk.Button(arow, text="📧 Mark Absences & Email", command=self._mark_absences_email).pack(side="right")

        # load courses
        if self.role in ("admin", "teacher"):
            self._refresh_courses()
        self._refresh_teachers_filtered()

    def _load_users_for_combo_only(self):
        try:
            rows = get_users()
            self.users_map = {f"{r['student_uid']} - {r['name']}": r["student_uid"] for r in rows}
            self.user_combo["values"] = list(self.users_map.keys())
        except Exception as e:
            messagebox.showerror("Error", f"Failed to load users: {e}")

    def _enroll_user(self):
        ukey = self.user_combo.get()
        ckey = self.course_combo.get()
        if not ukey or not ckey:
            messagebox.showwarning("Select", "Choose user and course")
            return
        try:
            student_uid = self.users_map[ukey]
            course_id = self.courses_map[ckey]
            enroll_student_in_course(student_uid, course_id)
            messagebox.showinfo("✓ Enrolled", f"{ukey}\nenrolled in\n{ckey}")
            self._update_status(f"Enrolled: {ukey}", COLOR_SUCCESS)
        except Exception as e:
            messagebox.showerror("Error", str(e))

    def _manual_sign_out(self):
        ckey = self.course_combo.get()
        if not ckey:
            messagebox.showwarning("Select", "Choose course")
            return
        try:
            course_id = self.courses_map[ckey]
            if not hasattr(self, "user_combo"):
                messagebox.showwarning("Select", "Choose a user first.")
                return
            ukey = (self.user_combo.get() or "").strip()
            if not ukey:
                messagebox.showwarning("Select", "Choose a user first.")
                return
            student_uid = self.users_map.get(ukey)
            if not student_uid:
                messagebox.showerror("Error", "Invalid user selection.")
                return

            sign_out_student(student_uid, course_id)
            latest = get_latest_attendance_for_student_course(student_uid, course_id)
            if latest:
                messagebox.showinfo(
                    "✓ Manual Sign-Out",
                    f"Signed out:\n{ukey}\nCourse: {ckey}\n\n"
                    f"Sign In: {latest.get('sign_in_time')}\n"
                    f"Sign Out: {latest.get('sign_out_time')}\n"
                    f"Date: {latest.get('date')}"
                )
            else:
                messagebox.showinfo("✓ Manual Sign-Out", f"Signed out:\n{ukey}\nCourse: {ckey}")
            self._update_status(f"Signed out: {ukey}", COLOR_WARNING)
        except Exception as e:
            messagebox.showerror("Error", str(e))

    def _run_att_thread(self, course_id: int):
        try:
            run_attendance_system(course_id, teacher_account_id=int(self.account_id) if self.role=='teacher' and self.account_id else None)
        except Exception:
            tb = traceback.format_exc()
            # Log crash to a file so you can inspect it later
            try:
                with open(LOG_PATH, "a", encoding="utf-8") as f:
                    f.write("\n--- Attendance thread error ---\n")
                    f.write(tb)
            except Exception:
                pass

            # Show a readable error snippet (last lines) without forcing you to open the log
            snippet_lines = tb.strip().splitlines()[-18:]
            snippet = "\n".join(snippet_lines)

            def _show_error():
                messagebox.showerror(
                    "Attendance Error",
                    "Camera session crashed.\n\n"
                    "Details (last lines):\n" + snippet + "\n\n"
                    f"Full log: {LOG_PATH}"
                )

            # Tkinter UI must run on the main thread
            try:
                self.after(0, _show_error)
            except Exception:
                try:
                    _show_error()
                except Exception:
                    pass
        finally:
            # Re-enable buttons safely (main thread)
            def _restore_buttons():
                try:
                    self.start_btn.config(state="normal")
                    self.stop_btn.config(state="disabled")
                except Exception:
                    pass

            try:
                self.after(0, _restore_buttons)
            except Exception:
                _restore_buttons()

            self._update_status("Attendance session ended", COLOR_INFO)
    def _start_attendance(self):
        ckey = self.course_combo.get().strip()
        if not ckey:
            messagebox.showwarning("Course required", "Select a course first.")
            return

        course_id = self.courses_map.get(ckey)
        if course_id is None:
            messagebox.showerror("Error", "Invalid course selection.")
            return

        # Teacher/Admin: start session for the whole course.
        # Optional: if a specific user is selected, verify enrollment before starting (extra safety).
        selected_uid: Optional[str] = None
        try:
            if hasattr(self, "user_combo") and self.user_combo is not None:
                ukey = (self.user_combo.get() or "").strip()
                if ukey and ukey in self.users_map:
                    selected_uid = self.users_map.get(ukey)
        except Exception:
            selected_uid = None

        if selected_uid:
            try:
                if not is_student_enrolled_in_course(selected_uid, course_id):
                    messagebox.showwarning("Not Enrolled", "Selected user is not enrolled in this course.")
                    self._update_status("Camera blocked – user not enrolled", COLOR_WARNING)
                    return
            except Exception as e:
                messagebox.showerror("Error", f"Failed to verify enrollment:\n{e}")
                return

        self.start_btn.config(state="disabled")
        self.stop_btn.config(state="normal")
        self._update_status(f"Started attendance for: {ckey}", COLOR_SUCCESS)

        self.att_thread = threading.Thread(
            target=self._run_att_thread,
            args=(course_id,),
            daemon=True
        )
        self.att_thread.start()

    def _stop_attendance_hint(self):
        messagebox.showinfo("How to Stop", "Click the OpenCV window and press 'q' to stop the camera.")

    def _end_session_finalize(self):
        # Avoid finalizing while the camera thread is running
        try:
            if self.att_thread is not None and self.att_thread.is_alive():
                messagebox.showwarning(
                    "Camera Running",
                    "Stop the camera first (press 'q' in the OpenCV window), then click End Session."
                )
                return
        except Exception:
            pass

        ckey = (self.course_combo.get() or "").strip()
        if not ckey:
            messagebox.showwarning("Course required", "Select a course")
            return
        cid = self.courses_map.get(ckey)
        if cid is None:
            messagebox.showerror("Error", "Invalid course selection")
            return

        date_str = None
        if hasattr(self, "finalize_date_var"):
            date_str = (self.finalize_date_var.get() or "").strip() or None

        date_txt = date_str or "today"
        if not messagebox.askyesno(
            "End Session",
            f"Finalize attendance for:\n\n{ckey}\nDate: {date_txt}\n\n"
            "This will:\n"
            "• Mark students who did NOT sign out as Absent (anti-proxy)\n"
            "• Mark absent students who didn't attend\n"
            "• Send/log absence emails\n\n"
            "Continue?"
        ):
            return

        try:
            res = finalize_course_session(cid, date_str)
            open_abs = int(res.get("open_marked_absent", 0))
            absent_marked = int(res.get("absent_marked", 0))
            sent = int(res.get("sent", 0))
            logged = int(res.get("logged", 0))
            failed = int(res.get("failed", 0))

            msg = (
                f"Course: {ckey}\nDate: {date_txt}\n\n"
                f"Open sign-ins marked Absent: {open_abs}\n"
                f"Absences marked: {absent_marked}\n\n"
                f"Emails sent: {sent}\n"
                f"Emails logged (SMTP not configured): {logged}\n"
                f"Email failures: {failed}\n\n"
                "(Tip: If emails are only logged, set SMTP env vars to enable sending.)"
            )

            messagebox.showinfo("✓ Session Finalized", msg)
            self._update_status(f"Session finalized for {ckey} ({date_txt})", COLOR_SUCCESS)

            # If enabled, clear today's rows from the database so the Live table is empty after End Session/restart
            try:
                if getattr(self, "clear_after_finalize_var", None) is not None and self.clear_after_finalize_var.get():
                    deleted = clear_attendance_for_course_date(cid, date_str)
                    self._update_status(f"Cleared {deleted} rows for {ckey} ({date_txt})", COLOR_WARNING)
            except Exception as ce:
                messagebox.showwarning("Clear failed", f"Could not clear today's records from the database:\n{ce}")

            # Always clear the Live table UI and stop auto-refresh so it doesn't repopulate immediately
            try:
                if hasattr(self, "live_auto_var"):
                    self.live_auto_var.set(False)
                if hasattr(self, "_toggle_live_auto_refresh"):
                    self._toggle_live_auto_refresh()
                if hasattr(self, "live_record_tree"):
                    self.live_record_tree.delete(*self.live_record_tree.get_children())
            except Exception:
                pass


            # After finalizing, jump to Records so teacher can review immediately
            try:
                if self.role in ("teacher", "admin") and hasattr(self, "data_frame"):
                    self.notebook.select(self.data_frame)
                    # set date filter to the finalized date (or blank for today)
                    if hasattr(self, "data_course_date_var"):
                        self.data_course_date_var.set(date_str or "")
                    # select the course in the courses tree
                    if hasattr(self, "course_overview_tree"):
                        for item in self.course_overview_tree.get_children():
                            vals = self.course_overview_tree.item(item, "values")
                            if len(vals) >= 3 and int(vals[2]) == cid:
                                self.course_overview_tree.selection_set(item)
                                self.course_overview_tree.see(item)
                                self.data_selected_course_id = cid
                                break
                    # load the course record
                    if hasattr(self, "_load_course_record"):
                        self._load_course_record()
            except Exception:
                pass
        except Exception as e:
            messagebox.showerror("Error", f"Failed to finalize session:\n{e}")
            self._update_status("Finalize session failed", COLOR_ERROR)

    def _mark_absences_email(self):
        ckey = self.course_combo.get()
        if not ckey:
            messagebox.showwarning("Course required", "Select a course")
            return
        cid = self.courses_map[ckey]
        the_date = self.abs_date_var.get().strip() or None
        try:
            result = mark_absences_and_send_emails(cid, the_date)
            sent_count = int(result.get("sent", 0)) if isinstance(result, dict) else 0
            logged_count = int(result.get("logged", 0)) if isinstance(result, dict) else 0
            failed_count = int(result.get("failed", 0)) if isinstance(result, dict) else 0
            absent_marked = int(result.get("absent_marked", 0)) if isinstance(result, dict) else 0
            messagebox.showinfo(
                "✓ Absences Processed",
                f"Course: {ckey}\n\n"
                f"Absences marked: {absent_marked}\n"
                f"Emails sent: {sent_count}\n"
                f"Emails logged: {logged_count}\n"
                f"Email failures: {failed_count}"
            )
            self._update_status(f"Marked absences for {ckey}", COLOR_SUCCESS)
        except Exception as e:
            messagebox.showerror("Error", str(e))

    # ---------------- data tab (admin + teacher) ----------------
    def _build_data_tab(self):
        # Student: show only personal records
        if self.role == "student":
            self._build_student_records_tab()
            return

        frm = self.data_frame
        container = ttk.Frame(frm, padding=PADDING_LARGE)
        container.pack(fill="both", expand=True)

        users_section = ttk.Labelframe(container, text="👥 Registered Users", padding=PADDING_LARGE)
        users_section.pack(fill="both", expand=True, pady=(0, PADDING_MEDIUM))

        tree_frame = ttk.Frame(users_section)
        tree_frame.pack(fill="both", expand=True)

        self.users_tree = ttk.Treeview(tree_frame, columns=("student_uid", "name", "email"), show="headings", height=8)
        for col, width, text in [("student_uid", 160, "Student ID"), ("name", 220, "Name"), ("email", 280, "Email")]:
            self.users_tree.heading(col, text=text)
            self.users_tree.column(col, width=width, anchor="w")

        self.users_tree.pack(side="left", fill="both", expand=True)
        ttk.Scrollbar(tree_frame, orient="vertical", command=self.users_tree.yview).pack(side="right", fill="y")

        ttk.Button(users_section, text="🔄 Refresh Users", command=self._load_users).pack(anchor="w", pady=(PADDING_SMALL, 0))

        courses_section = ttk.Labelframe(container, text="📚 Courses & Records", padding=PADDING_LARGE)
        courses_section.pack(fill="both", expand=True)

        top = ttk.Frame(courses_section)
        top.pack(fill="both", expand=True)

        left = ttk.Frame(top)
        left.pack(side="left", fill="y", padx=(0, PADDING_MEDIUM))

        ttk.Label(left, text="Courses (click):", font=FONT_SUBHEADING).pack(anchor="w")
        self.course_overview_tree = ttk.Treeview(left, columns=("code", "name", "course_id"), show="headings", height=8)
        self.course_overview_tree.heading("code", text="Code")
        self.course_overview_tree.heading("name", text="Name")
        self.course_overview_tree.heading("course_id", text="ID")
        self.course_overview_tree.column("code", width=100, anchor="w")
        self.course_overview_tree.column("name", width=200, anchor="w")
        self.course_overview_tree.column("course_id", width=0, stretch=False)
        self.course_overview_tree.pack(side="left", fill="y")
        ttk.Scrollbar(left, orient="vertical", command=self.course_overview_tree.yview).pack(side="right", fill="y")
        self.course_overview_tree.bind("<<TreeviewSelect>>", self._on_course_select)
        ttk.Button(left, text="🔄 Refresh Courses", command=self._load_courses_overview).pack(anchor="w", pady=(PADDING_SMALL, 0))

        right = ttk.Frame(top)
        right.pack(side="right", fill="both", expand=True)

        filter_row = ttk.Frame(right)
        filter_row.pack(fill="x")
        ttk.Label(filter_row, text="Date (YYYY-MM-DD, empty=today, 'all'=all):", font=FONT_LABEL).pack(side="left")
        self.data_course_date_var = tk.StringVar()
        ttk.Entry(filter_row, textvariable=self.data_course_date_var, width=14).pack(side="left", padx=8)
        ttk.Button(filter_row, text="📄 Load Record", command=self._load_course_record).pack(side="left")
        ttk.Button(filter_row, text="🔄 Refresh", command=self._load_course_record).pack(side="left", padx=8)
        if self.role in ("teacher", "admin"):
            ttk.Checkbutton(filter_row, text="Auto refresh", variable=self.records_auto_var, command=self._toggle_records_auto_refresh).pack(side="left", padx=8)


        record_frame = ttk.Frame(right)
        record_frame.pack(fill="both", expand=True, pady=(PADDING_SMALL, 0))

        self.course_record_tree = ttk.Treeview(
            record_frame,
            columns=("student_uid","name","email","status","sign_in","sign_out","duration","date"),
            show="headings",
            height=10
        )
        cols = [
            ("student_uid", 120, "Student ID"),
            ("name", 150, "Name"),
            ("email", 200, "Email"),
            ("status", 90, "Status"),
            ("sign_in", 130, "Sign In"),
            ("sign_out", 130, "Sign Out"),
            ("duration", 90, "Duration"),
            ("date", 90, "Date"),
        ]
        for c, w, t in cols:
            self.course_record_tree.heading(c, text=t)
            self.course_record_tree.column(c, width=w, anchor="w")

        self.course_record_tree.pack(side="left", fill="both", expand=True)
        ttk.Scrollbar(record_frame, orient="vertical", command=self.course_record_tree.yview).pack(side="right", fill="y")

        export_row = ttk.Frame(courses_section)
        export_row.pack(fill="x", pady=(PADDING_SMALL, 0))
        ttk.Button(export_row, text="📊 Export CSV", command=self._export_csv).pack(side="left", padx=(0, 6))
        ttk.Button(export_row, text="📈 Export Excel", command=self._export_excel).pack(side="left")

    def _load_users(self):
        """Load users for View Data tab.
        - Admin: all registered users
        - Teacher: only students assigned to this teacher (within active course if set)
        - Student: only the logged-in student
        """
        try:
            if self.role == "teacher" and self.account_id:
                cid = self.active_course_id
                rows = get_students_for_teacher(int(self.account_id), int(cid) if cid else None)
            elif self.role == "student" and self.logged_student_uid:
                u = get_user_by_uid(self.logged_student_uid)
                rows = [u] if u else []
            else:
                rows = get_users()
        except Exception:
            rows = get_users()

        self.users_tree.delete(*self.users_tree.get_children())
        count = 0
        for r in rows:
            # Some rows may include additional fields; keep it safe.
            self.users_tree.insert(
                "", "end",
                values=(r.get("student_uid",""), r.get("name",""), r.get("email",""))
            )
            count += 1
        self._update_status(f"Loaded {count} users", COLOR_INFO)

    def _load_courses_overview(self):
        rows = get_courses()
        self.course_overview_tree.delete(*self.course_overview_tree.get_children())
        for r in rows:
            self.course_overview_tree.insert("", "end", values=(r["code"], r["name"], r["id"]))
        self._update_status(f"Loaded {len(rows)} courses", COLOR_INFO)

    def _on_course_select(self, _evt=None):
        sel = self.course_overview_tree.selection()
        if not sel:
            return
        vals = self.course_overview_tree.item(sel[0], "values")
        try:
            self.data_selected_course_id = int(vals[2])
        except Exception:
            self.data_selected_course_id = None
            return
        self._load_course_record()
    def _load_course_record(self):
        cid = self.data_selected_course_id
        if cid is None:
            messagebox.showwarning("Course required", "Select a course from the list.")
            return

        raw = (self.data_course_date_var.get() or "").strip()
        teacher_id = int(self.account_id) if (self.role == "teacher" and self.account_id) else None

        try:
            if raw.lower() in ("all", "*"):
                # Show all rows for the course (all dates)
                rows = get_attendance(course_id=cid, teacher_account_id=teacher_id)
                shown = "all"
            else:
                # Default to TODAY when empty, so "current attendance" is loaded
                date_str = raw or datetime.date.today().isoformat()
                rows = get_course_attendance_overview(cid, date_str, teacher_id)
                shown = date_str
            if rows is None:
                rows = []
        except Exception as e:
            messagebox.showerror("Load failed", str(e))
            return

        self.course_record_tree.delete(*self.course_record_tree.get_children())
        for r in rows:
            self.course_record_tree.insert(
                "", "end",
                values=(
                    r.get("student_uid", ""),
                    r.get("name", ""),
                    r.get("email", ""),
                    r.get("status", ""),
                    r.get("sign_in_time", ""),
                    r.get("sign_out_time", ""),
                    r.get("duration", ""),
                    r.get("date", ""),
                )
            )

        self._update_status(f"Loaded {len(rows)} record rows ({shown})", COLOR_SUCCESS)



    def _export_csv(self):
        rows = get_attendance()
        fn = f"attendance_export_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        with open(fn, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["Student ID","Name","Course Code","Course Name","Sign In","Sign Out","Duration","Status","Date"])
            for r in rows:
                w.writerow([r["student_uid"], r["name"], r["course_code"], r["course_name"], r["sign_in_time"], r["sign_out_time"], r["duration"], r["status"], r["date"]])
        messagebox.showinfo("✓ Exported", f"CSV saved:\n{os.path.abspath(fn)}")

    def _export_excel(self):
        try:
            import pandas as pd
        except Exception:
            messagebox.showerror("Missing Package", "Install pandas + openpyxl for Excel export.")
            return
        rows = get_attendance()
        fn = f"attendance_export_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
        pd.DataFrame(rows).to_excel(fn, index=False)
        messagebox.showinfo("✓ Exported", f"Excel saved:\n{os.path.abspath(fn)}")



    def _refresh_courses(self):
        """
        Load courses into self.courses_map and update course selectors.
        Admin: all courses.
        Teacher: only the ONE active session course chosen at login.
        Student: handled by _refresh_courses_for_student().
        """
        try:
            if self.role == "teacher":
                # Only the active course for this session
                if self.active_course_id is None:
                    # If missing, try to reload from teacher assignment (defensive)
                    if self.account_id:
                        assigned = get_teacher_courses(int(self.account_id))
                        if assigned:
                            chosen = assigned[0]
                            self.active_course_id = int(chosen["id"])
                            self.active_course_key = f"{chosen['code']} — {chosen['name']}"
                            self.active_course_name = self.active_course_key
                courses = []
                if self.active_course_id is not None:
                    # Fetch course info from DB list (small DB; keep it simple)
                    for c in get_courses():
                        if int(c["id"]) == int(self.active_course_id):
                            courses = [c]
                            break
                    if not courses:
                        # fallback if not found in get_courses result
                        courses = [{"id": self.active_course_id, "code": self.active_course_key.split(" — ")[0], "name": " ".join(self.active_course_key.split(" — ")[1:])}]
            else:
                courses = get_courses()

            self.courses_map = {}
            for c in courses:
                key = f"{c['code']} — {c['name']}"
                self.courses_map[key] = int(c["id"])

            # Update course combobox if present
            if getattr(self, "course_combo", None) is not None and self._widget_alive(self.course_combo):
                vals = list(self.courses_map.keys())
                self.course_combo["values"] = vals
                if self.role == "teacher":
                    # lock to active
                    fixed = self.active_course_key or (vals[0] if vals else "")
                    if fixed:
                        self.course_combo.set(fixed)
                        if hasattr(self, "course_fixed_label") and self._widget_alive(self.course_fixed_label):
                            self.course_fixed_label.config(text=fixed)
                else:
                    # auto-select first if empty
                    if vals and not (self.course_combo.get() or "").strip():
                        self.course_combo.set(vals[0])

            # Update registration course list (admin register tab)
            if hasattr(self, "reg_course_list") and self._widget_alive(self.reg_course_list):
                self.reg_course_list.delete(0, "end")
                self._reg_course_ids = []
                for key, cid in self.courses_map.items():
                    self.reg_course_list.insert("end", key)
                    try:
                        self._reg_course_ids.append(int(cid))
                    except Exception:
                        self._reg_course_ids.append(cid)

            # Update staff course assignment list (admin)
            if hasattr(self, "staff_course_list") and self._widget_alive(self.staff_course_list):
                self._refresh_staff_course_list()

            # Refresh teachers list (admin register tab)
            try:
                if self.role == "admin":
                    self._refresh_teachers_filtered()
            except Exception:
                pass

            # Refresh overview/records depending on active tab
            try:
                if hasattr(self, "data_frame") and self.role in ("admin", "teacher"):
                    self._load_courses_overview()
            except Exception:
                pass

        except Exception as e:
            self._update_status(f"Failed to load courses: {e}", COLOR_ERROR)

    def _toggle_theme(self):
        # optional; only works when using ttkbootstrap Window
        if USE_BOOTSTRAP:
            try:
                current = self.style.theme_use()
            except Exception:
                current = "flatly"
            new_theme = "darkly" if current == "flatly" else "flatly"
            self.style.theme_use(new_theme)
            self._update_status(f"Theme changed to {new_theme}", COLOR_INFO)


    # ---------------- student records (student) ----------------
    def _build_student_records_tab(self):
        frm = self.data_frame
        container = ttk.Frame(frm, padding=PADDING_LARGE)
        container.pack(fill="both", expand=True)

        info = get_user_by_uid(self.logged_student_uid) if self.logged_student_uid else None
        student_name = info["name"] if info else ""
        ttk.Label(
            container,
            text=f"👤 My Attendance Records — {self.logged_student_uid} - {student_name}",
            font=FONT_SUBHEADING
        ).pack(anchor="w", pady=(0, PADDING_MEDIUM))

        filter_box = ttk.Labelframe(container, text="Filters", padding=PADDING_MEDIUM)
        filter_box.pack(fill="x", pady=(0, PADDING_MEDIUM))

        row = ttk.Frame(filter_box)
        row.pack(fill="x")

        ttk.Label(row, text="Course:", font=FONT_LABEL).pack(side="left")
        self.student_course_filter = ttk.Combobox(row, state="readonly", width=40, font=FONT_LABEL)
        self.student_course_filter.pack(side="left", padx=8, fill="x", expand=True)

        ttk.Label(row, text="Date (YYYY-MM-DD, optional):", font=FONT_LABEL).pack(side="left", padx=(12, 0))
        self.student_date_filter = tk.StringVar()
        ttk.Entry(row, textvariable=self.student_date_filter, width=14, font=FONT_LABEL).pack(side="left", padx=8)

        ttk.Button(row, text="🔎 Load", command=self._load_student_records).pack(side="right")

        table_box = ttk.Labelframe(container, text="Records", padding=PADDING_LARGE)
        table_box.pack(fill="both", expand=True)

        tree_frame = ttk.Frame(table_box)
        tree_frame.pack(fill="both", expand=True)

        self.student_records_tree = ttk.Treeview(
            tree_frame,
            columns=("course_code", "course_name", "date", "sign_in", "sign_out", "duration", "status"),
            show="headings",
            height=14
        )
        cols = [
            ("course_code", 110, "Course Code"),
            ("course_name", 240, "Course Name"),
            ("date", 110, "Date"),
            ("sign_in", 120, "Sign In"),
            ("sign_out", 120, "Sign Out"),
            ("duration", 90, "Duration"),
            ("status", 90, "Status"),
        ]
        for c, w, t in cols:
            self.student_records_tree.heading(c, text=t)
            self.student_records_tree.column(c, width=w, anchor="w")

        self.student_records_tree.pack(side="left", fill="both", expand=True)

        scroll = ttk.Scrollbar(tree_frame, orient="vertical", command=self.student_records_tree.yview)
        scroll.pack(side="right", fill="y")
        self.student_records_tree.configure(yscrollcommand=scroll.set)

        btn_row = ttk.Frame(container)
        btn_row.pack(fill="x", pady=(PADDING_SMALL, 0))
        ttk.Button(btn_row, text="🔄 Refresh", command=self._load_student_records).pack(side="left")

        # Load courses + initial records
        self._refresh_courses_for_student()
        self.student_course_filter["values"] = ["(All)"] + list(self.courses_map.keys())
        self.student_course_filter.set("(All)")
        self._load_student_records()

    def _load_student_records(self):
        sid = self.logged_student_uid
        if not sid:
            messagebox.showerror("Error", "Student account is not linked to a student ID.")
            return

        date_str = (self.student_date_filter.get() or "").strip() if hasattr(self, "student_date_filter") else ""
        course_key = (self.student_course_filter.get() or "").strip() if hasattr(self, "student_course_filter") else "(All)"

        try:
            all_rows = get_attendance()
        except Exception as e:
            messagebox.showerror("Error", f"Failed to load records: {e}")
            return

        rows = []
        for r in all_rows:
            if r.get("student_uid") != sid:
                continue
            if date_str and r.get("date") != date_str:
                continue
            if course_key and course_key != "(All)":
                cid = self.courses_map.get(course_key)
                if cid is not None and r.get("course_id") != cid:
                    continue
            rows.append(r)

        self.student_records_tree.delete(*self.student_records_tree.get_children())

        for r in rows:
            self.student_records_tree.insert(
                "",
                "end",
                values=(
                    r.get("course_code", ""),
                    r.get("course_name", ""),
                    r.get("date", ""),
                    r.get("sign_in_time", ""),
                    r.get("sign_out_time", ""),
                    r.get("duration", ""),
                    r.get("status", ""),
                )
            )

        self._update_status(f"Loaded {len(rows)} personal record(s)", COLOR_INFO)


    # ---------------- live/records helpers ----------------
    def _cancel_auto_refresh_jobs(self):
        """Cancel scheduled after() callbacks (important for logout/rebuild)."""
        try:
            if self._live_job is not None:
                self.after_cancel(self._live_job)
        except Exception:
            pass
        self._live_job = None

        try:
            if self._records_job is not None:
                self.after_cancel(self._records_job)
        except Exception:
            pass
        self._records_job = None

    def _on_course_change_live(self):
        """Refresh live record when course changes."""
        try:
            self._load_live_record()
        except Exception:
            pass

    def _selected_course_id(self):
        ckey = (self.course_combo.get() or "").strip() if hasattr(self, "course_combo") else ""
        if not ckey:
            return None
        return self.courses_map.get(ckey)

    def _selected_live_date(self):
        # Live tracking should default to today's date.
        date_str = ""
        if hasattr(self, "finalize_date_var"):
            date_str = (self.finalize_date_var.get() or "").strip()
        return date_str or datetime.date.today().isoformat()

    def _load_live_record(self):
        """Populate the live record table for the selected course/date."""
        if not hasattr(self, "live_record_tree"):
            return
        cid = self._selected_course_id()
        if cid is None:
            try:
                self.live_record_tree.delete(*self.live_record_tree.get_children())
            except Exception:
                pass
            return

        date_str = self._selected_live_date()
        rows = get_course_attendance_overview(cid, date_str, int(self.account_id) if self.role=='teacher' and self.account_id else None)

        self.live_record_tree.delete(*self.live_record_tree.get_children())
        for r in rows:
            self.live_record_tree.insert(
                "", "end",
                values=(
                    r.get("student_uid", ""),
                    r.get("name", ""),
                    r.get("email", ""),
                    r.get("status", ""),
                    r.get("sign_in_time", ""),
                    r.get("sign_out_time", ""),
                    r.get("duration", ""),
                    r.get("date", ""),
                ),
            )

    def _toggle_live_auto_refresh(self):
        """Start/stop live record auto-refresh loop."""
        try:
            if self._live_job is not None:
                self.after_cancel(self._live_job)
        except Exception:
            pass
        self._live_job = None

        if not hasattr(self, "live_auto_var") or not self.live_auto_var.get():
            return

        def tick():
            try:
                if self.live_auto_var.get():
                    self._load_live_record()
                    self._live_job = self.after(self.refresh_ms, tick)
            except Exception:
                self._live_job = None

        self._live_job = self.after(self.refresh_ms, tick)

    def _toggle_records_auto_refresh(self):
        """Start/stop auto-refresh for the Records tab (teacher/admin)."""
        try:
            if self._records_job is not None:
                self.after_cancel(self._records_job)
        except Exception:
            pass
        self._records_job = None

        if not hasattr(self, "records_auto_var") or not self.records_auto_var.get():
            return

        def tick():
            try:
                if self.records_auto_var.get():
                    if getattr(self, "data_selected_course_id", None) is not None:
                        self._load_course_record()
                    self._records_job = self.after(self.refresh_ms, tick)
            except Exception:
                self._records_job = None

        self._records_job = self.after(self.refresh_ms, tick)

    def _open_records_live(self):
        """Open Records tab and load the selected course/date immediately (live monitoring)."""
        if not hasattr(self, "data_frame"):
            return

        cid = self._selected_course_id()
        if cid is None:
            messagebox.showwarning("Course required", "Select a course first.")
            return

        # Set record date to today's session date for live monitoring
        try:
            if hasattr(self, "data_course_date_var"):
                self.data_course_date_var.set(self._selected_live_date())
        except Exception:
            pass

        # Select the course in the left courses list (if already loaded)
        try:
            if hasattr(self, "course_overview_tree"):
                for item in self.course_overview_tree.get_children():
                    vals = self.course_overview_tree.item(item, "values")
                    if len(vals) >= 3 and int(vals[2]) == cid:
                        self.course_overview_tree.selection_set(item)
                        self.course_overview_tree.see(item)
                        self.data_selected_course_id = cid
                        break
        except Exception:
            self.data_selected_course_id = cid

        try:
            self.notebook.select(self.data_frame)
        except Exception:
            pass
        try:
            self._load_course_record()
        except Exception:
            pass


def main():
    try:
        # Ensure DB schema + default accounts exist
        try:
            init_db()
            ensure_default_admin()
            ensure_default_teacher()
        except Exception:
            pass

        app = AttendanceGUI()
        app.mainloop()
    except SystemExit:
        return
    except Exception:
        # Always show startup errors (and write them to a file)
        err = traceback.format_exc()
        with open(LOG_PATH, "w", encoding="utf-8") as f:
            f.write(err)
        try:
            messagebox.showerror("Startup Error", f"The app crashed while starting.\n\nSee: {LOG_PATH}")
        except Exception:
            pass
        raise


if __name__ == "__main__":
    main()