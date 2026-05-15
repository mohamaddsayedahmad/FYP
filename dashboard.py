# dashboard.py
import os
import requests
import pandas as pd
import streamlit as st

API = os.getenv("API_URL", "http://127.0.0.1:5000")

st.title("AI Face Attendance — Courses, Enrolments, Attendance & Emails")


def fetch_users():
    r = requests.get(f"{API}/users", timeout=30)
    r.raise_for_status()
    return r.json()


def fetch_courses():
    r = requests.get(f"{API}/courses", timeout=30)
    r.raise_for_status()
    return r.json()


# --- Courses ---
st.header("Courses")
colA, colB = st.columns([2, 1])

with colA:
    c_code = st.text_input("Course Code (e.g., CS101)")
    c_name = st.text_input("Course Name")

with colB:
    if st.button("Create Course"):
        if not c_code or not c_name:
            st.error("Code and Name are required.")
        else:
            r = requests.post(f"{API}/courses",
                              json={"code": c_code, "name": c_name},
                              timeout=30)
            st.success("Course created." if r.ok else r.text)

courses = fetch_courses()
course_map = {f"{c['code']} - {c['name']}": c["id"] for c in courses}

if courses:
    dfc = pd.DataFrame(courses)
    st.dataframe(dfc, use_container_width=True)

# --- Registration ---
st.header("Register New User")
with st.form("reg_form"):
    name_in = st.text_input("Name")
    email_in = st.text_input("Email")
    folder_in = st.text_input("Image Folder Path")
    submitted = st.form_submit_button("Register")

if submitted:
    r = requests.post(
        f"{API}/register",
        json={"name": name_in, "email": email_in, "image_folder": folder_in},
        timeout=60
    )
    if r.ok:
        st.success(r.json().get("message", "Registered"))
    else:
        st.error(r.json().get("message", r.text))

# Show users with Student ID
st.subheader("Registered Users")
users = fetch_users()
if users:
    dfu = pd.DataFrame(users)[["id", "student_uid", "name", "email"]]
    st.dataframe(dfu, use_container_width=True)

# --- Enrolments & Manual Sign ---
st.header("Enrollments, Manual Sign-In/Out")
user_map = {f"{u['id']} - {u['name']}": u["id"] for u in users}

col1, col2, col3 = st.columns(3)
with col1:
    user_key = st.selectbox("User", list(user_map.keys()) or ["<no users>"])
with col2:
    course_key = st.selectbox("Course", list(course_map.keys()) or ["<no courses>"])
with col3:
    if st.button("Enroll user in course"):
        if user_map and course_map:
            r = requests.post(
                f"{API}/enroll",
                json={"user_id": user_map[user_key], "course_id": course_map[course_key]},
                timeout=30
            )
            st.success("Enrolled." if r.ok else r.text)

s1, s2 = st.columns(2)
with s1:
    if st.button("Manual Sign-In"):
        r = requests.post(
            f"{API}/sign_in/{course_map[course_key]}/{user_map[user_key]}",
            timeout=30
        )
        st.write(r.json())
with s2:
    if st.button("Manual Sign-Out"):
        r = requests.post(
            f"{API}/sign_out/{course_map[course_key]}/{user_map[user_key]}",
            timeout=30
        )
        st.write(r.json())

# --- Absence + Email ---
st.header("Mark Absences & Send Emails")
abs_course = st.selectbox("Course to process", list(course_map.keys()) or ["<no courses>"])
abs_date = st.text_input("Date (YYYY-MM-DD, optional; empty = today)")

if st.button("Mark absences and send emails"):
    payload = {"course_id": course_map[abs_course]}
    if abs_date.strip():
        payload["date"] = abs_date.strip()
    r = requests.post(f"{API}/notify_absent", json=payload, timeout=60)
    st.write(r.json())

# --- Attendance (Filtered) ---
st.header("Attendance")
sel_course = st.selectbox("Filter by course", ["<All>"] + list(course_map.keys()))
params = {}
if sel_course != "<All>":
    params["course_id"] = course_map[sel_course]

if st.button("Load Attendance"):
    r = requests.get(f"{API}/attendance", params=params, timeout=30)
    if r.ok:
        df = pd.DataFrame(r.json())
        if df.empty:
            st.info("No attendance yet.")
        else:
            st.dataframe(df, use_container_width=True)
            st.download_button("Download CSV",
                               df.to_csv(index=False),
                               "attendance.csv",
                               "text/csv")
    else:
        st.error(r.text)
