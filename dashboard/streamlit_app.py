"""
AI Face Attendance System — Streamlit analytics dashboard.

Role-aware design:
  Admin  — global view, all sidebar items, system-wide KPIs.
  Teacher — scoped view, "My X" sidebar items, data limited to their courses.
  Student — not supported in this dashboard (handled by API only).

All data fetching goes through the FastAPI backend using the caller's JWT.
The teacher-scoped endpoints (/teachers/me/*) enforce data isolation
server-side — the dashboard never passes a teacher_id as a query parameter.
"""

from __future__ import annotations

import os
from datetime import date, timedelta
from typing import Optional

import pandas as pd
import requests
import streamlit as st

API = os.getenv("API_URL", "http://127.0.0.1:8000/api/v1")

# Role constants — never hard-code "admin"/"teacher" strings in render paths.
ROLE_ADMIN = "admin"
ROLE_TEACHER = "teacher"

st.set_page_config(
    page_title="AI Attendance System",
    page_icon="🎓",
    layout="wide",
    initial_sidebar_state="expanded",
)


# ---- Session state helpers -------------------------------------------------

def _token() -> Optional[str]:
    return st.session_state.get("jwt_token")

def _role() -> Optional[str]:
    return st.session_state.get("role")

def _headers() -> dict:
    return {"Authorization": f"Bearer {_token()}"} if _token() else {}

def _api(method: str, path: str, **kwargs):
    """Make an authenticated API request. Returns (ok, data_or_error)."""
    url = f"{API}{path}"
    try:
        r = getattr(requests, method)(url, headers=_headers(), timeout=15, **kwargs)
        if r.ok:
            return True, r.json()
        return False, r.json().get("detail", r.text)
    except requests.exceptions.ConnectionError:
        return False, "Cannot connect to API server. Is uvicorn running?"
    except Exception as exc:
        return False, str(exc)


# ---- Cached data fetchers --------------------------------------------------

@st.cache_data(ttl=60, show_spinner=False)
def _fetch_courses(_token):
    ok, data = _api("get", "/courses/")
    return data if ok else []

@st.cache_data(ttl=60, show_spinner=False)
def _fetch_my_courses(_token):
    """Teacher-scoped: returns only courses assigned to the calling teacher."""
    ok, data = _api("get", "/teachers/me/courses")
    return data if ok else []

@st.cache_data(ttl=60, show_spinner=False)
def _fetch_my_students(_token):
    """Teacher-scoped: distinct students in the calling teacher's courses."""
    ok, data = _api("get", "/teachers/me/students")
    return data if ok else []

@st.cache_data(ttl=30, show_spinner=False)
def _fetch_teacher_summary(_token):
    ok, data = _api("get", "/teachers/me/summary")
    return data if ok else {}

@st.cache_data(ttl=60, show_spinner=False)
def _fetch_users(_token):
    ok, data = _api("get", "/users/")
    return data if ok else []

@st.cache_data(ttl=30, show_spinner=False)
def _fetch_attendance(_token, course_id=None):
    params = f"?course_id={course_id}" if course_id else ""
    ok, data = _api("get", f"/attendance/{params}")
    return data if ok else []

@st.cache_data(ttl=30, show_spinner=False)
def _fetch_stats(_token, course_id):
    ok, data = _api("get", f"/attendance/stats/{course_id}")
    return data if ok else {}


# ---- Login page ------------------------------------------------------------

def _login_page():
    st.title("🎓 AI Face Attendance System")
    st.markdown("### Login")

    col1, col2 = st.columns([1, 2])
    with col1:
        role = st.selectbox("Role", [ROLE_ADMIN, ROLE_TEACHER, "student"])
        username = st.text_input("Username")
        password = st.text_input("Password", type="password")

        if st.button("Login", use_container_width=True):
            ok, data = _api("post", "/auth/login", json={
                "username": username, "password": password, "role": role
            })
            if ok:
                st.session_state["jwt_token"] = data["access_token"]
                st.session_state["role"] = data["role"]
                st.session_state["username"] = data["username"]
                st.session_state["account_id"] = data["account_id"]
                st.session_state["student_uid"] = data.get("student_uid")
                st.rerun()
            else:
                st.error(f"Login failed: {data}")

    with col2:
        st.info(
            "**Default credentials (change after first login):**\n"
            "- Admin: `admin` / `admin123`\n"
            "- Teacher: `teacher` / `teacher123`"
        )


