"""
config.py
─────────
Single source of truth for environment variables, client initialisation,
and app-wide constants. Everything imports from here — nothing else calls
os.environ directly.
"""

import os
from dotenv import load_dotenv
from groq import Groq
from supabase import create_client, Client

load_dotenv()

# ── Flask ──────────────────────────────────────────────────────────────────
FLASK_SECRET_KEY: str = os.environ.get("FLASK_SECRET_KEY", "anvil-dev-secret")

# ── Groq ───────────────────────────────────────────────────────────────────
GROQ_API_KEY: str = os.environ.get("GROQ_API_KEY", "")
GROQ_MODEL: str = "llama-3.3-70b-versatile"

groq_client: Groq = Groq(api_key=GROQ_API_KEY)

# ── Supabase ───────────────────────────────────────────────────────────────
SUPABASE_URL: str = os.environ.get("SUPABASE_URL", "")
SUPABASE_ANON_KEY: str = os.environ.get("SUPABASE_ANON_KEY", "")

if not SUPABASE_URL or not SUPABASE_ANON_KEY:
    raise RuntimeError(
        "Missing SUPABASE_URL or SUPABASE_ANON_KEY — check your .env or Render env vars"
    )

supabase: Client = create_client(SUPABASE_URL, SUPABASE_ANON_KEY)

# ── Tool XP values ─────────────────────────────────────────────────────────
TOOL_XP: dict = {
    "linkedin":     25,
    "linkedin_pdf": 30,
    "idea":         30,
    "stack":        20,
    "resume":       35,
}
