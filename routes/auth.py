"""
routes/auth.py
──────────────
Google OAuth flow via Supabase.
Blueprint: auth_bp  prefix: /auth
"""

from flask import Blueprint, redirect, request, session
from config import supabase
from services.db_service import DatabaseService

auth_bp = Blueprint("auth", __name__, url_prefix="/auth")


@auth_bp.route("/login")
def login():
    redirect_url = request.url_root.rstrip("/") + "/auth/callback"
    result = supabase.auth.sign_in_with_oauth({
        "provider": "google",
        "options":  {"redirect_to": redirect_url}
    })
    return redirect(result.url)


@auth_bp.route("/callback")
def callback():
    code = request.args.get("code")
    print(f"[AUTH] Callback hit. Code present: {bool(code)}")
    print(f"[AUTH] Full URL: {request.url}")

    if not code:
        print("[AUTH] No code in callback — redirecting home")
        return redirect("/")

    try:
        result      = supabase.auth.exchange_code_for_session({"auth_code": code})
        user        = result.user
        access_token = result.session.access_token
        print(f"[AUTH] User: {user.email}")

        session["user"] = {
            "id":           user.id,
            "email":        user.email,
            "name":         user.user_metadata.get("full_name", user.email),
            "avatar":       user.user_metadata.get("avatar_url", ""),
            "access_token": access_token,
        }

        DatabaseService.upsert_user(
            user_id      = user.id,
            email        = user.email,
            display_name = user.user_metadata.get("full_name", user.email),
            avatar_url   = user.user_metadata.get("avatar_url", ""),
        )
        DatabaseService.ensure_user_stats_row(user.id)
        print("[AUTH] Login successful")

    except Exception as e:
        print(f"[AUTH] Error: {type(e).__name__}: {e}")

    return redirect("/")


@auth_bp.route("/logout")
def logout():
    session.clear()
    return redirect("/")
