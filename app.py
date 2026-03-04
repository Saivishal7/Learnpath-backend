from flask_jwt_extended import jwt_required, get_jwt_identity
from flask import jsonify
from datetime import datetime, timedelta


def admin_required():
    user_id = get_jwt_identity()
    db = get_db()
    user = db.execute("SELECT role FROM users WHERE id = ?", (user_id,)).fetchone()
    if not user or user["role"] != "admin":
        return False
    return True
from flask import Flask, request, jsonify
from flask_jwt_extended import (
    JWTManager,
    create_access_token,
    jwt_required,
    get_jwt
)
from flask_cors import CORS
from database import init_db, get_db
from recommendations import get_recommendations
from timetable import generate_timetable
import hashlib
import os
from ai_service import detect_intent, extract_missing_profile, generate_recommendation
from flask_jwt_extended import get_jwt_identity

# ───────────────────────── APP SETUP ───────────────────────── #

app = Flask(__name__)
CORS(app)


REQUIRED_FIELDS = ["grade", "weak_subject", "learning_goal", "learning_style"]

app.config["JWT_SECRET_KEY"] = os.environ.get(
    "JWT_SECRET_KEY",
    "super-secret-key"  # Change this in production!
)
from datetime import timedelta
app.config["JWT_ACCESS_TOKEN_EXPIRES"] = timedelta(days=15)
jwt = JWTManager(app)



with app.app_context():
    init_db()
    

# ───────────────────────── HEALTH CHECK ───────────────────────── #

@app.route("/", methods=["GET"])
def home():
    return jsonify({
        "message": "LearnPath Backend is running",
        "status": "success"
    }), 200

# ───────────────────────── AUTH ───────────────────────── #

@app.route("/api/register", methods=["POST"])
def api_register():
    data = request.get_json()

    if not data:
        return jsonify({"error": "Invalid request"}), 400

    username = data.get("username", "").strip()
    password = data.get("password", "")

    if not username or not password:
        return jsonify({"error": "Username and password required"}), 400

    pw_hash = hashlib.sha256(password.encode()).hexdigest()
    db = get_db()

    try:
        cursor = db.execute(
            "INSERT INTO users (username, password_hash, role) VALUES (?, ?, 'student')",
            (username, pw_hash)
        )

        user_id = cursor.lastrowid

        # Create empty student profile
        db.execute(
            "INSERT INTO students (user_id, name) VALUES (?, ?)",
            (user_id, username)
        )

        db.commit()

        return jsonify({"message": "Account created successfully"}), 201

    except Exception as e:
        print("REGISTER ERROR:", e)
        return jsonify({"error": str(e)}), 400


# DEBUG ROUTE (OUTSIDE REGISTER FUNCTION — VERY IMPORTANT)
@app.route("/api/debug/users", methods=["GET"])
def debug_users():
    db = get_db()
    users = db.execute("SELECT username FROM users").fetchall()
    return jsonify([u["username"] for u in users])


@app.route("/api/login", methods=["POST"])
def api_login():
    data = request.get_json()

    if not data:
        return jsonify({"error": "Invalid request"}), 400

    username = data.get("username", "").strip()
    password = data.get("password", "")

    if not username or not password:
        return jsonify({"error": "Username and password required"}), 400

    pw_hash = hashlib.sha256(password.encode()).hexdigest()

    db = get_db()
    user = db.execute(
        "SELECT * FROM users WHERE username=? AND password_hash=?",
        (username, pw_hash)
    ).fetchone()

    if not user:
        return jsonify({"error": "Invalid credentials"}), 401

    access_token = create_access_token(
        identity=str(user["id"]),
        additional_claims={
            "role": user["role"],
            "username": user["username"]
        }
    )

    return jsonify({
        "token": access_token,
        "role": user["role"],
        "username": user["username"]
    }), 200


