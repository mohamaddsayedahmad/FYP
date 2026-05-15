"""
Professional Streamlit analytics dashboard.

Architecture:
- Communicates with the FastAPI backend via authenticated HTTP requests.
- JWT token stored in st.session_state (not in URL or cookies).
- All data fetching is cached with st.cache_data (TTL = 60 s) so the
  dashboard remains responsive without hammering the API.

Dashboard sections:
1. Login — obtain JWT token
2. Overview — KPI cards (total students, courses, today's attendance rate)
3. Attendance Trends — line chart of daily attendance rate per course
4. Per-Student View — table + heatmap calendar
5. Course Management — create courses, enroll students
6. Admin Panel — account management (admin only)
7. Data Export — CSV / Excel download
"""

from __future__ import annotations

import os
from datetime import date, timedelta
from typing import Optional

import pandas as pd
import requests
import streamlit as st

API = os.getenv("API_URL", "http://127.0.0.1:8000/api/v1")

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
        role = st.selectbox("Role", ["admin", "teacher", "student"])
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


# ---- KPI cards helper -------------------------------------------------------

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


# ---- Overview section -------------------------------------------------------

def _overview():
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

    # Summary table
    with st.expander("Show daily breakdown"):
        daily["date"] = daily["date"].dt.strftime("%Y-%m-%d")
        daily["attendance_rate"] = daily["attendance_rate"].round(1).astype(str) + "%"
        st.dataframe(daily.rename(columns={
            "date": "Date", "present": "Present",
            "total": "Total", "attendance_rate": "Rate",
        }), use_container_width=True)


# ---- Attendance section -----------------------------------------------------

def _attendance_section():
    st.header("📋 Attendance Records")
    courses = _fetch_courses(_token())
    if not courses:
        st.warning("No courses found.")
        return

    course_options = {f"{c['code']} — {c['name']}": c["id"] for c in courses}
    selected_label = st.selectbox("Filter by course", ["All courses"] + list(course_options))
    selected_id = course_options.get(selected_label) if selected_label != "All courses" else None

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

    # Colour-code status
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

    # Export
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


# ---- Course management ------------------------------------------------------

def _courses_section():
    st.header("🎓 Course Management")
    tab1, tab2, tab3 = st.tabs(["All Courses", "Create Course", "Enroll Student"])

    with tab1:
        courses = _fetch_courses(_token())
        if courses:
            st.dataframe(pd.DataFrame(courses), use_container_width=True)
        else:
            st.info("No courses yet.")

    with tab2:
        if _role() not in ("admin",):
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


# ---- Registration -----------------------------------------------------------

def _registration_section():
    st.header("👤 Register Student")
    if _role() not in ("admin", "teacher"):
        st.warning("Only admins and teachers can register students.")
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


# ---- Notifications ----------------------------------------------------------

def _notifications_section():
    st.header("📧 Absence Notifications")
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


# ---- Main app layout --------------------------------------------------------

def main():
    if not _token():
        _login_page()
        return

    with st.sidebar:
        st.markdown(
            f"**Logged in as:** {st.session_state.get('username')}\n\n"
            f"**Role:** {_role()}"
        )
        st.markdown("---")
        page = st.radio(
            "Navigation",
            ["Overview", "Attendance", "Courses", "Register Student", "Notifications"],
            label_visibility="collapsed",
        )
        st.markdown("---")
        if st.button("Logout"):
            for key in ["jwt_token", "role", "username", "account_id", "student_uid"]:
                st.session_state.pop(key, None)
            st.cache_data.clear()
            st.rerun()

    if page == "Overview":
        _overview()
    elif page == "Attendance":
        _attendance_section()
    elif page == "Courses":
        _courses_section()
    elif page == "Register Student":
        _registration_section()
    elif page == "Notifications":
        _notifications_section()


if __name__ == "__main__":
    main()
