import os

from dotenv import load_dotenv

load_dotenv()


def _require(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"missing required environment variable: {name}")
    return value


TWILIO_ACCOUNT_SID = _require("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = _require("TWILIO_AUTH_TOKEN")
TWILIO_CALLER_NUMBER = _require("TWILIO_CALLER_NUMBER")
OPENAI_API_KEY = _require("OPENAI_API_KEY")
PUBLIC_SERVER_URL = _require("PUBLIC_SERVER_URL").rstrip("/")

OPENAI_REALTIME_MODEL = os.environ.get("OPENAI_REALTIME_MODEL", "gpt-realtime")
OPENAI_VOICE = os.environ.get("OPENAI_VOICE", "alloy")
PORT = int(os.environ.get("PORT", 8000))

# Fixed per the challenge brief. Every call goes to this number, no exceptions.
TARGET_NUMBER = "+18054398008"
