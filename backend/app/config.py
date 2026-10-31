"""Settings, all from the environment (.env via docker compose). Secrets are never logged or sent to the browser."""
from __future__ import annotations

import json
import os
from pathlib import Path

ROOT = Path(os.environ.get("APP_ROOT", Path(__file__).resolve().parents[2]))

DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE_URL = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com").rstrip("/")
MODELS = [m.strip() for m in os.environ.get("DEEPSEEK_MODELS", "deepseek-flash,deepseek-v4-pro").split(",") if m.strip()]
DEFAULT_MODEL = os.environ.get("DEEPSEEK_MODEL", MODELS[0] if MODELS else "deepseek-flash")

PIPEDRIVE_API_TOKEN = os.environ.get("PIPEDRIVE_API_TOKEN", "")
PIPEDRIVE_BASE_URL = os.environ.get("PIPEDRIVE_BASE_URL", "https://api.pipedrive.com").rstrip("/")

SKILL_DIRS = [ROOT / p for p in os.environ.get("SKILL_DIRS", "skills/komosion-skills:skills-local").split(":") if p]
ALWAYS_LOADED_SKILLS = [s for s in os.environ.get("ALWAYS_LOADED_SKILLS", "evidence-discipline").split(",") if s]

DATA_DIR = Path(os.environ.get("DATA_DIR", ROOT / "data"))
DB_PATH = DATA_DIR / "crm.db"

MAX_TOOL_STEPS = int(os.environ.get("MAX_TOOL_STEPS", "10"))
TOOL_RESULT_CHARS = int(os.environ.get("TOOL_RESULT_CHARS", "12000"))  # what the model sees per tool call
TRACE_RESULT_CHARS = 1500                                              # what the trace panel shows


def prices() -> dict:
    """USD per 1M tokens per model, from prices.json. Left empty on purpose: fill it from DeepSeek's pricing page
    rather than trusting numbers baked into code. A model with no entry shows tokens but no cost."""
    path = Path(os.environ.get("PRICES_FILE", ROOT / "prices.json"))
    try:
        return {k: v for k, v in json.loads(path.read_text()).items() if not k.startswith("_")}
    except (OSError, ValueError):
        return {}
