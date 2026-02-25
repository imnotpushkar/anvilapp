"""
routes/tools.py
───────────────
All AI tool endpoints. Each route:
  1. Parses the request
  2. Validates / garbage-checks input
  3. Calls the right comics.py prompt function
  4. Asks Groq via AIService
  5. Logs tool use via DatabaseService
  6. Returns JSON

Blueprint: tools_bp  prefix: /api
"""

from flask import Blueprint, jsonify, request
from services.ai_service import AIService
from services.db_service import DatabaseService
from services.linkedin_service import LinkedInService
from comics import (
    get_linkedin_prompt,
    get_linkedin_create_prompt,
    get_linkedin_pdf_prompt,
    get_idea_create_prompt,
    get_stack_create_prompt,
    get_resume_prompt,
    get_resume_create_prompt,
    get_garbage_prompt,
    is_garbage_input,
)

tools_bp = Blueprint("tools", __name__, url_prefix="/api")


# ── Helpers ────────────────────────────────────────────────────────────────

def _garbage_response(comic: str, tool: str, value: str, reason: str):
    """Return a garbage-detection JSON response."""
    return jsonify({"message": AIService.ask(get_garbage_prompt(comic, tool, value, reason))})


# ── Debug ──────────────────────────────────────────────────────────────────

@tools_bp.route("/test-linkedin-fetch", methods=["GET"])
def test_linkedin_fetch():
    """Debug route — checks whether Render's IP can reach LinkedIn."""
    text, error = LinkedInService.fetch_profile("https://www.linkedin.com/in/williamhgates/")
    if error:
        return jsonify({"success": False, "error": error})
    return jsonify({"success": True, "preview": text[:1000]})


# ── LinkedIn ───────────────────────────────────────────────────────────────

@tools_bp.route("/linkedin", methods=["POST"])
def linkedin():
    data         = request.json
    mode         = data.get("mode", "check")
    content_type = data.get("content_type", "post")
    comic        = data.get("comic", "abhishek_upmanyu")

    if mode == "create":
        intent = data.get("intent", "").strip()
        garbage, reason = is_garbage_input(intent)
        if garbage:
            return _garbage_response(comic, "linkedin", intent, reason)
        prompt = get_linkedin_create_prompt(comic, content_type, intent)

    else:
        url_input = data.get("profile_url", "").strip()
        content   = data.get("content", "").strip()

        if url_input:
            fetched, fetch_error = LinkedInService.fetch_profile(url_input)
            if fetch_error:
                return jsonify({
                    "message":     None,
                    "fetch_error": LinkedInService.get_fetch_error_message(fetch_error)
                })
            content      = fetched
            content_type = "profile"

        if not content:
            return jsonify({
                "message":     None,
                "fetch_error": "No content provided. Paste your LinkedIn content or enter a profile URL."
            })

        garbage, reason = is_garbage_input(content)
        if garbage:
            return _garbage_response(comic, "linkedin", content, reason)
        prompt = get_linkedin_prompt(comic, content_type, content)

    result = AIService.ask(prompt)
    DatabaseService.log_tool_use("linkedin")
    return jsonify({"message": result})


# ── LinkedIn PDF ───────────────────────────────────────────────────────────

@tools_bp.route("/linkedin-pdf", methods=["POST"])
def linkedin_pdf():
    comic = request.form.get("comic", "abhishek_upmanyu")
    mode  = request.form.get("mode", "analyse")   # analyse | rewrite
    file  = request.files.get("pdf")

    if not file:
        return jsonify({"error": "No PDF uploaded"}), 400

    text, extract_error = LinkedInService.extract_pdf_text(file.read())
    if extract_error:
        return jsonify({"error": extract_error}), 400

    prompt = get_linkedin_pdf_prompt(comic, text, mode)
    result = AIService.ask(prompt)
    DatabaseService.log_tool_use("linkedin_pdf")
    return jsonify({"message": result})


# ── Idea Checker ───────────────────────────────────────────────────────────

