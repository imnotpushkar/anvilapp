from flask import Flask, render_template, request, jsonify, redirect, session
from groq import Groq
from comics import get_comic_prompt, get_resume_prompt, get_garbage_prompt, is_garbage_input, COMIC_OPTIONS
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
    result = supabase.table("user_stats").select("xp, users(display_name, avatar_url)").order("xp", desc=True).limit(50).execute()
    return jsonify(result.data)


@app.route("/api/roast", methods=["POST"])
def roast():
    data = request.json
    prompt = get_comic_prompt(data.get("comic"), data.get("salary"), data.get("city"), data.get("age"), data.get("field"))
    return jsonify({"message": ask_groq(prompt)})


@app.route("/api/idea", methods=["POST"])
def idea():
    data = request.json
    idea_text = data.get("idea", "")
    market_text = data.get("market", "")
    comic = data.get("comic", "abhishek_upmanyu")

    # Check for garbage input
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
    return jsonify({"message": ask_groq(prompt)})


@app.route("/api/stack", methods=["POST"])
def stack():
    data = request.json
    project_text = data.get("project", "")
    comic = data.get("comic", "abhishek_upmanyu")

    # Check for garbage input
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
