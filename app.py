from flask import Flask, render_template, request, jsonify, redirect, session
from groq import Groq
from comics import get_resume_prompt, get_linkedin_prompt, get_linkedin_create_prompt, get_idea_create_prompt, get_stack_create_prompt, get_resume_create_prompt, get_garbage_prompt, is_garbage_input, COMIC_OPTIONS
from dotenv import load_dotenv
from supabase import create_client, Client
from datetime import datetime, timezone, timedelta
import os

load_dotenv()

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "anvil-dev-secret")

# Groq client
client = Groq(api_key=os.environ.get("GROQ_API_KEY"))

# Supabase client
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_ANON_KEY = os.environ.get("SUPABASE_ANON_KEY")

if not SUPABASE_URL or not SUPABASE_ANON_KEY:
    raise RuntimeError("Missing SUPABASE_URL or SUPABASE_ANON_KEY — check your .env or Render env vars")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_ANON_KEY)

# XP values per tool
TOOL_XP = {
    "linkedin": 25,
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
            return
        supabase.table("tool_uses").insert({
            "user_id": user["id"],
            "tool_name": tool_name,
            "xp_earned": TOOL_XP.get(tool_name, 0),
            "used_at": datetime.now(timezone.utc).isoformat()
        }).execute()
        print(f"[TOOL_USES] {tool_name} logged for {user['id']}")
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

        supabase.table("users").upsert({
            "id": user.id,
            "email": user.email,
            "display_name": user.user_metadata.get("full_name", user.email),
            "avatar_url": user.user_metadata.get("avatar_url", "")
        }).execute()

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
        now = datetime.now(timezone.utc)
        week_start = (now - timedelta(days=now.weekday())).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        week_start_iso = week_start.isoformat()

        result = supabase.table("tool_uses").select("user_id, xp_earned").gte("used_at", week_start_iso).execute()

        totals = {}
        for row in result.data:
            uid = row["user_id"]
            totals[uid] = totals.get(uid, 0) + row.get("xp_earned", 0)

        if not totals:
            return jsonify([]), 200

        user_ids = list(totals.keys())
        users_result = supabase.table("users").select("id, display_name, avatar_url").in_("id", user_ids).execute()
        user_map = {u["id"]: u for u in (users_result.data or [])}

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
        result = supabase.table("user_stats").select("*").eq("user_id", user["id"]).execute()
        stats = result.data[0] if result.data else {"xp": 0, "streak": 0, "tools_used": 0}

        rank_result = supabase.table("user_stats").select("user_id", count="exact").gt("xp", stats.get("xp", 0)).execute()
        rank = (rank_result.count or 0) + 1

        stats["rank"] = rank
        return jsonify(stats)
    except Exception as e:
        print(f"[PERSONAL] Error: {e}")
        return jsonify({"xp": 0, "streak": 0, "tools_used": 0, "rank": "—"}), 200


@app.route("/api/linkedin", methods=["POST"])
def linkedin():
    data = request.json
    mode = data.get("mode", "check")
    content_type = data.get("content_type", "post")
    comic = data.get("comic", "abhishek_upmanyu")

    if mode == "create":
        intent = data.get("intent", "").strip()
        garbage, g_reason = is_garbage_input(intent)
        if garbage:
            return jsonify({"message": ask_groq(get_garbage_prompt(comic, "linkedin", intent, g_reason))})
        prompt = get_linkedin_create_prompt(comic, content_type, intent)
    else:
        content = data.get("content", "").strip()
        garbage, g_reason = is_garbage_input(content)
        if garbage:
            return jsonify({"message": ask_groq(get_garbage_prompt(comic, "linkedin", content, g_reason))})
        prompt = get_linkedin_prompt(comic, content_type, content)

    result = ask_groq(prompt)
    log_tool_use("linkedin")
    return jsonify({"message": result})


@app.route("/api/idea", methods=["POST"])
def idea():
    data = request.json
    mode = data.get("mode", "check")
    comic = data.get("comic", "abhishek_upmanyu")

    if mode == "create":
        skills = data.get("skills", "").strip()
        interests = data.get("interests", "").strip()
        for val, label in [(skills, "skills"), (interests, "interests")]:
            garbage, g_reason = is_garbage_input(str(val))
            if garbage:
                return jsonify({"message": ask_groq(get_garbage_prompt(comic, "idea", val, g_reason))})
        edge = data.get("edge", "")
        role = data.get("role", "")
        market = data.get("market", "")
        idea_type = data.get("idea_type", "")
        time_commit = data.get("time", "")
        budget = data.get("budget", "")
        team = data.get("team", "")
        prompt = get_idea_create_prompt(comic, skills, interests, edge=edge, role=role, market=market, idea_type=idea_type, time_commit=time_commit, budget=budget, team=team)
    else:
        idea_text = data.get("idea", "")
        market_text = data.get("market", "")
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
    mode = data.get("mode", "check")
    comic = data.get("comic", "abhishek_upmanyu")

    if mode == "create":
        interests = data.get("interests", "").strip()
        garbage, g_reason = is_garbage_input(str(interests))
        if garbage:
            return jsonify({"message": ask_groq(get_garbage_prompt(comic, "stack", interests, g_reason))})
        shipped = data.get("shipped", "")
        known = data.get("known", "")
        learn = data.get("learn", "")
        exp = data.get("exp", "")
        pref = data.get("pref", "")
        goal = data.get("goal", "")
        time_commit = data.get("time", "")
        deadline = data.get("deadline", "")
        prompt = get_stack_create_prompt(comic, interests, shipped=shipped, known=known, learn=learn, exp=exp, pref=pref, goal=goal, time_commit=time_commit, deadline=deadline)
    else:
        project_text = data.get("project", "")
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
    mode = data.get("mode", "paste")
    comic = data.get("comic", "abhishek_upmanyu")

    if mode == "create":
        name = data.get("name", "").strip()
        if not name:
            return jsonify({"error": "Name is required"}), 400
        result = ask_groq(get_resume_create_prompt(
            comic,
            name,
            data.get("role", ""),
            data.get("experience", ""),
            data.get("projects", ""),
            data.get("skills", ""),
            data.get("education", "")
        ))
        log_tool_use("resume")
        return jsonify({"message": result})

    if mode == "paste":
        resume_content = data.get("resume_text", "").strip()
    else:
        name = data.get("name", "")
        role = data.get("role", "")
        experience = data.get("experience", "")
        projects = data.get("projects", "")
        skills = data.get("skills", "")
        education = data.get("education", "")
        resume_content = (
            f"Name/Role: {name} — {role}\n"
            f"Experience: {experience}\n"
            f"Projects: {projects}\n"
            f"Skills: {skills}\n"
            f"Education: {education}"
        ).strip()

    if not resume_content:
        return jsonify({"error": "No resume content provided"}), 400

    garbage, g_reason = is_garbage_input(resume_content)
    if garbage:
        return jsonify({"message": ask_groq(get_garbage_prompt(comic, "resume", resume_content, g_reason))})

    result = ask_groq(get_resume_prompt(comic, resume_content, mode=mode))
    log_tool_use("resume")
    return jsonify({"message": result})


if __name__ == "__main__":
    app.run(debug=True)
