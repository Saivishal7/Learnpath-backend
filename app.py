from flask import Flask, request, jsonify
from flask_jwt_extended import JWTManager, create_access_token, jwt_required, get_jwt
from flask_cors import CORS
from database import init_db, get_db
from recommendations import get_recommendations
from timetable import generate_timetable
import hashlib, os

app = Flask(__name__)

# JWT Configuration
app.config["JWT_SECRET_KEY"] = os.environ.get("JWT_SECRET_KEY", "super-secret-key")
jwt = JWTManager(app)

# Enable CORS
CORS(app)

# Initialize Database
with app.app_context():
    init_db()


# ───────────────────────── AUTH ───────────────────────── #

@app.route("/api/register", methods=["POST"])
def api_register():
    data = request.json

    username = data.get("username", "").strip()
    password = data.get("password", "")

    pw_hash = hashlib.sha256(password.encode()).hexdigest()
    db = get_db()

    try:
        db.execute(
            "INSERT INTO users (username, password_hash, role) VALUES (?, ?, 'student')",
            (username, pw_hash)
        )
        db.commit()
        return jsonify({"message": "Account created successfully"})
    except Exception:
        return jsonify({"error": "Username already exists"}), 400


@app.route("/api/login", methods=["POST"])
def api_login():
    data = request.json

    username = data.get("username", "").strip()
    password = data.get("password", "")
    pw_hash = hashlib.sha256(password.encode()).hexdigest()

    db = get_db()
    user = db.execute(
        "SELECT * FROM users WHERE username=? AND password_hash=?",
        (username, pw_hash)
    ).fetchone()

    if not user:
        return jsonify({"error": "Invalid credentials"}), 401

    token = create_access_token(
        identity=str(user["id"]),
        additional_claims={
            "role": user["role"],
            "username": user["username"]
        }
    )

    return jsonify({
        "token": token,
        "role": user["role"],
        "username": user["username"]
    })


# ───────────────────────── RECOMMENDATION ───────────────────────── #

@app.route("/api/recommend", methods=["POST"])
@jwt_required()
def api_recommend():
    data = request.json

    name = data.get("name", "")
    grade = data.get("grade", "")
    subject = data.get("subject", "Mathematics")
    goal = data.get("goal", "Improve grades")
    style = data.get("style", "Visual")

    recommendation_data = get_recommendations(name, grade, subject, goal, style)
    timetable = generate_timetable(subject, style, goal)

    return jsonify({
        "recommendations": recommendation_data,
        "timetable": timetable
    })


# ───────────────────────── ADMIN DASHBOARD ───────────────────────── #

@app.route("/api/admin/dashboard", methods=["GET"])
@jwt_required()
def api_dashboard():
    claims = get_jwt()

    # Role check
    if claims.get("role") != "admin":
        return jsonify({"error": "Admin access required"}), 403

    db = get_db()

    total_students = db.execute(
        "SELECT COUNT(*) FROM students"
    ).fetchone()[0]

    total_logs = db.execute(
        "SELECT COUNT(*) FROM progress_logs"
    ).fetchone()[0]

    return jsonify({
        "total_students": total_students,
        "total_logs": total_logs
    })


if __name__ == "__main__":
    app.run(debug=True)