"""
services/db_service.py
──────────────────────
Every Supabase read/write lives here.
Routes call DatabaseService methods — they never touch supabase directly.
"""

from datetime import datetime, timezone, timedelta
from flask import session
from config import supabase, TOOL_XP


class DatabaseService:

    # ── Tool use logging ───────────────────────────────────────────────────

    @staticmethod
    def log_tool_use(tool_name: str) -> None:
        """Insert a tool_uses row if the user is logged in. Silent on failure."""
        try:
            user = session.get("user")
            if not user:
                return
            supabase.table("tool_uses").insert({
                "user_id":   user["id"],
                "tool_name": tool_name,
                "xp_earned": TOOL_XP.get(tool_name, 0),
                "used_at":   datetime.now(timezone.utc).isoformat()
            }).execute()
            print(f"[DB] tool_use logged: {tool_name} for {user['id']}")
        except Exception as e:
            print(f"[DB] log_tool_use failed for {tool_name}: {type(e).__name__}: {e}")

    # ── User stats ─────────────────────────────────────────────────────────

    @staticmethod
    def get_user_stats(user_id: str) -> dict:
        """Return xp/streak/tools_used for a user, or zeroed defaults."""
        result = supabase.table("user_stats").select("*").eq("user_id", user_id).execute()
        if result.data:
            return result.data[0]
        return {"xp": 0, "streak": 0, "tools_used": 0}

    @staticmethod
    def save_user_stats(user_id: str, xp: int, streak: int, tools_used: int) -> None:
        supabase.table("user_stats").upsert({
            "user_id":    user_id,
            "xp":         xp,
            "streak":     streak,
            "tools_used": tools_used,
        }).execute()

    @staticmethod
    def get_user_rank(user_id: str, current_xp: int) -> int:
        """Return 1-based rank (number of users with more XP + 1)."""
        result = (
            supabase.table("user_stats")
            .select("user_id", count="exact")
            .gt("xp", current_xp)
            .execute()
        )
        return (result.count or 0) + 1

    # ── User upsert (auth callback) ────────────────────────────────────────

    @staticmethod
    def upsert_user(user_id: str, email: str, display_name: str, avatar_url: str) -> None:
        supabase.table("users").upsert({
            "id":           user_id,
            "email":        email,
            "display_name": display_name,
            "avatar_url":   avatar_url,
        }).execute()

    @staticmethod
    def ensure_user_stats_row(user_id: str) -> None:
        """Create a zeroed user_stats row if one doesn't exist yet."""
        existing = supabase.table("user_stats").select("*").eq("user_id", user_id).execute()
        if not existing.data:
            supabase.table("user_stats").insert({
                "user_id":    user_id,
                "xp":         0,
                "streak":     0,
                "tools_used": 0,
            }).execute()

    # ── Leaderboard ────────────────────────────────────────────────────────

    @staticmethod
    def get_global_leaderboard(limit: int = 50) -> list[dict]:
        try:
            result = (
                supabase.table("user_stats")
                .select("xp, user_id, users(display_name, avatar_url)")
                .order("xp", desc=True)
                .limit(limit)
                .execute()
            )
            rows = []
            for row in result.data:
                info = row.get("users") or {}
                rows.append({
                    "xp":           row.get("xp", 0),
                    "user_id":      row.get("user_id"),
                    "display_name": info.get("display_name") or "Anonymous",
                    "avatar_url":   info.get("avatar_url") or "",
                })
            return rows
        except Exception as e:
            print(f"[DB] global leaderboard error: {e}")
            return []

    @staticmethod
    def get_weekly_leaderboard(limit: int = 50) -> list[dict]:
        try:
            now = datetime.now(timezone.utc)
            week_start = (now - timedelta(days=now.weekday())).replace(
                hour=0, minute=0, second=0, microsecond=0
            )

            result = (
                supabase.table("tool_uses")
                .select("user_id, xp_earned")
                .gte("used_at", week_start.isoformat())
                .execute()
            )

            totals: dict[str, int] = {}
            for row in result.data:
                uid = row["user_id"]
                totals[uid] = totals.get(uid, 0) + row.get("xp_earned", 0)

            if not totals:
                return []

            user_ids = list(totals.keys())
            users_result = (
                supabase.table("users")
                .select("id, display_name, avatar_url")
                .in_("id", user_ids)
                .execute()
            )
            user_map = {u["id"]: u for u in (users_result.data or [])}

            rows = []
            for uid, xp in sorted(totals.items(), key=lambda x: x[1], reverse=True)[:limit]:
                u = user_map.get(uid, {})
                rows.append({
                    "user_id":      uid,
                    "xp":           xp,
                    "display_name": u.get("display_name") or "Anonymous",
                    "avatar_url":   u.get("avatar_url") or "",
                })
            return rows
        except Exception as e:
            print(f"[DB] weekly leaderboard error: {e}")
            return []
