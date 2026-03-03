from flask_jwt_extended import jwt_required, get_jwt_identity
from flask import jsonify
from datetime import datetime, timedelta
from flask import g


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
from database import init_db, get_db, migrate_admin_columns
from recommendations import get_recommendations
from timetable import generate_timetable
import hashlib
import os

# ───────────────────────── APP SETUP ───────────────────────── #

app = Flask(__name__)
CORS(
    app,
    resources={r"/api/*": {"origins": "*"}},
    allow_headers=["Content-Type", "Authorization"],
    methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"]
)


app.config["JWT_SECRET_KEY"] = os.environ.get(
    "JWT_SECRET_KEY",
    "super-secret-key"  # Change this in production!
)

jwt = JWTManager(app)


with app.app_context():
    init_db()
    migrate_admin_columns()

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
        db.execute(
            "INSERT INTO users (username, password_hash, role) VALUES (?, ?, 'student')",
            (username, pw_hash)
        )
        db.commit()
        return jsonify({"message": "Account created successfully"}), 201

    except Exception:
        return jsonify({"error": "Username already exists"}), 400


# 🔥 DEBUG ROUTE (OUTSIDE REGISTER FUNCTION — VERY IMPORTANT)
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

@app.route("/api/debug/tables")
def debug_tables():
    db = get_db()
    tables = db.execute(
        "SELECT name FROM sqlite_master WHERE type='table';"
    ).fetchall()
    return jsonify([t["name"] for t in tables])

# ───────────────────────── CHATBOT ───────────────────────── #

@app.route("/api/chat", methods=["POST"])
@jwt_required()
def api_chat():
    data = request.get_json()

    if not data or "message" not in data:
        return jsonify({"error": "Message required"}), 400

    message = data["message"].lower().strip()
    user_id = get_jwt_identity()
    db = get_db()

    # Get stored context
    context = db.execute(
        "SELECT subject, goal, style FROM chat_context WHERE user_id=?",
        (user_id,)
    ).fetchone()

    subject = context["subject"] if context else None
    goal = context["goal"] if context else None
    style = context["style"] if context else None

    # 1️⃣ SUBJECT STEP
    subjects = ["mathematics", "science", "english", "history", "geography", "computer"]
    for s in subjects:
        if s in message:
            subject = s.capitalize()
            goal = None
            style = None

            db.execute(
                "INSERT OR REPLACE INTO chat_context (user_id, subject, goal, style) VALUES (?, ?, ?, ?)",
                (user_id, subject, None, None)
            )
            db.commit()

            return jsonify({"message": f"Great! What is your goal for {subject}?"})

    # 2️⃣ GOAL STEP (only if subject exists AND goal not yet set)
    if subject and not goal:
        if "exam" in message:
            goal = "Exam preparation"
        elif "improve" in message:
            goal = "Improve grades"
        elif "foundation" in message:
            goal = "Build strong foundation"

        if goal:
            db.execute(
                "INSERT OR REPLACE INTO chat_context (user_id, subject, goal, style) VALUES (?, ?, ?, ?)",
                (user_id, subject, goal, None)
            )
            db.commit()

            return jsonify({
                "message": "Nice! What learning style do you prefer? (Visual / Auditory / Reading / Kinesthetic)"
            })

    # 3️⃣ STYLE STEP (only if subject AND goal exist AND style not set)
    styles = ["visual", "auditory", "reading", "kinesthetic"]

    if subject and goal and not style:
        for s in styles:
            if s in message:
                style = s.capitalize()

                db.execute(
                    "INSERT OR REPLACE INTO chat_context (user_id, subject, goal, style) VALUES (?, ?, ?, ?)",
                    (user_id, subject, goal, style)
                )
                db.commit()

                recommendations = get_recommendations(
                    "User",
                    "Grade",
                    subject,
                    goal,
                    style
                )

                return jsonify({
                    "type": "recommendation",
                    "data": {
                        "recommended_courses": recommendations,
                        "reasoning": f"Generated plan for {subject} with {style} learning style."
                    }
                })

    # 4️⃣ STUDY PLAN REQUEST
    if "study plan" in message and subject and goal and style:
        recommendations = get_recommendations(
            "User",
            "Grade",
            subject,
            goal,
            style
        )

        return jsonify({
            "type": "recommendation",
            "data": {
                "recommended_courses": recommendations,
                "reasoning": f"Custom study plan for {subject}."
            }
        })

    return jsonify({"message": "Tell me your subject to begin."})
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





# ───────────────────────── DB CLEANUP ───────────────────────── #

@app.teardown_appcontext
def close_db(exception):
    db = g.pop("db", None)
    if db is not None:
        db.close()

# ───────────────────────── RUN ───────────────────────── #

if __name__ == "__main__":
    app.run(debug=True)