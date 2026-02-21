from flask import Flask, render_template, request, jsonify, redirect, session
from groq import Groq
from comics import get_comic_prompt, get_resume_prompt, get_garbage_prompt, is_garbage_input, COMIC_OPTIONS
from dotenv import load_dotenv
from supabase import create_client, Client
from datetime import datetime, timezone
import os

load_dotenv()

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "anvil-dev-secret")

# Groq client
client = Groq(api_key=os.environ.get("GROQ_API_KEY"))

# Supabase client
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_ANON_KEY = os.environ.get("SUPABASE_ANON_KEY")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_ANON_KEY)

# XP values per tool
TOOL_XP = {
    "roast": 25,
    "idea": 30,
    "stack": 20,
    "resume": 35
}


def ask_groq(prompt):
    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role": "user", "content": prompt}]
    )
    return response.choices[0].message.content


def log_tool_use(tool_name):
    """Insert a row into tool_uses if user is logged in."""
    try:
        user = session.get("user")
        if not user:
            print(f"[TOOL_USES] Skipping — no user in session")
            return
        print(f"[TOOL_USES] Attempting insert for user {user['id']} tool {tool_name}")
        result = supabase.table("tool_uses").insert({
            "user_id": user["id"],
            "tool_name": tool_name,
            "xp_earned": TOOL_XP.get(tool_name, 0),
            "used_at": datetime.now(timezone.utc).isoformat()
        }).execute()
        print(f"[TOOL_USES] Insert result: {result}")
    except Exception as e:
        print(f"[TOOL_USES] Failed to log {tool_name}: {type(e).__name__}: {e}")


@app.route("/ping")
def ping():
    return "pong", 200


@app.route("/")
def index():
    user = session.get("user")
    return render_template("index.html", comic_options=COMIC_OPTIONS, user=user)


@app.route("/auth/login")
def login():
    redirect_url = request.url_root.rstrip("/") + "/auth/callback"
    result = supabase.auth.sign_in_with_oauth({
        "provider": "google",
        "options": {"redirect_to": redirect_url}
    })
    return redirect(result.url)


@app.route("/auth/callback")
def auth_callback():
    code = request.args.get("code")
    print(f"[AUTH] Callback hit. Code present: {bool(code)}")
    print(f"[AUTH] Full URL: {request.url}")

    if not code:
        print("[AUTH] No code in callback — redirecting home")
        return redirect("/")

    try:
        result = supabase.auth.exchange_code_for_session({"auth_code": code})
        user = result.user
        access_token = result.session.access_token
        print(f"[AUTH] User: {user.email}")

        session["user"] = {
            "id": user.id,
            "email": user.email,
            "name": user.user_metadata.get("full_name", user.email),
            "avatar": user.user_metadata.get("avatar_url", ""),
            "access_token": access_token
        }

        # Save display name + avatar to users table
        supabase.table("users").upsert({
            "id": user.id,
            "email": user.email,
            "display_name": user.user_metadata.get("full_name", user.email),
            "avatar_url": user.user_metadata.get("avatar_url", "")
        }).execute()

        # Create user_stats row if first login
        existing = supabase.table("user_stats").select("*").eq("user_id", user.id).execute()
        if not existing.data:
            supabase.table("user_stats").insert({
                "user_id": user.id,
                "xp": 0,
                "streak": 0,
                "tools_used": 0
            }).execute()

        print("[AUTH] Login successful")
    except Exception as e:
        print(f"[AUTH] Error: {type(e).__name__}: {e}")

    return redirect("/")


@app.route("/auth/logout")
def logout():
    session.clear()
    return redirect("/")


@app.route("/api/user/stats", methods=["GET"])
def get_user_stats():
    user = session.get("user")
    if not user:
        return jsonify({"error": "not logged in"}), 401
    result = supabase.table("user_stats").select("*").eq("user_id", user["id"]).execute()
    if result.data:
        return jsonify(result.data[0])
    return jsonify({"xp": 0, "streak": 0, "tools_used": 0})


@app.route("/api/user/xp", methods=["POST"])
def save_xp():
    user = session.get("user")
    if not user:
        return jsonify({"error": "not logged in"}), 401
    data = request.json
    supabase.table("user_stats").upsert({
        "user_id": user["id"],
        "xp": data.get("xp", 0),
        "streak": data.get("streak", 0),
        "tools_used": data.get("tools_used", 0)
    }).execute()
    return jsonify({"success": True})


@app.route("/api/leaderboard", methods=["GET"])
def leaderboard():
    try:
        result = supabase.table("user_stats").select("xp, user_id, users(display_name, avatar_url)").order("xp", desc=True).limit(50).execute()
        rows = []
        for row in result.data:
            user_info = row.get("users") or {}
            rows.append({
                "xp": row.get("xp", 0),
                "user_id": row.get("user_id"),
                "display_name": user_info.get("display_name") or "Anonymous",
                "avatar_url": user_info.get("avatar_url") or ""
            })
        return jsonify(rows)
    except Exception as e:
        print(f"[LEADERBOARD] Error: {e}")
        return jsonify([]), 200


