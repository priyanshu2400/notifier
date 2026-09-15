"""
Unified configuration — all constants, secrets, and paths in one place.
Loads from config.json (local) or environment variables (GitHub Actions).
"""

import json
import os
from pathlib import Path

# ─── Paths ────────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).parent
CONFIG_FILE = BASE_DIR / "config.json"
API_KEY_FILE = BASE_DIR / "api-key.txt"
PREFERENCES_FILE = BASE_DIR / "preferences.md"
DATABASE_FILE = BASE_DIR / "jobs.db"
LOG_FILE = BASE_DIR / "notifier.log"

# ─── HiringCafe ──────────────────────────────────────────────────────────
HIRINGCAFE_BASE_URL = "https://hiringcafe.com/"

# Default search: Bengaluru + Asia, Software Dev & Engineering, 0-2 YOE, past 2 days
DEFAULT_SEARCH_STATE = {
    "locations": [
        {
            "types": ["continent"],
            "formatted_address": "Asia",
            "address_components": [],
            "workplace_types": ["Remote"],
            "options": {},
            "id": "Asiacontinent",
        },
        {
            "id": "sxg1yZQBoEtHp_8UbmmX",
            "types": ["locality"],
            "address_components": [
                {"long_name": "Bengaluru", "short_name": "Bengaluru", "types": ["locality"]},
                {"long_name": "Karnataka", "short_name": "19", "types": ["administrative_area_level_1"]},
                {"long_name": "India", "short_name": "IN", "types": ["country"]},
            ],
            "geometry": {"location": {"lat": 12.97194, "lon": 77.59369}},
            "formatted_address": "Bengaluru, Karnataka, IN",
            "population": 8443675,
            "workplace_types": [],
            "options": {"radius": 50, "radius_unit": "miles", "ignore_radius": False},
        },
    ],
    "dateFetchedPastNDays": 2,
    "departments": ["Software+Development", "Engineering"],
    "roleYoeRange": [0, 2],
}

# ─── Filters ─────────────────────────────────────────────────────────────
SENIORITY_KEYWORDS = ["no prior", "entry", "junior", "associate", "not mentioned"]
INTERNSHIP_KEYWORDS = ["intern", "internship"]
MAX_COMPENSATION_LAKHS = 15

# ─── Gemini API ──────────────────────────────────────────────────────────
GEMINI_MODEL = "gemini-3.5-flash-lite"
GEMINI_API_URL = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"

# ─── Telegram ────────────────────────────────────────────────────────────
TELEGRAM_API = "https://api.telegram.org"

# ─── Scraping ────────────────────────────────────────────────────────────
SCRAPE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}


def load_config() -> dict:
    """Load config from config.json, with env var overrides for GitHub Actions."""
    config = {}

    if CONFIG_FILE.exists():
        with open(CONFIG_FILE, "r") as f:
            config = json.load(f)

    # Env var overrides (GitHub Actions)
    if v := os.environ.get("TELEGRAM_BOT_TOKEN"):
        config["telegram_bot_token"] = v
    if v := os.environ.get("TELEGRAM_CHAT_IDS"):
        config["telegram_chat_ids"] = json.loads(v)
    if v := os.environ.get("HIRINGCAFE_URL"):
        config["hiringcafe_url"] = v

    return config


def load_api_key() -> str | None:
    """Load Gemini API key from env or file."""
    if v := os.environ.get("GEMINI_API_KEY"):
        return v.strip()
    if API_KEY_FILE.exists():
        return API_KEY_FILE.read_text(encoding="utf-8").strip()
    return None


def load_preferences() -> str | None:
    """Load preferences from env or file."""
    if v := os.environ.get("PREFERENCES_MD"):
        return v
    if PREFERENCES_FILE.exists():
        return PREFERENCES_FILE.read_text(encoding="utf-8")
    return None
