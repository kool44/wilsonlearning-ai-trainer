"""Runtime configuration. Everything comes from environment variables (or .env)."""
import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

LLM_PROVIDER = os.getenv("LLM_PROVIDER", "anthropic")          # anthropic | mock
MODEL = os.getenv("MODEL", "claude-opus-5-5")
TEACH_EFFORT = os.getenv("TEACH_EFFORT", "medium")               # low | medium | high
GRADE_EFFORT = os.getenv("GRADE_EFFORT", "low")
USE_FALLBACKS = os.getenv("LLM_FALLBACKS", "1") == "1"
CONTENT_DIR = Path(os.getenv("CONTENT_DIR", ROOT / "content"))
DB_PATH = Path(os.getenv("DB_PATH", ROOT / "data" / "trainer.db"))
PORT = int(os.getenv("PORT", "8000"))