@tools_bp.route("/idea", methods=["POST"])
def idea():
    data  = request.json
    mode  = data.get("mode", "check")
    comic = data.get("comic", "abhishek_upmanyu")

    if mode == "create":
        skills    = data.get("skills", "").strip()
        interests = data.get("interests", "").strip()
        for val in [skills, interests]:
            garbage, reason = is_garbage_input(val)
            if garbage:
                return _garbage_response(comic, "idea", val, reason)
        prompt = get_idea_create_prompt(
            comic, skills, interests,
            edge        = data.get("edge", ""),
            role        = data.get("role", ""),
            market      = data.get("market", ""),
            idea_type   = data.get("idea_type", ""),
            time_commit = data.get("time", ""),
            budget      = data.get("budget", ""),
            team        = data.get("team", ""),
        )
    else:
        idea_text   = data.get("idea", "")
        market_text = data.get("market", "")
        for val in [idea_text, market_text]:
            garbage, reason = is_garbage_input(str(val))
            if garbage:
                return _garbage_response(comic, "idea", val, reason)
        # Inline prompt kept exactly as original — move to comics.py separately later
        prompt = f"""You are a sharp startup analyst with a dark sense of humor.
    Analyze this startup idea and tell the person:
    1. If it already exists (and name competitors)
    2. How original it actually is (score out of 10)
    3. Whether it has potential or is dead on arrival
    4. One savage but constructive piece of advice
    Idea: {idea_text}
    Target Market: {market_text}
    Keep it punchy, honest, and slightly brutal. 4-5 sentences max."""

    result = AIService.ask(prompt)
    DatabaseService.log_tool_use("idea")
    return jsonify({"message": result})


# ── Stack Picker ───────────────────────────────────────────────────────────

@tools_bp.route("/stack", methods=["POST"])
def stack():
    data  = request.json
    mode  = data.get("mode", "check")
    comic = data.get("comic", "abhishek_upmanyu")

    if mode == "create":
        interests = data.get("interests", "").strip()
        garbage, reason = is_garbage_input(str(interests))
        if garbage:
            return _garbage_response(comic, "stack", interests, reason)
        prompt = get_stack_create_prompt(
            comic, interests,
            shipped     = data.get("shipped", ""),
            known       = data.get("known", ""),
            learn       = data.get("learn", ""),
            exp         = data.get("exp", ""),
            pref        = data.get("pref", ""),
            goal        = data.get("goal", ""),
            time_commit = data.get("time", ""),
            deadline    = data.get("deadline", ""),
        )
    else:
        project_text = data.get("project", "")
        garbage, reason = is_garbage_input(str(project_text))
        if garbage:
            return _garbage_response(comic, "stack", project_text, reason)
        # Inline prompt kept exactly as original
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

    result = AIService.ask(prompt)
    DatabaseService.log_tool_use("stack")
    return jsonify({"message": result})


# ── Resume Roaster ─────────────────────────────────────────────────────────

@tools_bp.route("/resume", methods=["POST"])
def resume():
    data  = request.json
    mode  = data.get("mode", "paste")
    comic = data.get("comic", "abhishek_upmanyu")

    if mode == "create":
        name = data.get("name", "").strip()
        if not name:
            return jsonify({"error": "Name is required"}), 400
        result = AIService.ask(get_resume_create_prompt(
            comic,
            name,
            data.get("role", ""),
            data.get("experience", ""),
            data.get("projects", ""),
            data.get("skills", ""),
            data.get("education", ""),
        ))
        DatabaseService.log_tool_use("resume")
        return jsonify({"message": result})

    if mode == "paste":
        resume_content = data.get("resume_text", "").strip()
    else:
        resume_content = (
            f"Name/Role: {data.get('name', '')} — {data.get('role', '')}\n"
            f"Experience: {data.get('experience', '')}\n"
            f"Projects: {data.get('projects', '')}\n"
            f"Skills: {data.get('skills', '')}\n"
            f"Education: {data.get('education', '')}"
        ).strip()

    if not resume_content:
        return jsonify({"error": "No resume content provided"}), 400

    garbage, reason = is_garbage_input(resume_content)
    if garbage:
        return _garbage_response(comic, "resume", resume_content, reason)

    result = AIService.ask(get_resume_prompt(comic, resume_content, mode=mode))
    DatabaseService.log_tool_use("resume")
    return jsonify({"message": result})
