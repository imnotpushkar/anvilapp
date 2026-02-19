from flask import Flask, render_template, request, jsonify
from groq import Groq
from comics import get_comic_prompt, get_resume_prompt, COMIC_OPTIONS
from dotenv import load_dotenv
load_dotenv()

app = Flask(__name__)

import os
client = Groq(api_key=os.environ.get("GROQ_API_KEY"))


def ask_groq(prompt):
    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role": "user", "content": prompt}]
    )
    return response.choices[0].message.content

@app.route("/ping")
def ping():
    return "pong", 200


    return render_template("index.html", comic_options=COMIC_OPTIONS)

@app.route("/api/roast", methods=["POST"])
def roast():
    data = request.json
    salary = data.get("salary")
    city = data.get("city")
    age = data.get("age")
    field = data.get("field")
    comic = data.get("comic")
    prompt = get_comic_prompt(comic, salary, city, age, field)
    return jsonify({"message": ask_groq(prompt)})

@app.route("/api/idea", methods=["POST"])
def idea():
    data = request.json
    idea = data.get("idea")
    market = data.get("market")
    prompt = f"""You are a sharp startup analyst with a dark sense of humor.
    Analyze this startup idea and tell the person:
    1. If it already exists (and name competitors)
    2. How original it actually is (score out of 10)
    3. Whether it has potential or is dead on arrival
    4. One savage but constructive piece of advice
    Idea: {idea}
    Target Market: {market}
    Keep it punchy, honest, and slightly brutal. 4-5 sentences max."""
    return jsonify({"message": ask_groq(prompt)})

@app.route("/api/stack", methods=["POST"])
def stack():
    data = request.json
    project = data.get("project")
    level = data.get("level")
    priority = data.get("priority")
    prompt = f"""You are an opinionated senior developer who gives direct tech stack recommendations.
    Recommend a tech stack for this project. Be specific and decisive — no wishy-washy answers.
    Project: {project}
    Developer Experience Level: {level}
    Priority: {priority}
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
    mode = data.get("mode")          # "paste" or "form"
    comic = data.get("comic")

    if mode == "paste":
        resume_content = data.get("resume_text", "").strip()
    else:
        name = data.get("name", "")
        experience = data.get("experience", "")
        skills = data.get("skills", "")
        education = data.get("education", "")
        resume_content = f"Name/Title: {name}\nExperience: {experience}\nSkills: {skills}\nEducation: {education}"

    if not resume_content:
        return jsonify({"error": "No resume content provided"}), 400

    prompt = get_resume_prompt(comic, resume_content)
    result = ask_groq(prompt)
    return jsonify({"message": result})

if __name__ == "__main__":
    app.run(debug=True)