# ---- KPI card helper -------------------------------------------------------

def _kpi_card(label: str, value: str, delta: Optional[str] = None, color: str = "#3B82F6"):
    delta_html = f"<p style='font-size:0.8rem;color:#6B7280;margin:0'>{delta}</p>" if delta else ""
    st.markdown(
        f"""
        <div style="background:{color};border-radius:12px;padding:20px;color:white;text-align:center">
            <p style="font-size:0.9rem;margin:0;opacity:0.85">{label}</p>
            <p style="font-size:2rem;font-weight:bold;margin:4px 0">{value}</p>
            {delta_html}
        </div>
        """,
        unsafe_allow_html=True,
    )


# ============================================================================
# ADMIN pages (unchanged from original)
# ============================================================================

def _overview():
    """Admin overview — global KPIs."""
    st.header("📊 Overview")
    courses = _fetch_courses(_token())
    users = _fetch_users(_token())
    all_att = _fetch_attendance(_token())

    today_str = date.today().isoformat()
    today_records = [r for r in all_att if r.get("date") == today_str]
    present_today = sum(1 for r in today_records if r.get("status") == "Present")
    total_today = len(today_records)
    rate_today = f"{present_today/total_today*100:.1f}%" if total_today else "—"

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        _kpi_card("Registered Students", str(len(users)), color="#3B82F6")
    with c2:
        _kpi_card("Active Courses", str(len(courses)), color="#10B981")
    with c3:
        _kpi_card("Today's Attendance", rate_today,
                  delta=f"{present_today}/{total_today} present" if total_today else None,
                  color="#F59E0B")
    with c4:
        _kpi_card("Total Records", str(len(all_att)), color="#8B5CF6")

    if all_att:
        st.markdown("---")
        _attendance_trend_chart(all_att)


def _attendance_trend_chart(records: list):
    st.subheader("📈 Attendance Rate Trend (Last 30 Days)")

    df = pd.DataFrame(records)
    if df.empty or "date" not in df.columns:
        st.info("No attendance data yet.")
        return

    df["date"] = pd.to_datetime(df["date"])
    cutoff = pd.Timestamp(date.today() - timedelta(days=30))
    df = df[df["date"] >= cutoff]

    if df.empty:
        st.info("No attendance in the last 30 days.")
        return

    daily = df.groupby("date").apply(
        lambda g: pd.Series({
            "present": (g["status"] == "Present").sum(),
            "total": len(g),
        })
    ).reset_index()
    daily["attendance_rate"] = daily["present"] / daily["total"] * 100

    st.line_chart(daily.set_index("date")[["attendance_rate"]], height=300)

    with st.expander("Show daily breakdown"):
        daily["date"] = daily["date"].dt.strftime("%Y-%m-%d")
        daily["attendance_rate"] = daily["attendance_rate"].round(1).astype(str) + "%"
        st.dataframe(daily.rename(columns={
            "date": "Date", "present": "Present",
            "total": "Total", "attendance_rate": "Rate",
        }), use_container_width=True)


