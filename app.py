"""
app.py
──────
Flask application entry point.
This file only does three things:
  1. Creates the Flask app
  2. Registers blueprints
  3. Defines the two simple routes that don't belong to a blueprint (/ and /ping)

All business logic lives in services/.
All route handlers live in routes/.
All config and clients live in config.py.
"""

from flask import Flask, render_template, session
from config import FLASK_SECRET_KEY
from comics import COMIC_OPTIONS

from routes.auth  import auth_bp
from routes.user  import user_bp
from routes.tools import tools_bp

# ── App factory ────────────────────────────────────────────────────────────
app = Flask(__name__)
app.secret_key = FLASK_SECRET_KEY

# ── Register blueprints ────────────────────────────────────────────────────
app.register_blueprint(auth_bp)
app.register_blueprint(user_bp)
app.register_blueprint(tools_bp)


# ── Core routes ────────────────────────────────────────────────────────────

@app.route("/ping")
def ping():
    return "pong", 200


@app.route("/")
def index():
    user = session.get("user")
    return render_template("index.html", comic_options=COMIC_OPTIONS, user=user)


# ── Dev server ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    app.run(debug=True)
