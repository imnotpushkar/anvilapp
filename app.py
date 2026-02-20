from flask import Flask, render_template, request, jsonify, redirect, session
from groq import Groq
from comics import get_comic_prompt, get_resume_prompt, COMIC_OPTIONS
from dotenv import load_dotenv
from supabase import create_client, Client
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


def ask_groq(prompt):
    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role": "user", "content": prompt}]
    )
    return response.choices[0].message.content


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
        print(f"[AUTH] Session exchange result: {result}")
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
        result = supabase.table("user_stats").select("xp, streak, tools_used, user_id").order("xp", desc=True).limit(50).execute()
        rows = result.data or []
        # Enrich with user info from session or users table
        enriched = []
        for i, row in enumerate(rows):
            enriched.append({
                "rank": i + 1,
                "xp": row.get("xp", 0),
                "streak": row.get("streak", 0),
                "tools_used": row.get("tools_used", 0),
                "user_id": row.get("user_id"),
                "display_name": "Anonymous",
                "avatar_url": ""
            })
        return jsonify(enriched)
    except Exception as e:
        print(f"[LEADERBOARD] Error: {e}")
        return jsonify([])


@app.route("/api/leaderboard/weekly", methods=["GET"])
def leaderboard_weekly():
    try:
        from datetime import datetime, timedelta
        start_of_week = (datetime.utcnow() - timedelta(days=datetime.utcnow().weekday())).strftime("%Y-%m-%dT00:00:00")
        result = supabase.table("tool_uses").select("user_id, xp_earned").gte("used_at", start_of_week).execute()
        rows = result.data or []

        # Aggregate XP per user
        weekly_xp = {}
        for row in rows:
            uid = row["user_id"]
            weekly_xp[uid] = weekly_xp.get(uid, 0) + row.get("xp_earned", 0)

        # Sort and rank
        sorted_users = sorted(weekly_xp.items(), key=lambda x: x[1], reverse=True)[:50]
        enriched = []
        for i, (uid, xp) in enumerate(sorted_users):
            enriched.append({
                "rank": i + 1,
                "user_id": uid,
                "xp": xp,
                "display_name": "Anonymous",
                "avatar_url": ""
            })
        return jsonify(enriched)
    except Exception as e:
        print(f"[LEADERBOARD/WEEKLY] Error: {e}")
        return jsonify([])


@app.route("/api/leaderboard/personal", methods=["GET"])
def leaderboard_personal():
    user = session.get("user")
    if not user:
        return jsonify({"error": "not logged in"}), 401
    try:
        # Get user stats
        stats = supabase.table("user_stats").select("*").eq("user_id", user["id"]).execute()
        user_data = stats.data[0] if stats.data else {"xp": 0, "streak": 0, "tools_used": 0}

        # Get global rank — count users with more XP
        higher = supabase.table("user_stats").select("user_id", count="exact").gt("xp", user_data.get("xp", 0)).execute()
        rank = (higher.count or 0) + 1

        # Get achievements
        achievements = supabase.table("achievements").select("*").eq("user_id", user["id"]).execute()

        return jsonify({
            "name": user.get("name", ""),
            "avatar": user.get("avatar", ""),
            "xp": user_data.get("xp", 0),
            "streak": user_data.get("streak", 0),
            "tools_used": user_data.get("tools_used", 0),
            "rank": rank,
            "achievements": achievements.data or []
        })
    except Exception as e:
        print(f"[LEADERBOARD/PERSONAL] Error: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/roast", methods=["POST"])
def roast():
    data = request.json
    prompt = get_comic_prompt(data.get("comic"), data.get("salary"), data.get("city"), data.get("age"), data.get("field"))
    return jsonify({"message": ask_groq(prompt)})


@app.route("/api/idea", methods=["POST"])
def idea():
    data = request.json
    prompt = f"""You are a sharp startup analyst with a dark sense of humor.
    Analyze this startup idea and tell the person:
    1. If it already exists (and name competitors)
    2. How original it actually is (score out of 10)
    3. Whether it has potential or is dead on arrival
    4. One savage but constructive piece of advice
    Idea: {data.get("idea")}
    Target Market: {data.get("market")}
    Keep it punchy, honest, and slightly brutal. 4-5 sentences max."""
    return jsonify({"message": ask_groq(prompt)})


@app.route("/api/stack", methods=["POST"])
def stack():
    data = request.json
    prompt = f"""You are an opinionated senior developer who gives direct tech stack recommendations.
    Recommend a tech stack for this project. Be specific and decisive - no wishy-washy answers.
    Project: {data.get("project")}
    Developer Experience Level: {data.get("level")}
    Priority: {data.get("priority")}
    Format your answer as:
    FRONTEND: ...
    BACKEND: ...
    DATABASE: ...
    HOSTING: ...
    WHY: one punchy sentence explaining the choice."""
    return jsonify({"message": ask_groq(prompt)})


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
    return jsonify({"message": ask_groq(get_resume_prompt(comic, resume_content))})


if __name__ == "__main__":
    app.run(debug=True)
