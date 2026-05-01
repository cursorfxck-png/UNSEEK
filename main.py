import json
import os
import random
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen


def load_env_file(path=".env"):
    env_path = Path(path)
    if not env_path.exists():
        return

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


load_env_file()

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
SUPABASE_URL = os.getenv("SUPABASE_URL", "").rstrip("/")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY", os.getenv("SUPABASE_ANON_KEY", "")).strip()
PASSCODE_TABLE = os.getenv("SUPABASE_PASSCODE_TABLE", "passcodes").strip()
PASSCODE_TTL_MINUTES = int(os.getenv("PASSCODE_TTL_MINUTES", "10"))


def require_config():
    missing = []
    if not BOT_TOKEN:
        missing.append("TELEGRAM_BOT_TOKEN")
    if not SUPABASE_URL:
        missing.append("SUPABASE_URL")
    if not SUPABASE_KEY:
        missing.append("SUPABASE_SERVICE_ROLE_KEY or SUPABASE_ANON_KEY")

    if missing:
        raise SystemExit(f"Missing environment variable(s): {', '.join(missing)}")


def telegram_api(method, payload=None):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/{method}"
    body = json.dumps(payload or {}).encode("utf-8")
    request = Request(url, data=body, headers={"Content-Type": "application/json"})
    with urlopen(request, timeout=30) as response:
        data = json.loads(response.read().decode("utf-8"))
    if not data.get("ok"):
        raise RuntimeError(data)
    return data["result"]


def supabase_request(method, path, payload=None, prefer="return=representation"):
    url = f"{SUPABASE_URL}/rest/v1/{path}"
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
        "Prefer": prefer,
    }
    request = Request(url, data=body, headers=headers, method=method)
    with urlopen(request, timeout=30) as response:
        text = response.read().decode("utf-8")
    return json.loads(text) if text else None


def normalize_username(text):
    username = " ".join(text.split()).strip()
    return username[:64]


def passcode_exists(code):
    query = urlencode({"select": "id", "passcode": f"eq.{code}", "used": "eq.false", "limit": "1"})
    rows = supabase_request("GET", f"{quote(PASSCODE_TABLE)}?{query}", prefer="return=minimal")
    return bool(rows)


def new_passcode():
    for _ in range(8):
        code = str(random.randint(100000, 999999))
        if not passcode_exists(code):
            return code
    return str(random.randint(100000, 999999))


def create_passcode(username, telegram_user_id):
    code = new_passcode()
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=PASSCODE_TTL_MINUTES)
    payload = {
        "username": username,
        "passcode": code,
        "telegram_user_id": telegram_user_id,
        "expires_at": expires_at.isoformat(),
        "used": False,
    }
    supabase_request("POST", quote(PASSCODE_TABLE), payload)
    return code, expires_at


def send_message(chat_id, text):
    return telegram_api("sendMessage", {"chat_id": chat_id, "text": text})


def handle_message(message):
    chat_id = message["chat"]["id"]
    telegram_user_id = message.get("from", {}).get("id")
    text = (message.get("text") or "").strip()

    if text.startswith("/start"):
        username = normalize_username(text.removeprefix("/start"))
        if username:
            code, expires_at = create_passcode(username, telegram_user_id)
            send_message(
                chat_id,
                f"Passcode for {username}: {code}\nValid until {expires_at:%H:%M UTC}.",
            )
            return

        send_message(
            chat_id,
            "Send /passcode YOUR_USERNAME to generate a login passcode.",
        )
        return

    if text.startswith("/passcode"):
        username = normalize_username(text.removeprefix("/passcode"))
        if not username:
            send_message(chat_id, "Example: /passcode PRAKHAR")
            return

        code, expires_at = create_passcode(username, telegram_user_id)
        send_message(
            chat_id,
            f"Passcode for {username}: {code}\nValid until {expires_at:%H:%M UTC}.",
        )
        return

    send_message(chat_id, "Use /passcode YOUR_USERNAME to generate a passcode.")


def run_bot():
    require_config()
    offset = None
    print("Telegram passcode bot is running. Press Ctrl+C to stop.")

    while True:
        payload = {"timeout": 25, "allowed_updates": ["message"]}
        if offset is not None:
            payload["offset"] = offset

        try:
            updates = telegram_api("getUpdates", payload)
            for update in updates:
                offset = update["update_id"] + 1
                if "message" in update:
                    handle_message(update["message"])
        except (HTTPError, URLError, TimeoutError, RuntimeError) as error:
            print(f"Bot error: {error}")
            time.sleep(3)


if __name__ == "__main__":
    run_bot()
