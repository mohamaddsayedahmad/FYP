# app.py
from flask import Flask, request, jsonify

from registration import register_user
from database import (
    get_users, get_attendance, add_course, get_courses,
    enroll_student_in_course, sign_in_student, sign_out_student,
    mark_absences_and_send_emails
)

app = Flask(__name__)


@app.route("/", methods=["GET"])
def index():
    return jsonify({
        "status": "ok",
        "endpoints": {
            "GET /users": {},
            "GET /courses": {},
            "POST /courses": {"code": "str", "name": "str"},
            "POST /enroll": {"user_id": "int", "course_id": "int"},
            "POST /sign_in/<course_id>/<user_id>": {},
            "POST /sign_out/<course_id>/<user_id>": {},
            "GET /attendance?course_id=<int>": {},
            "POST /register": {"name": "str", "email": "str", "image_folder": "str"},
            "POST /notify_absent": {"course_id": "int", "date?": "YYYY-MM-DD"}
        }
    })


@app.route("/users", methods=["GET"])
def users():
    rows = get_users()
    return jsonify([{
        "id": r["id"],
        "student_uid": r["student_uid"],
        "name": r["name"],
        "email": r["email"]
    } for r in rows])


@app.route("/register", methods=["POST"])
def register():
    data = request.get_json(silent=True) or {}
    name = data.get("name", "").strip()
    email = data.get("email", "").strip()
    folder = data.get("image_folder", "").strip()

    if not name or not email or not folder:
        return jsonify({"message": "Missing name, email or image_folder"}), 400

    res = register_user(name, email, folder)  # should call database.add_user internally

    if isinstance(res, tuple):
        ok, msg = res
        return (jsonify({"message": msg}), 200) if ok else (jsonify({"message": msg}), 400)

    return jsonify({"message": "User registered"}), 200


@app.route("/courses", methods=["GET"])
def list_courses():
    rows = get_courses()
    return jsonify([{"id": r["id"], "code": r["code"], "name": r["name"]} for r in rows])


@app.route("/courses", methods=["POST"])
def create_course():
    data = request.get_json(silent=True) or {}
    code = data.get("code", "").strip()
    name = data.get("name", "").strip()

    if not code or not name:
        return jsonify({"message": "Missing code or name"}), 400

    add_course(code, name)
    return jsonify({"message": "Course created"}), 200


@app.route("/enroll", methods=["POST"])
def enroll():
    data = request.get_json(silent=True) or {}
    student_uid = data.get("student_uid") or data.get("user_id")
    course_id = data.get("course_id")

    if not student_uid or not course_id:
        return jsonify({"message": "Missing student_uid (or user_id) and course_id"}), 400

    enroll_student_in_course(str(student_uid), int(course_id))
    return jsonify({"message": "Enrolled"}), 200


@app.route("/sign_in/<int:course_id>/<student_uid>", methods=["POST"])
def sign_in(course_id, student_uid):
    try:
        sign_in_student(str(student_uid), course_id)
        return jsonify({"message": f"student {student_uid} signed in to course {course_id}"}), 200
    except Exception as e:
        return jsonify({"message": str(e)}), 400


@app.route("/sign_out/<int:course_id>/<student_uid>", methods=["POST"])
def sign_out(course_id, student_uid):
    try:
        sign_out_student(str(student_uid), course_id)
        return jsonify({"message": f"student {student_uid} signed out of course {course_id}"}), 200
    except Exception as e:
        return jsonify({"message": str(e)}), 400


@app.route("/attendance", methods=["GET"])
def attendance():
    course_id = request.args.get("course_id", type=int)
    rows = get_attendance(course_id=course_id)
    return jsonify([{
        "student_uid": r["student_uid"],
        "name": r["name"],
        "course_code": r["course_code"],
        "course_name": r["course_name"],
        "sign_in_time": r["sign_in_time"],
        "sign_out_time": r["sign_out_time"],
        "duration": r["duration"],
        "status": r["status"],
        "date": r["date"]
    } for r in rows])


@app.route("/notify_absent", methods=["POST"])
def notify_absent():
    data = request.get_json(silent=True) or {}
    course_id = data.get("course_id")
    the_date = data.get("date")  # optional; defaults to today in DB layer

    if not course_id:
        return jsonify({"message": "Missing course_id"}), 400

    result = mark_absences_and_send_emails(int(course_id), the_date)
    return jsonify({"message": "Absent marked & emails attempted", **result}), 200


if __name__ == "__main__":
    app.run(debug=True, port=5000)
