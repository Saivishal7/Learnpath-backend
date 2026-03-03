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