def _courses_section():
    """Admin courses page — create courses, enroll students, view all."""
    st.header("🎓 Course Management")
    tab1, tab2, tab3 = st.tabs(["All Courses", "Create Course", "Enroll Student"])

    with tab1:
        courses = _fetch_courses(_token())
        if courses:
            st.dataframe(pd.DataFrame(courses), use_container_width=True)
        else:
            st.info("No courses yet.")

    with tab2:
        if _role() != ROLE_ADMIN:
            st.warning("Only admins can create courses.")
        else:
            with st.form("create_course"):
                code = st.text_input("Course Code (e.g. CS101)")
                name = st.text_input("Course Name")
                if st.form_submit_button("Create Course"):
                    if not code or not name:
                        st.error("Code and name are required.")
                    else:
                        ok, data = _api("post", "/courses/",
                                        json={"code": code, "name": name})
                        if ok:
                            st.success(f"Course '{name}' created.")
                            st.cache_data.clear()
                        else:
                            st.error(f"Failed: {data}")

    with tab3:
        courses = _fetch_courses(_token())
        users = _fetch_users(_token())
        if not courses or not users:
            st.warning("Need at least one course and one student.")
        else:
            with st.form("enroll"):
                student_map = {f"{u['student_uid']} — {u['name']}": u["student_uid"] for u in users}
                course_map = {f"{c['code']} — {c['name']}": c["id"] for c in courses}
                s_key = st.selectbox("Student", list(student_map))
                c_key = st.selectbox("Course", list(course_map))
                if st.form_submit_button("Enroll"):
                    ok, data = _api("post", "/courses/enroll", json={
                        "student_uid": student_map[s_key],
                        "course_id": course_map[c_key],
                    })
                    if ok:
                        st.success("Enrolled successfully.")
                    else:
                        st.error(f"Failed: {data}")


def _registration_section():
    """Admin: register a student with face images."""
    st.header("👤 Register Student")

    if _role() != ROLE_ADMIN:
        st.error("Access denied — registering students requires the admin role.")
        return

    with st.form("register"):
        uid = st.text_input("Student ID")
        name = st.text_input("Full Name")
        email = st.text_input("Email")
        folder = st.text_input("Image Folder Path (on server)")
        if st.form_submit_button("Register"):
            if not all([uid, name, email, folder]):
                st.error("All fields are required.")
            else:
                ok, data = _api("post", "/users/register", json={
                    "student_uid": uid, "name": name,
                    "email": email, "image_folder": folder,
                })
                if ok:
                    st.success(
                        f"Registered '{data.get('name')}' — "
                        f"{data.get('images_used', 0)} image(s) used."
                    )
                    st.cache_data.clear()
                else:
                    st.error(f"Failed: {data}")


def _register_teacher_section():
    """Admin: create a teacher account and assign courses."""
    st.header("👨‍🏫 Register Teacher")

    if _role() != ROLE_ADMIN:
        st.error("Access denied — this page requires the admin role.")
        return

    courses = _fetch_courses(_token())
    course_options = {f"{c['code']} — {c['name']}": c["id"] for c in courses}

    with st.form("register_teacher", clear_on_submit=True):
        username = st.text_input("Username", help="Unique login name, no spaces")
        name = st.text_input("Full Name")
        email = st.text_input("Email")

        col_pw, col_confirm = st.columns(2)
        with col_pw:
            password = st.text_input("Password", type="password",
                                     help="Minimum 8 characters")
        with col_confirm:
            confirm = st.text_input("Confirm Password", type="password")

        st.markdown("**Assign Courses**")
        if course_options:
            selected_course_labels = st.multiselect(
                "Select courses to assign to this teacher",
                options=list(course_options.keys()),
                help="The teacher will be able to take attendance for these courses.",
            )
        else:
            st.info("No courses exist yet. Create courses first, then assign them here.")
            selected_course_labels = []

        submitted = st.form_submit_button("Register Teacher", use_container_width=True)

    if not submitted:
        return

    username = username.strip()
    name = name.strip()
    email = email.strip()
    selected_course_ids = [course_options[lbl] for lbl in selected_course_labels]

    errors = []
    if not username:
        errors.append("Username is required.")
    elif " " in username:
        errors.append("Username must not contain spaces.")
    if not name:
        errors.append("Full name is required.")
    if not email or "@" not in email or "." not in email.split("@")[-1]:
        errors.append("A valid email address is required.")
    if len(password) < 8:
        errors.append("Password must be at least 8 characters.")
    if password != confirm:
        errors.append("Passwords do not match.")

    if errors:
        for e in errors:
            st.error(e)
        return

    ok, data = _api("post", "/admin/register-teacher", json={
        "username": username,
        "name": name,
        "email": email,
        "password": password,
        "course_ids": selected_course_ids,
    })

    if ok:
        assigned = data.get("courses_assigned", 0)
        course_msg = f" Assigned to **{assigned}** course(s)." if assigned else ""
        st.success(
            f"Teacher registered successfully: "
            f"**{data.get('name')}** (username: `{data.get('username')}`)."
            f"{course_msg}"
        )
    else:
        st.error(f"Registration failed: {data}")


