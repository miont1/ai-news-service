"""Interactive script to authenticate Telethon session for Telegram channel parsing.

Can be run from project root or from scripts/ directory:
    uv run python scripts/auth_telegram.py
"""

import sys
from pathlib import Path

# Ensure project root is on sys.path so 'app' module can always be found
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from telethon.sync import TelegramClient

from app.config import settings


def main() -> None:
    print("=" * 60)
    print(" Telegram Client Authentication Helper")
    print("=" * 60)

    if not settings.TG_API_ID or not settings.TG_API_HASH:
        print("ERROR: TG_API_ID and TG_API_HASH must be configured in .env file.")
        print("Obtain them from https://my.telegram.org/apps")
        return

    session_name = settings.TG_SESSION_NAME or "aibot_session"
    print(f"Using session name: {session_name}")
    print(f"API ID: {settings.TG_API_ID}")
    print("\nStarting interactive login in terminal...")
    print("(You will be prompted for your phone number and Telegram verification code)")

    # Using Telethon's synchronous context manager handles start(), login prompts, and disconnect
    with TelegramClient(session_name, int(settings.TG_API_ID), settings.TG_API_HASH) as client:
        me = client.get_me()
        username = f"@{me.username}" if getattr(me, "username", None) else "no username"
        print("\n" + "=" * 60)
        print(f" SUCCESS: Logged in as {getattr(me, 'first_name', '')} ({username})")
        print(f" Session file '{session_name}.session' is now authorized!")
        print(" You can now run the app and parse Telegram channels without errors.")
        print("=" * 60)


if __name__ == "__main__":
    main()