@app.route("/api/profile", methods=["GET"])
@jwt_required()
def get_profile():
    user_id = get_jwt_identity()
    db = get_db()

    user = db.execute(
        "SELECT full_name, email, class_year, current_course FROM users WHERE id = ?",
        (user_id,)
    ).fetchone()

    if not user:
        return jsonify({"error": "User not found"}), 404

    return jsonify({
        "full_name": user["full_name"],
        "email": user["email"],
        "class_year": user["class_year"],
        "current_course": user["current_course"]
    })

# ───────────────────────── RECOMMENDATION ───────────────────────── #

@app.route("/api/recommend", methods=["POST"])
@jwt_required()
def api_recommend():
    data = request.get_json()

    if not data:
        return jsonify({"error": "Invalid request"}), 400

    name = data.get("name", "")
    grade = data.get("grade", "")
    subject = data.get("subject", "Mathematics")
    goal = data.get("goal", "Improve grades")
    style = data.get("style", "Visual")

    recommendations = get_recommendations(
        name, grade, subject, goal, style
    )
    timetable = generate_timetable(subject, style, goal)

    return jsonify({
        "recommendations": recommendations,
        "timetable": timetable
    }), 200


# ───────────────────────── ADMIN DASHBOARD ───────────────────────── #

@app.route("/api/admin/dashboard", methods=["GET"])
@jwt_required()
def api_admin_dashboard():
    claims = get_jwt()

    if claims.get("role") != "admin":
        return jsonify({"error": "Admin access required"}), 403

    db = get_db()

    total_users = db.execute(
        "SELECT COUNT(*) FROM users WHERE role='student'"
    ).fetchone()[0]

    total_logs = db.execute(
        "SELECT COUNT(*) FROM progress_logs"
    ).fetchone()[0]

    return jsonify({
        "total_students": total_users,
        "total_logs": total_logs
    }), 200

# ───────────────────────── AI CHAT ───────────────────────── #

@app.route("/api/chat", methods=["POST"])
@jwt_required()
def api_chat():

    user_id = get_jwt_identity()
    db = get_db()

    data = request.get_json()
    if not data:
        return jsonify({"error": "Invalid request"}), 400

    message = data.get("message", "").strip()
    if not message:
        return jsonify({"error": "Message required"}), 400

    # Fetch student profile
    student = db.execute(
        "SELECT * FROM students WHERE user_id = ?",
        (user_id,)
    ).fetchone()

    if not student:
        return jsonify({"error": "Student profile not found"}), 404

    profile = dict(student)

    # Check missing fields
    missing_fields = [
        field for field in REQUIRED_FIELDS
        if not profile.get(field)
    ]

    if missing_fields:

        extracted_data = extract_missing_profile(
            message,
            missing_fields,
            profile
        )

        if extracted_data:
            for key, value in extracted_data.items():
                db.execute(
                    f"UPDATE students SET {key} = ? WHERE user_id = ?",
                    (value, user_id)
                )

            db.commit()

            # reload updated profile
            student = db.execute(
                "SELECT * FROM students WHERE user_id = ?",
                (user_id,)
            ).fetchone()

            profile = dict(student)

        remaining_fields = [
            field for field in REQUIRED_FIELDS
            if not profile.get(field)
        ]

        if remaining_fields:
            questions = {
                "grade": "What grade are you currently in?",
                "weak_subject": "Which subject do you want to improve?",
                "learning_style": "How do you learn best? (visual / reading / practice)",
                "learning_goal": "What is your learning goal?"
            }

            return jsonify({
                "message": questions[remaining_fields[0]]
            })

    # Generate roadmap
    response = generate_recommendation(profile, user_message=message)

    return jsonify({
        "message": response
    })
# ───────────────────────── ERROR HANDLERS ───────────────────────── #

@jwt.unauthorized_loader
def missing_token_callback(err):
    return jsonify({"error": "Authorization token required"}), 401


@jwt.invalid_token_loader
def invalid_token_callback(err):
    return jsonify({"error": "Invalid token"}), 401


@jwt.expired_token_loader
def expired_token_callback(jwt_header, jwt_payload):
    return jsonify({"error": "Token expired"}), 401


# ───────────────────────── RUN ───────────────────────── #

if __name__ == "__main__":
    app.run(debug=True)