def _notifications_section():
    """Admin/teacher: send absence notifications, finalize sessions."""
    st.header("📧 Absence Notifications")

    # Teachers see only their own courses; admins see all.
    if _role() == ROLE_TEACHER:
        courses = _fetch_my_courses(_token())
    else:
        courses = _fetch_courses(_token())

    if not courses:
        st.warning("No courses found.")
        return

    course_map = {f"{c['code']} — {c['name']}": c["id"] for c in courses}
    selected = st.selectbox("Course", list(course_map))
    notify_date = st.date_input("Date (default: today)", value=date.today())

    col1, col2 = st.columns(2)
    with col1:
        if st.button("📧 Send Absence Notifications", use_container_width=True):
            ok, data = _api("post",
                            f"/attendance/notify-absent/{course_map[selected]}",
                            params={"on_date": notify_date.isoformat()})
            if ok:
                st.success(
                    f"Notified {data.get('notified', 0)} student(s): "
                    f"sent={data.get('sent', 0)}, "
                    f"logged={data.get('logged', 0)}, "
                    f"failed={data.get('failed', 0)}"
                )
            else:
                st.error(f"Failed: {data}")

    with col2:
        if st.button("🔒 Finalize Session (Anti-Proxy)", use_container_width=True):
            ok, data = _api("post",
                            f"/attendance/finalize/{course_map[selected]}",
                            params={"on_date": notify_date.isoformat()})
            if ok:
                st.success(
                    f"Session finalized: "
                    f"open_marked_absent={data.get('open_marked_absent', 0)}, "
                    f"newly_absent={data.get('newly_absent', 0)}"
                )
            else:
                st.error(f"Failed: {data}")


