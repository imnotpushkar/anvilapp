"""
services/linkedin_service.py
─────────────────────────────
Everything LinkedIn-specific lives here:
  - URL profile fetching (currently blocked on Render, graceful fallback)
  - PDF text extraction (S13 — slot ready, implementation added when pymupdf lands)
"""

import re
import requests
from bs4 import BeautifulSoup

# ── Browser-like headers to avoid bot detection ────────────────────────────
LINKEDIN_HEADERS = {
    "User-Agent":                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                                 "AppleWebKit/537.36 (KHTML, like Gecko) "
                                 "Chrome/120.0.0.0 Safari/537.36",
    "Accept":                    "text/html,application/xhtml+xml,application/xml;"
                                 "q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language":           "en-US,en;q=0.9",
    "Accept-Encoding":           "gzip, deflate, br",
    "Connection":                "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest":            "document",
    "Sec-Fetch-Mode":            "navigate",
    "Sec-Fetch-Site":            "none",
    "Cache-Control":             "max-age=0",
}

# ── User-facing error messages ─────────────────────────────────────────────
FETCH_ERROR_MESSAGES = {
    "BLOCKED":           "LinkedIn blocked the request from our server. "
                         "Please paste your profile content manually instead.",
    "AUTHWALL":          "This profile requires login to view. "
                         "Please paste your profile content manually instead.",
    "TIMEOUT":           "LinkedIn took too long to respond. "
                         "Please paste your profile content manually instead.",
    "INSUFFICIENT_DATA": "Couldn't extract enough data from this profile — "
                         "it may be private. Please paste your content manually instead.",
    "INVALID_URL":       "That doesn't look like a valid LinkedIn profile URL. "
                         "Try: https://linkedin.com/in/yourname",
}


class LinkedInService:

    # ── URL fetch ──────────────────────────────────────────────────────────

    @staticmethod
    def fetch_profile(url: str) -> tuple[str | None, str | None]:
        """
        Attempt to scrape a public LinkedIn profile.
        Returns (extracted_text, None) on success, or (None, error_code) on failure.
        Error codes: INVALID_URL | BLOCKED | AUTHWALL | TIMEOUT | INSUFFICIENT_DATA | HTTP_xxx
        """
        url = url.strip()
        if not re.match(r'https?://(www\.)?linkedin\.com/in/[\w\-]+/?', url):
            return None, "INVALID_URL"

        try:
            resp = requests.get(url, headers=LINKEDIN_HEADERS, timeout=10, allow_redirects=True)

            if resp.status_code == 999:
                return None, "BLOCKED"
            if any(x in resp.url for x in ["authwall", "login", "checkpoint"]):
                return None, "AUTHWALL"
            if resp.status_code != 200:
                return None, f"HTTP_{resp.status_code}"

            soup = BeautifulSoup(resp.text, "html.parser")
            sections = []

            for prop in ["og:title", "og:description"]:
                tag = soup.find("meta", {"property": prop})
                if tag and tag.get("content"):
                    sections.append(tag["content"].strip())

            desc = soup.find("meta", {"name": "description"})
            if desc and desc.get("content"):
                sections.append(desc["content"].strip())

            h1 = soup.find("h1")
            if h1:
                sections.append(f"Name: {h1.get_text(strip=True)}")

            main = soup.find("main") or soup.find("body")
            if main:
                for tag in main.find_all(["h2", "h3", "p", "li"]):
                    text = tag.get_text(strip=True)
                    if len(text) > 40:
                        sections.append(text)

            if len(sections) < 2:
                return None, "INSUFFICIENT_DATA"

            seen, unique = set(), []
            for s in sections:
                if s not in seen:
                    seen.add(s)
                    unique.append(s)

            return "\n".join(unique[:40]), None

        except requests.exceptions.Timeout:
            return None, "TIMEOUT"
        except Exception as e:
            return None, f"ERROR:{str(e)}"

    @staticmethod
    def get_fetch_error_message(error_code: str) -> str:
        return FETCH_ERROR_MESSAGES.get(
            error_code,
            "Couldn't fetch this profile. Please paste your content manually instead."
        )

    # ── PDF extraction — S13 slot ──────────────────────────────────────────

    @staticmethod
    def extract_pdf_text(file_bytes: bytes) -> tuple[str | None, str | None]:
        """
        Extract and clean text from a LinkedIn profile PDF.
        Returns (cleaned_text, None) on success, or (None, error_message) on failure.
        Requires: pymupdf (import fitz) — add to requirements.txt before calling.
        """
        try:
            import fitz  # pymupdf

            doc = fitz.open(stream=file_bytes, filetype="pdf")
            pages = []
            for page in doc:
                pages.append(page.get_text())
            doc.close()

            raw = "\n".join(pages)

            # Clean: strip page numbers, blank lines, LinkedIn boilerplate
            lines = []
            for line in raw.splitlines():
                line = line.strip()
                if not line:
                    continue
                if line.isdigit():          # page numbers
                    continue
                if "linkedin.com" in line.lower() and len(line) < 60:
                    continue
                if line.lower() in ("contact", "page", "profile"):
                    continue
                lines.append(line)

            cleaned = "\n".join(lines)

            if len(cleaned) < 100:
                return None, "PDF appears to be empty or unreadable."

            return cleaned, None

        except ImportError:
            return None, "PDF parsing library not installed. Add pymupdf to requirements.txt."
        except Exception as e:
            return None, f"Could not read PDF: {str(e)}"
