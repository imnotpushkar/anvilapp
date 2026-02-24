"""
routes/user.py
──────────────
User stats, XP saving, and leaderboard endpoints.
Blueprint: user_bp  prefix: /api
"""

from flask import Blueprint, jsonify, request, session
from services.db_service import DatabaseService

user_bp = Blueprint("user", __name__, url_prefix="/api")


@user_bp.route("/user/stats", methods=["GET"])
def get_user_stats():
    user = session.get("user")
    if not user:
        return jsonify({"error": "not logged in"}), 401
    stats = DatabaseService.get_user_stats(user["id"])
    return jsonify(stats)


@user_bp.route("/user/xp", methods=["POST"])
def save_xp():
    user = session.get("user")
    if not user:
        return jsonify({"error": "not logged in"}), 401
    data = request.json
    DatabaseService.save_user_stats(
        user_id    = user["id"],
        xp         = data.get("xp", 0),
        streak     = data.get("streak", 0),
        tools_used = data.get("tools_used", 0),
    )
    return jsonify({"success": True})


@user_bp.route("/leaderboard", methods=["GET"])
def leaderboard():
    rows = DatabaseService.get_global_leaderboard()
    return jsonify(rows)


@user_bp.route("/leaderboard/weekly", methods=["GET"])
def leaderboard_weekly():
    rows = DatabaseService.get_weekly_leaderboard()
    return jsonify(rows)


@user_bp.route("/leaderboard/personal", methods=["GET"])
def leaderboard_personal():
    user = session.get("user")
    if not user:
        return jsonify({"error": "not logged in"}), 401
    try:
        stats = DatabaseService.get_user_stats(user["id"])
        stats["rank"] = DatabaseService.get_user_rank(user["id"], stats.get("xp", 0))
        return jsonify(stats)
    except Exception as e:
        print(f"[USER] personal leaderboard error: {e}")
        return jsonify({"xp": 0, "streak": 0, "tools_used": 0, "rank": "—"}), 200