@app.route("/api/leaderboard/weekly", methods=["GET"])
def leaderboard_weekly():
    try:
        # Get start of current week (Monday)
        now = datetime.now(timezone.utc)
        week_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        week_start = week_start.replace(day=now.day - now.weekday())
        week_start_iso = week_start.isoformat()

        # Sum XP earned per user this week from tool_uses
        result = supabase.table("tool_uses").select("user_id, xp_earned").gte("used_at", week_start_iso).execute()

        # Aggregate XP per user
        totals = {}
        for row in result.data:
            uid = row["user_id"]
            totals[uid] = totals.get(uid, 0) + row.get("xp_earned", 0)

        if not totals:
            return jsonify([]), 200

        # Get display names for all user_ids in the result
        user_ids = list(totals.keys())
        users_result = supabase.table("users").select("id, display_name, avatar_url").in_("id", user_ids).execute()
        user_map = {u["id"]: u for u in (users_result.data or [])}

        # Build sorted leaderboard
        rows = []
        for uid, xp in sorted(totals.items(), key=lambda x: x[1], reverse=True)[:50]:
            u = user_map.get(uid, {})
            rows.append({
                "user_id": uid,
                "xp": xp,
                "display_name": u.get("display_name") or "Anonymous",
                "avatar_url": u.get("avatar_url") or ""
            })

        return jsonify(rows)
    except Exception as e:
        print(f"[WEEKLY] Error: {e}")
        return jsonify([]), 200


@app.route("/api/leaderboard/personal", methods=["GET"])
def leaderboard_personal():
    user = session.get("user")
    if not user:
        return jsonify({"error": "not logged in"}), 401
    try:
        # Get user stats
        result = supabase.table("user_stats").select("*").eq("user_id", user["id"]).execute()
        stats = result.data[0] if result.data else {"xp": 0, "streak": 0, "tools_used": 0}

        # Calculate rank — count how many users have strictly more XP
        rank_result = supabase.table("user_stats").select("user_id", count="exact").gt("xp", stats.get("xp", 0)).execute()
        rank = (rank_result.count or 0) + 1

        stats["rank"] = rank
        return jsonify(stats)
    except Exception as e:
        print(f"[PERSONAL] Error: {e}")
        return jsonify({"xp": 0, "streak": 0, "tools_used": 0, "rank": "—"}), 200


@app.route("/api/roast", methods=["POST"])
def roast():
    data = request.json
    prompt = get_comic_prompt(data.get("comic"), data.get("salary"), data.get("city"), data.get("age"), data.get("field"))
    result = ask_groq(prompt)
    log_tool_use("roast")
    return jsonify({"message": result})


@app.route("/api/idea", methods=["POST"])
def idea():
    data = request.json
    idea_text = data.get("idea", "")
    market_text = data.get("market", "")
    comic = data.get("comic", "abhishek_upmanyu")

    for val, label in [(idea_text, "idea"), (market_text, "market")]:
        garbage, g_reason = is_garbage_input(str(val))
        if garbage:
            return jsonify({"message": ask_groq(get_garbage_prompt(comic, "idea", val, g_reason))})

    prompt = f"""You are a sharp startup analyst with a dark sense of humor.
    Analyze this startup idea and tell the person:
    1. If it already exists (and name competitors)
    2. How original it actually is (score out of 10)
    3. Whether it has potential or is dead on arrival
    4. One savage but constructive piece of advice
    Idea: {idea_text}
    Target Market: {market_text}
    Keep it punchy, honest, and slightly brutal. 4-5 sentences max."""
    result = ask_groq(prompt)
    log_tool_use("idea")
    return jsonify({"message": result})


@app.route("/api/stack", methods=["POST"])
def stack():
    data = request.json
    project_text = data.get("project", "")
    comic = data.get("comic", "abhishek_upmanyu")

    garbage, g_reason = is_garbage_input(str(project_text))
    if garbage:
        return jsonify({"message": ask_groq(get_garbage_prompt(comic, "stack", project_text, g_reason))})

    prompt = f"""You are an opinionated senior developer who gives direct tech stack recommendations.
    Recommend a tech stack for this project. Be specific and decisive - no wishy-washy answers.
    Project: {project_text}
    Developer Experience Level: {data.get("level")}
    Priority: {data.get("priority")}
    Format your answer as:
    FRONTEND: ...
    BACKEND: ...
    DATABASE: ...
    HOSTING: ...
    WHY: one punchy sentence explaining the choice."""
    result = ask_groq(prompt)
    log_tool_use("stack")
    return jsonify({"message": result})


@app.route("/api/resume", methods=["POST"])
def resume():
    data = request.json
    mode = data.get("mode")
    comic = data.get("comic")
    if mode == "paste":
        resume_content = data.get("resume_text", "").strip()
    else:
        resume_content = f"Name/Title: {data.get('name','')}\nExperience: {data.get('experience','')}\nSkills: {data.get('skills','')}\nEducation: {data.get('education','')}"
    if not resume_content:
        return jsonify({"error": "No resume content provided"}), 400
    result = ask_groq(get_resume_prompt(comic, resume_content))
    log_tool_use("resume")
    return jsonify({"message": result})


if __name__ == "__main__":
    app.run(debug=True)