def _attendance_section(preselect_course_id: Optional[int] = None):
    """
    Attendance records page.

    For admins: all courses in filter; all records shown.
    For teachers: only their assigned courses in filter; records are
    already scoped server-side by the JWT.

    preselect_course_id: when navigated from "Take Attendance" the caller
    may pass a specific course to pre-select (unused by default — teacher
    will see "All my courses" which is already scoped).
    """
    st.header("📋 Attendance Records")

    if _role() == ROLE_TEACHER:
        courses = _fetch_my_courses(_token())
        all_label = "All my courses"
    else:
        courses = _fetch_courses(_token())
        all_label = "All courses"

    if not courses:
        st.warning("No courses found.")
        return

    course_options = {f"{c['code']} — {c['name']}": c["id"] for c in courses}

    # Build filter options; pre-select if a course was requested
    filter_options = [all_label] + list(course_options)
    default_idx = 0
    if preselect_course_id is not None:
        for i, label in enumerate(filter_options):
            if label != all_label and course_options.get(label) == preselect_course_id:
                default_idx = i
                break

    selected_label = st.selectbox(
        "Filter by course", filter_options, index=default_idx
    )
    selected_id = course_options.get(selected_label) if selected_label != all_label else None

    records = _fetch_attendance(_token(), selected_id)
    if not records:
        st.info("No attendance records.")
        return

    df = pd.DataFrame(records)
    df = df.rename(columns={
        "student_uid": "Student ID", "course_id": "Course ID",
        "date": "Date", "sign_in_time": "Sign In", "sign_out_time": "Sign Out",
        "duration_minutes": "Duration (min)", "status": "Status",
    })

    def _style_status(val):
        if val == "Present":
            return "background-color: #D1FAE5; color: #065F46"
        if val == "Absent":
            return "background-color: #FEE2E2; color: #991B1B"
        return ""

    styled = df.style.applymap(_style_status, subset=["Status"])
    st.dataframe(styled, use_container_width=True, height=400)

    if selected_id:
        _render_stats(selected_id)

    st.markdown("---")
    c1, c2 = st.columns(2)
    with c1:
        csv = df.to_csv(index=False)
        st.download_button("⬇ Download CSV", csv, "attendance.csv", "text/csv",
                           use_container_width=True)
    with c2:
        import io
        buf = io.BytesIO()
        df.to_excel(buf, index=False, engine="openpyxl")
        st.download_button("⬇ Download Excel", buf.getvalue(),
                           "attendance.xlsx",
                           "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                           use_container_width=True)


def _render_stats(course_id: int):
    stats = _fetch_stats(_token(), course_id)
    if not stats:
        return

    st.subheader("📊 Course Statistics")
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        _kpi_card("Attendance Rate", f"{stats.get('attendance_rate', 0):.1f}%",
                  color="#3B82F6")
    with c2:
        _kpi_card("Present", str(stats.get("present", 0)), color="#10B981")
    with c3:
        _kpi_card("Absent", str(stats.get("absent", 0)), color="#EF4444")
    with c4:
        _kpi_card("Unique Students", str(stats.get("unique_students", 0)), color="#8B5CF6")


# ============================================================================
# TEACHER pages
# ============================================================================

def _teacher_overview():
    """
    Teacher overview — scoped KPIs + prominent Take Attendance CTA.

    All data comes from /teachers/me/summary which is scoped server-side
    to the calling teacher's JWT. Zero-state values are always shown as 0.
    """
    st.header("📊 My Overview")

    # --- Primary call-to-action: Take Attendance ----------------------------
    st.markdown(
        """
        <div style="background:linear-gradient(135deg,#3B82F6,#1D4ED8);
                    border-radius:14px;padding:28px 32px;color:white;margin-bottom:24px">
            <p style="font-size:1.1rem;font-weight:600;margin:0 0 6px 0">
                📷 Ready to take attendance?
            </p>
            <p style="font-size:0.9rem;margin:0;opacity:0.85">
                View and manage today's attendance records for your courses.
            </p>
        </div>
        """,
        unsafe_allow_html=True,
    )
    if st.button("📷 Take Attendance", use_container_width=True, type="primary"):
        # Cannot write to "sidebar_nav" after the radio widget is rendered.
        # Write to an intermediary key instead; main() resolves it on the next run
        # before the radio widget is instantiated.
        st.session_state["_nav_request"] = "Attendance"
        st.rerun()

    st.markdown("---")

    # --- KPI cards ---------------------------------------------------------
    summary = _fetch_teacher_summary(_token())

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        _kpi_card("My Active Courses",
                  str(summary.get("my_courses", 0)), color="#3B82F6")
    with c2:
        _kpi_card("My Students",
                  str(summary.get("my_students", 0)), color="#10B981")
    with c3:
        _kpi_card("Today's Attendance",
                  str(summary.get("today_attendance", 0)), color="#F59E0B")
    with c4:
        _kpi_card("This Week",
                  str(summary.get("this_week_attendance", 0)), color="#8B5CF6")


def _my_courses_section():
    """Teacher: view assigned courses and enroll existing students."""
    st.header("🎓 My Courses")

    tab1, tab2 = st.tabs(["My Assigned Courses", "Enroll Student"])

    with tab1:
        courses = _fetch_my_courses(_token())
        if courses:
            st.dataframe(pd.DataFrame(courses), use_container_width=True)
        else:
            st.info("You have no courses assigned yet. Ask an admin to assign courses to you.")

    with tab2:
        courses = _fetch_my_courses(_token())
        # Teachers enroll students into their own courses only.
        # Student list comes from the global API (admin must have registered them).
        ok, all_students = _api("get", "/users/")
        if not ok:
            # Teachers cannot call /users/ (admin-only). Surface a helpful message.
            st.info(
                "Student list is not available. Ask an admin to enroll students, "
                "or use the Courses page in the admin panel."
            )
            return

        if not courses:
            st.warning("You have no courses to enroll students into.")
            return

        with st.form("enroll_teacher"):
            student_map = {
                f"{u['student_uid']} — {u['name']}": u["student_uid"]
                for u in all_students
            }
            course_map = {
                f"{c['code']} — {c['name']}": c["id"]
                for c in courses
            }
            s_key = st.selectbox("Student", list(student_map) or ["<no students>"])
            c_key = st.selectbox("Course", list(course_map))
            if st.form_submit_button("Enroll"):
                if not student_map:
                    st.error("No students available.")
                else:
                    ok, data = _api("post", "/courses/enroll", json={
                        "student_uid": student_map[s_key],
                        "course_id": course_map[c_key],
                        "teacher_account_id": st.session_state.get("account_id"),
                    })
                    if ok:
                        st.success("Enrolled successfully.")
                    else:
                        st.error(f"Failed: {data}")


def _my_students_section():
    """Teacher: view distinct students enrolled across all their courses."""
    st.header("👥 My Students")

    students = _fetch_my_students(_token())
    if not students:
        st.info(
            "No students are enrolled in your courses yet. "
            "Use **My Courses → Enroll Student** to add students."
        )
        return

    df = pd.DataFrame(students).rename(columns={
        "student_uid": "Student ID", "name": "Name", "email": "Email"
    })
    st.dataframe(df, use_container_width=True, height=400)
    st.caption(f"{len(students)} student(s) across all your courses")


# ============================================================================
# Main app layout
# ============================================================================

def _build_nav_pages() -> list:
    """Return the sidebar page list appropriate to the current role."""
    if _role() == ROLE_TEACHER:
        return ["Overview", "Attendance", "My Courses", "My Students", "Notifications"]
    # Admin (default)
    return [
        "Overview", "Attendance", "Courses",
        "Register Student", "Register Teacher", "Notifications",
    ]


def main():
    if not _token():
        _login_page()
        return

    nav_pages = _build_nav_pages()

    with st.sidebar:
        st.markdown(
            f"**Logged in as:** {st.session_state.get('username')}\n\n"
            f"**Role:** {_role()}"
        )
        st.markdown("---")

        # Resolve any pending navigation request BEFORE the radio widget is
        # instantiated. Writing to "sidebar_nav" after st.radio renders it raises
        # StreamlitAPIException — the intermediary "_nav_request" key avoids that.
        if "_nav_request" in st.session_state:
            requested = st.session_state.pop("_nav_request")
            if requested in nav_pages:
                st.session_state["sidebar_nav"] = requested

        if "sidebar_nav" not in st.session_state:
            st.session_state["sidebar_nav"] = "Overview"

        # Guard: fall back to Overview if the stored page is no longer in the list.
        if st.session_state["sidebar_nav"] not in nav_pages:
            st.session_state["sidebar_nav"] = "Overview"

        page = st.radio(
            "Navigation",
            nav_pages,
            key="sidebar_nav",
            label_visibility="collapsed",
        )

        st.markdown("---")
        if st.button("Logout"):
            for key in list(st.session_state.keys()):
                del st.session_state[key]
            st.cache_data.clear()
            st.rerun()

    # ---- Page dispatch -------------------------------------------------------
    if page == "Overview":
        if _role() == ROLE_TEACHER:
            _teacher_overview()
        else:
            _overview()

    elif page == "Attendance":
        _attendance_section()

    elif page == "Courses":
        _courses_section()

    elif page == "My Courses":
        _my_courses_section()

    elif page == "My Students":
        _my_students_section()

    elif page == "Register Student":
        _registration_section()

    elif page == "Register Teacher":
        _register_teacher_section()

    elif page == "Notifications":
        _notifications_section()


if __name__ == "__main__":
    main()
